from datetime import datetime
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
    SupplierOfferDB,
    SupplierOfferVerificationDB,
)
from app.commercial.excel_importer import inspect_price_list
from app.commercial.import_service import (
    _normalize,
    import_price_list,
    match_import_row,
)
from app.commercial.service import (
    get_all_supplier_offers,
    get_current_supplier_offers,
    verify_supplier_offer,
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


@app.get("/commercial/products/duplicates")
def get_commercial_product_duplicates(
    db: Session = Depends(get_db),
):
    """Находит точные совпадения товаров каталога для ручной проверки."""

    rows = (
        db.query(ProductDB, ManufacturerDB)
        .outerjoin(
            ManufacturerDB,
            ProductDB.manufacturer_id == ManufacturerDB.id,
        )
        .order_by(ProductDB.id.asc())
        .all()
    )

    records = []
    articles = {}
    names = {}

    for product, manufacturer in rows:
        record = {
            "id": product.id,
            "name": product.name,
            "article_number": product.article_number,
            "manufacturer_id": product.manufacturer_id,
            "manufacturer": manufacturer.name if manufacturer else None,
            "unit": product.unit,
            "category": product.category,
        }
        records.append((product, record))

        article = _normalize(product.article_number)
        if article:
            articles.setdefault(article, []).append(record)

        name = _normalize(product.name)
        if name:
            names.setdefault(
                (product.manufacturer_id, name),
                [],
            ).append(record)

    groups = []

    def add_group(group_type, match_value, manufacturer_id, products, requires_review):
        if len(products) < 2:
            return

        manufacturer_names = {
            item["manufacturer"]
            for item in products
            if item["manufacturer"] is not None
        }

        groups.append({
            "type": group_type,
            "match_value": match_value,
            "manufacturer_id": manufacturer_id,
            "manufacturer": (
                next(iter(manufacturer_names))
                if len(manufacturer_names) == 1
                else None
            ),
            "requires_review": requires_review,
            "products": products,
        })

    for article, article_records in articles.items():
        manufacturer_ids = {
            item["manufacturer_id"]
            for item in article_records
            if item["manufacturer_id"] is not None
        }

        if len(manufacturer_ids) > 1:
            add_group(
                "article_across_manufacturers",
                article,
                None,
                article_records,
                True,
            )

        by_manufacturer = {}
        for item in article_records:
            by_manufacturer.setdefault(
                item["manufacturer_id"],
                [],
            ).append(item)

        for manufacturer_id, products in by_manufacturer.items():
            if len(products) > 1:
                add_group(
                    (
                        "article_without_manufacturer"
                        if manufacturer_id is None
                        else "duplicate_article"
                    ),
                    article,
                    manufacturer_id,
                    products,
                    manufacturer_id is None,
                )

    for (manufacturer_id, name), products in names.items():
        if len(products) > 1:
            add_group(
                (
                    "name_without_manufacturer"
                    if manufacturer_id is None
                    else "duplicate_name"
                ),
                name,
                manufacturer_id,
                products,
                manufacturer_id is None,
            )

    groups.sort(
        key=lambda group: (
            group["type"],
            group["match_value"],
            group["manufacturer_id"] or 0,
        )
    )

    return {
        "count": len(groups),
        "groups": groups,
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


@app.get("/commercial/offers")
def list_commercial_offers(
    supplier_id: int | None = None,
    product_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Возвращает все предложения с названиями и статусом актуальности."""

    offers = get_all_supplier_offers(
        db,
        supplier_id=supplier_id,
        product_id=product_id,
    )

    supplier_ids = {offer.supplier_id for offer in offers}
    product_ids = {offer.product_id for offer in offers}

    suppliers = {
        item.id: item.name
        for item in db.query(SupplierDB).filter(
            SupplierDB.id.in_(supplier_ids)
        ).all()
    } if supplier_ids else {}

    products = {
        item.id: item.name
        for item in db.query(ProductDB).filter(
            ProductDB.id.in_(product_ids)
        ).all()
    } if product_ids else {}

    return [
        {
            column.name: getattr(offer, column.name)
            for column in SupplierOfferDB.__table__.columns
        } | {
            "supplier_name": suppliers.get(offer.supplier_id),
            "product_name": products.get(offer.product_id),
            "freshness_status": (
                "Требуется перепроверка"
                if offer.valid_until is not None
                and offer.valid_until < datetime.now()
                else "Срок не указан"
                if offer.valid_until is None
                else "Не просрочено"
            ),
            "freshness_warning": (
                "Требуется уточнить у поставщика актуальность цены и наличия"
                if offer.valid_until is not None
                and offer.valid_until < datetime.now()
                else None
            ),
        }
        for offer in offers
    ]


@app.post("/commercial/offers/{offer_id}/verification")
def create_commercial_offer_verification(
    offer_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Подтверждает или отклоняет предложение с сохранением истории."""

    allowed_fields = {"verification_status", "verified_by", "notes"}
    unknown_fields = set(payload) - allowed_fields

    if unknown_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Неизвестные поля: {', '.join(sorted(unknown_fields))}",
        )

    verification_status = payload.get("verification_status")

    if not isinstance(verification_status, str) or verification_status not in {"Подтверждено", "Отклонено"}:
        raise HTTPException(
            status_code=422,
            detail="verification_status должен быть 'Подтверждено' или 'Отклонено'",
        )

    for field in ("verified_by", "notes"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise HTTPException(
                status_code=422,
                detail=f"{field} должен быть строкой",
            )

    try:
        verification = verify_supplier_offer(
            db=db,
            offer_id=offer_id,
            verification_status=verification_status,
            verified_by=payload.get("verified_by"),
            notes=payload.get("notes"),
        )
    except ValueError as exc:
        if str(exc) == "Предложение поставщика не найдено":
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "id": verification.id,
        "offer_id": verification.offer_id,
        "verification_status": verification.verification_status,
        "verified_at": verification.verified_at,
        "verified_by": verification.verified_by,
        "notes": verification.notes,
    }


@app.get("/commercial/offers/{offer_id}/verifications")
def get_commercial_offer_verifications(
    offer_id: int,
    db: Session = Depends(get_db),
):
    """Возвращает историю проверок коммерческого предложения."""

    offer = db.get(SupplierOfferDB, offer_id)
    if offer is None:
        raise HTTPException(
            status_code=404,
            detail="Предложение поставщика не найдено",
        )

    verifications = (
        db.query(SupplierOfferVerificationDB)
        .filter(SupplierOfferVerificationDB.offer_id == offer_id)
        .order_by(
            SupplierOfferVerificationDB.verified_at.desc(),
            SupplierOfferVerificationDB.id.desc(),
        )
        .all()
    )

    return [
        {
            "id": item.id,
            "offer_id": item.offer_id,
            "verification_status": item.verification_status,
            "verified_at": item.verified_at,
            "verified_by": item.verified_by,
            "notes": item.notes,
        }
        for item in verifications
    ]
