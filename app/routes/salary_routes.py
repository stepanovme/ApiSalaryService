import asyncio
import re
import uuid
from datetime import datetime
from typing import Any
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

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

                db.expire_all()
                row = db.query(AuthSessionDB).filter(
                    AuthSessionDB.token_id == token_id
                ).first()

                if row and row.status != last_status:
                    await websocket.send_json({
                        "type": "status_changed",
                        "token_id": token_id,
                        "status": row.status,
                    })
                    last_status = row.status

                elapsed = (datetime.utcnow() - token_created_at).total_seconds()
                if elapsed >= 60:
                    if row and row.status == "pending":
                        db.delete(row)
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


def _ascii_download_name(file_name: str) -> str:
    suffix = Path(file_name).suffix
    stem = Path(file_name).stem or "file"
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "file"
    if suffix and not fallback.endswith(suffix):
        fallback = f"{fallback}{suffix}"
    return fallback


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
]

for resource in crud_resources:
    register_crud(**resource)
