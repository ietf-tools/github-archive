# github-archive

Backs up the GitHub repositories that the IETF Datatracker links to. It is meant to run once a day as a Kubernetes CronJob with a persistent volume at `DATA_DIR`.

Each run:

1. Builds the inventory from the Datatracker's `github_org` and `github_repo` resources for groups of the types in `GROUP_TYPES`, by default working groups only. A link to an owner pulls in all of that owner's public repos, forks included. The run aborts if the inventory is empty.
2. Updates a persistent `git clone --mirror` of each repo, including `refs/pull/*`.
3. Clones each mirror into the day's directory. A local clone hardlinks the object files, so a day's copy costs little more than its refs, and later fetches or a force-push on GitHub can't change it.
4. Saves the repo's issues and pull requests, with their comments and reviews, as JSON using [archive-repo](https://github.com/MikeBishop/archive-repo). The newest earlier copy is passed as a reference, so only what changed since is fetched.
5. Deletes day directories that fall outside the retention rules.

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
    <owner>/<repo>.archive.json
```

Owner and repo names are lower case. Dates are UTC.

## Configuration

All configuration comes from environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | required | Token for the GitHub REST and GraphQL APIs; read access to public repos is enough. Git clones are anonymous |
| `DATATRACKER_URL` | `https://datatracker.ietf.org` | Inventory source |
| `GROUP_TYPES` | `wg` | Comma-separated Datatracker group types whose GitHub links are backed up, e.g. `wg,rg` |
| `DATA_DIR` | `/data` | Where mirrors and day directories live. Must support hardlinks |
| `EXTRA_REPOS` | empty | Comma-separated `owner/repo` to add |
| `EXCLUDE_REPOS` | empty | Comma-separated `owner/repo` to leave out |
| `EXCLUDE_OWNERS` | empty | Comma-separated owners whose repos are all left out |
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

## Container

```
podman build --platform linux/amd64 -t github-archive .
```

The image runs `github-archive run` as UID 1000. Mount a writable volume at `DATA_DIR` and an `emptyDir` at `/tmp` if the root filesystem is read-only. Run it as a daily CronJob with `concurrencyPolicy: Forbid` and `backoffLimit: 0`: a repo that fails is retried by the next day's run.

## Cost

Measured on the 27 `ietf-wg-dnsop` repos with `CONCURRENCY=4`:

| | Time | GraphQL points | Points per repo |
|---|---|---|---|
| First run | 45 s | 540 | 20 |
| Next run | 24 s | 243 | 9 |

At about 700 repos, the first run needs around 14,000 points and later runs around 6,500. A token gets 5,000 points an hour, so the first run spends about three hours waiting on the rate limit and later runs about one. archive-repo waits out the limit rather than failing. The inventory's REST requests come from a separate budget.

## Known gaps

- archive-repo is pinned to a commit on a personal fork, `sargeant/archive-repo` (branch `github-archive`), which carries six fixes: retries, rate-limit handling, a broken PR comments query, atomic output, reading the token from `GITHUB_TOKEN`, and upgrading legacy reference files. They need to go upstream as PRs, or the fork needs to move to `ietf-tools`.
- No alerting. A run reports only through its exit code and the JSON logs (`repo_failed`, `inventory_missing`, `run_done`).
- No CI and no published image yet.
- Not yet run in full. Disk use for all repos, and how often `git gc --auto` repacks a mirror (which stops later day copies sharing objects with earlier ones), are still unknown.
- Not backed up: wikis, Git LFS objects, release assets, and Discussions.
- Repos are keyed by name. A rename starts a new mirror and a new issue history, and a reused name continues the old ones.
- An owner link pulls in every public repo of that owner, with no cap on count or size.
- archive-repo truncates labels and assignees at 100, and leaves out some review comment detail (author, path, line).
