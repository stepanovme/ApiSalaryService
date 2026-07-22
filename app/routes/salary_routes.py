import asyncio
import atexit
import os
import re
import tempfile
import uuid
from datetime import datetime
from typing import Any
from pathlib import Path
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import text

from app.database import AuthDbSession, DbSession, ReferenceDbSession, SalarySessionLocal, TimetrackDbSession
from app.middleware.auth_middleware import get_session
from app.models.salary import (
    AllowedDeviceDB,
    AuthSessionDB,
    BuhSalaryDB,
    CategoryDB,
    EmployeeDB,
    EmployeeSalaryDB,
    EmploymentHistoryDB,
    ExtractDB,
    ExtractFilesDB,
    ExtractItemDB,
    FileDB,
    FinancialSourceDB,
    MethodDB,
    ObjectDB,
    OperationDB,
    OperationSalaryDB,
    PersonDB,
    ReceiptCategoryDB,
    ReceiptDB,
    ReceiptItemDB,
    ReceiptListDB,
    ReceiptListViewDB,
    TypeDB,
)
from app.repositories.session_repository import AuthenticatedSession
from app.schemas import (
    AllowedDeviceCreate,
    AllowedDeviceUpdate,
    AuthSessionCreate,
    AuthSessionUpdate,
    BuhSalaryCreate,
    BuhSalaryUpdate,
    DictionaryCreate,
    DictionaryUpdate,
    EmployeeCreate,
    EmployeeSalaryCreate,
    EmployeeSalaryUpdate,
    EmployeeUpdate,
    EmploymentHistoryCreate,
    EmploymentHistoryUpdate,
    ExtractCreate,
    ExtractFilesCreate,
    ExtractFilesUpdate,
    ExtractItemCreate,
    ExtractItemUpdate,
    ExtractUpdate,
    FinancialSourceCreate,
    FinancialSourceUpdate,
    MonthPeriod,
    NamedCreate,
    NamedUpdate,
    ObjectCreate,
    ObjectUpdate,
    OperationCreate,
    OperationSalaryCreate,
    OperationSalaryUpdate,
    OperationUpdate,
    PersonCreate,
    PersonUpdate,
    ReceiptCategoryCreate,
    ReceiptCategoryUpdate,
    ReceiptCreate,
    ReceiptItemCreate,
    ReceiptItemUpdate,
    ReceiptListCreate,
    ReceiptListUpdate,
    ReceiptListViewCreate,
    ReceiptListViewUpdate,
    ReceiptUpdate,
)
from app.services.salary_service import SalaryService
from app.services.mistral_service import MistralOperationDraftService
from app.services.file_service import FileService
from app.services.extract_ai_service import ExtractAIService

salary_router = APIRouter()


