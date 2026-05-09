from fastapi import FastAPI

from app.routes import main_router

app = FastAPI(
    title="SalaryService",
    debug=True,
)

app.include_router(main_router)
