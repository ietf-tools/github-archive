import json
import shutil
from datetime import date

from .log import event


def day_dirs(daily):
    dirs = {}
    if daily.is_dir():
        for path in daily.iterdir():
            try:
                dirs[date.fromisoformat(path.name)] = path
            except ValueError:
                continue
    return dirs


def backed_up_anything(day_dir):
    run = day_dir / "run.json"
    return run.exists() and json.loads(run.read_text())["ok"] > 0


def days_to_keep(days, complete, today, keep_daily, keep_monthly):
    keep = {day for day in days if (today - day).days < keep_daily}
    first_of_month = {}
    for day in sorted(complete):
        first_of_month.setdefault((day.year, day.month), day)
    for (year, month), day in first_of_month.items():
        months_ago = (today.year - year) * 12 + today.month - month
        if keep_monthly == 0 or months_ago < keep_monthly:
            keep.add(day)
    return keep


def apply_retention(daily, today, keep_daily, keep_monthly):
    dirs = day_dirs(daily)
    complete = {day for day, path in dirs.items() if backed_up_anything(path)}
    keep = days_to_keep(dirs, complete, today, keep_daily, keep_monthly)
    deleted = sorted(day for day in dirs if day not in keep)
    for day in deleted:
        shutil.rmtree(dirs[day])
    event("retention_done", kept=len(keep), deleted=[day.isoformat() for day in deleted])
