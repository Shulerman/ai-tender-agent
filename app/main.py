import hashlib
import json
import tempfile
import uuid
from pathlib import Path

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
)
from sqlalchemy.orm import Session

from app.tenders.models import Tender
from app.database import SessionLocal, TenderDB

from app.documents.storage import save_document
from app.documents.pdf_reader import extract_text_from_pdf
from app.documents.docx_reader import extract_text_from_docx
from app.documents.doc_reader import extract_text_from_doc
from app.documents.html_reader import extract_text_from_html

from app.ai.technical_analyst import analyze_technical_requirements
from app.ai.legal_analyst import analyze_legal_requirements
from app.ai.full_analyst import analyze_full_tender

from app.commercial.models import (
    SupplierDB,
    ProductDB,
    ManufacturerDB,
    PriceListImportDB,
    PriceListImportRowDB,
)
from app.commercial.excel_importer import inspect_price_list
from app.commercial.import_service import (
    import_price_list,
    match_import_row,
)


app = FastAPI(
    title="AI Tender Agent",
    description="Tender monitoring and analysis system",
    version="0.1.0",
)


COMMERCIAL_PRICE_LISTS_DIR = Path("data/commercial/price_lists")
ALLOWED_EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_excel_filename(file: UploadFile) -> tuple[str, str]:
    """Проверяет имя и расширение загруженного Excel-файла."""

    original_name = Path(
        (file.filename or "").replace("\\", "/")
    ).name

    if not original_name or original_name in {".", ".."}:
        raise ValueError("Не указано имя Excel-файла")

    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_EXCEL_EXTENSIONS:
        raise ValueError(
            "Поддерживаются только файлы XLSX и XLSM"
        )

    return original_name, extension


def _read_column_mapping(mapping_json: str) -> dict:
    """Преобразует JSON сопоставления столбцов в словарь."""

    try:
        mapping = json.loads(mapping_json)
    except (json.JSONDecodeError, TypeError):
        raise ValueError(
            "column_mapping должен содержать корректный JSON"
        )

    if not isinstance(mapping, dict):
        raise ValueError(
            "column_mapping должен быть JSON-объектом"
        )

    return mapping


@app.get("/")
def home():
    return {
        "project": "AI Tender Agent",
        "status": "running",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
    }


@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    try:
        document = await save_document(file)

        extension = document["detected_extension"]
        file_path = document["file_path"]

        if extension == ".pdf":
            extracted_text = extract_text_from_pdf(file_path)

        elif extension == ".docx":
            extracted_text = extract_text_from_docx(file_path)

        elif extension == ".doc":
            extracted_text = extract_text_from_doc(file_path)

        elif extension == ".html":
            extracted_text = extract_text_from_html(file_path)

        else:
            raise ValueError("Неподдерживаемый формат документа")

        return {
            "message": "Документ успешно загружен и обработан",
            "document_id": document["document_id"],
            "original_name": document["original_name"],
            "detected_extension": extension,
            "size_bytes": document["size_bytes"],
            "text_length": len(extracted_text),
            "text": extracted_text,
        }

    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Ошибка при обработке документа",
        )


@app.post("/commercial/imports/excel/preview")
async def preview_excel_price_list(
    file: UploadFile = File(...),
    header_row: int = Form(default=1),
    sheet_name: str | None = Form(default=None),
):
    """
    Предварительно анализирует Excel-прайс.

    Не сохраняет файл постоянно и не изменяет базу данных.
    Возвращает структуру книги и предлагаемое сопоставление столбцов.
    """

    temporary_path = None

    try:
        original_name, extension = _get_excel_filename(file)

        content = await file.read()

        if not content:
            raise ValueError("Загруженный файл пуст")

        with tempfile.NamedTemporaryFile(
            suffix=extension,
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)

        result = inspect_price_list(
            temporary_path,
            sheet_name=sheet_name,
            header_row=header_row,
        )

        result["file_name"] = original_name
        result["size_bytes"] = len(content)

        return {
            "message": "Предварительный просмотр Excel выполнен",
            "preview": result,
        }

    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Не удалось прочитать Excel-файл",
        )

    finally:
        await file.close()

        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@app.post("/commercial/imports/excel")
