from workers.fuzzy_matcher import fuzzy_match, batch_fuzzy_match, build_full_name
from core.matching import MatchVerdict

def test_fuzzy_match():
    # Exact match
    result = fuzzy_match("JOHN A SMITH", "JOHN A SMITH")
    assert result.score == 1.0
    assert result.verdict == MatchVerdict.MATCH

    # Minor typo
    result = fuzzy_match("JOHN A SMITH", "JOHN A SMIHT")
    assert 0.9 <= result.score < 1.0
    assert result.verdict == MatchVerdict.MATCH

    # Different order
    result = fuzzy_match("JOHN A SMITH", "SMITH JOHN A")
    assert result.score == 1.0
    assert result.verdict == MatchVerdict.MATCH
    

# Missing middle name
    result = fuzzy_match("ROBERT JOHNSON", "ROB JOHNSON")
    assert result.verdict == MatchVerdict.REVIEW
    assert 0.75 <= result.score < 0.90

# Completely different
    result = fuzzy_match("JOHN A SMITH", "JANE DOE")
    print(result)
    assert result.score < 0.75
    assert result.verdict == MatchVerdict.NO_MATCH

def test_batch_fuzzy_match():
    pairs = [
        ("JOHN A SMITH", "JOHN A SMITH"),  # Exact match
        ("JOHN A SMITH", "JOHN A SMIHT"),  # Minor typo
        ("JOHN A SMITH", "SMITH JOHN A"),  # Different order
        ("ROBERT JOHNSON", "ROB JOHNSON"),     # Missing middle name
        ("JOHN A SMITH", "JANE DOE"),       # Completely different
    ]
    results = batch_fuzzy_match(pairs)
    assert len(results) == 5
    assert results[0].verdict == MatchVerdict.MATCH
    assert results[1].verdict == MatchVerdict.MATCH
    assert results[2].verdict == MatchVerdict.MATCH
    assert results[3].verdict == MatchVerdict.REVIEW
    assert results[4].verdict == MatchVerdict.NO_MATCH

def test_build_full_name():
    assert build_full_name("John", "A", "Smith") == "JOHN A SMITH"
    assert build_full_name("John", None, "Smith") == "JOHN SMITH"
    assert build_full_name(" John ", " A ", " Smith ") == "JOHN A SMITH"
    assert build_full_name("", "", "Smith") == "SMITH"
    assert build_full_name("", None, "Smith") == "SMITH"