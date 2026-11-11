
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from app.tenders.models import Tender
from app.database import SessionLocal, TenderDB

app = FastAPI(
    title="AI Tender Agent",
    description="Tender monitoring and analysis system",
    version="0.1.0"
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def home():
    return {
        "project": "AI Tender Agent",
        "status": "running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.post("/tenders")
def create_tender(tender: Tender, db: Session = Depends(get_db)):

    existing = db.query(TenderDB).filter(
        TenderDB.tender_id == tender.tender_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Tender already exists"
        )

    new_tender = TenderDB(**tender.model_dump())

    db.add(new_tender)
    db.commit()
    db.refresh(new_tender)

    return {
        "message": "Tender successfully saved",
        "database_id": new_tender.id,
        "tender": tender
    }
