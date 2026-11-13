
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker


class Settings(BaseSettings):
    DATABASE_URL: str
    POSTGRES_PASSWORD: str

    class Config:
        env_file = ".env"


settings = Settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()
class TenderDB(Base):
    __tablename__ = "tenders"

    from sqlalchemy import Column, Integer, String, Float

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
