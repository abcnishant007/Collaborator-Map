import re
from typing import Optional


NON_WORD_RE = re.compile(r"[^\w\s]")
SPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    lowered = value.casefold().strip()
    without_punct = NON_WORD_RE.sub(" ", lowered)
    return SPACE_RE.sub(" ", without_punct).strip()


def normalize_institution_key(
    institution_id: Optional[str],
    institution_name: Optional[str],
) -> Optional[str]:
    if institution_id:
        return f"oa:{institution_id}"
    if institution_name:
        normalized = normalize_text(institution_name)
        if normalized:
            return f"name:{normalized}"
    return None

