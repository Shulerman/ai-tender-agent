
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class LegalAct(BaseModel):
    """Нормативный правовой акт."""

    act_id: str
    title: str
    act_number: str
    act_date: Optional[date] = None

    authority: Optional[str] = None
    official_source_url: str

    publication_date: Optional[date] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None

    status: str = "Не проверен"
    last_checked_at: Optional[datetime] = None


class LegalVersion(BaseModel):
    """Конкретная редакция нормативного акта."""

    version_id: str
    act_id: str

    effective_from: Optional[date] = None
    effective_to: Optional[date] = None

    source_url: str
    retrieved_at: Optional[datetime] = None


class LegalProvision(BaseModel):
    """Статья или отдельное положение закона."""

    provision_id: str
    version_id: str

    article_number: str
    title: Optional[str] = None
    text: str
