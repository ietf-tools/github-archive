import json
from datetime import date, timedelta

from github_archive.retention import apply_retention, days_to_keep, latest_before

TODAY = date(2026, 10, 20)


def every_day(start, end):
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def test_keeps_recent_days_and_first_of_each_month():
    days = every_day(date(2025, 1, 1), TODAY)
    keep = days_to_keep(days, days, TODAY, keep_daily=30, keep_monthly=12)
    recent = set(every_day(TODAY - timedelta(days=29), TODAY))
    monthly = {date(2025, 11, 1), date(2025, 12, 1)} | {date(2026, m, 1) for m in range(1, 11)}
    assert keep == recent | monthly


def test_first_of_month_is_the_earliest_directory_not_the_1st():
    days = [date(2026, 3, 4), date(2026, 3, 9), date(2026, 4, 2)]
    assert days_to_keep(days, days, TODAY, keep_daily=30, keep_monthly=12) == {date(2026, 3, 4), date(2026, 4, 2)}


def test_keep_monthly_zero_keeps_every_month():
    days = [date(2019, 6, 3), date(2019, 6, 4), date(2023, 1, 15)]
    assert days_to_keep(days, days, TODAY, keep_daily=30, keep_monthly=0) == {date(2019, 6, 3), date(2023, 1, 15)}



def test_monthly_snapshot_skips_days_that_backed_up_nothing(tmp_path):
    runs = {"2026-03-01": None, "2026-03-02": {"ok": 0}, "2026-03-03": {"ok": 5}, "2026-03-04": {"ok": 5}}
    for day, run in runs.items():
        (tmp_path / day).mkdir()
        if run:
            (tmp_path / day / "run.json").write_text(json.dumps(run))
    (tmp_path / "lost+found").mkdir()

    apply_retention(tmp_path, TODAY, keep_daily=30, keep_monthly=12)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-03-03", "lost+found"]


def test_latest_before_finds_the_newest_earlier_copy(tmp_path):
    for day in ("2026-10-17", "2026-10-18", "2026-10-21"):
        (tmp_path / day / "owner").mkdir(parents=True)
        (tmp_path / day / "owner" / "repo.archive.json").write_text("{}")
    (tmp_path / "2026-10-19").mkdir()

    assert latest_before(tmp_path, TODAY, "owner/repo.archive.json") == tmp_path / "2026-10-18" / "owner" / "repo.archive.json"
    assert latest_before(tmp_path, TODAY, "owner/other.archive.json") is None
