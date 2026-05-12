from __future__ import annotations

import uuid
from datetime import datetime
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
    ) -> None:
        self.db = db
        self.model = model
        self.primary_key = primary_key
        self.auth_db = auth_db
        self.reference_db = reference_db
        self._cache: dict[tuple[str, Any], Any] = {}

    def list(self, limit: int = 100, offset: int = 0):
        rows = self.db.query(self.model).offset(offset).limit(limit).all()
        return [self._serialize(row) for row in rows]

    def get(self, row_id: Any):
        row = self._find(row_id)
        return self._serialize(row) if row else None

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
        self._apply_employee_user_data(data)
        self._apply_update_defaults(data, actor_id)
        for field, value in data.items():
            setattr(row, field, value)

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
                    AND os.type_id = bs.type_id
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

        if data.get("employee_id"):
            data["employee"] = self._get_employee(data["employee_id"])

        if data.get("counterparties_id"):
            data["counterparties_name"] = self._get_reference_name(
                "counterparties", data["counterparties_id"]
            )

        if data.get("object_id"):
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
                    SELECT id, name, surname, patronymic
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

    def _get_object_name(self, object_id: str) -> str | None:
        reference_name = self._get_reference_name("objects", object_id)
        if reference_name:
            return reference_name
        return self._get_named_salary_row("objects", "id", object_id)

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
    def _month_bounds(mounth_period: str, year: int):
        from calendar import monthrange
        from datetime import date

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
        month_number = month_numbers[mounth_period]
        return (
            date(year, month_number, 1),
            date(year, month_number, monthrange(year, month_number)[1]),
        )
