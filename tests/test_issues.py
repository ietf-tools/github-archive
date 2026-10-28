import json
import subprocess

from github_archive import issues


def test_counts_issues_prs_and_query_cost(tmp_path, monkeypatch):
    out = tmp_path / "owner" / "repo.archive.json"
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        out.write_text(json.dumps({"issues": [{}, {}], "pulls": [{}]}))
        return subprocess.CompletedProcess(command, 0, "", "Used 3 points; 4706 remaining\nnoise\nUsed 5 points; 4701 remaining\n")

    monkeypatch.setattr(subprocess, "run", run)
    assert issues.archive_issues("owner/repo", out, tmp_path / "old.json") == (2, 1, 8)
    assert calls[0][-2:] == ["--reference", str(tmp_path / "old.json")]
