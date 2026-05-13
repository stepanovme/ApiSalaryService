from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import text
from sqlalchemy.orm import Session


OPERATIONS_FILE_DIR = Path(
    os.getenv("OPERATIONS_FILE_DIR", "/home/webserver/models/finance/operations")
)


class FileService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_files(self, limit: int = 100, offset: int = 0):
        rows = self.db.execute(
            text(
                """
                SELECT id, original_name, storage_name, file_path, uploaded_by, uploaded_at
                FROM files
                ORDER BY uploaded_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        ).mappings().all()
        return [dict(row) for row in rows]

    def get_file(self, file_id: str) -> dict | None:
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
        return dict(row) if row else None

    def upload_file(self, *, original_name: str, uploaded_by: str, file_stream: BinaryIO):
        OPERATIONS_FILE_DIR.mkdir(parents=True, exist_ok=True)
        file_id = str(uuid.uuid4())
        safe_name = self._safe_filename(original_name)
        storage_name = f"{file_id}_{safe_name}"
        file_path = OPERATIONS_FILE_DIR / storage_name

        with file_path.open("wb") as output:
            while chunk := file_stream.read(1024 * 1024):
                output.write(chunk)

        uploaded_at = datetime.utcnow()
        self.db.execute(
            text(
                """
                INSERT INTO files (
                    id, original_name, storage_name, file_path, uploaded_by, uploaded_at
                )
                VALUES (
                    :id, :original_name, :storage_name, :file_path, :uploaded_by, :uploaded_at
                )
                """
            ),
            {
                "id": file_id,
                "original_name": original_name,
                "storage_name": storage_name,
                "file_path": str(file_path),
                "uploaded_by": uploaded_by,
                "uploaded_at": uploaded_at,
            },
        )
        self.db.commit()
        return self.get_file(file_id)

    def delete_file(self, file_id: str) -> dict | None:
        data = self.get_file(file_id)
        if not data:
            return None

        file_path = Path(data["file_path"])
        if file_path.exists():
            file_path.unlink()

        self.db.execute(text("DELETE FROM files WHERE id = :file_id"), {"file_id": file_id})
        self.db.commit()
        return data

    @staticmethod
    def _safe_filename(file_name: str) -> str:
        cleaned = Path(file_name).name.strip() or "file"
        return re.sub(r"[^A-Za-zА-Яа-я0-9._-]+", "_", cleaned)[:180]
