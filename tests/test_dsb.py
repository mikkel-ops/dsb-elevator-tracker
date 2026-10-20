import pytest

from elevator_tracker.dsb import EXPECTED, INDEFINITE, PERMANENT, ParseError, classify_status, parse


def test_fixture_elevators_only(html):
    r = parse(html)
    assert r.found_section
    assert len(r.rows) == 19
    assert not any("Tåstrup" in x.raw_label for x in r.rows)  # escalators ignored
    assert not any("Vipperød" in x.raw_label for x in r.rows)  # modernisation ignored
    assert r.dsb_updated == "20. okt. 13:33"


def test_bispebjerg(html):
    row = next(x for x in parse(html).rows if x.raw_label == "Bispebjerg")
    assert (row.status_kind, row.expected_date) == (EXPECTED, "2026-10-24")


@pytest.mark.parametrize("text,kind,date", [
    ("Forventes i drift den 24.10.26", EXPECTED, "2026-10-24"),
    ("Forventes i drift 14.02.25", EXPECTED, "2025-02-14"),
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


def test_paragraph_headings_and_duplicates():
    html = """<section aria-label="Stations information">
      <h3><b>Elevatorer på følgende stationer er ude af drift:</b></h3>
      <p><b>Ordrup lift:</b> Forventes i drift 14.02.25</p>
      <p><b>Ordrup lift :</b> Forventes i drift 14.02.25</p>
      <p><b><u>Rulletrapperne på følgende stationer er ude af drift:</u></b></p>
      <p><b>Nørrebro spor 11 op:</b> Forventes i drift den 20.02.25</p>
    </section>"""
    assert [x.raw_label for x in parse(html).rows] == ["Ordrup lift"]


def test_no_elevator_section():
    r = parse('<section aria-label="Stations information"><h3>Kommende moderniseringsprojekter:</h3>'
              '<p><b>Holbæk:</b> x</p></section>')
    assert not r.found_section and r.rows == []
