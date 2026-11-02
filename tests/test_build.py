from datetime import date

from hyrox.build import with_readiness


def test_readiness_filled_from_recovery_metrics():
    well = {f"2026-10-{d:02d}": {"date": f"2026-10-{d:02d}", "hrv": 50, "resting_hr": 50,
                                  "sleep_score": 80, "body_battery_high": 90, "readiness": None}
            for d in range(20, 31)}
    rows = with_readiness(well, date(2026, 10, 25))
    assert [r["date"] for r in rows][0] == "2026-10-25"
    assert all(isinstance(r["readiness"], int) and 0 <= r["readiness"] <= 100 for r in rows)
    assert well["2026-10-30"]["readiness"] is None  # cached data left untouched


def test_garmin_readiness_kept_and_no_data_stays_empty():
    well = {"2026-10-30": {"date": "2026-10-30", "readiness": 62},
            "2026-10-31": {"date": "2026-10-31", "readiness": None}}
    rows = with_readiness(well, date(2026, 10, 1))
    assert rows[0]["readiness"] == 62
    assert rows[1]["readiness"] is None
