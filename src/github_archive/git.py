import os
import shutil
import subprocess

ENV = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"} | {"GIT_TERMINAL_PROMPT": "0"}

# Anonymous clones, maintenance in the foreground so it can't race the day
# copy, and give up on a transfer that stalls.
CONFIG = (
    "credential.helper=",
    "maintenance.autoDetach=false",
    "gc.autoDetach=false",
    "http.lowSpeedLimit=1000",
    "http.lowSpeedTime=600",
)


def git(*args):
    options = [arg for setting in CONFIG for arg in ("-c", setting)]
    return subprocess.run(
        ["git", *options, *args],
        env=ENV, check=True, capture_output=True, text=True,
    ).stdout


def github_url(name):
    return f"https://github.com/{name}.git"


def clone(source, dest, *options):
    # Clone aside so a failed or killed clone never replaces a good one.
    partial = dest.with_name(dest.name + ".partial")
    if partial.exists():
        shutil.rmtree(partial)
    dest.parent.mkdir(parents=True, exist_ok=True)
    git("clone", "--mirror", "--quiet", *options, source, partial)
    return partial


def update_mirror(name, mirror):
    if mirror.exists():
        # Only one run holds DATA_DIR/lock, so any git lock left here is stale.
        for lock in mirror.rglob("*.lock"):
            lock.unlink()
        git("-C", mirror, "remote", "update", "--prune")
        return False
    clone(github_url(name), mirror).rename(mirror)
    return True


def copy_mirror(name, mirror, copy):
    # A local clone hardlinks the objects; --template= skips the sample hooks.
    partial = clone(mirror, copy, "--template=")
    git("-C", partial, "remote", "set-url", "origin", github_url(name))
    if copy.exists():
        shutil.rmtree(copy)
    partial.rename(copy)


def ref_count(repo):
    return len(git("-C", repo, "for-each-ref", "--format=x").splitlines())


def size_bytes(repo):
    stats = dict(line.split(": ") for line in git("-C", repo, "count-objects", "-v").splitlines())
    return (int(stats["size"]) + int(stats["size-pack"])) * 1024
