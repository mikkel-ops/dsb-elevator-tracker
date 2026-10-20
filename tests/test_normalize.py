import pytest

from scraper.normalize import normalize


@pytest.mark.parametrize("a,b", [
    ("Århus H Spor 2 Ned", "Århus spor 2 ned"),
    ("Høje Tåstrup spor 3-4 op ", "Høje  Tåstrup spor 3-4 op"),
    ("København syd op ved P-Plads", "København Syd op ved P-plads"),
])
def test_variants_collapse(a, b):
    assert normalize("escalator", a).asset_id == normalize("escalator", b).asset_id


def test_station_extraction():
    a = normalize("elevator", "København H, Reventlowsgade til Forhal")
    assert a.station == "København H"
    assert a.asset_id == "elevator:koebenhavn-h:reventlowsgade-til-forhal"
    assert normalize("elevator", "Bispebjerg").asset_id == "elevator:bispebjerg"
    assert normalize("escalator", "Køge nord St. Tugela spor 1 S-tog").station == "Køge Nord"


def test_lift_suffix():
    assert normalize("elevator", "Ordrup lift").asset_id == "elevator:ordrup:lift"
