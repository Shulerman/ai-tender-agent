from datetime import datetime
from difflib import SequenceMatcher
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
from app.documents.extraction_service import extract_document_content
from app.documents.persistence_service import save_document_with_chunks
from app.documents.models import (
    TenderDocumentDB,
    TenderAnalysisDB,
    TenderRequirementDB,
)
from app.documents.analysis_service import (
    analyze_and_save_document_requirements,
    retry_semantic_validation,
)

from app.ai.gemini import is_gemini_enabled
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
    CommercialAnalysisDB,
    CommercialMatchRunDB,
    CommercialMatchDB,
    ProductDuplicateReviewDB,
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
    run_commercial_matcher,
    compare_supplier_offers,
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
async def upload_document(
    file: UploadFile = File(...),
    tender_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
):
    try:
        if tender_id is not None and db.get(TenderDB, tender_id) is None:
            raise HTTPException(
                status_code=404,
                detail="Тендер не найден",
            )

        document = await save_document(file)

        extension = document["detected_extension"]
        extracted = extract_document_content(document["file_path"])
        extracted_text = extracted["text"]
        blocks = extracted["blocks"]

        document_record = save_document_with_chunks(
            db=db,
            document=document,
            blocks=blocks,
            tender_id=tender_id,
        )

        return {
            "message": "Документ успешно загружен и обработан",
            "document_id": document["document_id"],
            "database_id": document_record.id,
            "chunks_count": len(blocks),
            "original_name": document["original_name"],
            "detected_extension": extension,
            "size_bytes": document["size_bytes"],
            "text_length": len(extracted_text),
            "text": extracted_text,
        }

    except HTTPException:
        raise

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


@app.post("/documents/{document_id}/analyze")
async def analyze_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    try:
        return await analyze_and_save_document_requirements(
            db=db,
            document_id=document_id,
        )

    except ValueError as exc:
        message = str(exc)

        if message == "Документ не найден":
            status_code = 404
        elif message in {
            "У документа нет текстовых фрагментов",
            "Текст документа пуст",
        }:
            status_code = 400
        else:
            status_code = 422

        raise HTTPException(
            status_code=status_code,
            detail=message,
        )

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Ошибка анализа документа",
        )




@app.post(
    "/documents/{document_id}/analyses/{analysis_id}/retry-semantic-validation"
)
async def retry_document_semantic_validation(
    document_id: int,
    analysis_id: int,
    db: Session = Depends(get_db),
):
    try:
        return await retry_semantic_validation(
            db=db,
            document_id=document_id,
            analysis_id=analysis_id,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "Анализ не найден":
            status_code = 404
        elif message == "Основной анализ ещё не завершён":
            status_code = 409
        else:
            status_code = 422

        raise HTTPException(status_code=status_code, detail=message)
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Ошибка повторной семантической проверки",
        )


