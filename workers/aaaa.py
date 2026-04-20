from rapidfuzz import fuzz
print(fuzz.token_sort_ratio("KATHERINE ELIZABETH SMITH", "KATHY SMITH"))
print(fuzz.token_sort_ratio("ROBERT JOHNSON", "ROB JOHNSON"))