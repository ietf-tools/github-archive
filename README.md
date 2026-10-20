# github-archive

Backs up the GitHub repositories that the IETF Datatracker links to. It is meant to run once a day as a Kubernetes CronJob with a persistent volume at `DATA_DIR`.

Each run:

1. Builds the inventory from the Datatracker's `github_org` and `github_repo` resources for groups and documents. A link to an owner pulls in all of that owner's public repos, forks included. The run aborts if the inventory is empty.
2. Updates a persistent `git clone --mirror` of each repo, including `refs/pull/*`.
3. Clones each mirror into the day's directory. A local clone hardlinks the object files, so a day's copy costs little more than its refs, and later fetches or a force-push on GitHub can't change it.
4. Deletes day directories that fall outside the retention rules.

Logs are JSON lines on stdout. The process exits non-zero if the run aborted or any repo failed.

## Layout

```
DATA_DIR/
  lock
  mirrors/<owner>/<repo>.git
  daily/<YYYY-MM-DD>/
    inventory.json
    run.json
    <owner>/<repo>.git
```

Owner and repo names are lower case. Dates are UTC.

## Configuration

All configuration comes from environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | required | Read-only token for the GitHub API. Git clones are anonymous |
| `DATATRACKER_URL` | `https://datatracker.ietf.org` | Inventory source |
| `DATA_DIR` | `/data` | Where mirrors and day directories live. Must support hardlinks |
| `EXTRA_REPOS` | empty | Comma-separated `owner/repo` to add |
| `EXCLUDE_REPOS` | empty | Comma-separated `owner/repo` to leave out |
| `ONLY_OWNERS`, `ONLY_REPOS` | empty | Restrict the run to these owners or repos |
| `KEEP_DAILY` | `30` | Keep every day directory from the last this many days |
| `KEEP_MONTHLY` | `12` | Also keep the first day directory of each of the last this many months that backed up at least one repo; `0` keeps every month |
| `CONCURRENCY` | `1` | Repos processed in parallel |
| `LOG_LEVEL` | `info` | |

## Running

```
uv sync
GITHUB_TOKEN=$(gh auth token) DATA_DIR=./data uv run github-archive run
```

`github-archive inventory` builds, checks and writes today's `inventory.json` without backing anything up. Either command with `--dry-run` prints the inventory and leaves `DATA_DIR` alone.
