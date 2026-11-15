from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import (
    LegalActDB,
    LegalVersionDB,
    LegalProvisionDB,
)


def save_legal_document(
    db: Session,
    legal_act,
    legal_version,
    provisions,
):
    """
    Сохраняет нормативный акт, его редакцию и статьи.

    Повторный импорт обновляет существующие записи,
    а не создаёт дубликаты.
    """

    try:
        act = db.query(LegalActDB).filter(
            LegalActDB.act_id == legal_act.act_id
        ).first()

        if act is None:
            act = LegalActDB(act_id=legal_act.act_id)
            db.add(act)

        act_fields = (
            "title",
            "act_number",
            "act_date",
            "authority",
            "official_source_url",
            "publication_date",
            "effective_from",
            "effective_to",
            "status",
            "last_checked_at",
        )

        for field in act_fields:
            value = getattr(legal_act, field, None)

            if value is not None and value != "":
                setattr(act, field, value)

        version = db.query(LegalVersionDB).filter(
            LegalVersionDB.version_id == legal_version.version_id
        ).first()

        if version is None:
            version = LegalVersionDB(
                version_id=legal_version.version_id,
                act_id=legal_version.act_id,
                source_url=legal_version.source_url or "",
            )
            db.add(version)

        version.act_id = legal_version.act_id

        for field in (
            "effective_from",
            "effective_to",
            "source_url",
            "retrieved_at",
        ):
            value = getattr(legal_version, field, None)

            if value is not None and value != "":
                setattr(version, field, value)

        inserted = 0
        updated = 0

        for provision_data in provisions:
            provision = db.query(LegalProvisionDB).filter(
                LegalProvisionDB.version_id
                == provision_data["version_id"],
                LegalProvisionDB.article_number
                == provision_data["article_number"],
            ).first()

            if provision is None:
                provision = LegalProvisionDB(
                    provision_id=provision_data["provision_id"],
                    version_id=provision_data["version_id"],
                    article_number=provision_data["article_number"],
                    title=provision_data.get("title"),
                    text=provision_data["text"],
                )
                db.add(provision)
                inserted += 1
            else:
                provision.title = provision_data.get("title")
                provision.text = provision_data["text"]
                updated += 1

        db.commit()

        return {
            "status": "success",
            "act_id": legal_act.act_id,
            "version_id": legal_version.version_id,
            "inserted_articles": inserted,
            "updated_articles": updated,
            "total_articles": len(provisions),
        }

    except Exception:
        db.rollback()
        raise


def get_legal_provision(
    db: Session,
    version_id: str,
    article_number: str,
):
    provision = (
        db.query(LegalProvisionDB)
        .filter(
            LegalProvisionDB.version_id == version_id,
            LegalProvisionDB.article_number == article_number,
        )
        .first()
    )

    if not provision:
        return None

    return {
        "article_number": provision.article_number,
        "title": provision.title,
        "text": provision.text,
    }


def search_legal_provisions(
    db: Session,
    version_id: str,
    search_text: str,
    limit: int = 10,
):
    provisions = (
        db.query(LegalProvisionDB)
        .filter(
            LegalProvisionDB.version_id == version_id,
            or_(
                LegalProvisionDB.title.ilike(f"%{search_text}%"),
                LegalProvisionDB.text.ilike(f"%{search_text}%"),
            ),
        )
        .order_by(LegalProvisionDB.article_number)
        .limit(limit)
        .all()
    )

    return [
        {
            "article_number": provision.article_number,
            "title": provision.title,
            "text": provision.text,
        }
        for provision in provisions
    ]
