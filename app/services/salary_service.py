from __future__ import annotations

import uuid
from calendar import monthrange
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session


class SalaryService:
    def __init__(
        self,
        db: Session,
        model: type,
        primary_key: str,
        auth_db: Session,
        reference_db: Session,
        timetrack_db: Session | None = None,
    ) -> None:
        self.db = db
        self.model = model
        self.primary_key = primary_key
        self.auth_db = auth_db
        self.reference_db = reference_db
        self.timetrack_db = timetrack_db
        self._cache: dict[tuple[str, Any], Any] = {}

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
    ):
        query = self.db.query(self.model)
        for field, value in (filters or {}).items():
            if value is not None and self._has_column(field):
                query = query.filter(getattr(self.model, field) == value)
        rows = query.offset(offset).limit(limit).all()
        return [self._serialize(row) for row in rows]

    def get(self, row_id: Any):
        row = self._find(row_id)
        if not row:
            return None
        data = self._serialize(row)
        if self.model.__tablename__ == "receipt":
            data["items"] = self._get_receipt_items(data["id"])
        if self.model.__tablename__ == "extracts":
            data["items"] = self._get_extract_items(data["id"])
        return data

    def create(self, payload: BaseModel, actor_id: str | None):
        data = payload.model_dump(exclude_none=True)
        self._apply_employee_user_data(data)
        self._apply_create_defaults(data, actor_id)
        row = self.model(**data)
        self.db.add(row)
        self._commit("Некорректные данные для создания записи")
        self.db.refresh(row)
        return self._serialize(row)

    def update(self, row_id: Any, payload: BaseModel, actor_id: str | None):
        row = self._find(row_id)
        if not row:
            return None

        data = payload.model_dump(exclude_unset=True)

        if self.model.__tablename__ == "extract_item":
            old_employee_id = row.employee_id
            old_consider = row.consider
            old_result = row.result
        else:
            old_employee_id = old_consider = old_result = None

        self._apply_employee_user_data(data)
        self._apply_update_defaults(data, actor_id)
        for field, value in data.items():
            setattr(row, field, value)

        if self.model.__tablename__ == "extract_item":
            self._sync_extract_item_ops(
                item=row,
                old_employee_id=old_employee_id,
                old_consider=old_consider,
                old_result=old_result,
                actor_id=actor_id,
            )

        self._commit("Некорректные данные для изменения записи")
        self.db.refresh(row)
        return self._serialize(row)

    def delete(self, row_id: Any):
        row = self._find(row_id)
        if not row:
            return None
        data = self._serialize(row)
        self.db.delete(row)
        self._commit("Не удалось удалить запись")
        return data

    def buh_salary_report(self, mounth_period: str, year: int):
        period_start, period_end = self._month_bounds(mounth_period, year)
        rows = self.db.execute(
            text(
                """
                SELECT
                    eh.counterparties_id,
                    eh.department,
                    eh.position,
                    eh.start_date,
                    eh.end_date,
                    e.id AS employee_id,
                    e.name,
                    e.surname,
                    e.patronymic,
                    e.userId,
                    e.marker,
                    bs.id AS buh_salary_id,
                    bs.value AS accrued_value,
                    bs.type_id,
                    bs.created_by,
                    bs.edit_by,
                    bs.created_at,
                    COALESCE(SUM(os.value), 0) AS paid_value
                FROM employment_history eh
                JOIN employee e ON e.id = eh.employee_id
                LEFT JOIN buh_salary bs
                    ON bs.employee_id = e.id
                    AND bs.mounth_period = :mounth_period
                    AND bs.year = :year
                LEFT JOIN operations_salary os
                    ON os.employee_id = e.id
                    AND os.nounth_period = :mounth_period
                    AND os.year = :year
                    AND (bs.id IS NULL OR os.type_id = bs.type_id)
                WHERE eh.start_date <= :period_end
                  AND (eh.end_date IS NULL OR eh.end_date >= :period_start)
                GROUP BY
                    eh.counterparties_id,
                    eh.department,
                    eh.position,
                    eh.start_date,
                    eh.end_date,
                    e.id,
                    e.name,
                    e.surname,
                    e.patronymic,
                    e.userId,
                    e.marker,
                    bs.id,
                    bs.value,
                    bs.type_id,
                    bs.created_by,
                    bs.edit_by,
                    bs.created_at
                ORDER BY eh.counterparties_id, e.surname, e.name, bs.type_id
                """
            ),
            {
                "mounth_period": mounth_period,
                "year": year,
                "period_start": period_start,
                "period_end": period_end,
            },
        ).mappings().all()

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            counterparty_id = row["counterparties_id"]
            group = grouped.setdefault(
                counterparty_id,
                {
                    "counterparties_id": counterparty_id,
                    "counterparties_name": self._get_reference_name(
                        "counterparties", counterparty_id
                    ),
                    "total_accrued": 0,
                    "total_paid": 0,
                    "total_remaining": 0,
                    "employees": {},
                },
            )

            employee = self._serialize_report_employee(row)
            accrued_value = float(row["accrued_value"] or 0)
            paid_value = float(row["paid_value"] or 0)
            remaining_value = accrued_value - paid_value
            employee_item = group["employees"].setdefault(
                employee["id"],
                {
                    "employee": employee,
                    "department": row["department"],
                    "position": row["position"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "total_accrued": 0,
                    "total_paid": 0,
                    "total_remaining": 0,
                    "accruals": [],
                },
            )
            if row["buh_salary_id"]:
                employee_item["accruals"].append(
                    {
                        "buh_salary_id": row["buh_salary_id"],
                        "type_id": row["type_id"],
                        "type_name": self._get_named_salary_row(
                            "type", "id", row["type_id"]
                        ),
                        "accrued_value": accrued_value,
                        "paid_value": paid_value,
                        "remaining_value": remaining_value,
                        "created_by": row["created_by"],
                        "created_by_user": self._get_auth_user(row["created_by"]),
                        "edit_by": row["edit_by"],
                        "edit_by_user": (
                            self._get_auth_user(row["edit_by"]) if row["edit_by"] else None
                        ),
                        "created_at": row["created_at"],
                    }
                )
            elif paid_value > 0:
                ops_rows = self.db.execute(
                    text(
                        """
                        SELECT type_id, SUM(value) AS paid
                        FROM operations_salary
                        WHERE employee_id = :employee_id
                          AND nounth_period = :mounth_period
                          AND year = :year
                        GROUP BY type_id
                        """
                    ),
                    {
                        "employee_id": row["employee_id"],
                        "mounth_period": mounth_period,
                        "year": year,
                    },
                ).mappings().all()
                for ops_row in ops_rows:
                    ops_paid = float(ops_row["paid"])
                    employee_item["accruals"].append(
                        {
                            "buh_salary_id": None,
                            "type_id": ops_row["type_id"],
                            "type_name": self._get_named_salary_row(
                                "type", "id", ops_row["type_id"]
                            ),
                            "accrued_value": 0,
                            "paid_value": ops_paid,
                            "remaining_value": -ops_paid,
                            "created_by": None,
                            "created_by_user": None,
                            "edit_by": None,
                            "edit_by_user": None,
                            "created_at": None,
                        }
                    )
            employee_item["total_accrued"] += accrued_value
            employee_item["total_paid"] += paid_value
            employee_item["total_remaining"] += remaining_value
            group["total_accrued"] += accrued_value
            group["total_paid"] += paid_value
            group["total_remaining"] += remaining_value

        for group in grouped.values():
            group["employees"] = list(group["employees"].values())

        return {
            "mounth_period": mounth_period,
            "year": year,
            "period_start": period_start,
            "period_end": period_end,
            "counterparties": list(grouped.values()),
        }

    def director_salary_report(self, mounth_period: str, year: int):
        if self.timetrack_db is None:
            raise ValueError("Не подключена БД timetrack_service")

        period_start, period_end = self._month_bounds(mounth_period, year)
        rows = self.db.execute(
            text(
                """
                SELECT
                    eh.counterparties_id,
                    eh.department,
                    eh.position,
                    eh.start_date,
                    eh.end_date,
                    e.id AS employee_id,
                    e.name,
                    e.surname,
                    e.patronymic,
                    e.userId,
                    e.marker
                FROM employment_history eh
                JOIN employee e ON e.id = eh.employee_id
                WHERE eh.start_date <= :period_end
                  AND (eh.end_date IS NULL OR eh.end_date >= :period_start)
                ORDER BY eh.counterparties_id, e.surname, e.name
                """
            ),
            {"period_start": period_start, "period_end": period_end},
        ).mappings().all()

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            counterparty_id = row["counterparties_id"]
            group = grouped.setdefault(
                counterparty_id,
                {
                    "counterparties_id": counterparty_id,
                    "counterparties_name": self._get_reference_name(
                        "counterparties", counterparty_id
                    ),
                    "total_salary_accrued": 0,
                    "total_paid": 0,
                    "total_remaining": 0,
                    "employees": [],
                },
            )

            employee = self._serialize_report_employee(row)
            metrics = self._director_employee_metrics(
                employee_id=row["employee_id"],
                user_id=row["userId"],
                mounth_period=mounth_period,
                year=year,
                period_start=period_start,
                period_end=period_end,
                apply_overpayment=True,
            )
            item = {
                "employee": employee,
                "department": row["department"],
                "position": row["position"],
                "employment_start_date": row["start_date"],
                "employment_end_date": row["end_date"],
                **metrics,
            }
            group["employees"].append(item)
            group["total_salary_accrued"] += metrics["salary_accrued"]
            group["total_paid"] += metrics["paid_total_with_overpayment"]
            group["total_remaining"] += metrics["remaining"]

        return {
            "mounth_period": mounth_period,
            "year": year,
            "period_start": period_start,
            "period_end": period_end,
            "counterparties": list(grouped.values()),
        }

    def _director_employee_metrics(
        self,
        *,
        employee_id: str,
        user_id: str | None,
        mounth_period: str,
        year: int,
        period_start: date,
        period_end: date,
        apply_overpayment: bool,
    ) -> dict[str, Any]:
        user = self._get_auth_user(user_id) if user_id else None
        gender_id = user.get("gender_id") if user else None
        standard_hours = (
            self._get_standard_hours(user_id, gender_id, mounth_period, year)
            if user_id and gender_id
            else None
        )
        worked_hours = (
            self._get_worked_hours(user_id, period_start, period_end)
            if user_id
            else None
        )
        vacation_days = (
            self._get_vacation_days(user_id, period_start, period_end)
            if user_id
            else None
        )
        sick_days = (
            self._get_sick_days(user_id, period_start, period_end)
            if user_id
            else None
        )
        salary = self._get_employee_salary(employee_id, period_start, period_end)
        salary_total = self._calculate_salary_total(salary, standard_hours)
        salary_accrued = self._calculate_salary_accrued(
            salary,
            standard_hours,
            worked_hours,
        )
        vacation_total = self._calculate_vacation_total(
            salary_total,
            vacation_days,
        )
        advance = self._sum_operations_salary(employee_id, mounth_period, year, 5)
        bonus = self._sum_operations_salary(employee_id, mounth_period, year, 7)
        buh_total = self._sum_buh_salary(employee_id, mounth_period, year)
        vacation_buh = self._sum_buh_salary(employee_id, mounth_period, year, 4)
        vacation_ev = vacation_total - vacation_buh
        paid_total = buh_total + self._sum_operations_salary(employee_id, mounth_period, year, exclude_type_ids=[1, 2, 3, 4, 7])
        overpayment = (
            self._get_previous_overpayment(employee_id, mounth_period, year)
            if apply_overpayment
            else None
        )
        if user_id is None and salary_total == 0:
            overpayment = None
        overpayment_value = overpayment["amount"] if overpayment else 0
        paid_total_with_overpayment = paid_total + overpayment_value
        if user_id is None:
            salary_accrued = salary_total

        salary_accrued += bonus

        remaining = salary_accrued + vacation_ev - paid_total_with_overpayment
        if user_id is None and salary_total == 0 and buh_total > 0 and remaining < 0:
            remaining = 0

        salary_accrued = self._money(salary_accrued)
        vacation_total = self._money(vacation_total)
        vacation_ev = self._money(vacation_ev)
        remaining = self._money(remaining)

        return {
            "standard_hours": standard_hours,
            "worked_hours": worked_hours,
            "vacation_days": vacation_days,
            "sick_days": sick_days,
            "salary": salary,
            "salary_total": salary_total,
            "salary_accrued": salary_accrued,
            "advance": advance,
            "bonus": bonus,
            "buh_total": buh_total,
            "vacation_total": vacation_total,
            "vacation_buh": vacation_buh,
            "vacation_ev": vacation_ev,
            "paid_total": paid_total,
            "overpayment_applied": overpayment,
            "paid_total_with_overpayment": paid_total_with_overpayment,
            "remaining": remaining,
        }

    def _find(self, row_id: Any):
        return (
            self.db.query(self.model)
            .filter(getattr(self.model, self.primary_key) == row_id)
            .first()
        )

    def _apply_create_defaults(self, data: dict[str, Any], actor_id: str | None) -> None:
        pk_column = self._column(self.primary_key)
        if self.primary_key not in data and self._is_uuid_pk(pk_column):
            data[self.primary_key] = str(uuid.uuid4())

        if self._has_column("created_at") and "created_at" not in data:
            data["created_at"] = datetime.utcnow()

        if self._has_column("user_id"):
            data["user_id"] = data.get("user_id") or actor_id
            if not data["user_id"]:
                raise ValueError("Не удалось определить user_id из session")

        if self._has_column("created_by"):
            data["created_by"] = data.get("created_by") or actor_id
            if not data["created_by"]:
                raise ValueError("Не удалось определить created_by из session")

        if self._has_column("edit_by"):
            edit_column = self._column("edit_by")
            if not edit_column.nullable:
                data["edit_by"] = data.get("edit_by") or actor_id
                if not data["edit_by"]:
                    raise ValueError("Не удалось определить edit_by из session")

    def _apply_update_defaults(self, data: dict[str, Any], actor_id: str | None) -> None:
        if self._has_column("edit_by"):
            data["edit_by"] = data.get("edit_by") or actor_id
            if not data["edit_by"]:
                raise ValueError("Не удалось определить edit_by из session")

    def _commit(self, message: str) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError(message) from exc

    def _serialize(self, row) -> dict[str, Any]:
        data = {
            column.key: getattr(row, column.key)
            for column in inspect(row).mapper.column_attrs
        }
        self._enrich(data)
        return data

    def _apply_employee_user_data(self, data: dict[str, Any]) -> None:
        if not self._has_column("userId") or not data.get("userId"):
            return

        user = self._get_auth_user(data["userId"])
        if not user:
            raise ValueError("userId не найден в authorization_service.users")

        data["name"] = user["name"]
        data["surname"] = user["surname"]
        data["patronymic"] = user["patronymic"]

    def _enrich(self, data: dict[str, Any]) -> None:
        if data.get("userId"):
            user = self._get_auth_user(data["userId"])
            data["user"] = user
            if self._has_column("userId") and user:
                data["name"] = user["name"]
                data["surname"] = user["surname"]
                data["patronymic"] = user["patronymic"]
                data["full_name"] = user["full_name"]

        for field in ("created_by", "edit_by"):
            if data.get(field):
                data[f"{field}_user"] = self._get_auth_user(data[field])

        if data.get("user_id"):
            data["user"] = self._get_auth_user(data["user_id"])

        if data.get("employee_id"):
            data["employee"] = self._get_employee(data["employee_id"])

        if data.get("counterparties_id"):
            data["counterparties_name"] = self._get_reference_name(
                "counterparties", data["counterparties_id"]
            )

        if data.get("object_id"):
            salary_object = self._get_salary_object(data["object_id"])
            if salary_object:
                data["object_name"] = salary_object["name"]
                data["object"] = salary_object
                if salary_object.get("object_id"):
                    data["object_project_name"] = self._get_reference_name(
                        "objects", salary_object["object_id"]
                    )
            else:
                data["object_name"] = self._get_object_name(data["object_id"])

        if data.get("from_person"):
            data["from_person_data"] = self._get_person(data["from_person"])

        if data.get("whom_person"):
            data["whom_person_data"] = self._get_person(data["whom_person"])

        if data.get("category_id"):
            data["category_name"] = self._get_named_salary_row(
                "category", "id", data["category_id"]
            )

        if data.get("financial_source_id"):
            data["financial_source_name"] = self._get_named_salary_row(
                "financial_sources", "id", data["financial_source_id"]
            )

        if data.get("file_id"):
            data["file"] = self._get_file(data["file_id"])

        if data.get("receipt_list_id"):
            data["receipt_list"] = self._get_receipt_list(data["receipt_list_id"])

        if data.get("receipt_id"):
            data["receipt"] = self._get_receipt(data["receipt_id"])

        if self.model.__tablename__ == "receipt" and data.get("id"):
            data["categories"] = self._get_receipt_categories(data["id"])

        if data.get("method_pay"):
            data["method_pay_name"] = self._get_named_salary_row(
                "method", "id", data["method_pay"]
            )

        if data.get("method_id"):
            data["method_name"] = self._get_named_salary_row(
                "method", "id", data["method_id"]
            )

        if data.get("type_id"):
            data["type_name"] = self._get_named_salary_row("type", "id", data["type_id"])

        if data.get("mounth_period"):
            data["mounth_period_name"] = data["mounth_period"]

    def _get_auth_user(self, user_id: str) -> dict[str, Any] | None:
        cache_key = ("auth_user", user_id)
        if cache_key not in self._cache:
            row = self.auth_db.execute(
                text(
                    """
                    SELECT id, name, surname, patronymic, gender_id
                    FROM users
                    WHERE id = :user_id
                    LIMIT 1
                    """
                ),
                {"user_id": user_id},
            ).mappings().first()
            self._cache[cache_key] = (
                {
                    "id": row["id"],
                    "name": row["name"],
                    "surname": row["surname"],
                    "patronymic": row["patronymic"],
                    "gender_id": row["gender_id"],
                    "full_name": self._full_name(
                        row["surname"], row["name"], row["patronymic"]
                    ),
                }
                if row
                else None
            )
        return self._cache[cache_key]

    def _get_employee(self, employee_id: str) -> dict[str, Any] | None:
        cache_key = ("employee", employee_id)
        if cache_key not in self._cache:
            row = self.db.execute(
                text(
                    """
                    SELECT id, name, surname, patronymic, userId, marker
                    FROM employee
                    WHERE id = :employee_id
                    LIMIT 1
                    """
                ),
                {"employee_id": employee_id},
            ).mappings().first()
            self._cache[cache_key] = (
                self._serialize_employee_lookup(row)
                if row
                else None
            )
        return self._cache[cache_key]

    def _serialize_employee_lookup(self, row) -> dict[str, Any]:
        user = self._get_auth_user(row["userId"]) if row["userId"] else None
        name = user["name"] if user else row["name"]
        surname = user["surname"] if user else row["surname"]
        patronymic = user["patronymic"] if user else row["patronymic"]
        return {
            "id": row["id"],
            "name": name,
            "surname": surname,
            "patronymic": patronymic,
            "full_name": self._full_name(surname, name, patronymic),
            "userId": row["userId"],
            "user": user,
            "marker": row["marker"],
        }

    def _serialize_report_employee(self, row) -> dict[str, Any]:
        user = self._get_auth_user(row["userId"]) if row["userId"] else None
        name = user["name"] if user else row["name"]
        surname = user["surname"] if user else row["surname"]
        patronymic = user["patronymic"] if user else row["patronymic"]
        return {
            "id": row["employee_id"],
            "name": name,
            "surname": surname,
            "patronymic": patronymic,
            "full_name": self._full_name(surname, name, patronymic),
            "userId": row["userId"],
            "user": user,
            "marker": row["marker"],
        }

    def _get_standard_hours(
        self,
        user_id: str,
        gender_id: int | None,
        mounth_period: str,
        year: int,
    ) -> float | None:
        if self.timetrack_db is None or gender_id is None:
            return None

        month_number = self._month_number(mounth_period)
        gender_column = self._first_existing_column(
            self.timetrack_db, "work_standards", ("gender", "gender_id")
        )
        user_id_column = self._first_existing_column(
            self.timetrack_db, "work_standards", ("user_id", "userId")
        )
        if not gender_column or not user_id_column:
            return None

        row = self.timetrack_db.execute(
            text(
                f"""
                SELECT standard_hours
                FROM work_standards
                WHERE month = :month
                  AND year = :year
                  AND {gender_column} = :gender_id
                  AND ({user_id_column} = :user_id OR {user_id_column} IS NULL)
                ORDER BY CASE WHEN {user_id_column} = :user_id THEN 0 ELSE 1 END
                LIMIT 1
                """
            ),
            {
                "month": month_number,
                "year": year,
                "gender_id": gender_id,
                "user_id": user_id,
            },
        ).first()
        return float(row[0]) if row and row[0] is not None else None

    def _get_worked_hours(
        self, user_id: str, period_start: date, period_end: date
    ) -> float | None:
        if self.timetrack_db is None:
            return None

        hours_column = self._first_existing_column(
            self.timetrack_db,
            "user_time_entries",
            (
                "hours_worked",
                "hours",
                "work_hours",
                "worked_hours",
                "duration_hours",
                "value",
            ),
        )
        if hours_column:
            row = self.timetrack_db.execute(
                text(
                    f"""
                    SELECT COALESCE(SUM({hours_column}), 0)
                    FROM user_time_entries
                    WHERE user_id = :user_id
                      AND entry_date BETWEEN :period_start AND :period_end
                    """
                ),
                {
                    "user_id": user_id,
                    "period_start": period_start,
                    "period_end": period_end,
                },
            ).first()
            return float(row[0]) if row else 0

        row = self.timetrack_db.execute(
            text(
                """
                SELECT COUNT(*) * 8
                FROM user_time_entries
                WHERE user_id = :user_id
                  AND entry_date BETWEEN :period_start AND :period_end
                """
            ),
            {
                "user_id": user_id,
                "period_start": period_start,
                "period_end": period_end,
            },
        ).first()
        return float(row[0]) if row else 0

    def _get_vacation_days(
        self, user_id: str, period_start: date, period_end: date
    ) -> int | None:
        if self.timetrack_db is None:
            return None

        rows = self.timetrack_db.execute(
            text(
                """
                SELECT start_date, end_date
                FROM vacations
                WHERE user_id = :user_id
                  AND start_date <= :period_end
                  AND end_date >= :period_start
                """
            ),
            {
                "user_id": user_id,
                "period_start": period_start,
                "period_end": period_end,
            },
        ).mappings().all()
        total_days = 0
        for row in rows:
            start_date = max(self._as_date(row["start_date"]), period_start)
            end_date = min(self._as_date(row["end_date"]), period_end)
            total_days += (end_date - start_date).days + 1
        return total_days

    def _get_sick_days(self, user_id: str, period_start: date, period_end: date) -> int | None:
        if self.timetrack_db is None:
            return None

        row = self.timetrack_db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM user_time_entries
                WHERE user_id = :user_id
                  AND entry_date BETWEEN :period_start AND :period_end
                  AND day_type_id = '48f5ccec-d661-11f0-b7e5-b05cda34b6c7'
                """
            ),
            {
                "user_id": user_id,
                "period_start": period_start,
                "period_end": period_end,
            },
        ).first()
        return int(row[0]) if row else 0

    def _get_employee_salary(
        self, employee_id: str, period_start: date, period_end: date
    ) -> dict[str, Any] | None:
        row = self.db.execute(
            text(
                """
                SELECT employee_salary_id, salary_mounth, salary_hours, start_date, end_date
                FROM employee_salary
                WHERE employee_id = :employee_id
                  AND start_date <= :period_end
                  AND (end_date IS NULL OR end_date >= :period_start)
                ORDER BY start_date DESC
                LIMIT 1
                """
            ),
            {
                "employee_id": employee_id,
                "period_start": period_start,
                "period_end": period_end,
            },
        ).mappings().first()
        if not row:
            return None
        return {
            "employee_salary_id": row["employee_salary_id"],
            "salary_mounth": (
                float(row["salary_mounth"]) if row["salary_mounth"] is not None else None
            ),
            "salary_hours": (
                float(row["salary_hours"]) if row["salary_hours"] is not None else None
            ),
            "start_date": row["start_date"],
            "end_date": row["end_date"],
        }

    def _calculate_salary_total(
        self, salary: dict[str, Any] | None, standard_hours: float | None
    ) -> float:
        if not salary:
            return 0
        if salary["salary_mounth"] is not None:
            return salary["salary_mounth"]
        if salary["salary_hours"] is not None and standard_hours is not None:
            return salary["salary_hours"] * standard_hours
        return 0

    def _calculate_salary_accrued(
        self,
        salary: dict[str, Any] | None,
        standard_hours: float | None,
        worked_hours: float | None,
    ) -> float:
        if not salary or worked_hours is None:
            return 0
        if salary["salary_mounth"] is not None:
            if not standard_hours:
                return salary["salary_mounth"]
            return salary["salary_mounth"] / standard_hours * worked_hours
        if salary["salary_hours"] is not None:
            return salary["salary_hours"] * worked_hours
        return 0

    def _calculate_vacation_total(
        self,
        salary_total: float,
        vacation_days: int | None,
    ) -> float:
        if vacation_days is None:
            return 0
        return salary_total / 30 * vacation_days

    def _sum_operations_salary(
        self,
        employee_id: str,
        mounth_period: str,
        year: int,
        type_id: int | None = None,
        exclude_type_ids: list[int] | None = None,
    ) -> float:
        conditions = []
        params = {
            "employee_id": employee_id,
            "mounth_period": mounth_period,
            "year": year,
        }
        if type_id is not None:
            conditions.append("type_id = :type_id")
            params["type_id"] = type_id
        if exclude_type_ids:
            placeholders = [f":exclude_{i}" for i in range(len(exclude_type_ids))]
            conditions.append(f"type_id NOT IN ({', '.join(placeholders)})")
            for i, tid in enumerate(exclude_type_ids):
                params[f"exclude_{i}"] = tid
        type_filter = f"AND {' AND '.join(conditions)}" if conditions else ""
        row = self.db.execute(
            text(
                f"""
                SELECT COALESCE(SUM(value), 0)
                FROM operations_salary
                WHERE employee_id = :employee_id
                  AND nounth_period = :mounth_period
                  AND year = :year
                  {type_filter}
                """
            ),
            params,
        ).first()
        return float(row[0]) if row else 0

    def _sum_buh_salary(
        self,
        employee_id: str,
        mounth_period: str,
        year: int,
        type_id: int | None = None,
    ) -> float:
        type_filter = "AND type_id = :type_id" if type_id is not None else ""
        params = {
            "employee_id": employee_id,
            "mounth_period": mounth_period,
            "year": year,
        }
        if type_id is not None:
            params["type_id"] = type_id
        row = self.db.execute(
            text(
                f"""
                SELECT COALESCE(SUM(value), 0)
                FROM buh_salary
                WHERE employee_id = :employee_id
                  AND mounth_period = :mounth_period
                  AND year = :year
                  {type_filter}
                """
            ),
            params,
        ).first()
        return float(row[0]) if row else 0

    def _get_previous_overpayment(
        self, employee_id: str, mounth_period: str, year: int
    ) -> dict[str, Any] | None:
        previous = self._previous_month(mounth_period, year)
        if previous is None:
            return None

        previous_period, previous_year = previous
        employee_row = self.db.execute(
            text(
                """
                SELECT id AS employee_id, name, surname, patronymic, userId, marker
                FROM employee
                WHERE id = :employee_id
                LIMIT 1
                """
            ),
            {"employee_id": employee_id},
        ).mappings().first()
        if not employee_row:
            return None

        period_start, period_end = self._month_bounds(previous_period, previous_year)
        metrics = self._director_employee_metrics(
            employee_id=employee_id,
            user_id=employee_row["userId"],
            mounth_period=previous_period,
            year=previous_year,
            period_start=period_start,
            period_end=period_end,
            apply_overpayment=False,
        )
        overpayment = metrics["paid_total"] - metrics["salary_accrued"]
        if overpayment <= 0:
            return None
        return {
            "amount": overpayment,
            "from_mounth_period": previous_period,
            "from_year": previous_year,
            "reason": "Переплата прошлого периода учтена как оплаченная сумма",
        }

    def _get_person(self, person_id: str) -> dict[str, Any] | None:
        cache_key = ("person", person_id)
        if cache_key not in self._cache:
            row = self.db.execute(
                text(
                    """
                    SELECT id, name, surname, patronymic
                    FROM persons
                    WHERE id = :person_id
                    LIMIT 1
                    """
                ),
                {"person_id": person_id},
            ).mappings().first()
            self._cache[cache_key] = (
                {
                    "id": row["id"],
                    "name": row["name"],
                    "surname": row["surname"],
                    "patronymic": row["patronymic"],
                    "full_name": self._full_name(
                        row["surname"], row["name"], row["patronymic"]
                    ),
                }
                if row
                else None
            )
        return self._cache[cache_key]

    def _get_reference_name(self, table_name: str, row_id: str) -> str | None:
        cache_key = (f"reference_{table_name}", row_id)
        if cache_key not in self._cache:
            row = self.reference_db.execute(
                text(
                    f"""
                    SELECT short_name
                    FROM {table_name}
                    WHERE id = :row_id
                    LIMIT 1
                    """
                ),
                {"row_id": row_id},
            ).first()
            self._cache[cache_key] = row[0] if row else None
        return self._cache[cache_key]

    def _get_file(self, file_id: str) -> dict[str, Any] | None:
        cache_key = ("file", file_id)
        if cache_key not in self._cache:
            row = self.db.execute(
                text(
                    """
                    SELECT id, original_name, storage_name, file_path, uploaded_by, uploaded_at
                    FROM files
                    WHERE id = :file_id
                    LIMIT 1
                    """
                ),
                {"file_id": file_id},
            ).mappings().first()
            if row:
                data = dict(row)
                data["uploaded_by_user"] = self._get_auth_user(data["uploaded_by"])
                self._cache[cache_key] = data
            else:
                self._cache[cache_key] = None
        return self._cache[cache_key]

    def _get_receipt_list(self, receipt_list_id: int) -> dict[str, Any] | None:
        cache_key = ("receipt_list", receipt_list_id)
        if cache_key not in self._cache:
            row = self.db.execute(
                text(
                    """
                    SELECT id, name, user_id
                    FROM receipt_list
                    WHERE id = :receipt_list_id
                    LIMIT 1
                    """
                ),
                {"receipt_list_id": receipt_list_id},
            ).mappings().first()
            if row:
                data = dict(row)
                data["user"] = self._get_auth_user(data["user_id"])
                self._cache[cache_key] = data
            else:
                self._cache[cache_key] = None
        return self._cache[cache_key]

    def _get_receipt(self, receipt_id: int) -> dict[str, Any] | None:
        cache_key = ("receipt", receipt_id)
        if cache_key not in self._cache:
            row = self.db.execute(
                text(
                    """
                    SELECT
                        id,
                        store_name,
                        retailPlaceAddress,
                        fiscalDriveNumber,
                        fiscalDocumentNumber,
                        fiscalSign,
                        sum,
                        user_id,
                        receipt_list_id,
                        status,
                        created_at
                    FROM receipt
                    WHERE id = :receipt_id
                    LIMIT 1
                    """
                ),
                {"receipt_id": receipt_id},
            ).mappings().first()
            if row:
                data = dict(row)
                data["user"] = self._get_auth_user(data["user_id"])
                data["receipt_list"] = self._get_receipt_list(data["receipt_list_id"])
                data["categories"] = self._get_receipt_categories(data["id"])
                self._cache[cache_key] = data
            else:
                self._cache[cache_key] = None
        return self._cache[cache_key]

    def _get_receipt_items(self, receipt_id: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                SELECT id, receipt_id, name, quantity, price, nds, nds_sum, sum
                FROM receipt_item
                WHERE receipt_id = :receipt_id
                ORDER BY id
                """
            ),
            {"receipt_id": receipt_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def _get_extract_items(self, extract_id: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                SELECT id, extract_id, num, fio, employee_id,
                       account_num, bik, withheld, sum, result,
                       comment_result, consider
                FROM extract_item
                WHERE extract_id = :extract_id
                ORDER BY num
                """
            ),
            {"extract_id": extract_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def _sync_extract_item_ops(
        self,
        *,
        item: Any,
        old_employee_id: str | None,
        old_consider: bool,
        old_result: str | None,
        actor_id: str | None,
    ) -> None:
        new_employee_id = item.employee_id
        new_consider = item.consider
        new_result = item.result

        should_have = (
            new_employee_id is not None
            and new_consider
            and new_result == "Зачислено"
        )

        old_should_have = (
            old_employee_id is not None
            and old_consider
            and old_result == "Зачислено"
        )

        extract_row = self.db.execute(
            text("SELECT type, date, period FROM extracts WHERE id = :id LIMIT 1"),
            {"id": item.extract_id},
        ).mappings().first()
        if not extract_row:
            return
        if extract_row["type"] not in ("salary", "report", "vacation"):
            return

        if old_should_have and old_employee_id != new_employee_id:
            self.db.execute(
                text(
                    "DELETE FROM operations_salary WHERE extract_id = :eid AND employee_id = :e"
                ),
                {"eid": item.extract_id, "e": old_employee_id},
            )

        if should_have:
            existing = self.db.execute(
                text(
                    "SELECT id FROM operations_salary WHERE extract_id = :eid AND employee_id = :e LIMIT 1"
                ),
                {"eid": item.extract_id, "e": new_employee_id},
            ).first()

            extract_type = extract_row["type"]
            extract_date = extract_row["date"]
            period = extract_row["period"]
            now = datetime.utcnow()

            if extract_type == "salary":
                day = extract_date.day if extract_date else 1
                type_id = 1 if 20 <= day <= 30 else 2
            elif extract_type == "report":
                type_id = 6
            else:
                type_id = 4

            if existing:
                self.db.execute(
                    text(
                        """
                        UPDATE operations_salary
                        SET value = :value, date = :date, nounth_period = :period,
                            year = :year, type_id = :type_id
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": existing[0],
                        "value": item.sum,
                        "date": extract_date,
                        "period": period,
                        "year": extract_date.year if extract_date else datetime.utcnow().year,
                        "type_id": type_id,
                    },
                )
            else:
                op_id = str(uuid.uuid4())
                self.db.execute(
                    text(
                        """
                        INSERT INTO operations_salary (
                            id, date, nounth_period, year, employee_id,
                            created_by, value, type_id, method_id, extract_id, created_at
                        )
                        VALUES (
                            :id, :date, :period, :year, :employee_id,
                            :created_by, :value, :type_id, :method_id, :extract_id, :created_at
                        )
                        """
                    ),
                    {
                        "id": op_id,
                        "date": extract_date,
                        "period": period,
                        "year": extract_date.year if extract_date else datetime.utcnow().year,
                        "employee_id": new_employee_id,
                        "created_by": actor_id,
                        "value": item.sum,
                        "type_id": type_id,
                        "method_id": 3,
                        "extract_id": item.extract_id,
                        "created_at": now,
                    },
                )
        elif old_should_have:
            self.db.execute(
                text(
                    "DELETE FROM operations_salary WHERE extract_id = :eid AND employee_id = :e"
                ),
                {"eid": item.extract_id, "e": old_employee_id},
            )

    def _get_receipt_categories(self, receipt_id: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text(
                """
                SELECT rc.id, rc.receipt_id, rc.category_id, c.name AS category_name
                FROM receipt_category rc
                LEFT JOIN category c ON c.id = rc.category_id
                WHERE rc.receipt_id = :receipt_id
                ORDER BY rc.id
                """
            ),
            {"receipt_id": receipt_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def _get_object_name(self, object_id: str) -> str | None:
        reference_name = self._get_reference_name("objects", object_id)
        if reference_name:
            return reference_name
        return self._get_named_salary_row("objects", "id", object_id)

    def _get_salary_object(self, object_id: str) -> dict[str, Any] | None:
        cache_key = ("salary_object", object_id)
        if cache_key not in self._cache:
            row = self.db.execute(
                text(
                    """
                    SELECT id, name, object_id
                    FROM objects
                    WHERE id = :object_id
                    LIMIT 1
                    """
                ),
                {"object_id": object_id},
            ).mappings().first()
            self._cache[cache_key] = dict(row) if row else None
        return self._cache[cache_key]

    def _get_named_salary_row(self, table_name: str, key_name: str, row_id: Any) -> str | None:
        cache_key = (f"salary_{table_name}_{key_name}", row_id)
        if cache_key not in self._cache:
            row = self.db.execute(
                text(
                    f"""
                    SELECT name
                    FROM {table_name}
                    WHERE {key_name} = :row_id
                    LIMIT 1
                    """
                ),
                {"row_id": row_id},
            ).first()
            self._cache[cache_key] = row[0] if row else None
        return self._cache[cache_key]

    @staticmethod
    def _full_name(surname: str | None, name: str | None, patronymic: str | None) -> str | None:
        parts = [surname, name, patronymic]
        full_name = " ".join(part for part in parts if part)
        return full_name or None

    def _has_column(self, name: str) -> bool:
        return name in self.model.__table__.columns

    def _column(self, name: str):
        return self.model.__table__.columns[name]

    @staticmethod
    def _is_uuid_pk(column) -> bool:
        return getattr(column.type, "length", None) == 36

    @staticmethod
    def _month_number(mounth_period: str) -> int:
        month_numbers = {
            "jun": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "june": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        return month_numbers[mounth_period]

    @classmethod
    def _previous_month(cls, mounth_period: str, year: int) -> tuple[str, int] | None:
        month_number = cls._month_number(mounth_period)
        if month_number == 1:
            return "dec", year - 1

        periods_by_month = {
            1: "jun",
            2: "feb",
            3: "mar",
            4: "apr",
            5: "may",
            6: "june",
            7: "jul",
            8: "aug",
            9: "sep",
            10: "oct",
            11: "nov",
            12: "dec",
        }
        return periods_by_month[month_number - 1], year

    def _first_existing_column(
        self, db: Session, table_name: str, candidates: tuple[str, ...]
    ) -> str | None:
        cache_key = ("columns", db.bind.url.database if db.bind else "", table_name)
        if cache_key not in self._cache:
            rows = db.execute(
                text(
                    """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = :table_name
                    """
                ),
                {"table_name": table_name},
            ).fetchall()
            self._cache[cache_key] = {row[0] for row in rows}
        columns = self._cache[cache_key]
        return next((column for column in candidates if column in columns), None)

    @staticmethod
    def _as_date(value: date | datetime) -> date:
        return value.date() if isinstance(value, datetime) else value

    @staticmethod
    def _money(value: float) -> float:
        return round(float(value), 2)

    @staticmethod
    def _month_bounds(mounth_period: str, year: int):
        month_number = SalaryService._month_number(mounth_period)
        return (
            date(year, month_number, 1),
            date(year, month_number, monthrange(year, month_number)[1]),
        )
