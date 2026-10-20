from datetime import datetime, timedelta, timezone

from elevator_tracker.dsb import Row, parse
from elevator_tracker.incidents import load_all, reconcile
from elevator_tracker.stats import compute

T0 = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)


def bis(expected="2026-10-24"):
    return Row("Bispebjerg", f"Forventes i drift den {expected}", "expected", expected)


SORO = Row("Sorø spor 1", "x", "expected", "2026-11-07")


def get(table, station="Bispebjerg"):
    return [i for i in load_all(table) if i["station"] == station]


def test_first_scrape_is_lower_bound(table, html):
    reconcile(table, parse(html).rows, T0)
    assert len(load_all(table)) == 19
    assert all(i["start_is_lower_bound"] for i in load_all(table))
    reconcile(table, [bis(), Row("Valby", "x", "unknown", None)], T0 + H)
    assert not get(table, "Valby")[0]["start_is_lower_bound"]


def test_closes_after_two_absences(table):
    reconcile(table, [bis(), SORO], T0)
    reconcile(table, [SORO], T0 + H)
    assert get(table)[0]["end"] is None
    assert reconcile(table, [SORO], T0 + 2 * H).closed == ["bispebjerg"]
    assert get(table)[0]["end"] == (T0 + H).isoformat()  # first absent scrape


def test_single_blip_does_not_close(table):
    for t, rows in [(0, [bis(), SORO]), (1, [SORO]), (2, [bis(), SORO]), (3, [bis(), SORO])]:
        reconcile(table, rows, T0 + t * H)
    assert len(get(table)) == 1 and get(table)[0]["end"] is None


def test_reappearing_within_24h_merges(table):
    for t, rows in [(0, [bis(), SORO]), (1, [SORO]), (2, [SORO])]:
        reconcile(table, rows, T0 + t * H)
    assert reconcile(table, [bis(), SORO], T0 + 10 * H).reopened == ["bispebjerg"]
    assert len(get(table)) == 1 and get(table)[0]["end"] is None


def test_reappearing_after_24h_is_new_incident(table):
    for t, rows in [(0, [bis(), SORO]), (1, [SORO]), (2, [SORO]), (48, [bis(), SORO])]:
        reconcile(table, rows, T0 + t * H)
    assert len(get(table)) == 2


def test_scraper_downtime(table):
    reconcile(table, [bis(), SORO], T0)
    # Scraper down for 3 days: close on first absence, new incident's start imprecise.
    s = reconcile(table, [SORO, Row("Valby", "x", "unknown", None)], T0 + 72 * H)
    assert s.closed == ["bispebjerg"]
    assert not get(table)[0]["end_is_precise"]
    assert get(table, "Valby")[0]["start_is_lower_bound"]


def test_expected_date_history_and_stats(table):
    reconcile(table, [SORO], T0 - H)  # so Bispebjerg's start is known
    reconcile(table, [bis(), SORO], T0)
    reconcile(table, [bis("2026-10-30"), SORO], T0 + H)
    end = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    reconcile(table, [bis("2026-10-30"), SORO], end - H)
    reconcile(table, [SORO], end)
    reconcile(table, [SORO], end + H)
    assert get(table)[0]["expected_history"] == ["2026-10-24", "2026-10-30"]

    stats, current = compute(load_all(table), end + H)
    assert stats["repair_days"]["n"] == 1 and stats["repair_days"]["median"] == 13.0
    assert stats["promises"]["closed_late"] == 1 and stats["promises"]["date_moved"] == 1
    assert [c["station"] for c in current] == ["Sorø"]
    assert stats["open_now"] == {"total": 1, "overdue": 0}


def test_lower_bound_excluded_from_repair_stats(table):
    reconcile(table, [bis(), SORO], T0)  # first scrape: start unknown
    for t in (1, 2):
        reconcile(table, [SORO], T0 + t * H)
    stats, _ = compute(load_all(table), T0 + 3 * H)
    assert stats["repair_days"]["n"] == 0
