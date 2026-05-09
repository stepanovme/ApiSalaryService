from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class SalarySchema(BaseModel):
    model_config = ConfigDict(use_enum_values=True)


class EmployeeMarker(StrEnum):
    EV = "EV"
    VV = "VV"
    OV = "OV"


class OperationKind(StrEnum):
    entrance = "entrance"
    expenditure = "expenditure"


class MonthPeriod(StrEnum):
    jun = "jun"
    feb = "feb"
    mar = "mar"
    apr = "apr"
    may = "may"
    june = "june"
    jul = "jul"
    aug = "aug"
    sep = "sep"
    oct = "oct"
    nov = "nov"
    dec = "dec"


class NamedCreate(SalarySchema):
    id: Optional[str] = None
    name: str
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class NamedUpdate(SalarySchema):
    name: Optional[str] = None
    edit_by: Optional[str] = None


class DictionaryCreate(SalarySchema):
    id: Optional[int] = None
    name: str
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class DictionaryUpdate(SalarySchema):
    name: Optional[str] = None
    edit_by: Optional[str] = None


class EmployeeCreate(SalarySchema):
    id: Optional[str] = None
    name: Optional[str] = None
    surname: Optional[str] = None
    patronymic: Optional[str] = None
    userId: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    marker: Optional[EmployeeMarker] = None


class EmployeeUpdate(SalarySchema):
    name: Optional[str] = None
    surname: Optional[str] = None
    patronymic: Optional[str] = None
    userId: Optional[str] = None
    edit_by: Optional[str] = None
    marker: Optional[EmployeeMarker] = None


class EmployeeSalaryCreate(SalarySchema):
    employee_salary_id: Optional[str] = None
    employee_id: str
    salary_mounth: Optional[int] = None
    salary_hours: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class EmployeeSalaryUpdate(SalarySchema):
    employee_id: Optional[str] = None
    salary_mounth: Optional[int] = None
    salary_hours: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    edit_by: Optional[str] = None


class EmploymentHistoryCreate(SalarySchema):
    employment_history_id: Optional[str] = None
    employee_id: str
    counterparties_id: str
    department: Optional[str] = None
    position: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class EmploymentHistoryUpdate(SalarySchema):
    employee_id: Optional[str] = None
    counterparties_id: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    edit_by: Optional[str] = None


class ObjectCreate(SalarySchema):
    id: Optional[str] = None
    name: Optional[str] = None
    object_id: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class ObjectUpdate(SalarySchema):
    name: Optional[str] = None
    object_id: Optional[str] = None
    edit_by: Optional[str] = None


class OperationCreate(SalarySchema):
    id: Optional[str] = None
    date_payment: Optional[date] = None
    from_person: Optional[str] = None
    whom_person: Optional[str] = None
    value: Optional[float] = None
    type_operation: Optional[OperationKind] = None
    method_pay: Optional[int] = None
    category_id: Optional[str] = None
    coment: Optional[str] = None
    object_id: Optional[str] = None
    financial_source_id: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    edit_by: Optional[str] = None


class OperationUpdate(SalarySchema):
    date_payment: Optional[date] = None
    from_person: Optional[str] = None
    whom_person: Optional[str] = None
    value: Optional[float] = None
    type_operation: Optional[OperationKind] = None
    method_pay: Optional[int] = None
    category_id: Optional[str] = None
    coment: Optional[str] = None
    object_id: Optional[str] = None
    financial_source_id: Optional[str] = None
    edit_by: Optional[str] = None


class OperationSalaryCreate(SalarySchema):
    id: Optional[str] = None
    date: date
    nounth_period: MonthPeriod
    year: int
    employee_id: str
    value: float
    type_id: int
    method_id: int
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class OperationSalaryUpdate(SalarySchema):
    date: Optional[date] = None
    nounth_period: Optional[MonthPeriod] = None
    year: Optional[int] = None
    employee_id: Optional[str] = None
    value: Optional[float] = None
    type_id: Optional[int] = None
    method_id: Optional[int] = None
    edit_by: Optional[str] = None


class PersonCreate(SalarySchema):
    id: Optional[str] = None
    name: str
    surname: str
    patronymic: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class PersonUpdate(SalarySchema):
    name: Optional[str] = None
    surname: Optional[str] = None
    patronymic: Optional[str] = None
    edit_by: Optional[str] = None
