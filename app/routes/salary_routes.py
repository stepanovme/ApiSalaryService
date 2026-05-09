from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.database import DbSession
from app.middleware.auth_middleware import get_session
from app.models.salary import (
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
    TypeDB,
)
from app.repositories.session_repository import AuthenticatedSession
from app.schemas import (
    DictionaryCreate,
    DictionaryUpdate,
    EmployeeCreate,
    EmployeeSalaryCreate,
    EmployeeSalaryUpdate,
    EmployeeUpdate,
    EmploymentHistoryCreate,
    EmploymentHistoryUpdate,
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
)
from app.services.salary_service import SalaryService

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

    def list_items(
        db: DbSession,
        limit: int = 100,
        offset: int = 0,
        current_session: AuthenticatedSession = Depends(get_session),
    ):
        _ = current_session
        return SalaryService(db, model, primary_key).list(limit=limit, offset=offset)

    def get_item(
        item_id: str,
        db: DbSession,
        current_session: AuthenticatedSession = Depends(get_session),
    ):
        _ = current_session
        data = SalaryService(db, model, primary_key).get(item_id)
        if not data:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        return data

    def create_item(
        payload,
        db: DbSession,
        current_session: AuthenticatedSession = Depends(get_session),
    ):
        try:
            return SalaryService(db, model, primary_key).create(
                payload, current_session.user_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def update_item(
        item_id: str,
        payload,
        db: DbSession,
        current_session: AuthenticatedSession = Depends(get_session),
    ):
        try:
            data = SalaryService(db, model, primary_key).update(
                item_id, payload, current_session.user_id
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not data:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        return data

    def delete_item(
        item_id: str,
        db: DbSession,
        current_session: AuthenticatedSession = Depends(get_session),
    ):
        _ = current_session
        try:
            data = SalaryService(db, model, primary_key).delete(item_id)
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


crud_resources: list[dict[str, Any]] = [
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
        "create_schema": NamedCreate,
        "update_schema": NamedUpdate,
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
