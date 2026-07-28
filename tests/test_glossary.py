from rift_translate.glossary import find_terms


def test_finds_common_league_terms_case_insensitively() -> None:
    matches = find_terms("JG DIFF, ff15 and go next")
    terms = {entry.term for entry in matches}
    assert {"diff", "ff15", "go next"}.issubset(terms)
    assert "ff" not in terms


def test_does_not_match_terms_inside_other_words() -> None:
    matches = find_terms("different difficult waffles")
    terms = {entry.term for entry in matches}
    assert "ff" not in terms
