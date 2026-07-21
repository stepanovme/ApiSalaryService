from sqlalchemy import CHAR, Boolean, Column, Date, DateTime, Enum, Float, Integer, String, Text, ForeignKey

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
    employee_id = Column(CHAR(36))


class FileDB(Base):
    __tablename__ = "files"

    id = Column(CHAR(36), primary_key=True)
    original_name = Column(String(300), nullable=False)
    storage_name = Column(String(300), nullable=False)
    file_path = Column(Text, nullable=False)
    uploaded_by = Column(CHAR(36), nullable=False)
    uploaded_at = Column(DateTime, nullable=False)


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
    phone = Column(String(18))
    coment = Column(Text)
    object_id = Column(CHAR(36))
    financial_source_id = Column(CHAR(36))
    file_id = Column(CHAR(36))
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
    extract_id = Column(Integer)
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


class ReceiptListDB(Base):
    __tablename__ = "receipt_list"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    user_id = Column(CHAR(36), nullable=False)


class ReceiptDB(Base):
    __tablename__ = "receipt"

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_name = Column(Text)
    retailPlaceAddress = Column(Text)
    fiscalDriveNumber = Column(String(300))
    fiscalDocumentNumber = Column(String(300))
    fiscalSign = Column(String(300))
    date = Column(DateTime)
    inn = Column(String(100))
    sum = Column(Float)
    user_id = Column(CHAR(36), nullable=False)
    receipt_list_id = Column(Integer, nullable=False)
    status = Column(Enum("paid", "not_paid", native_enum=False))
    created_at = Column(DateTime)


class ReceiptCategoryDB(Base):
    __tablename__ = "receipt_category"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(Integer, nullable=False)
    category_id = Column(CHAR(36), nullable=False)


class ReceiptItemDB(Base):
    __tablename__ = "receipt_item"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(Integer)
    name = Column(Text)
    quantity = Column(Float)
    price = Column(Float)
    nds = Column(Integer)
    nds_sum = Column(Float)
    sum = Column(Float)


class ReceiptListViewDB(Base):
    __tablename__ = "receipt_list_view"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_list_id = Column(Integer, nullable=False)
    user_id = Column(CHAR(36), nullable=False)


class TypeDB(AuditMixin, Base):
    __tablename__ = "type"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)


class AuthSessionDB(Base):
    __tablename__ = "auth_session"

    token_id = Column(CHAR(36), primary_key=True)
    status = Column(
        Enum("pending", "rejected", "approved", native_enum=False),
        nullable=False,
        default="pending",
    )
    device_id = Column(CHAR(36), nullable=False)
    created_at = Column(DateTime, nullable=False)


class AllowedDeviceDB(Base):
    __tablename__ = "allowed_devices"

    device_id = Column(CHAR(36), primary_key=True)
    owner_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)


class ExtractDB(Base):
    __tablename__ = "extracts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(
        Enum("salary", "report", "vacation", "extract", native_enum=False),
        nullable=False,
    )
    date = Column(Date)
    counterparties_id = Column(CHAR(36))
    num = Column(Integer)
    period = Column(String(4))
    created_at = Column(DateTime, nullable=False)
    created_by = Column(CHAR(36), nullable=False)


class ExtractItemDB(Base):
    __tablename__ = "extract_item"

    id = Column(CHAR(36), primary_key=True)
    extract_id = Column(Integer, nullable=False)
    num = Column(Integer, nullable=False)
    fio = Column(Text, nullable=False)
    employee_id = Column(CHAR(36))
    account_num = Column(String(100))
    bik = Column(String(100))
    withheld = Column(Float)
    sum = Column(Float)
    result = Column(Text)
    comment_result = Column(Text)
    consider = Column(Boolean, nullable=False, default=False)


class ExtractFilesDB(Base):
    __tablename__ = "extract_files"

    id = Column(CHAR(36), primary_key=True)
    extract_id = Column(Integer, nullable=False)
    original_name = Column(Text, nullable=False)
    storage_name = Column(Text, nullable=False)
    extension = Column(String(100))
    mime_type = Column(String(100))
    file_path = Column(Text, nullable=False)
    uploaded_by = Column(CHAR(36), nullable=False)
    uploaded_at = Column(DateTime, nullable=False)
