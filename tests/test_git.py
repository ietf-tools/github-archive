import pytest

from github_archive import git

NAME = "ietf-wg-example/draft"


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    repo = tmp_path / "upstream"
    git.git("init", "--quiet", "--initial-branch=main", repo)
    commit(repo, "one")
    monkeypatch.setattr(git, "github_url", lambda name: str(repo))
    return repo


def commit(repo, message, *options):
    git.git(
        "-C", repo, "-c", "user.name=test", "-c", "user.email=test@example.org", "-c", "commit.gpgsign=false",
        "commit", "--quiet", "--allow-empty", "-m", message, *options,
    )
    return git.git("-C", repo, "rev-parse", "HEAD").strip()


def head(repo):
    return git.git("-C", repo, "rev-parse", "main").strip()


def object_inodes(repo):
    objects = repo / "objects"
    return {p.relative_to(objects): p.stat().st_ino for p in objects.rglob("*") if p.is_file() and "info" not in p.parts}


def test_day_copies_share_objects(tmp_path, upstream):
    mirror = tmp_path / "mirror.git"
    assert git.update_mirror(NAME, mirror) is True
    git.copy_mirror(NAME, mirror, tmp_path / "day1.git")
    commit(upstream, "two")
    assert git.update_mirror(NAME, mirror) is False
    git.copy_mirror(NAME, mirror, tmp_path / "day2.git")

    day1 = object_inodes(tmp_path / "day1.git")
    day2 = object_inodes(tmp_path / "day2.git")
    assert day1 and day1.items() < day2.items()
    assert git.git("-C", tmp_path / "day2.git", "remote", "get-url", "origin").strip() == str(upstream)


def test_force_push_and_gc_leave_earlier_copies_intact(tmp_path, upstream):
    mirror = tmp_path / "mirror.git"
    git.update_mirror(NAME, mirror)
    git.copy_mirror(NAME, mirror, tmp_path / "day1.git")
    original = head(upstream)

    rewritten = commit(upstream, "rewritten", "--amend")
    git.update_mirror(NAME, mirror)
    git.git("-C", mirror, "gc", "--quiet", "--prune=now")
    git.copy_mirror(NAME, mirror, tmp_path / "day2.git")

    assert head(tmp_path / "day1.git") == original
    assert head(tmp_path / "day2.git") == rewritten
    git.git("-C", tmp_path / "day1.git", "fsck", "--no-progress")


def test_recovers_from_a_killed_run(tmp_path, upstream):
    mirror = tmp_path / "mirror.git"
    (tmp_path / "mirror.git.partial").mkdir()
    git.git("-C", upstream, "branch", "old")
    git.update_mirror(NAME, mirror)
    (mirror / "packed-refs.lock").touch()
    git.git("-C", upstream, "branch", "-D", "old")

    git.update_mirror(NAME, mirror)
    assert git.git("-C", mirror, "for-each-ref", "--format=%(refname)").split() == ["refs/heads/main"]
    assert not (tmp_path / "mirror.git.partial").exists()
