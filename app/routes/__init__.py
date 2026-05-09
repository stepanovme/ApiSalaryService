from fastapi import APIRouter

from app.routes.salary_routes import salary_router

main_router = APIRouter(prefix="/api/salary")

main_router.include_router(salary_router)
