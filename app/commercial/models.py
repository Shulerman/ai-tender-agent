from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Numeric,
    JSON,
    UniqueConstraint,
    Index,
    CheckConstraint,
    text,
)

from app.database import Base


class ManufacturerDB(Base):
    """Производитель товаров."""

    __tablename__ = "manufacturers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    country = Column(String, nullable=True)
    website = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=True)


class SupplierDB(Base):
    """Поставщик товаров."""

    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)

    inn = Column(String, nullable=True, unique=True, index=True)
    country = Column(String, nullable=True)
    region = Column(String, nullable=True)
    address = Column(Text, nullable=True)

    contact_person = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    website = Column(String, nullable=True)

    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=True)


class PriceListImportDB(Base):
    """Запись об импорте прайс-листа поставщика."""

    __tablename__ = "price_list_imports"

    id = Column(Integer, primary_key=True, index=True)

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id"),
        nullable=False,
        index=True,
    )

    file_name = Column(String, nullable=False)
    file_path = Column(Text, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)

    sheet_name = Column(String, nullable=True)
    header_row = Column(Integer, nullable=False, default=1)

    column_mapping = Column(JSON, nullable=True)

    status = Column(
        String,
        nullable=False,
        default="Создан",
    )

    total_rows = Column(Integer, nullable=False, default=0)
    imported_rows = Column(Integer, nullable=False, default=0)
    error_rows = Column(Integer, nullable=False, default=0)

    errors = Column(JSON, nullable=True)

    created_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class ProductDB(Base):
    """Товар в коммерческом каталоге."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    article_number = Column(String, nullable=True, index=True)

    manufacturer_id = Column(
        Integer,
        ForeignKey("manufacturers.id"),
        nullable=True,
        index=True,
    )

    description = Column(Text, nullable=True)
    technical_characteristics = Column(Text, nullable=True)
    technical_attributes = Column(JSON, nullable=True)
    unit = Column(String, nullable=True)
    category = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=True)


class ProductUnitConversionDB(Base):
    """Коэффициент пересчёта единиц для товара."""

    __tablename__ = "product_unit_conversions"

    __table_args__ = (
        CheckConstraint(
            "conversion_factor > 0",
            name="ck_product_unit_conversion_factor_positive",
        ),
        Index(
            "uq_product_unit_conversion_global",
            "product_id",
            "source_unit",
            "target_unit",
            unique=True,
            sqlite_where=text("supplier_id IS NULL"),
            postgresql_where=text("supplier_id IS NULL"),
        ),
        Index(
            "uq_product_unit_conversion_supplier",
            "product_id",
            "supplier_id",
            "source_unit",
            "target_unit",
            unique=True,
            sqlite_where=text("supplier_id IS NOT NULL"),
            postgresql_where=text("supplier_id IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id"),
        nullable=True,
        index=True,
    )

    source_unit = Column(String, nullable=False)
    target_unit = Column(String, nullable=False)
    conversion_factor = Column(Numeric(18, 9), nullable=False)

    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class SupplierProductMappingDB(Base):
    """Постоянная связь артикула поставщика с товаром каталога."""

    __tablename__ = "supplier_product_mappings"

    __table_args__ = (
        UniqueConstraint(
            "supplier_id",
            "normalized_supplier_article_number",
            name="uq_supplier_product_mapping_article",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id"),
        nullable=False,
        index=True,
    )

    supplier_article_number = Column(String, nullable=False)
    normalized_supplier_article_number = Column(String, nullable=False)

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )

    supplier_product_name = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class PriceListImportRowDB(Base):
    """Отдельная строка импортированного прайс-листа."""

    __tablename__ = "price_list_import_rows"

    __table_args__ = (
        UniqueConstraint(
            "import_id",
            "source_row",
            name="uq_price_list_import_source_row",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    import_id = Column(
        Integer,
        ForeignKey("price_list_imports.id"),
        nullable=False,
        index=True,
    )

    source_row = Column(Integer, nullable=False)
    source_values = Column(JSON, nullable=True)

    source_name = Column(String, nullable=True)
    source_article_number = Column(String, nullable=True)

    price = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(3), nullable=True)
    unit = Column(String, nullable=True)
    available_quantity = Column(Numeric(14, 3), nullable=True)
    valid_until = Column(DateTime, nullable=True)
    delivery_time_days = Column(Integer, nullable=True)

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=True,
        index=True,
    )

    status = Column(
        String,
        nullable=False,
        default="Требует сопоставления",
        index=True,
    )

    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)


class SupplierOfferDB(Base):
    """Коммерческое предложение поставщика на товар."""

    __tablename__ = "supplier_offers"

    id = Column(Integer, primary_key=True, index=True)

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id"),
        nullable=False,
        index=True,
    )

    import_id = Column(
        Integer,
        ForeignKey("price_list_imports.id"),
        nullable=True,
        index=True,
    )

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )

    price = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), default="RUB", nullable=False)
    unit = Column(String, nullable=True)

    available_quantity = Column(Numeric(14, 3), nullable=True)
    availability_status = Column(String, nullable=True)

    delivery_time_days = Column(Integer, nullable=True)
    payment_terms = Column(Text, nullable=True)
    delivery_cost = Column(Numeric(14, 2), nullable=True)

    received_at = Column(DateTime, nullable=False)
    valid_until = Column(DateTime, nullable=True)

    source_type = Column(String, nullable=False)
    source_reference = Column(Text, nullable=True)

    verification_status = Column(
        String,
        default="Не проверено",
        nullable=False,
    )

    notes = Column(Text, nullable=True)


class SupplierOfferVerificationDB(Base):
    """История проверок коммерческого предложения."""

    __tablename__ = "supplier_offer_verifications"

    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('Подтверждено', 'Отклонено')",
            name="ck_supplier_offer_verification_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    offer_id = Column(
        Integer,
        ForeignKey("supplier_offers.id"),
        nullable=False,
        index=True,
    )

    verification_status = Column(String, nullable=False)
    verified_at = Column(DateTime, nullable=False)
    verified_by = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

class CommercialAnalysisDB(Base):
    """Сохранённый результат коммерческого анализа тендера."""

    __tablename__ = "commercial_analyses"

    id = Column(Integer, primary_key=True, index=True)

    tender_id = Column(
        String,
        ForeignKey("tenders.tender_id"),
        nullable=False,
        index=True,
    )

    status = Column(String, default="Не завершён", nullable=False)

    total_purchase_cost = Column(Numeric(16, 2), nullable=True)
    additional_costs = Column(Numeric(16, 2), nullable=True)
    contract_revenue = Column(Numeric(16, 2), nullable=True)

    gross_profit = Column(Numeric(16, 2), nullable=True)
    gross_margin_percent = Column(Numeric(8, 3), nullable=True)

    currency = Column(String(3), default="RUB", nullable=False)

    data_completeness = Column(String, default="Не оценено")
    commercial_risks = Column(Text, nullable=True)
    recommendations = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)



class CommercialMatchRunDB(Base):
    """История отдельного запуска сопоставления требований с каталогом."""

    __tablename__ = "commercial_match_runs"

    id = Column(Integer, primary_key=True, index=True)

    commercial_analysis_id = Column(
        Integer,
        ForeignKey("commercial_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    tender_analysis_id = Column(
        Integer,
        ForeignKey("tender_analyses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = Column(String(30), nullable=False, default="Ожидает запуска")
    algorithm_version = Column(String(50), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    statistics = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

class CommercialMatchDB(Base):
    """Сопоставление требования тендера с товаром и предложением."""

    __tablename__ = "commercial_matches"

    id = Column(Integer, primary_key=True, index=True)

    analysis_id = Column(
        Integer,
        ForeignKey("commercial_analyses.id"),
        nullable=False,
        index=True,
    )

    tender_requirement_id = Column(
        Integer,
        ForeignKey("tender_requirements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    match_run_id = Column(
        Integer,
        ForeignKey("commercial_match_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=True,
        index=True,
    )

    offer_id = Column(
        Integer,
        ForeignKey("supplier_offers.id"),
        nullable=True,
        index=True,
    )

    tender_requirement = Column(Text, nullable=False)

    match_status = Column(
        String,
        default="Не проверено",
        nullable=False,
    )

    match_score = Column(Numeric(5, 2), nullable=True)

    confirmed_characteristics = Column(Text, nullable=True)
    missing_characteristics = Column(Text, nullable=True)
    discrepancies = Column(Text, nullable=True)

    evidence_status = Column(
        String,
        default="Не проверено",
        nullable=False,
    )

    evidence_references = Column(Text, nullable=True)

    estimated_quantity = Column(Numeric(14, 3), nullable=True)
    estimated_unit_price = Column(Numeric(14, 2), nullable=True)
    estimated_total_price = Column(Numeric(16, 2), nullable=True)

    currency = Column(String(3), default="RUB", nullable=False)

    notes = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=True)

