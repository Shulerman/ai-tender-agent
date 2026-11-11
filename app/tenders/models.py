
from pydantic import BaseModel
from typing import Optional


class Tender(BaseModel):
    """Основная информация о закупке."""

    tender_id: str
    title: str
    customer: Optional[str] = None
    price: Optional[float] = None
    region: Optional[str] = None
    law: Optional[str] = None
    status: str = "new"




