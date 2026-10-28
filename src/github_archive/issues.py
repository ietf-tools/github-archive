import json
import re
import subprocess
import sys

COST = re.compile(r"^Used (\d+) points", re.MULTILINE)


def archive_issues(name, out, reference):
    # archive-repo reads GITHUB_TOKEN from the environment and logs each query's cost to stderr.
    command = [sys.executable, "-m", "archive-repo", "archive", name, str(out)]
    if reference:
        command += ["--reference", str(reference)]
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    archive = json.loads(out.read_text())
    points = sum(int(cost) for cost in COST.findall(result.stderr))
    return len(archive["issues"]), len(archive.get("pulls", [])), points
