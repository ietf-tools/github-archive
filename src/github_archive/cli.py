import argparse
import fcntl
import json
import logging
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from subprocess import CalledProcessError

from . import git
from .inventory import GitHub, build_inventory
from .issues import archive_issues
from .log import event, setup
from .retention import apply_retention, latest_before


@dataclass(frozen=True)
class Config:
    datatracker_url: str
    data_dir: Path
    extra_repos: tuple
    exclude_repos: tuple
    only_owners: tuple
    only_repos: tuple
    keep_daily: int
    keep_monthly: int
    concurrency: int
    log_level: str


def load_config(env):
    def names(name):
        return tuple(n.strip() for n in env.get(name, "").split(",") if n.strip())

    def lower(name):
        return tuple(n.lower() for n in names(name))

    return Config(
        datatracker_url=env.get("DATATRACKER_URL", "https://datatracker.ietf.org").rstrip("/"),
        data_dir=Path(env.get("DATA_DIR", "/data")),
        extra_repos=names("EXTRA_REPOS"),
        exclude_repos=lower("EXCLUDE_REPOS"),
        only_owners=lower("ONLY_OWNERS"),
        only_repos=lower("ONLY_REPOS"),
        keep_daily=int(env.get("KEEP_DAILY", "30")),
        keep_monthly=int(env.get("KEEP_MONTHLY", "12")),
        concurrency=int(env.get("CONCURRENCY", "1")),
        log_level=env.get("LOG_LEVEL", "info"),
    )


def take_inventory(config, github, day_dir):
    try:
        repos, sources = build_inventory(config, github)
    except (OSError, json.JSONDecodeError) as e:
        event("inventory_failed", logging.ERROR, reason=f"API error: {e}")
        return None
    event("inventory_done", sources=sources, repos=len(repos))
    if not repos:
        event("inventory_failed", logging.ERROR, reason="empty")
        return None
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "inventory.json").write_text(json.dumps(repos, indent=2) + "\n")
    return repos


def backup_repo(config, name, day_dir):
    started = time.monotonic()
    mirror = config.data_dir / "mirrors" / f"{name.lower()}.git"
    copy = day_dir / f"{name.lower()}.git"
    archive = f"{name.lower()}.archive.json"
    step = "fetch"
    try:
        created = git.update_mirror(name, mirror)
        step = "copy"
        git.copy_mirror(name, mirror, copy)
        refs, size = git.ref_count(copy), git.size_bytes(mirror)
        step = "archive"
        reference = latest_before(day_dir.parent, date.fromisoformat(day_dir.name), archive)
        issues, prs, points = archive_issues(name, day_dir / archive, reference)
    except Exception as e:
        # archive-repo logs every query, so its error is at the end.
        error = "\n".join(e.stderr.strip().splitlines()[-5:]) if isinstance(e, CalledProcessError) else repr(e)
        event("repo_failed", logging.ERROR, repo=name, step=step, error=error)
        return None
    event(
        "repo_done",
        repo=name,
        duration=round(time.monotonic() - started, 1),
        refs=refs,
        mirror_bytes=size,
        mirror_created=created,
        issues=issues,
        prs=prs,
        incremental=reference is not None,
        graphql_points=points,
    )
    return points


def run(config, token, command, dry_run):
    started = time.monotonic()
    today = datetime.now(UTC).date()
    daily = config.data_dir / "daily"
    day_dir = daily / today.isoformat()
    github = GitHub(token)
    event("run_start", version=version("github-archive"), command=command, dry_run=dry_run, config=asdict(config))

    if dry_run:
        repos, sources = build_inventory(config, github)
        event("inventory_done", sources=sources, repos=len(repos))
        print("\n".join(repos))
        return 0

    config.data_dir.mkdir(parents=True, exist_ok=True)
    with open(config.data_dir / "lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            event("run_done", logging.ERROR, aborted="another run holds the lock")
            return 1

        repos = take_inventory(config, github, day_dir)
        if repos is None:
            event("run_done", logging.ERROR, aborted="inventory", duration=round(time.monotonic() - started))
            return 1
        if command == "inventory":
            return 0

        with ThreadPoolExecutor(config.concurrency) as pool:
            results = list(pool.map(lambda name: backup_repo(config, name, day_dir), repos))
        apply_retention(daily, today, config.keep_daily, config.keep_monthly)

        failed = results.count(None)
        summary = {
            "repos": len(repos),
            "ok": len(repos) - failed,
            "failed": failed,
            "duration": round(time.monotonic() - started),
            "rest_requests": github.requests,
            "graphql_points": sum(points for points in results if points is not None),
        }
        (day_dir / "run.json").write_text(json.dumps(summary, indent=2) + "\n")
        event("run_done", logging.ERROR if summary["failed"] else logging.INFO, **summary)
        return 1 if summary["failed"] else 0


def main():
    parser = argparse.ArgumentParser(prog="github-archive")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help in (
        ("run", "back up every repo in the inventory"),
        ("inventory", "build the inventory and write it to today's directory"),
    ):
        command = commands.add_parser(name, help=help)
        command.add_argument("--dry-run", action="store_true", help="print the inventory and exit without touching DATA_DIR")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or sys.exit("GITHUB_TOKEN is not set")
    config = load_config(os.environ)
    setup(config.log_level, uuid.uuid4().hex[:12], token)
    sys.exit(run(config, token, args.command, args.dry_run))
