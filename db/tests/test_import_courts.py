import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from import_courts import BAILIFF_RE, COURT_RE, csv_field, infer_court_type  # noqa: E402


def test_infer_court_type_keywords():
    cases = {
        "Кассационный суд общей юрисдикции №1": "кассационный",
        "Второй апелляционный суд общей юрисдикции": "апелляционный",
        "Арбитражный суд Московской области": "арбитражный",
        "Верховный суд Российской Федерации": "верховный",
        "Московский областной суд": "областной",
        "Пресненский районный суд города Москвы": "районный",
        "Тверской городской суд": "районный",
        "Судебный участок №5": "мировой",
        "мировой судья участка №3": "мировой",
        "Московский гарнизонный военный суд": "военный",
    }
    for name, expected in cases.items():
        assert infer_court_type(name) == expected, name


def test_infer_court_type_unknown_returns_none():
    assert infer_court_type("Министерство юстиции") is None


def test_court_re_matches_explicit_court_phrases():
    assert COURT_RE.search("Пресненский районный суд города Москвы")
    assert COURT_RE.search("Арбитражный суд Московской области")
    assert COURT_RE.search("Судебный участок №12")


def test_court_re_rejects_place_names_containing_sud():
    # "Судак" and "Суджанский" contain "суд" but are not courts
    assert not COURT_RE.search("Судак")
    assert not COURT_RE.search("Суджанский районный отдел")


def test_court_re_matches_standalone_word_after_comma():
    assert COURT_RE.search("Иваново, суд")


def test_bailiff_re_excludes_bailiff_offices():
    assert BAILIFF_RE.search("Отдел судебных приставов по Ленинскому району")
    assert BAILIFF_RE.search("УФССП России по Московской области")
    assert not BAILIFF_RE.search("Пресненский районный суд города Москвы")


def test_csv_field_escapes_quotes_and_backslashes():
    assert csv_field(None) == r"\N"
    assert csv_field("Simple") == '"Simple"'
    assert csv_field('With "quotes"') == '"With ""quotes"""'
    assert csv_field("back\\slash") == '"back\\\\slash"'
