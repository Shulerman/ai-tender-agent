from sqlalchemy.orm import Session

from app.tenders.models import Tender
from app.database import TenderDB


def upsert_tender(db: Session, tender_data: dict):
    """
    Создаёт закупку, если её нет в базе,
    или обновляет переданные поля, если она уже существует.
    """

    if not isinstance(tender_data, dict):
        raise ValueError("Tender data must be a dictionary")

    tender_id = tender_data.get("tender_id")

    if not tender_id:
        raise ValueError("tender_id is required")

    allowed_fields = set(Tender.model_fields.keys())
    unknown_fields = set(tender_data.keys()) - allowed_fields

    if unknown_fields:
        raise ValueError(
            f"Unknown fields: {', '.join(sorted(unknown_fields))}"
        )

    existing = db.query(TenderDB).filter(
        TenderDB.tender_id == tender_id
    ).first()

    if existing is None:
        validated = Tender.model_validate(tender_data)
        new_tender = TenderDB(**validated.model_dump())

        db.add(new_tender)
        db.commit()
        db.refresh(new_tender)

        return new_tender, "created"

    current_data = {
        field: getattr(existing, field)
        for field in allowed_fields
    }

    current_data.update(tender_data)

    validated = Tender.model_validate(current_data)

    for field, value in validated.model_dump().items():
        if field != "tender_id":
            setattr(existing, field, value)

    db.commit()
    db.refresh(existing)

    return existing, "updated"
