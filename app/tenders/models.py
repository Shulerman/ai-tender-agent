from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class Tender(BaseModel):
    """Основная информация о закупке."""

    tender_id: str
    title: str
    customer: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_address: Optional[str] = None
    delivery_address: Optional[str] = None
    price: Optional[float] = None
    region: Optional[str] = None
    law: Optional[str] = None
    status: str = "new"

    application_start: Optional[datetime] = None
    application_end: Optional[datetime] = None
    price_procedure_date: Optional[datetime] = None
    results_date: Optional[datetime] = None
