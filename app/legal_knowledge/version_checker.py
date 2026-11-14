
from datetime import date

from app.legal_knowledge.models import LegalVersion


def is_version_valid_on_date(
    version: LegalVersion,
    check_date: date
) -> bool:
    """Проверяет, действовала ли редакция закона на указанную дату."""

    if version.effective_from is None:
        return False

    if check_date < version.effective_from:
        return False

    if (
        version.effective_to is not None
        and check_date > version.effective_to
    ):
        return False

    return True
