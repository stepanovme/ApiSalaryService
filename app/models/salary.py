from sqlalchemy import CHAR, Column, Date, DateTime, Enum, Float, Integer, String, Text

from app.database import Base


class AuditMixin:
    created_at = Column(DateTime, nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    edit_by = Column(CHAR(36))


class CategoryDB(AuditMixin, Base):
    __tablename__ = "category"

    id = Column(CHAR(36), primary_key=True)
    name = Column(String(100), nullable=False)


class EmployeeDB(Base):
    __tablename__ = "employee"

    id = Column(CHAR(36), primary_key=True)
    name = Column(String(100))
    surname = Column(String(100))
    patronymic = Column(String(100))
    userId = Column(CHAR(36))
    created_at = Column(DateTime, nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    edit_by = Column(CHAR(36))
    marker = Column(Enum("EV", "VV", "OV", native_enum=False))


class EmployeeSalaryDB(Base):
    __tablename__ = "employee_salary"

    employee_salary_id = Column(CHAR(36), primary_key=True)
    employee_id = Column(CHAR(36), nullable=False)
    salary_mounth = Column(Integer)
    salary_hours = Column(Integer)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    created_at = Column(DateTime, nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    edit_by = Column(CHAR(36))


class EmploymentHistoryDB(Base):
    __tablename__ = "employment_history"

    employment_history_id = Column(CHAR(36), primary_key=True)
    employee_id = Column(CHAR(36), nullable=False)
    counterparties_id = Column(CHAR(36), nullable=False)
    department = Column(String(100))
    position = Column(String(100))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    created_at = Column(DateTime, nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    edit_by = Column(CHAR(36))


class FinancialSourceDB(AuditMixin, Base):
    __tablename__ = "financial_sources"

    id = Column(CHAR(36), primary_key=True)
    name = Column(String(100), nullable=False)


class MethodDB(AuditMixin, Base):
    __tablename__ = "method"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)


class ObjectDB(Base):
    __tablename__ = "objects"

    id = Column(CHAR(36), primary_key=True)
    name = Column(String(100))
    object_id = Column(CHAR(36))
    created_at = Column(DateTime, nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    edit_by = Column(CHAR(36))


class OperationDB(Base):
    __tablename__ = "operations"

    id = Column(CHAR(36), primary_key=True)
    date_payment = Column(Date)
    from_person = Column(CHAR(36))
    whom_person = Column(CHAR(36))
    value = Column(Float)
    type_operation = Column(Enum("entrance", "expenditure", native_enum=False))
    method_pay = Column(Integer)
    category_id = Column(CHAR(36))
    coment = Column(Text)
    object_id = Column(CHAR(36))
    financial_source_id = Column(CHAR(36))
    created_at = Column(DateTime, nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    edit_by = Column(CHAR(36), nullable=False)


class OperationSalaryDB(Base):
    __tablename__ = "operations_salary"

    id = Column(CHAR(36), primary_key=True)
    date = Column(Date, nullable=False)
    nounth_period = Column(
        Enum(
            "jun",
            "feb",
            "mar",
            "apr",
            "may",
            "june",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
            native_enum=False,
        ),
        nullable=False,
    )
    year = Column(Integer, nullable=False)
    employee_id = Column(CHAR(36), nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    edit_by = Column(CHAR(36))
    value = Column(Float, nullable=False)
    type_id = Column(Integer, nullable=False)
    method_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False)


class BuhSalaryDB(Base):
    __tablename__ = "buh_salary"

    id = Column(CHAR(36), primary_key=True)
    value = Column(Float, nullable=False)
    mounth_period = Column(
        Enum(
            "jun",
            "feb",
            "mar",
            "apr",
            "may",
            "june",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
            native_enum=False,
        ),
        nullable=False,
    )
    year = Column(Integer, nullable=False)
    employee_id = Column(CHAR(36), nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    edit_by = Column(CHAR(36))
    type_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False)


class PersonDB(Base):
    __tablename__ = "persons"

    id = Column(CHAR(36), primary_key=True)
    name = Column(String(100), nullable=False)
    surname = Column(String(100), nullable=False)
    patronymic = Column(String(100))
    created_at = Column(DateTime, nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    edit_by = Column(CHAR(36))


class TypeDB(AuditMixin, Base):
    __tablename__ = "type"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