async def upload_excel_price_list(
    supplier_id: int = Form(...),
    file: UploadFile = File(...),
    column_mapping: str = Form(...),
    header_row: int = Form(default=1),
    sheet_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """
    Сохраняет и импортирует Excel-прайс поставщика.

    Файл сохраняется отдельно от документов тендера.
    Все операции импорта выполняются сервисом одной транзакцией.
    """

    saved_directory = None

    try:
        supplier = db.get(SupplierDB, supplier_id)

        if supplier is None:
            raise HTTPException(
                status_code=404,
                detail="Поставщик не найден",
            )

        original_name, extension = _get_excel_filename(file)

        mapping = _read_column_mapping(column_mapping)

        content = await file.read()

        if not content:
            raise ValueError("Загруженный файл пуст")

        file_hash = hashlib.sha256(content).hexdigest()

        unique_directory = uuid.uuid4().hex
        saved_directory = (
            COMMERCIAL_PRICE_LISTS_DIR / unique_directory
        )

        saved_directory.mkdir(
            parents=True,
            exist_ok=False,
        )

        saved_path = saved_directory / original_name
        saved_path.write_bytes(content)

        result = import_price_list(
            db,
            supplier_id=supplier_id,
            file_path=str(saved_path),
            column_mapping=mapping,
            header_row=header_row,
            sheet_name=sheet_name,
            file_hash=file_hash,
        )

        return {
            "message": "Импорт прайс-листа завершён",
            "original_name": original_name,
            "file_hash": file_hash,
            "result": result,
        }

    except HTTPException:
        if saved_directory is not None:
            import shutil
            shutil.rmtree(saved_directory, ignore_errors=True)
        raise

    except (ValueError, FileNotFoundError) as exc:
        if saved_directory is not None:
            import shutil
            shutil.rmtree(saved_directory, ignore_errors=True)

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        if saved_directory is not None:
            import shutil
            shutil.rmtree(saved_directory, ignore_errors=True)

        raise HTTPException(
            status_code=500,
            detail="Ошибка при импорте прайс-листа",
        )

    finally:
        await file.close()



@app.get("/commercial/products/search")
def search_commercial_products(
    q: str,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Ищет товары каталога по названию и артикулу."""

    search_term = q.strip().casefold()

    if not search_term:
        raise HTTPException(
            status_code=422,
            detail="Поисковый запрос не может быть пустым",
        )

    if len(search_term) > 500:
        raise HTTPException(
            status_code=422,
            detail="Поисковый запрос не должен превышать 500 символов",
        )

    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=422,
            detail="limit должен быть от 1 до 50",
        )

    products = (
        db.query(ProductDB, ManufacturerDB)
        .outerjoin(
            ManufacturerDB,
            ProductDB.manufacturer_id == ManufacturerDB.id,
        )
        .order_by(ProductDB.id.asc())
        .all()
    )

    exact_matches = []
    partial_matches = []

    for product, manufacturer in products:
        name = (product.name or "").casefold()
        article = (product.article_number or "").casefold()

        if search_term == name or search_term == article:
            exact_matches.append((product, manufacturer))
        elif search_term in name or search_term in article:
            partial_matches.append((product, manufacturer))

    matches = (exact_matches + partial_matches)[:limit]

    return {
        "query": q.strip(),
        "count": len(matches),
        "limit": limit,
        "products": [
            {
                "id": product.id,
                "name": product.name,
                "article_number": product.article_number,
                "manufacturer": manufacturer.name if manufacturer else None,
                "manufacturer_country": manufacturer.country if manufacturer else None,
                "unit": product.unit,
                "category": product.category,
            }
            for product, manufacturer in matches
        ],
    }


@app.get("/commercial/imports/{import_id}/unmatched")
def get_unmatched_import_rows(
    import_id: int,
    db: Session = Depends(get_db),
):
    """Возвращает строки импорта, ожидающие ручного сопоставления."""

    import_record = db.get(PriceListImportDB, import_id)

    if import_record is None:
        raise HTTPException(
            status_code=404,
            detail="Импорт не найден",
        )

    rows = (
        db.query(PriceListImportRowDB)
        .filter(
            PriceListImportRowDB.import_id == import_id,
            PriceListImportRowDB.status == "Требует сопоставления",
        )
        .order_by(PriceListImportRowDB.source_row.asc())
        .all()
    )

    return {
        "import_id": import_id,
        "count": len(rows),
        "rows": [
            {
                "row_id": row.id,
                "source_row": row.source_row,
                "article_number": row.source_article_number,
                "name": row.source_name,
                "price": row.price,
                "currency": row.currency,
                "unit": row.unit,
                "available_quantity": row.available_quantity,
                "delivery_time_days": row.delivery_time_days,
                "valid_until": row.valid_until,
                "status": row.status,
            }
            for row in rows
        ],
    }


@app.post("/commercial/imports/{import_id}/rows/{row_id}/match")
def manually_match_import_row(
    import_id: int,
    row_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Связывает строку импорта с существующим товаром каталога."""

    product_id = payload.get("product_id")

    if (
        not isinstance(product_id, int)
        or isinstance(product_id, bool)
    ):
        raise HTTPException(
            status_code=422,
            detail="product_id должен быть целым числом",
        )

    import_record = db.get(PriceListImportDB, import_id)

    if import_record is None:
        raise HTTPException(
            status_code=404,
            detail="Импорт не найден",
        )

    import_row = (
        db.query(PriceListImportRowDB)
        .filter_by(
            id=row_id,
            import_id=import_id,
        )
        .first()
    )

    if import_row is None:
        raise HTTPException(
            status_code=404,
            detail="Строка не найдена в указанном импорте",
        )

    if import_row.status != "Требует сопоставления":
        raise HTTPException(
            status_code=409,
            detail="Строка уже обработана или не требует сопоставления",
        )

    if db.get(ProductDB, product_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Товар каталога не найден",
        )

    if import_row.price is None:
        raise HTTPException(
            status_code=400,
            detail="Нельзя создать предложение: в строке отсутствует цена",
        )

    try:
        result = match_import_row(
            db,
            import_id=import_id,
            row_id=row_id,
            product_id=product_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )

    return {
        "message": "Строка успешно сопоставлена",
        "result": result,
    }

@app.post("/tenders")
def create_tender(
    tender: Tender,
    db: Session = Depends(get_db),
):
    existing = db.query(TenderDB).filter(
        TenderDB.tender_id == tender.tender_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Tender already exists",
        )

    new_tender = TenderDB(**tender.model_dump())

    db.add(new_tender)
    db.commit()
    db.refresh(new_tender)

    return {
        "message": "Tender successfully saved",
        "database_id": new_tender.id,
        "tender": tender,
    }


@app.get("/tenders")
def get_tenders(db: Session = Depends(get_db)):
    tenders = (
        db.query(TenderDB)
        .order_by(TenderDB.id.desc())
        .all()
    )

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
            "results_date": tender.results_date,
        }
        for tender in tenders
    ]


