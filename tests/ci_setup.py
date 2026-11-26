"""
Подготовка изолированной SQLite-базы для CI.

Все тексты статей синтетические.
Они используются только для проверки поиска и валидации.
Не предназначены для юридического анализа.
"""

from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

from sqlalchemy import text

from app.database import (
    engine,
    SessionLocal,
    LegalActDB,
    LegalVersionDB,
    LegalProvisionDB,
)

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
    if engine.dialect.name != "sqlite":
        raise RuntimeError("CI setup ожидает SQLite-базу.")

    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    except Exception as exc:
        raise RuntimeError(
            "Схема БД не подготовлена Alembic. "
            "Сначала выполните: python -m alembic upgrade head"
        ) from exc

    alembic_config = Config(
        str(Path(__file__).resolve().parents[1] / "alembic.ini")
    )
    expected_revision = ScriptDirectory.from_config(
        alembic_config
    ).get_current_head()
    if revision != expected_revision:
        raise RuntimeError(
            f"Неверная ревизия БД: {revision!r}; "
            f"ожидается {expected_revision!r}. "
            "Выполните: python -m alembic upgrade head"
        )

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

        print(f"Тестовые данные подготовлены. Статей: {count}")
        print("ТЕСТОВАЯ БАЗА ГОТОВА")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