@app.get("/documents/{document_id}/requirements")
def get_document_requirements(
    document_id: int,
    analysis_id: int | None = None,
    db: Session = Depends(get_db),
):
    document = db.get(TenderDocumentDB, document_id)

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Документ не найден",
        )

    if analysis_id is not None:
        analysis = (
            db.query(TenderAnalysisDB)
            .filter(
                TenderAnalysisDB.id == analysis_id,
                TenderAnalysisDB.document_id == document_id,
                TenderAnalysisDB.status == "Завершён",
            )
            .first()
        )
    else:
        analysis = (
            db.query(TenderAnalysisDB)
            .filter(
                TenderAnalysisDB.document_id == document_id,
                TenderAnalysisDB.status == "Завершён",
            )
            .order_by(
                TenderAnalysisDB.created_at.desc(),
                TenderAnalysisDB.id.desc(),
            )
            .first()
        )

    if analysis is None:
        if analysis_id is not None:
            raise HTTPException(
                status_code=404,
                detail="Завершённый анализ не найден",
            )

        return {
            "document_id": document_id,
            "analysis_id": None,
            "semantic_validation_status": None,
            "requirements": [],
        }

    requirements = (
        db.query(TenderRequirementDB)
        .filter(
            TenderRequirementDB.document_id == document_id,
            TenderRequirementDB.analysis_id == analysis.id,
        )
        .order_by(TenderRequirementDB.id)
        .all()
    )

    return {
        "document_id": document_id,
        "analysis_id": analysis.id,
        "semantic_validation_status": analysis.semantic_validation_status,
        "requirements": [
            {
                "id": item.id,
                "requirement_type": item.requirement_type,
                "requirement_text": item.requirement_text,
                "attributes": item.attributes,
                "source_chunk_id": item.source_chunk_id,
                "evidence_quote": item.evidence_quote,
                "confidence": item.confidence,
                "extraction_status": item.extraction_status,
            }
            for item in requirements
        ],
    }


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
        known_manufacturer_records = [
            item
            for item in article_records
            if item["manufacturer_id"] is not None
        ]
        manufacturer_ids = {
            item["manufacturer_id"]
            for item in known_manufacturer_records
        }

        if len(manufacturer_ids) > 1:
            add_group(
                "article_across_manufacturers",
                article,
                None,
                known_manufacturer_records,
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

    # Потенциальные дубли: отдельные пары для ручной проверки.
    products_by_manufacturer = {}
    for product, record in records:
        if record["manufacturer_id"] is not None:
            products_by_manufacturer.setdefault(
                record["manufacturer_id"],
                [],
            ).append(record)

    for manufacturer_id, manufacturer_products in products_by_manufacturer.items():
        for index, first in enumerate(manufacturer_products):
            first_name = _normalize(first["name"])
            if not first_name:
                continue

            for second in manufacturer_products[index + 1:]:
                second_name = _normalize(second["name"])
                if not second_name or first_name == second_name:
                    continue

                similarity = SequenceMatcher(
                    None,
                    first_name,
                    second_name,
                ).ratio()

                if similarity < 0.85:
                    continue

                matching_attributes = []
                for field in ("category", "unit"):
                    first_value = _normalize(first[field])
                    second_value = _normalize(second[field])
                    if (
                        first_value
                        and second_value
                        and first_value == second_value
                    ):
                        matching_attributes.append(field)

                if not matching_attributes:
                    continue

                groups.append({
                    "type": "potential_name_match",
                    "match_value": f'{first["name"]} <> {second["name"]}',
                    "manufacturer_id": manufacturer_id,
                    "manufacturer": first["manufacturer"],
                    "requires_review": True,
                    "similarity_percent": round(similarity * 100, 1),
                    "matching_attributes": matching_attributes,
                    "products": [first, second],
                })

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



DUPLICATE_REVIEW_STATUSES = {
    "Ожидает решения",
    "Один товар",
    "Разные товары",
    "Требует уточнения",
}


def _duplicate_review_payload(db, review):
    product_1 = db.get(ProductDB, review.product_id_1)
    product_2 = db.get(ProductDB, review.product_id_2)

    return {
        "id": review.id,
        "product_id_1": review.product_id_1,
        "product_1_name": product_1.name if product_1 else None,
        "product_id_2": review.product_id_2,
        "product_2_name": product_2.name if product_2 else None,
        "status": review.status,
        "comment": review.comment,
        "created_at": review.created_at,
        "reviewed_at": review.reviewed_at,
    }


@app.get("/commercial/products/duplicate-reviews")
def get_product_duplicate_reviews(db: Session = Depends(get_db)):
    """Возвращает журнал ручной проверки дублей товаров."""

    reviews = (
        db.query(ProductDuplicateReviewDB)
        .order_by(ProductDuplicateReviewDB.created_at.desc())
        .all()
    )

    return {
        "count": len(reviews),
        "reviews": [
            _duplicate_review_payload(db, review)
            for review in reviews
        ],
    }


@app.post("/commercial/products/duplicate-reviews")
def create_product_duplicate_review(
    payload: dict,
    db: Session = Depends(get_db),
):
    """Создаёт запись ручной проверки пары товаров."""

    if (
        not isinstance(payload, dict)
        or set(payload) - {"product_id_1", "product_id_2", "comment"}
        or not {"product_id_1", "product_id_2"}.issubset(payload)
    ):
        raise HTTPException(
            status_code=422,
            detail="Ожидаются product_id_1, product_id_2 и необязательный comment",
        )

    first_id = payload["product_id_1"]
    second_id = payload["product_id_2"]

    for value in (first_id, second_id):
        if not isinstance(value, int) or isinstance(value, bool):
            raise HTTPException(
                status_code=422,
                detail="ID товаров должны быть целыми числами",
            )

    if first_id <= 0 or second_id <= 0 or first_id == second_id:
        raise HTTPException(
            status_code=422,
            detail="Необходимо указать два разных положительных ID товаров",
        )

    comment = payload.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise HTTPException(
            status_code=422,
            detail="comment должен быть строкой или null",
        )

    for product_id in (first_id, second_id):
        if db.get(ProductDB, product_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Товар каталога с ID {product_id} не найден",
            )

    product_id_1, product_id_2 = sorted((first_id, second_id))

    existing = (
        db.query(ProductDuplicateReviewDB)
        .filter_by(
            product_id_1=product_id_1,
            product_id_2=product_id_2,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Проверка этой пары товаров уже существует",
        )

    review = ProductDuplicateReviewDB(
        product_id_1=product_id_1,
        product_id_2=product_id_2,
        status="Ожидает решения",
        comment=comment,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    return _duplicate_review_payload(db, review)


@app.put("/commercial/products/duplicate-reviews/{review_id}")
def update_product_duplicate_review(
    review_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Сохраняет решение по ручной проверке пары товаров."""

    if (
        not isinstance(payload, dict)
        or not payload
        or set(payload) - {"status", "comment"}
        or "status" not in payload
    ):
        raise HTTPException(
            status_code=422,
            detail="Ожидаются обязательный status и необязательный comment",
        )

    status = payload["status"]
    if not isinstance(status, str) or status not in DUPLICATE_REVIEW_STATUSES:
        raise HTTPException(
            status_code=422,
            detail="Недопустимый статус проверки",
        )

    if "comment" in payload:
        comment = payload["comment"]
        if comment is not None and not isinstance(comment, str):
            raise HTTPException(
                status_code=422,
                detail="comment должен быть строкой или null",
            )
    else:
        comment = None

    review = db.get(ProductDuplicateReviewDB, review_id)
    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Запись проверки дублей не найдена",
        )

    review.status = status
    if "comment" in payload:
        review.comment = comment
    review.reviewed_at = (
        None if status == "Ожидает решения" else datetime.now()
    )

    db.commit()
    db.refresh(review)

    return _duplicate_review_payload(db, review)


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




def _matcher_json_value(value):
    """Преобразует сохранённое JSON-поле в Python-объект."""

    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _matcher_run_payload(run):
    return {
        "id": run.id,
        "commercial_analysis_id": run.commercial_analysis_id,
        "tender_analysis_id": run.tender_analysis_id,
        "status": run.status,
        "algorithm_version": run.algorithm_version,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "error": run.error,
        "statistics": run.statistics,
        "created_at": run.created_at,
    }


def _matcher_result_payload(db, match):
    product = db.get(ProductDB, match.product_id) if match.product_id else None
    requirement = (
        db.get(TenderRequirementDB, match.tender_requirement_id)
        if match.tender_requirement_id
        else None
    )

    return {
        "id": match.id,
        "match_run_id": match.match_run_id,
        "match_status": match.match_status,
        "match_score": (
            float(match.match_score)
            if match.match_score is not None
            else None
        ),
        "product": (
            {
                "id": product.id,
                "name": product.name,
                "article_number": product.article_number,
                "manufacturer_id": product.manufacturer_id,
                "description": product.description,
                "technical_characteristics": product.technical_characteristics,
                "technical_attributes": product.technical_attributes,
                "unit": product.unit,
                "category": product.category,
            }
            if product is not None
            else None
        ),
        "offer_id": match.offer_id,
        "tender_requirement": match.tender_requirement,
        "requirement": (
            {
                "id": requirement.id,
                "requirement_type": requirement.requirement_type,
                "requirement_text": requirement.requirement_text,
                "attributes": requirement.attributes,
                "evidence_quote": requirement.evidence_quote,
                "extraction_status": requirement.extraction_status,
            }
            if requirement is not None
            else None
        ),
        "confirmed_characteristics": _matcher_json_value(
            match.confirmed_characteristics
        ),
        "missing_characteristics": _matcher_json_value(
            match.missing_characteristics
        ),
        "discrepancies": _matcher_json_value(match.discrepancies),
        "evidence_status": match.evidence_status,
        "evidence_references": _matcher_json_value(
            match.evidence_references
        ),
        "estimated_quantity": (
            float(match.estimated_quantity)
            if match.estimated_quantity is not None
            else None
        ),
        "estimated_unit_price": (
            float(match.estimated_unit_price)
            if match.estimated_unit_price is not None
            else None
        ),
        "estimated_total_price": (
            float(match.estimated_total_price)
            if match.estimated_total_price is not None
            else None
        ),
        "currency": match.currency,
        "notes": match.notes,
        "recommendation": match.recommendation,
        "created_at": match.created_at,
    }


def _run_commercial_matcher_api(
    analysis_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Запускает сопоставление товаров с требованиями тендера."""

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422,
            detail="Тело запроса должно быть JSON-объектом",
        )

    if set(payload) != {"tender_analysis_id"}:
        raise HTTPException(
            status_code=422,
            detail="Ожидается только поле tender_analysis_id",
        )

    tender_analysis_id = payload.get("tender_analysis_id")
    if (
        isinstance(tender_analysis_id, bool)
        or not isinstance(tender_analysis_id, int)
        or tender_analysis_id <= 0
    ):
        raise HTTPException(
            status_code=422,
            detail="tender_analysis_id должен быть положительным целым числом",
        )

    try:
        run = run_commercial_matcher(
            db=db,
            analysis_id=analysis_id,
            tender_analysis_id=tender_analysis_id,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = (
            404
            if message in {
                "Коммерческий анализ не найден",
                "Анализ требований тендера не найден",
            }
            else 400
        )
        raise HTTPException(status_code=status_code, detail=message)

    return _matcher_run_payload(run)


@app.post("/commercial/analyses/{analysis_id}/matches/run")
def run_commercial_matcher_endpoint(
    analysis_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    return _run_commercial_matcher_api(analysis_id, payload, db)


@app.post("/documents/{document_id}/full-analysis")
async def run_full_document_analysis(
    document_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Выполняет технический анализ документа и коммерческий подбор."""

    if not isinstance(payload, dict) or set(payload) != {"commercial_analysis_id"}:
        raise HTTPException(
            status_code=422,
            detail="Ожидается только поле commercial_analysis_id",
        )

    commercial_analysis_id = payload.get("commercial_analysis_id")

    if (
        isinstance(commercial_analysis_id, bool)
        or not isinstance(commercial_analysis_id, int)
        or commercial_analysis_id <= 0
    ):
        raise HTTPException(
            status_code=422,
            detail="commercial_analysis_id должен быть положительным целым числом",
        )

    if not is_gemini_enabled():
        raise HTTPException(
            status_code=503,
            detail="Gemini отключён. Установите GEMINI_ENABLED=true.",
        )

    document = db.get(TenderDocumentDB, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    commercial_analysis = db.get(
        CommercialAnalysisDB,
        commercial_analysis_id,
    )
    if commercial_analysis is None:
        raise HTTPException(
            status_code=404,
            detail="Коммерческий анализ не найден",
        )

    tender = db.query(TenderDB).filter(
        TenderDB.tender_id == commercial_analysis.tender_id
    ).first()

    if tender is None or document.tender_id != tender.id:
        raise HTTPException(
            status_code=400,
            detail="Документ относится к другому тендеру",
        )

    try:
        technical_result = await analyze_and_save_document_requirements(
            db=db,
            document_id=document_id,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = (
            404 if message == "Документ не найден"
            else 400 if message in {
                "У документа нет текстовых фрагментов",
                "Текст документа пуст",
            }
            else 422
        )
        raise HTTPException(status_code=status_code, detail=message)
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Ошибка технического анализа документа",
        )

    technical_analysis_id = technical_result.get("analysis_id")

    if (
        technical_result.get("status") != "Завершён"
        or isinstance(technical_analysis_id, bool)
        or not isinstance(technical_analysis_id, int)
        or technical_analysis_id <= 0
    ):
        raise HTTPException(
            status_code=502,
            detail="Технический анализ не вернул завершённый результат",
        )

    matcher_result = _run_commercial_matcher_api(
        analysis_id=commercial_analysis_id,
        payload={"tender_analysis_id": technical_analysis_id},
        db=db,
    )

    return {
        "document_analysis": technical_result,
        "commercial_match_run": matcher_result,
    }


@app.get("/commercial/analyses/{analysis_id}/match-runs")
def get_commercial_match_runs(
    analysis_id: int,
    db: Session = Depends(get_db),
):
    """Возвращает историю запусков сопоставления, новые первыми."""

    if db.get(CommercialAnalysisDB, analysis_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Коммерческий анализ не найден",
        )

    runs = (
        db.query(CommercialMatchRunDB)
        .filter(
            CommercialMatchRunDB.commercial_analysis_id == analysis_id
        )
        .order_by(
            CommercialMatchRunDB.created_at.desc(),
            CommercialMatchRunDB.id.desc(),
        )
        .all()
    )
    return [_matcher_run_payload(run) for run in runs]


@app.get("/commercial/analyses/{analysis_id}/matches")
def get_commercial_analysis_matches(
    analysis_id: int,
    run_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Возвращает полные совпадения и потенциальные аналоги отдельно."""

    if db.get(CommercialAnalysisDB, analysis_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Коммерческий анализ не найден",
        )

    if run_id is not None:
        run = db.get(CommercialMatchRunDB, run_id)
        if run is None or run.commercial_analysis_id != analysis_id:
            raise HTTPException(
                status_code=404,
                detail="Запуск сопоставления не найден для указанного анализа",
            )
    else:
        run = (
            db.query(CommercialMatchRunDB)
            .filter(
                CommercialMatchRunDB.commercial_analysis_id == analysis_id
            )
            .order_by(
                CommercialMatchRunDB.created_at.desc(),
                CommercialMatchRunDB.id.desc(),
            )
            .first()
        )

    if run is None:
        return {
            "analysis_id": analysis_id,
            "run_id": None,
            "full_matches": [],
            "potential_analogues": [],
        }

    matches = (
        db.query(CommercialMatchDB)
        .filter(
            CommercialMatchDB.analysis_id == analysis_id,
            CommercialMatchDB.match_run_id == run.id,
        )
        .order_by(CommercialMatchDB.id.asc())
        .all()
    )

    full_matches = []
    potential_analogues = []

    for match in matches:
        item = _matcher_result_payload(db, match)
        item["offers_comparison"] = _match_offers_comparison_payload(
            db,
            match,
            unavailable_as_status=True,
        )
        if match.match_status == "Полное соответствие":
            full_matches.append(item)
        elif match.match_status == "Потенциальный аналог":
            potential_analogues.append(item)

    return {
        "analysis_id": analysis_id,
        "run_id": run.id,
        "full_matches": full_matches,
        "potential_analogues": potential_analogues,
    }


def _match_offers_comparison_payload(
    db,
    match,
    unavailable_as_status=False,
):
    """Формирует единый результат сравнения предложений для сопоставления."""

    def unavailable(reason):
        if not unavailable_as_status:
            raise HTTPException(status_code=422, detail=reason)

        return {
            "status": "unavailable",
            "reason": reason,
            "ranked_offers": [],
            "unranked_offers": [],
            "expired_offers": [],
            "expired_unranked_offers": [],
        }

    if match.product_id is None:
        return unavailable("Для сопоставления не выбран товар каталога")

    if match.estimated_quantity is None:
        return unavailable(
            "Нельзя сравнить предложения: количество не определено достоверно"
        )

    try:
        comparison = compare_supplier_offers(
            db=db,
            product_id=match.product_id,
            required_quantity=match.estimated_quantity,
        )
    except ValueError as exc:
        return unavailable(str(exc))

    def serialize_item(item, include_totals=False):
        offer = item["offer"]
        supplier = item.get("supplier")
        result = {
            "id": offer.id,
            "supplier_id": offer.supplier_id,
            "import_id": offer.import_id,
            "product_id": offer.product_id,
            "price": offer.price,
            "currency": offer.currency,
            "unit": offer.unit,
            "available_quantity": offer.available_quantity,
            "availability_status": offer.availability_status,
            "delivery_time_days": offer.delivery_time_days,
            "payment_terms": offer.payment_terms,
            "delivery_cost": offer.delivery_cost,
            "received_at": offer.received_at,
            "valid_until": offer.valid_until,
            "source_type": offer.source_type,
            "source_reference": offer.source_reference,
            "verification_status": offer.verification_status,
            "notes": offer.notes,
            "supplier_name": supplier.name if supplier else None,
            "freshness_status": item.get("freshness_status"),
            "freshness_warning": item.get("freshness_warning"),
        }

        if include_totals:
            for field in (
                "normalized_unit_price",
                "goods_total",
                "landed_total",
            ):
                result[field] = item.get(field)
        elif item.get("reason") is not None:
            result["reason"] = item["reason"]

        return result

    return {
        "status": "available",
        "reason": None,
        "ranked_offers": [
            serialize_item(item, include_totals=True)
            for item in comparison["ranked_offers"]
        ],
        "unranked_offers": [
            serialize_item(item)
            for item in comparison["unranked_offers"]
        ],
        "expired_offers": [
            serialize_item(item, include_totals=True)
            for item in comparison["expired_offers"]
        ],
        "expired_unranked_offers": [
            serialize_item(item)
            for item in comparison["expired_unranked_offers"]
        ],
    }


@app.get("/commercial/analyses/{analysis_id}/matches/{match_id}/offers/compare")
def compare_match_supplier_offers(
    analysis_id: int,
    match_id: int,
    db: Session = Depends(get_db),
):
    """Сравнивает предложения по количеству из требования тендера."""

    if db.get(CommercialAnalysisDB, analysis_id) is None:
        raise HTTPException(status_code=404, detail="Коммерческий анализ не найден")

    match = db.get(CommercialMatchDB, match_id)
    if match is None or match.analysis_id != analysis_id:
        raise HTTPException(
            status_code=404,
            detail="Сопоставление не найдено для указанного анализа",
        )

    comparison = _match_offers_comparison_payload(db, match)

    return {
        "analysis_id": analysis_id,
        "match_id": match_id,
        "product_id": match.product_id,
        "estimated_quantity": match.estimated_quantity,
        **comparison,
    }




@app.put("/commercial/analyses/{analysis_id}/matches/{match_id}/offer")
def select_commercial_match_offer(
    analysis_id: int,
    match_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Сохраняет выбранное актуальное предложение для сопоставления."""

    if not isinstance(payload, dict) or set(payload) != {"offer_id"}:
        raise HTTPException(
            status_code=422,
            detail="Ожидается только поле offer_id",
        )

    offer_id = payload.get("offer_id")
    if not isinstance(offer_id, int) or isinstance(offer_id, bool):
        raise HTTPException(
            status_code=422,
            detail="offer_id должен быть целым числом",
        )

    if db.get(CommercialAnalysisDB, analysis_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Коммерческий анализ не найден",
        )

    match = db.get(CommercialMatchDB, match_id)
    if match is None or match.analysis_id != analysis_id:
        raise HTTPException(
            status_code=404,
            detail="Сопоставление не найдено для указанного анализа",
        )

    comparison = _match_offers_comparison_payload(db, match)
    selected = next(
        (
            item
            for item in comparison["ranked_offers"]
            if item["id"] == offer_id
        ),
        None,
    )

    if selected is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Предложение нельзя выбрать: оно отсутствует среди "
                "актуальных предложений, пригодных для расчёта"
            ),
        )

    match.offer_id = offer_id
    match.estimated_unit_price = selected["normalized_unit_price"]
    match.estimated_total_price = selected["landed_total"]
    match.currency = "RUB"

    db.commit()
    db.refresh(match)

    return {
        "analysis_id": analysis_id,
        "match_id": match.id,
        "offer_id": match.offer_id,
        "supplier_name": selected["supplier_name"],
        "estimated_quantity": match.estimated_quantity,
        "estimated_unit_price": match.estimated_unit_price,
        "estimated_total_price": match.estimated_total_price,
        "currency": match.currency,
        "verification_status": selected["verification_status"],
        "freshness_status": selected["freshness_status"],
        "freshness_warning": selected["freshness_warning"],
    }


@app.get("/commercial/products/{product_id}/suppliers/{supplier_id}/price-history")
def get_supplier_product_price_history(
    product_id: int,
    supplier_id: int,
    db: Session = Depends(get_db),
):
    """Возвращает историю цен конкретного товара у конкретного поставщика."""

    if db.get(ProductDB, product_id) is None:
        raise HTTPException(status_code=404, detail="Товар не найден")

    if db.get(SupplierDB, supplier_id) is None:
        raise HTTPException(status_code=404, detail="Поставщик не найден")

    offers = (
        db.query(SupplierOfferDB)
        .filter(
            SupplierOfferDB.product_id == product_id,
            SupplierOfferDB.supplier_id == supplier_id,
        )
        .order_by(
            SupplierOfferDB.received_at.desc(),
            SupplierOfferDB.id.desc(),
        )
        .all()
    )

    now = datetime.now()
    history = []

    for offer in offers:
        is_expired = (
            offer.valid_until is not None
            and offer.valid_until < now
        )
        freshness_status = (
            "Требуется перепроверка"
            if is_expired
            else "Срок не указан"
            if offer.valid_until is None
            else "Не просрочено"
        )

        history.append({
            "id": offer.id,
            "supplier_id": offer.supplier_id,
            "product_id": offer.product_id,
            "import_id": offer.import_id,
            "price": offer.price,
            "currency": offer.currency,
            "unit": offer.unit,
            "available_quantity": offer.available_quantity,
            "availability_status": offer.availability_status,
            "received_at": offer.received_at,
            "valid_until": offer.valid_until,
            "verification_status": offer.verification_status,
            "delivery_time_days": offer.delivery_time_days,
            "delivery_cost": offer.delivery_cost,
            "payment_terms": offer.payment_terms,
            "source_type": offer.source_type,
            "freshness_status": freshness_status,
            "freshness_warning": (
                "Требуется уточнить у поставщика актуальность цены и наличия"
                if is_expired
                else None
            ),
        })

    return history


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

