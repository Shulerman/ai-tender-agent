
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.tenders.models import Tender
from app.database import SessionLocal, TenderDB
from app.documents.storage import save_document
from app.documents.pdf_reader import extract_text_from_pdf
from app.documents.docx_reader import extract_text_from_docx
from app.ai.technical_analyst import analyze_technical_requirements
from app.ai.legal_analyst import analyze_legal_requirements

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

@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    try:
        document = await save_document(file)

        if document["original_name"].lower().endswith(".pdf"):            extracted_text = extract_text_from_pdf(
                document["file_path"]
            )
        elif document["original_name"].lower().endswith(".docx"):
            extracted_text = extract_text_from_docx(
                document["file_path"]
            )
        else:
            raise ValueError("Неподдерживаемый формат документа")

        return {
            "message": "Документ успешно загружен и обработан",
            "document_id": document["document_id"],
            "original_name": document["original_name"],
            "size_bytes": document["size_bytes"],
            "text_length": len(extracted_text),
            "text": extracted_text
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
    return {
        "message": "Tender successfully saved",
        "database_id": new_tender.id,
        "tender": tender
    }


@app.get("/tenders")
def get_tenders(db: Session = Depends(get_db)):
    tenders = db.query(TenderDB).order_by(TenderDB.id.desc()).all()

    return [
        {
            "id": tender.id,
            "tender_id": tender.tender_id,
            "title": tender.title,
            "customer": tender.customer,
            "customer_phone": tender.customer_phone,
            "customer_email": tender.customer_email,
            "customer_address": tender.customer_address,
            "delivery_address": tender.delivery_address,
            "price": tender.price,
            "region": tender.region,
            "law": tender.law,
            "status": tender.status,
            "application_start": tender.application_start,
            "application_end": tender.application_end,
            "price_procedure_date": tender.price_procedure_date,
            "results_date": tender.results_date
        }
        for tender in tenders
    ]


@app.patch("/tenders/{tender_id}")
def update_tender(
    tender_id: str,
    updates: dict,
    db: Session = Depends(get_db)
):
    existing = db.query(TenderDB).filter(
        TenderDB.tender_id == tender_id
    ).first()

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Tender not found"
        )

    allowed_fields = set(Tender.model_fields.keys()) - {"tender_id"}
    unknown_fields = set(updates.keys()) - allowed_fields

    if unknown_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown fields: {', '.join(sorted(unknown_fields))}"
        )

    current_data = {
        field: getattr(existing, field)
        for field in Tender.model_fields.keys()
    }

    current_data.update(updates)

    try:
        validated = Tender.model_validate(current_data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    for field, value in validated.model_dump().items():
        if field != "tender_id":
            setattr(existing, field, value)

    db.commit()
    db.refresh(existing)

    return {
        "message": "Tender successfully updated",
        "tender_id": existing.tender_id,
        "updated_fields": sorted(updates.keys())
    }
@app.post("/analysis/technical")
async def analyze_technical(payload: dict):
    document_text = payload.get("document_text")

    if not isinstance(document_text, str) or not document_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Document text is required"
        )

    result = await analyze_technical_requirements(document_text)

    return {
        "message": "Technical analysis completed",
        "analysis": result
    }

@app.post("/analysis/legal")
async def analyze_legal(payload: dict):
    document_text = payload.get("document_text")

    if not isinstance(document_text, str) or not document_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Document text is required"
        )

    result = await analyze_legal_requirements(document_text)

    return {
        "message": "Legal analysis completed",
        "analysis": result
    }