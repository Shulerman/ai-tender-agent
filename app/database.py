
from pydantic_settings import BaseSettings

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Date,
    Text,
    ForeignKey,
    UniqueConstraint,
)

from sqlalchemy.orm import declarative_base, sessionmaker


class Settings(BaseSettings):
    DATABASE_URL: str
    POSTGRES_PASSWORD: str

    class Config:
        env_file = ".env"


settings = Settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


class TenderDB(Base):
    __tablename__ = "tenders"

    id = Column(Integer, primary_key=True, index=True)
    tender_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    customer = Column(String, nullable=True)
    price = Column(Float, nullable=True)
    region = Column(String, nullable=True)
    law = Column(String, nullable=True)
    status = Column(String, default="new")

    customer_phone = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    customer_address = Column(String, nullable=True)
    delivery_address = Column(String, nullable=True)

    application_start = Column(DateTime, nullable=True)
    application_end = Column(DateTime, nullable=True)
    price_procedure_date = Column(DateTime, nullable=True)
    results_date = Column(DateTime, nullable=True)


class LegalActDB(Base):
    __tablename__ = "legal_acts"

    act_id = Column(String, primary_key=True)
    title = Column(Text, nullable=False)
    act_number = Column(String, nullable=False)
    act_date = Column(Date, nullable=True)

    authority = Column(String, nullable=True)
    official_source_url = Column(Text, nullable=False)

    publication_date = Column(Date, nullable=True)
    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)

    status = Column(String, default="Не проверен")
    last_checked_at = Column(DateTime, nullable=True)


class LegalVersionDB(Base):
    __tablename__ = "legal_versions"

    version_id = Column(String, primary_key=True)

    act_id = Column(
        String,
        ForeignKey("legal_acts.act_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)

    source_url = Column(Text, nullable=False)
    retrieved_at = Column(DateTime, nullable=True)


class LegalProvisionDB(Base):
    __tablename__ = "legal_provisions"

    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "article_number",
            name="uq_legal_provision_version_article",
        ),
    )

    provision_id = Column(String, primary_key=True)

    version_id = Column(
        String,
        ForeignKey("legal_versions.version_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    article_number = Column(String, nullable=False)
    title = Column(Text, nullable=True)
    text = Column(Text, nullable=False)
