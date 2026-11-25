from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Float,
    JSON,
    UniqueConstraint,
    Index,
)

from app.database import Base


class TenderDocumentDB(Base):
    """Загруженный документ тендера."""

    __tablename__ = "tender_documents"

    id = Column(Integer, primary_key=True, index=True)

    document_uuid = Column(
        String(36),
        nullable=False,
        unique=True,
        index=True,
    )

    tender_id = Column(
        Integer,
        ForeignKey("tenders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    original_name = Column(String, nullable=False)
    file_path = Column(Text, nullable=False)
    file_hash = Column(String(64), nullable=True, index=True)

    detected_extension = Column(String(10), nullable=False)
    size_bytes = Column(Integer, nullable=False)

    processing_status = Column(
        String,
        nullable=False,
        default="Загружен",
        index=True,
    )

    extraction_error = Column(Text, nullable=True)

    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )


class DocumentChunkDB(Base):
    """Страница или логический фрагмент документа."""

    __tablename__ = "document_chunks"

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "sequence_number",
            name="uq_document_chunk_sequence",
        ),
        Index(
            "ix_document_chunks_locator",
            "document_id",
            "locator_type",
            "locator_value",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(
        Integer,
        ForeignKey("tender_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    sequence_number = Column(Integer, nullable=False)

    locator_type = Column(String(30), nullable=False)
    locator_value = Column(String(255), nullable=True)

    text = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)

    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )


class TenderAnalysisDB(Base):
    """Сохранённый результат анализа документа."""

    __tablename__ = "tender_analyses"

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(
        Integer,
        ForeignKey("tender_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    analysis_type = Column(String(30), nullable=False, index=True)

    status = Column(
        String(30),
        nullable=False,
        default="Не завершён",
        index=True,
    )

    semantic_validation_status = Column(
        String(30),
        nullable=False,
        default="Не запускалась",
        server_default="Не запускалась",
    )
    result_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    completed_at = Column(DateTime, nullable=True)


class TenderRequirementDB(Base):
    """Структурированное требование из документации закупки."""

    __tablename__ = "tender_requirements"

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(
        Integer,
        ForeignKey("tender_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    analysis_id = Column(
        Integer,
        ForeignKey("tender_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source_chunk_id = Column(
        Integer,
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    requirement_type = Column(String(50), nullable=False, index=True)
    requirement_text = Column(Text, nullable=False)

    attributes = Column(JSON, nullable=True)

    evidence_quote = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)

    extraction_status = Column(
        String(30),
        nullable=False,
        default="Не проверено",
        index=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
