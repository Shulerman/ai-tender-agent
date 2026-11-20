"""
Подготовка изолированной SQLite-базы для CI.

Все тексты статей синтетические.
Они используются только для проверки поиска и валидации.
Не предназначены для юридического анализа.
"""

from sqlalchemy import inspect, text

from app.database import (
    Base,
    engine,
    SessionLocal,
    LegalActDB,
    LegalVersionDB,
    LegalProvisionDB,
)

from app.commercial.models import (
    ManufacturerDB,
    SupplierDB,
    PriceListImportDB,
    PriceListImportRowDB,
    ProductDB,
    SupplierOfferDB,
    SupplierOfferVerificationDB,
    SupplierProductMappingDB,
    ProductUnitConversionDB,
)

from app.documents import models as document_models  # noqa: F401

VERSION_ID = "44-FZ-2026-10-01"

TEST_ARTICLES = [
    {
        "article_number": "1",
        "title": "Тестовая статья 1",
        "text": (
            "Синтетический текст для проверки получения "
            "статьи из базы."
        ),
    },
    {
        "article_number": "34",
        "title": "Тестовая статья 34",
        "text": (
            "Синтетический текст: срок поставки, приемка товара, "
            "ответственность поставщика, условия оплаты."
        ),
    },
    {
        "article_number": "95",
        "title": "Тестовая статья 95",
        "text": (
            "Синтетический текст: изменение условий контракта, "
            "расторжение контракта, односторонний отказ."
        ),
    },
    {
        "article_number": "96",
        "title": "Тестовая статья 96",
        "text": (
            "Синтетический текст: обеспечение исполнения контракта."
        ),
    },
]


def main():
    Base.metadata.create_all(bind=engine)

    if engine.dialect.name != "sqlite":
        raise RuntimeError("CI setup ожидает SQLite-базу.")

    with engine.begin() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("supplier_offers")
        }

        if "unit" not in columns:
            connection.execute(
                text("ALTER TABLE supplier_offers ADD COLUMN unit VARCHAR")
            )
            print("Добавлена колонка supplier_offers.unit")

    db = SessionLocal()

    try:
        act = db.query(LegalActDB).filter(
            LegalActDB.act_id == "44-ФЗ"
        ).first()

        if act is None:
            act = LegalActDB(
                act_id="44-ФЗ",
                title="Синтетический тестовый нормативный акт",
                act_number="44-ФЗ",
                official_source_url="",
                status="Тестовые данные",
            )
            db.add(act)

        version = db.query(LegalVersionDB).filter(
            LegalVersionDB.version_id == VERSION_ID
        ).first()

        if version is None:
            version = LegalVersionDB(
                version_id=VERSION_ID,
                act_id="44-ФЗ",
                source_url="",
            )
            db.add(version)

        db.flush()

        for item in TEST_ARTICLES:
            provision = db.query(LegalProvisionDB).filter(
                LegalProvisionDB.version_id == VERSION_ID,
                LegalProvisionDB.article_number == item["article_number"],
            ).first()

            if provision is None:
                provision = LegalProvisionDB(
                    provision_id=f"ci-test-{item['article_number']}",
                    version_id=VERSION_ID,
                    article_number=item["article_number"],
                    title=item["title"],
                    text=item["text"],
                )
                db.add(provision)
            else:
                provision.title = item["title"]
                provision.text = item["text"]

        db.commit()

        count = db.query(LegalProvisionDB).filter(
            LegalProvisionDB.version_id == VERSION_ID
        ).count()

        print(f"Таблицы созданы. Тестовых статей: {count}")
        print("ТЕСТОВАЯ БАЗА ГОТОВА")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
