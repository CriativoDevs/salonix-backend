"""
BE-MARKETING-04 (regressão): ICS_BASE_URL em produção é uma lista separada por
vírgulas (ex.: múltiplos domínios), mas era usada como se fosse uma única URL,
gerando links quebrados nos emails (ex.: ".../ics/?rid=..." colado a dois
domínios). `first_csv_value` deve extrair só a primeira entrada não vazia.
"""

from salonix_backend.settings import first_csv_value


def test_first_csv_value_with_single_url():
    assert first_csv_value("https://api.timelyone.today") == "https://api.timelyone.today"


def test_first_csv_value_with_multiple_urls_picks_first():
    raw = "https://salonix-backend-production.up.railway.app,https://api.timelyone.today"
    assert first_csv_value(raw) == "https://salonix-backend-production.up.railway.app"


def test_first_csv_value_strips_whitespace_around_entries():
    raw = "  https://a.example.com , https://b.example.com "
    assert first_csv_value(raw) == "https://a.example.com"


def test_first_csv_value_with_empty_string_returns_empty():
    assert first_csv_value("") == ""


def test_first_csv_value_with_leading_comma_skips_empty_entries():
    assert first_csv_value(",https://a.example.com") == "https://a.example.com"