def register_crud(
    *,
    prefix: str,
    tags: list[str],
    model: type,
    primary_key: str,
    create_schema: type,
    update_schema: type,
):
    router = APIRouter(prefix=prefix, tags=tags)

    def get_service(db: DbSession, auth_db: AuthDbSession, reference_db: ReferenceDbSession):
        return SalaryService(db, model, primary_key, auth_db, reference_db)

    def list_items(
        db: DbSession,
        auth_db: AuthDbSession,
        reference_db: ReferenceDbSession,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None = None,
        employee_id: str | None = None,
        receipt_list_id: int | None = None,
        current_session: AuthenticatedSession = Depends(get_session),
    ):
        _ = current_session
        return get_service(db, auth_db, reference_db).list(
            limit=limit,
            offset=offset,
            filters={
                "user_id": user_id,
                "employee_id": employee_id,
                "receipt_list_id": receipt_list_id,
            },
        )

    def get_item(
        item_id: str,
        db: DbSession,
        auth_db: AuthDbSession,
        reference_db: ReferenceDbSession,
        current_session: AuthenticatedSession = Depends(get_session),
    ):
        _ = current_session
        data = get_service(db, auth_db, reference_db).get(item_id)
        if not data:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        return data

    def create_item(
        payload,
        db: DbSession,
        auth_db: AuthDbSession,
        reference_db: ReferenceDbSession,
        current_session: AuthenticatedSession = Depends(get_session),
    ):
        try:
            return get_service(db, auth_db, reference_db).create(
                payload,
                current_session.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def update_item(
        item_id: str,
        payload,
        db: DbSession,
        auth_db: AuthDbSession,
        reference_db: ReferenceDbSession,
        current_session: AuthenticatedSession = Depends(get_session),
    ):
        try:
            data = get_service(db, auth_db, reference_db).update(
                item_id,
                payload,
                current_session.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not data:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        return data

    def delete_item(
        item_id: str,
        db: DbSession,
        auth_db: AuthDbSession,
        reference_db: ReferenceDbSession,
        current_session: AuthenticatedSession = Depends(get_session),
    ):
        _ = current_session
        try:
            data = get_service(db, auth_db, reference_db).delete(item_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not data:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        return data

    create_item.__annotations__["payload"] = create_schema
    update_item.__annotations__["payload"] = update_schema
    list_items.__name__ = f"list_{prefix.strip('/').replace('-', '_')}"
    get_item.__name__ = f"get_{prefix.strip('/').replace('-', '_')}"
    create_item.__name__ = f"create_{prefix.strip('/').replace('-', '_')}"
    update_item.__name__ = f"update_{prefix.strip('/').replace('-', '_')}"
    delete_item.__name__ = f"delete_{prefix.strip('/').replace('-', '_')}"

    router.add_api_route("", list_items, methods=["GET"], summary="Список записей")
    router.add_api_route("/{item_id}", get_item, methods=["GET"], summary="Получить запись")
    router.add_api_route("", create_item, methods=["POST"], summary="Создать запись")
    router.add_api_route(
        "/{item_id}", update_item, methods=["PATCH"], summary="Изменить запись"
    )
    router.add_api_route(
        "/{item_id}", delete_item, methods=["DELETE"], summary="Удалить запись"
    )
    salary_router.include_router(router)


@salary_router.get(
    "/buh-salaries/report",
    tags=["Бухгалтерские начисления"],
    summary="Отчёт бухгалтерских начислений по периоду",
)
def get_buh_salary_report(
    mounth_period: MonthPeriod,
    year: int,
    db: DbSession,
    auth_db: AuthDbSession,
    reference_db: ReferenceDbSession,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    return SalaryService(
        db,
        BuhSalaryDB,
        "id",
        auth_db,
        reference_db,
    ).buh_salary_report(mounth_period, year)


@salary_router.get(
    "/director-salaries/report",
    tags=["Директорская зарплата"],
    summary="Директорский отчёт по зарплате за период",
)
def get_director_salary_report(
    mounth_period: MonthPeriod,
    year: int,
    db: DbSession,
    auth_db: AuthDbSession,
    reference_db: ReferenceDbSession,
    timetrack_db: TimetrackDbSession,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    try:
        return SalaryService(
            db,
            EmployeeDB,
            "id",
            auth_db,
            reference_db,
            timetrack_db,
        ).director_salary_report(mounth_period, year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@salary_router.post(
    "/operations/ai-draft",
    tags=["Операции"],
    summary="AI-черновик операции из текста или файла",
)
async def create_operation_ai_draft(
    db: DbSession,
    prompt: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    photo: UploadFile | None = File(default=None),
    receipt: UploadFile | None = File(default=None),
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    upload = file or photo or receipt
    file_name = upload.filename if upload else None
    content_type = upload.content_type if upload else None
    file_bytes = await upload.read() if upload else None
    if not prompt and not file_bytes:
        raise HTTPException(status_code=400, detail="Передайте prompt или файл")

    service = MistralOperationDraftService(db)
    try:
        return await service.create_operation_draft(
            prompt=prompt,
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Mistral API error: {exc.response.status_code} {exc.response.text}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Mistral API error: {exc}") from exc


@salary_router.get(
    "/files",
    tags=["Файлы"],
    summary="Список файлов",
)
def list_files(
    db: DbSession,
    limit: int = 100,
    offset: int = 0,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    return FileService(db).list_files(limit=limit, offset=offset)


@salary_router.get(
    "/files/{file_id}",
    tags=["Файлы"],
    summary="Получить информацию о файле",
)
def get_file(
    file_id: str,
    db: DbSession,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    data = FileService(db).get_file(file_id)
    if not data:
        raise HTTPException(status_code=404, detail="Файл не найден")
    return data


@salary_router.get(
    "/files/{file_id}/download",
    tags=["Файлы"],
    summary="Скачать файл",
)
def download_file(
    file_id: str,
    db: DbSession,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    data = FileService(db).get_file(file_id)
    if not data:
        raise HTTPException(status_code=404, detail="Файл не найден")
    file_path = Path(data["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл отсутствует на диске")
    download_name = data["original_name"] or file_path.name
    fallback_name = _ascii_download_name(download_name)
    disposition = (
        f'attachment; filename="{fallback_name}"; '
        f"filename*=UTF-8''{quote(download_name, safe='')}"
    )
    return FileResponse(
        path=file_path,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@salary_router.post(
    "/files",
    tags=["Файлы"],
    summary="Загрузить файл",
)
async def upload_file(
    db: DbSession,
    file: UploadFile = File(...),
    current_session: AuthenticatedSession = Depends(get_session),
):
    if not current_session.user_id:
        raise HTTPException(status_code=400, detail="Не удалось определить uploaded_by")
    return FileService(db).upload_file(
        original_name=file.filename or "file",
        uploaded_by=current_session.user_id,
        file_stream=file.file,
    )


@salary_router.delete(
    "/files/{file_id}",
    tags=["Файлы"],
    summary="Удалить файл",
)
def delete_file(
    file_id: str,
    db: DbSession,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    data = FileService(db).delete_file(file_id)
    if not data:
        raise HTTPException(status_code=404, detail="Файл не найден")
    return data


@salary_router.websocket("/auth-ws")
async def auth_websocket(websocket: WebSocket):
    await websocket.accept()

    db = SalarySessionLocal()
    session_device_id = str(uuid.uuid4())
    try:
        while True:
            token_id = str(uuid.uuid4())
            now = datetime.utcnow()
            session = AuthSessionDB(
                token_id=token_id,
                status="pending",
                device_id=session_device_id,
                created_at=now,
            )
            db.add(session)
            db.commit()

            await websocket.send_json({
                "type": "token_created",
                "token_id": token_id,
            })

            last_status = "pending"
            token_created_at = datetime.utcnow()

            while True:
                await asyncio.sleep(1)

                db.commit()
                result = db.execute(
                    text("SELECT status FROM auth_session WHERE token_id = :token_id"),
                    {"token_id": token_id},
                ).first()
                current_status = result[0] if result else None

                if current_status is not None and current_status != last_status:
                    await websocket.send_json({
                        "type": "status_changed",
                        "token_id": token_id,
                        "status": current_status,
                    })
                    last_status = current_status

                elapsed = (datetime.utcnow() - token_created_at).total_seconds()
                if elapsed >= 60:
                    db.execute(
                        text(
                            "DELETE FROM auth_session "
                            "WHERE token_id = :token_id AND status = 'pending'"
                        ),
                        {"token_id": token_id},
                    )
                    db.commit()
                    break
    except WebSocketDisconnect:
        pass
    finally:
        db.close()


async def verify_api_key(api_key: str = Header(alias="api-key")):
    if api_key != "bN_vkSL4O1bN_vkSL4O1":
        raise HTTPException(status_code=403, detail="Invalid API key")


def _auth_service(db: DbSession) -> SalaryService:
    return SalaryService(db, AuthSessionDB, "token_id", db, db)


def _device_service(db: DbSession) -> SalaryService:
    return SalaryService(db, AllowedDeviceDB, "device_id", db, db)


@salary_router.post("/auth-sessions", tags=["Сессии авторизации"], summary="Создать сессию")
def create_auth_session(
    payload: AuthSessionCreate,
    db: DbSession,
    _: None = Depends(verify_api_key),
):
    return _auth_service(db).create(payload, None)


@salary_router.get(
    "/auth-sessions/{token_id}",
    tags=["Сессии авторизации"],
    summary="Получить сессию",
)
def get_auth_session(
    token_id: str,
    db: DbSession,
    _: None = Depends(verify_api_key),
):
    data = _auth_service(db).get(token_id)
    if not data:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return data


@salary_router.patch(
    "/auth-sessions/{token_id}",
    tags=["Сессии авторизации"],
    summary="Изменить сессию",
)
def update_auth_session(
    token_id: str,
    payload: AuthSessionUpdate,
    db: DbSession,
    _: None = Depends(verify_api_key),
):
    try:
        data = _auth_service(db).update(token_id, payload, None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not data:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return data


@salary_router.delete(
    "/auth-sessions/{token_id}",
    tags=["Сессии авторизации"],
    summary="Удалить сессию",
)
def delete_auth_session(
    token_id: str,
    db: DbSession,
    _: None = Depends(verify_api_key),
):
    data = _auth_service(db).delete(token_id)
    if not data:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return data


@salary_router.post("/allowed-devices", tags=["Допущенные устройства"], summary="Создать устройство")
def create_allowed_device(
    payload: AllowedDeviceCreate,
    db: DbSession,
    _: None = Depends(verify_api_key),
):
    return _device_service(db).create(payload, None)


@salary_router.get(
    "/allowed-devices/{device_id}",
    tags=["Допущенные устройства"],
    summary="Получить устройство",
)
def get_allowed_device(
    device_id: str,
    db: DbSession,
    _: None = Depends(verify_api_key),
):
    data = _device_service(db).get(device_id)
    if not data:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return data


@salary_router.patch(
    "/allowed-devices/{device_id}",
    tags=["Допущенные устройства"],
    summary="Изменить устройство",
)
def update_allowed_device(
    device_id: str,
    payload: AllowedDeviceUpdate,
    db: DbSession,
    _: None = Depends(verify_api_key),
):
    try:
        data = _device_service(db).update(device_id, payload, None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not data:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return data


@salary_router.delete(
    "/allowed-devices/{device_id}",
    tags=["Допущенные устройства"],
    summary="Удалить устройство",
)
def delete_allowed_device(
    device_id: str,
    db: DbSession,
    _: None = Depends(verify_api_key),
):
    data = _device_service(db).delete(device_id)
    if not data:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return data


EXTRACTS_FILE_DIR = Path("/home/webserver/models/finance/extracts")


def _safe_filename(file_name: str) -> str:
    cleaned = Path(file_name).name.strip() or "file"
    return re.sub(r"[^A-Za-zА-Яа-я0-9._-]+", "_", cleaned)[:180]


@salary_router.post(
    "/extract-files",
    tags=["Файлы выписок"],
    summary="Загрузить файл выписки",
)
async def upload_extract_file(
    db: DbSession,
    extract_id: int = Form(...),
    file: UploadFile = File(...),
    current_session: AuthenticatedSession = Depends(get_session),
):
    if not current_session.user_id:
        raise HTTPException(status_code=400, detail="Не удалось определить uploaded_by")

    EXTRACTS_FILE_DIR.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    safe_name = _safe_filename(file.filename or "file")
    ext = Path(file.filename).suffix if file.filename else None
    storage_name = f"{file_id}_{safe_name}"
    file_path = EXTRACTS_FILE_DIR / storage_name

    with file_path.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            output.write(chunk)

    uploaded_at = datetime.utcnow()
    db.execute(
        text(
            """
            INSERT INTO extract_files (
                id, extract_id, original_name, storage_name, extension,
                mime_type, file_path, uploaded_by, uploaded_at
            )
            VALUES (
                :id, :extract_id, :original_name, :storage_name, :extension,
                :mime_type, :file_path, :uploaded_by, :uploaded_at
            )
            """
        ),
        {
            "id": file_id,
            "extract_id": extract_id,
            "original_name": file.filename,
            "storage_name": storage_name,
            "extension": ext,
            "mime_type": file.content_type,
            "file_path": str(file_path),
            "uploaded_by": current_session.user_id,
            "uploaded_at": uploaded_at,
        },
    )
    db.commit()

    row = db.execute(
        text("SELECT * FROM extract_files WHERE id = :id"), {"id": file_id}
    ).mappings().first()
    return dict(row) if row else None


@salary_router.get(
    "/extract-files",
    tags=["Файлы выписок"],
    summary="Список файлов выписки",
)
def list_extract_files(
    db: DbSession,
    extract_id: int | None = None,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    if extract_id:
        rows = db.execute(
            text(
                "SELECT * FROM extract_files WHERE extract_id = :extract_id ORDER BY uploaded_at DESC"
            ),
            {"extract_id": extract_id},
        ).mappings().all()
    else:
        rows = db.execute(
            text("SELECT * FROM extract_files ORDER BY uploaded_at DESC")
        ).mappings().all()
    return [dict(row) for row in rows]


@salary_router.get(
    "/extract-files/{file_id}",
    tags=["Файлы выписок"],
    summary="Получить информацию о файле",
)
def get_extract_file(
    file_id: str,
    db: DbSession,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    row = db.execute(
        text("SELECT * FROM extract_files WHERE id = :file_id LIMIT 1"),
        {"file_id": file_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Файл не найден")
    return dict(row)


@salary_router.get(
    "/extract-files/{file_id}/download",
    tags=["Файлы выписок"],
    summary="Скачать файл",
)
def download_extract_file(
    file_id: str,
    db: DbSession,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    row = db.execute(
        text("SELECT * FROM extract_files WHERE id = :file_id LIMIT 1"),
        {"file_id": file_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Файл не найден")
    file_path = Path(row["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл отсутствует на диске")
    return FileResponse(
        path=file_path,
        media_type=row["mime_type"] or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{row["original_name"]}"'
        },
    )


@salary_router.patch(
    "/extract-files/{file_id}",
    tags=["Файлы выписок"],
    summary="Изменить метаданные файла",
)
def update_extract_file(
    file_id: str,
    payload: ExtractFilesUpdate,
    db: DbSession,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    row = db.execute(
        text("SELECT * FROM extract_files WHERE id = :file_id LIMIT 1"),
        {"file_id": file_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Файл не найден")

    data = payload.model_dump(exclude_unset=True)
    if not data:
        return dict(row)

    sets = ", ".join(f"{k} = :{k}" for k in data)
    data["file_id"] = file_id
    db.execute(
        text(f"UPDATE extract_files SET {sets} WHERE id = :file_id"),
        data,
    )
    db.commit()

    updated = db.execute(
        text("SELECT * FROM extract_files WHERE id = :file_id LIMIT 1"),
        {"file_id": file_id},
    ).mappings().first()
    return dict(updated) if updated else None


@salary_router.delete(
    "/extract-files/{file_id}",
    tags=["Файлы выписок"],
    summary="Удалить файл",
)
def delete_extract_file(
    file_id: str,
    db: DbSession,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    row = db.execute(
        text("SELECT * FROM extract_files WHERE id = :file_id LIMIT 1"),
        {"file_id": file_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Файл не найден")

    file_path = Path(row["file_path"])
    if file_path.exists():
        file_path.unlink()

    db.execute(
        text("DELETE FROM extract_files WHERE id = :file_id"),
        {"file_id": file_id},
    )
    db.commit()
    return dict(row)


@salary_router.post(
    "/extracts/process-file",
    tags=["Выписки"],
    summary="Распознать файл через ИИ и создать выписку",
)
async def process_extract_file(
    db: DbSession,
    reference_db: ReferenceDbSession,
    file: UploadFile = File(...),
    current_session: AuthenticatedSession = Depends(get_session),
):
    file_bytes = await file.read()
    service = ExtractAIService(db, reference_db)
    try:
        return await service.process_file(
            file_bytes=file_bytes,
            file_name=file.filename,
            content_type=file.content_type,
            actor_id=current_session.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Mistral API error: {exc.response.status_code} {exc.response.text}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Mistral API error: {exc}") from exc


def _ascii_download_name(file_name: str) -> str:
    suffix = Path(file_name).suffix
    stem = Path(file_name).stem or "file"
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "file"
    if suffix and not fallback.endswith(suffix):
        fallback = f"{fallback}{suffix}"
    return fallback


_sberbank_cert_path: str | None = None
_sberbank_key_path: str | None = None


def _sberbank_pfx_cert() -> tuple[str, str]:
    global _sberbank_cert_path, _sberbank_key_path

    if _sberbank_cert_path and _sberbank_key_path:
        return _sberbank_cert_path, _sberbank_key_path

    pfx_path = os.getenv("SBERBANK_PFX_PATH")
    passphrase = os.getenv("SBERBANK_PFX_PASSPHRASE")
    if not pfx_path:
        raise HTTPException(status_code=500, detail="SBERBANK_PFX_PATH not configured")
    if not os.path.exists(pfx_path):
        raise HTTPException(
            status_code=500,
            detail=f"SBERBANK_PFX_PATH not found: {pfx_path}",
        )

    with open(pfx_path, "rb") as f:
        pfx_data = f.read()

    try:
        pfx_password = passphrase.encode() if passphrase else None
        private_key, certificate, _ = pkcs12.load_key_and_certificates(
            pfx_data, pfx_password
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse PFX (check format or passphrase): {exc}",
        ) from exc

    if not certificate or not private_key:
        raise HTTPException(
            status_code=500,
            detail="PFX contains no certificate or private key",
        )

    cert_pem = certificate.public_bytes(Encoding.PEM)
    key_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    )

    cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="wb")
    cert_file.write(cert_pem)
    cert_file.close()
    _sberbank_cert_path = cert_file.name

    key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="wb")
    key_file.write(key_pem)
    key_file.close()
    _sberbank_key_path = key_file.name

    return _sberbank_cert_path, _sberbank_key_path


@atexit.register
def _cleanup_sberbank_cert():
    for path in (_sberbank_cert_path, _sberbank_key_path):
        if path and os.path.exists(path):
            os.unlink(path)


@salary_router.get(
    "/bank-accounts/balance",
    tags=["Банковские счета"],
    summary="Баланс и обороты по счёту из Sberbank API",
)
async def get_bank_account_balance(
    account_number: str,
    statement_date: str | None = None,
    current_session: AuthenticatedSession = Depends(get_session),
):
    _ = current_session
    host = os.getenv("SBERBANK_API_HOST")
    if not host:
        raise HTTPException(status_code=500, detail="SBERBANK_API_HOST not configured")

    token = os.getenv("SBERBANK_API_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="SBERBANK_API_TOKEN not configured")

    cert_path, key_path = _sberbank_pfx_cert()
    params = {"accountNumber": account_number}
    if statement_date:
        params["statementDate"] = statement_date

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        verify=False, cert=(cert_path, key_path), timeout=30
    ) as client:
        try:
            resp = await client.get(
                f"{host}/fintech/api/v2/statement/summary",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"Sberbank API error: {exc.response.text}",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"Sberbank API error: {exc}"
            ) from exc


crud_resources: list[dict[str, Any]] = [
    {
        "prefix": "/buh-salaries",
        "tags": ["Бухгалтерские начисления"],
        "model": BuhSalaryDB,
        "primary_key": "id",
        "create_schema": BuhSalaryCreate,
        "update_schema": BuhSalaryUpdate,
    },
    {
        "prefix": "/categories",
        "tags": ["Категории"],
        "model": CategoryDB,
        "primary_key": "id",
        "create_schema": NamedCreate,
        "update_schema": NamedUpdate,
    },
    {
        "prefix": "/employees",
        "tags": ["Сотрудники"],
        "model": EmployeeDB,
        "primary_key": "id",
        "create_schema": EmployeeCreate,
        "update_schema": EmployeeUpdate,
    },
    {
        "prefix": "/employee-salaries",
        "tags": ["Оклады сотрудников"],
        "model": EmployeeSalaryDB,
        "primary_key": "employee_salary_id",
        "create_schema": EmployeeSalaryCreate,
        "update_schema": EmployeeSalaryUpdate,
    },
    {
        "prefix": "/employment-history",
        "tags": ["История трудоустройства"],
        "model": EmploymentHistoryDB,
        "primary_key": "employment_history_id",
        "create_schema": EmploymentHistoryCreate,
        "update_schema": EmploymentHistoryUpdate,
    },
    {
        "prefix": "/financial-sources",
        "tags": ["Источники финансирования"],
        "model": FinancialSourceDB,
        "primary_key": "id",
        "create_schema": FinancialSourceCreate,
        "update_schema": FinancialSourceUpdate,
    },
    {
        "prefix": "/methods",
        "tags": ["Методы оплаты"],
        "model": MethodDB,
        "primary_key": "id",
        "create_schema": DictionaryCreate,
        "update_schema": DictionaryUpdate,
    },
    {
        "prefix": "/objects",
        "tags": ["Объекты"],
        "model": ObjectDB,
        "primary_key": "id",
        "create_schema": ObjectCreate,
        "update_schema": ObjectUpdate,
    },
    {
        "prefix": "/operations",
        "tags": ["Операции"],
        "model": OperationDB,
        "primary_key": "id",
        "create_schema": OperationCreate,
        "update_schema": OperationUpdate,
    },
    {
        "prefix": "/salary-operations",
        "tags": ["Операции по зарплате"],
        "model": OperationSalaryDB,
        "primary_key": "id",
        "create_schema": OperationSalaryCreate,
        "update_schema": OperationSalaryUpdate,
    },
    {
        "prefix": "/persons",
        "tags": ["Физлица"],
        "model": PersonDB,
        "primary_key": "id",
        "create_schema": PersonCreate,
        "update_schema": PersonUpdate,
    },
    {
        "prefix": "/receipt-lists",
        "tags": ["Списки чеков"],
        "model": ReceiptListDB,
        "primary_key": "id",
        "create_schema": ReceiptListCreate,
        "update_schema": ReceiptListUpdate,
    },
    {
        "prefix": "/receipts",
        "tags": ["Чеки"],
        "model": ReceiptDB,
        "primary_key": "id",
        "create_schema": ReceiptCreate,
        "update_schema": ReceiptUpdate,
    },
    {
        "prefix": "/receipt-categories",
        "tags": ["Категории чеков"],
        "model": ReceiptCategoryDB,
        "primary_key": "id",
        "create_schema": ReceiptCategoryCreate,
        "update_schema": ReceiptCategoryUpdate,
    },
    {
        "prefix": "/receipt-items",
        "tags": ["Позиции чеков"],
        "model": ReceiptItemDB,
        "primary_key": "id",
        "create_schema": ReceiptItemCreate,
        "update_schema": ReceiptItemUpdate,
    },
    {
        "prefix": "/receipt-list-views",
        "tags": ["Доступ к спискам чеков"],
        "model": ReceiptListViewDB,
        "primary_key": "id",
        "create_schema": ReceiptListViewCreate,
        "update_schema": ReceiptListViewUpdate,
    },
    {
        "prefix": "/types",
        "tags": ["Типы начислений"],
        "model": TypeDB,
        "primary_key": "id",
        "create_schema": DictionaryCreate,
        "update_schema": DictionaryUpdate,
    },
    {
        "prefix": "/extracts",
        "tags": ["Выписки"],
        "model": ExtractDB,
        "primary_key": "id",
        "create_schema": ExtractCreate,
        "update_schema": ExtractUpdate,
    },
    {
        "prefix": "/extract-items",
        "tags": ["Позиции выписок"],
        "model": ExtractItemDB,
        "primary_key": "id",
        "create_schema": ExtractItemCreate,
        "update_schema": ExtractItemUpdate,
    },
]

for resource in crud_resources:
    register_crud(**resource)
