import pytest

from scraper.parse import EXPECTED, INDEFINITE, PERMANENT, ParseError, classify_status, parse


def test_fixture_counts(html):
    r = parse(html)
    assert r.sections_found == {"elevator", "escalator"}
    assert sum(x.asset_type == "elevator" for x in r.rows) == 19
    # 17 lines on the page, 3 are exact duplicates
    assert sum(x.asset_type == "escalator" for x in r.rows) == 14
    assert r.dsb_updated == "20. okt. 13:33"


def test_modernisation_section_ignored(html):
    assert not any("Vipperød" in x.raw_label for x in parse(html).rows)


def test_bispebjerg(html):
    row = next(x for x in parse(html).rows if x.raw_label == "Bispebjerg")
    assert (row.status_kind, row.expected_date) == (EXPECTED, "2026-10-24")


@pytest.mark.parametrize("text,kind,date", [
    ("Forventes i drift den 24.10.26", EXPECTED, "2026-10-24"),
    ("Forventes i drift den 7/11-2026", EXPECTED, "2026-11-07"),
    ("Ude af drift, på ubestemt tid", INDEFINITE, None),
    ("Ude af drift indtil videre", INDEFINITE, None),
    ("Taget ud af drift permanent", PERMANENT, None),
])
def test_classify(text, kind, date):
    assert classify_status(text) == (kind, date)


def test_layout_change_raises():
    with pytest.raises(ParseError):
        parse("<html><body><p>nothing</p></body></html>")


def test_old_layout_paragraph_headings():
    html = """<section aria-label="Stations information">
      <h3><b>Elevatorer på følgende stationer er ude af drift:</b></h3>
      <p><b>Ordrup lift:</b> Forventes i drift 14.02.25</p>
      <p><b><u>Rulletrapperne på følgende stationer er ude af drift:</u></b></p>
      <p><b>Nørrebro spor 11 op:</b> Forventes i drift den 20.02.25</p>
      <p><b>Kommende moderniseringsprojekter:</b></p>
      <p><b>Holbæk spor 1:</b> Renovering af elevator.</p>
    </section>"""
    r = parse(html)
    assert [(x.asset_type, x.raw_label) for x in r.rows] == [
        ("elevator", "Ordrup lift"), ("escalator", "Nørrebro spor 11 op")]
    assert r.rows[0].expected_date == "2025-02-14"
