import pytest

from elevator_tracker.stations import normalize


@pytest.mark.parametrize("a,b", [
    ("Århus H Spor 2-3", "Århus spor 2-3"),
    ("Århus Banegård spor 2-3", "Aarhus H spor 2-3"),
    ("Sorø spor 1 ", "Sorø  spor 1"),
])
def test_variants_collapse(a, b):
    assert normalize(a).asset_id == normalize(b).asset_id


@pytest.mark.parametrize("label,asset_id,station", [
    ("Bispebjerg", "bispebjerg", "Bispebjerg"),
    ("Svanemøllen spor 3-4", "svanemoellen:spor-3-4", "Svanemøllen"),
    ("København H, Reventlowsgade til Forhal", "koebenhavn-h:reventlowsgade-til-forhal", "København H"),
    ("Taastrup st. spor 3-4 gangtunnel", "taastrup:spor-3-4-gangtunnel", "Taastrup"),
    ("Birkerød Læssevej sti", "birkeroed:laessevej-sti", "Birkerød"),
    ("Malmparken St. - spor 1", "malmparken:spor-1", "Malmparken"),
    ("Viborg Bygningselevator", "viborg:bygningselevator", "Viborg"),
    ("Ordrup lift", "ordrup:lift", "Ordrup"),
])
def test_normalize(label, asset_id, station):
    a = normalize(label)
    assert (a.asset_id, a.station) == (asset_id, station)
