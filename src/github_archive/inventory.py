import json
import logging
import time
import urllib.request
from collections import Counter
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlsplit

from .log import event

SOURCES = ("group/groupextresource", "doc/docextresource")
RESOURCE_NAMES = ("github_org", "github_repo")
GITHUB_HOSTS = ("github.com", "www.github.com")
# Gone, or blocked for legal reasons. Anything else (rate limits included) aborts the inventory.
MISSING = (404, 410, 451)
ATTEMPTS = 3


def fetch_json(request):
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response), response.headers


def get_json(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    for attempt in range(1, ATTEMPTS):
        try:
            return fetch_json(request)
        except OSError as e:
            if isinstance(e, HTTPError) and e.code < 500:
                raise
        time.sleep(10 * attempt)
    return fetch_json(request)


def datatracker_resources(base_url):
    for source in SOURCES:
        for name in RESOURCE_NAMES:
            url = f"{base_url}/api/v1/{source}/?format=json&name={name}&limit=500"
            while url:
                page, _ = get_json(url)
                for obj in page["objects"]:
                    yield source, obj["resource_uri"], obj["value"]
                url = page["meta"]["next"] and urljoin(base_url, page["meta"]["next"])


def parse_github_url(value):
    try:
        url = urlsplit(value.strip())
    except ValueError:
        return None
    if url.scheme not in ("http", "https") or url.hostname not in GITHUB_HOSTS:
        return None
    parts = [p for p in url.path.split("/") if p]
    # github.com/orgs/<org>/ is an org's page.
    if parts[:1] == ["orgs"]:
        parts = parts[1:2]
    if not parts:
        return None
    repo = parts[1].removesuffix(".git") if len(parts) > 1 else None
    return parts[0], repo or None


def next_link(header):
    for part in (header or "").split(","):
        url, _, rel = part.partition(";")
        if rel.strip() == 'rel="next"':
            return url.strip()[1:-1]
    return None


class GitHub:
    def __init__(self, token):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.requests = 0

    def get(self, path):
        self.requests += 1
        data, _ = get_json("https://api.github.com" + path, self.headers)
        return data

    def pages(self, path):
        url = "https://api.github.com" + path
        while url:
            self.requests += 1
            data, headers = get_json(url, self.headers)
            yield data
            url = next_link(headers.get("Link"))


def build_inventory(config, github):
    owners = {}
    repos = {}
    sources = Counter()
    for source, uri, value in datatracker_resources(config.datatracker_url):
        sources[source] += 1
        parsed = parse_github_url(value)
        if parsed is None:
            event("inventory_skipped", logging.WARNING, source=uri, url=value, reason="not a GitHub owner or repo URL")
            continue
        owner, repo = parsed
        if repo:
            repos.setdefault(f"{owner}/{repo}".lower(), (f"{owner}/{repo}", uri))
        else:
            owners.setdefault(owner.lower(), (owner, uri))
    for name in config.extra_repos:
        repos.setdefault(name.lower(), (name, "EXTRA_REPOS"))

    # Skip API calls for owners an ONLY_* restriction would drop anyway.
    only = {*config.only_owners, *(name.split("/")[0] for name in config.only_repos)}
    if only:
        owners = {k: v for k, v in owners.items() if k in only}
        repos = {k: v for k, v in repos.items() if k.split("/")[0] in only}

    found = {}
    for owner, source in sorted(owners.values()):
        try:
            for page in github.pages(f"/users/{quote(owner)}/repos?per_page=100"):
                for repo in page:
                    found[repo["full_name"].lower()] = repo["full_name"]
        except HTTPError as e:
            if e.code not in MISSING:
                raise
            event("inventory_missing", logging.WARNING, owner=owner, source=source, status=e.code)
    for key, (name, source) in sorted(repos.items()):
        if key in found:
            continue
        try:
            repo = github.get(f"/repos/{quote(name)}")
        except HTTPError as e:
            if e.code not in MISSING:
                raise
            event("inventory_missing", logging.WARNING, repo=name, source=source, status=e.code)
            continue
        found[repo["full_name"].lower()] = repo["full_name"]

    def wanted(key):
        if key in config.exclude_repos:
            return False
        if config.only_owners or config.only_repos:
            return key.split("/")[0] in config.only_owners or key in config.only_repos
        return True

    return [found[key] for key in sorted(found) if wanted(key)], dict(sources)
