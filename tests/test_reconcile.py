from datetime import datetime, timedelta, timezone

from scraper.parse import Row, parse
from scraper.reconcile import reconcile
from scraper.stats import compute, load_incidents

T0 = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)
BOTH = {"elevator", "escalator"}


def row(label="Bispebjerg", expected="2026-10-24"):
    return Row("elevator", label, f"Forventes i drift den {expected}", "expected", expected)


def other():
    return Row("elevator", "Sorø spor 1", "x", "expected", "2026-11-07")


def incidents(table):
    return load_incidents(table)


def test_first_scrape_is_lower_bound(table, html):
    reconcile(table, parse(html).rows, BOTH, T0)
    incs = incidents(table)
    assert len(incs) == 33
    assert all(i["start_is_lower_bound"] for i in incs)
    reconcile(table, [row(), Row("elevator", "Valby", "x", "unknown", None)], BOTH, T0 + H)
    new = next(i for i in incidents(table) if i["station"] == "Valby")
    assert not new["start_is_lower_bound"]


def test_closes_after_two_absences(table):
    reconcile(table, [row(), other()], BOTH, T0)
    reconcile(table, [other()], BOTH, T0 + H)
    assert next(i for i in incidents(table) if i["station"] == "Bispebjerg")["end"] is None
    s = reconcile(table, [other()], BOTH, T0 + 2 * H)
    assert s.closed == ["elevator:bispebjerg"]
    bis = next(i for i in incidents(table) if i["station"] == "Bispebjerg")
    assert bis["end"] == (T0 + H).isoformat()  # first absent scrape


def test_single_blip_does_not_close(table):
    reconcile(table, [row(), other()], BOTH, T0)
    reconcile(table, [other()], BOTH, T0 + H)
    reconcile(table, [row(), other()], BOTH, T0 + 2 * H)
    reconcile(table, [row(), other()], BOTH, T0 + 3 * H)
    bis = [i for i in incidents(table) if i["station"] == "Bispebjerg"]
    assert len(bis) == 1 and bis[0]["end"] is None


def test_reappearing_within_24h_merges(table):
    reconcile(table, [row(), other()], BOTH, T0)
    reconcile(table, [other()], BOTH, T0 + H)
    reconcile(table, [other()], BOTH, T0 + 2 * H)
    s = reconcile(table, [row(), other()], BOTH, T0 + 10 * H)
    assert s.reopened == ["elevator:bispebjerg"]
    bis = [i for i in incidents(table) if i["station"] == "Bispebjerg"]
    assert len(bis) == 1 and bis[0]["end"] is None


def test_reappearing_after_24h_is_new_incident(table):
    reconcile(table, [row(), other()], BOTH, T0)
    reconcile(table, [other()], BOTH, T0 + H)
    reconcile(table, [other()], BOTH, T0 + 2 * H)
    reconcile(table, [row(), other()], BOTH, T0 + 48 * H)
    assert len([i for i in incidents(table) if i["station"] == "Bispebjerg"]) == 2


def test_missing_section_does_not_close(table):
    reconcile(table, [row(), Row("escalator", "Nørrebro spor 11 op", "x", "unknown", None)], BOTH, T0)
    for n in (1, 2, 3):
        reconcile(table, [row()], {"elevator"}, T0 + n * H)
    esc = next(i for i in incidents(table) if i["asset_type"] == "escalator")
    assert esc["end"] is None


def test_expected_date_history_and_stats(table):
    reconcile(table, [other()], BOTH, T0 - H)  # so Bispebjerg start is precise
    reconcile(table, [row(), other()], BOTH, T0)
    reconcile(table, [row(expected="2026-10-30"), other()], BOTH, T0 + H)
    end = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    reconcile(table, [row(expected="2026-10-30"), other()], BOTH, end - H)
    reconcile(table, [other()], BOTH, end)
    reconcile(table, [other()], BOTH, end + H)
    bis = next(i for i in incidents(table) if i["station"] == "Bispebjerg")
    assert bis["expected_history"] == ["2026-10-24", "2026-10-30"]
    assert bis["expected_changes"] == 1

    stats, current = compute(incidents(table), end + H)
    assert stats["repair_days"]["elevator"]["n"] == 1
    assert stats["repair_days"]["elevator"]["median"] == 13.0
    assert stats["promises"]["closed_late"] == 1
    assert stats["promises"]["date_moved"] == 1
    assert [c["station"] for c in current] == ["Sorø"]


def test_wide_start_window_is_lower_bound(table):
    reconcile(table, [other()], BOTH, T0 - timedelta(days=90), source="wayback")
    reconcile(table, [row(), other()], BOTH, T0)
    bis = next(i for i in incidents(table) if i["station"] == "Bispebjerg")
    assert bis["start_is_lower_bound"] and bis["estimated"]