@app.patch("/tenders/{tender_id}")
def update_tender(
    tender_id: str,
    updates: dict,
    db: Session = Depends(get_db),
):
    existing = db.query(TenderDB).filter(
        TenderDB.tender_id == tender_id
    ).first()

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Tender not found",
        )

    allowed_fields = (
        set(Tender.model_fields.keys()) - {"tender_id"}
    )

    unknown_fields = set(updates.keys()) - allowed_fields

    if unknown_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown fields: {', '.join(sorted(unknown_fields))}",
        )

    current_data = {
        field: getattr(existing, field)
        for field in Tender.model_fields.keys()
    }

    current_data.update(updates)

    try:
        validated = Tender.model_validate(current_data)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        )

    for field, value in validated.model_dump().items():
        if field != "tender_id":
            setattr(existing, field, value)

    db.commit()
    db.refresh(existing)

    return {
        "message": "Tender successfully updated",
        "tender_id": existing.tender_id,
        "updated_fields": sorted(updates.keys()),
    }


@app.post("/analysis/technical")
async def analyze_technical(payload: dict):
    document_text = payload.get("document_text")

    if not isinstance(document_text, str) or not document_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Document text is required",
        )

    try:
        result = await analyze_technical_requirements(document_text)

        return {
            "message": "Technical analysis completed",
            "analysis": result,
        }

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Ошибка технического анализа",
        )


@app.post("/analysis/legal")
async def analyze_legal(payload: dict):
    document_text = payload.get("document_text")

    if not isinstance(document_text, str) or not document_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Document text is required",
        )

    try:
        result = await analyze_legal_requirements(document_text)

        return {
            "message": "Legal analysis completed",
            "analysis": result,
        }

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Ошибка юридического анализа",
        )


@app.post("/analysis/full")
async def analyze_full(payload: dict):
    document_text = payload.get("document_text")

    if not isinstance(document_text, str) or not document_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Document text is required",
        )

    try:
        result = await analyze_full_tender(document_text)
        return {
            "message": "Full tender analysis completed",
            "analysis": result,
        }
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Ошибка полного анализа закупки",
        )
