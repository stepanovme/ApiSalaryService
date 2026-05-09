from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session


class SalaryService:
    def __init__(self, db: Session, model: type, primary_key: str) -> None:
        self.db = db
        self.model = model
        self.primary_key = primary_key

    def list(self, limit: int = 100, offset: int = 0):
        rows = self.db.query(self.model).offset(offset).limit(limit).all()
        return [self._serialize(row) for row in rows]

    def get(self, row_id: Any):
        row = self._find(row_id)
        return self._serialize(row) if row else None

    def create(self, payload: BaseModel, actor_id: str | None):
        data = payload.model_dump(exclude_none=True)
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
        return {column.key: getattr(row, column.key) for column in inspect(row).mapper.column_attrs}

    def _has_column(self, name: str) -> bool:
        return name in self.model.__table__.columns

    def _column(self, name: str):
        return self.model.__table__.columns[name]

    @staticmethod
    def _is_uuid_pk(column) -> bool:
        return getattr(column.type, "length", None) == 36
