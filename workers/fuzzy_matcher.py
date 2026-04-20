from rapidfuzz import fuzz
from core.matching import MatchResult, MatchVerdict



print(fuzz.token_sort_ratio("KATHERINE ELIZABETH SMITH", "KATHY SMITH"))
print(fuzz.token_sort_ratio("ROBERT JOHNSON", "ROB JOHNSON"))

def fuzzy_match(npi_name: str, dca_name: str) -> MatchResult:
    """Compute a fuzzy match score between two names and return a MatchResult."""
    score = fuzz.token_sort_ratio(npi_name, dca_name) / 100.0  # Normalize to [0,1]

    if score >= 0.9:
        verdict = MatchVerdict.MATCH
    elif score >= 0.75:
        verdict = MatchVerdict.REVIEW
    else:
        verdict = MatchVerdict.NO_MATCH

    return MatchResult(npi_name=npi_name, dca_name=dca_name, score=score, verdict=verdict)



def batch_fuzzy_match(pairs: list[tuple[str, str]]) -> list[MatchResult]:
    """Apply fuzzy_match to a batch of name pairs."""
    return [fuzzy_match(npi_name, dca_name) for npi_name, dca_name in pairs]

# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def build_full_name(first: str, middle: str | None, last: str) -> str:
    parts = filter(None, [first, middle, last])
    return " ".join(word.strip() for word in parts).upper().strip()