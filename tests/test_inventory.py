import io
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import unquote

import pytest

from github_archive import inventory as inv
from github_archive.cli import load_config
from github_archive.inventory import next_link, parse_github_url


@pytest.mark.parametrize("value, expected", [
    ("https://github.com/core-wg/yang-cbor", ("core-wg", "yang-cbor")),
    ("https://github.com/intarchboard/program-rfced-future/", ("intarchboard", "program-rfced-future")),
    ("http://github.com/thunderpoot/readability-draft/", ("thunderpoot", "readability-draft")),
    ("https://www.github.com/ietf-wg-dnsop/wg-materials", ("ietf-wg-dnsop", "wg-materials")),
    ("https://github.com/Flowdalic/xeps/tree/master/draft-schmaus-kitten-sasl-ht", ("Flowdalic", "xeps")),
    ("https://github.com/Domain-Connect/spec/tree/feature/ietf-submission", ("Domain-Connect", "spec")),
    ("https://github.com/tls-stuff/rfc8447bis/blob/main/draft-salowey-tls-rfc8447bis.md", ("tls-stuff", "rfc8447bis")),
    ("https://github.com/isakruas/ecdp/releases/tag/draft-ruas-cfrg-ecdp-00", ("isakruas", "ecdp")),
    ("https://github.com/PowerDNS/parent-signals-dot/draft-vandijk-dprive-ds-dot-signal-and-pin", ("PowerDNS", "parent-signals-dot")),
    ("https://github.com/radext-wg/draft-ietf-radext-radiusv11.git", ("radext-wg", "draft-ietf-radext-radiusv11")),
    ("https://github.com/elochin", ("elochin", None)),
    ("https://github.com/BrianSipos?tab=repositories", ("BrianSipos", None)),
    ("https://github.com/orgs/ietf-wg-srv6ops/", ("ietf-wg-srv6ops", None)),
    (" https://GitHub.com/DNSOP/wg-materials ", ("DNSOP", "wg-materials")),
])
def test_parse_github_url(value, expected):
    assert parse_github_url(value) == expected


@pytest.mark.parametrize("value", [
    "https://mlswg.github.io",
    "https://github.com",
    "https://gitlab.com/ietf/foo",
    "github.com/core-wg/yang-cbor",
    "https://[github.com/core-wg/yang-cbor",
])
def test_parse_github_url_rejects(value):
    assert parse_github_url(value) is None


def test_next_link():
    header = '<https://api.github.com/user/1/repos?page=2>; rel="next", <https://api.github.com/user/1/repos?page=5>; rel="last"'
    assert next_link(header) == "https://api.github.com/user/1/repos?page=2"
    assert next_link('<https://api.github.com/user/1/repos?page=1>; rel="prev"') is None
    assert next_link(None) is None


class FakeGitHub:
    def __init__(self, owners, renamed=None):
        self.owners = owners
        self.renamed = renamed or {}
        self.gets = []

    def pages(self, path):
        owner = path.split("/")[2].lower()
        if owner not in self.owners:
            raise HTTPError(path, 404, "Not Found", Message(), None)
        yield [{"full_name": name} for name in self.owners[owner]]

    def get(self, path):
        self.gets.append(path)
        name = unquote(path.removeprefix("/repos/")).lower()
        name = self.renamed.get(name, name)
        for repos in self.owners.values():
            for full_name in repos:
                if full_name.lower() == name:
                    return {"full_name": full_name}
        raise HTTPError(path, 404, "Not Found", Message(), None)


def inventory(monkeypatch, links, github, **env):
    monkeypatch.setattr(inv, "datatracker_resources", lambda base_url: [("group/groupextresource", f"/r/{i}/", v) for i, v in enumerate(links)])
    return inv.build_inventory(load_config(env), github)[0]


GITHUB = {
    "core-wg": ["core-wg/yang-cbor", "core-wg/wg-materials"],
    "ietf-wg-dnsop": ["ietf-wg-dnsop/wg-materials", "ietf-wg-dnsop/draft-ietf-dnsop-3901bis"],
    "flowdalic": ["Flowdalic/xeps"],
}


def test_dedupes_case_and_paths_and_keeps_canonical_names(monkeypatch):
    links = [
        "https://github.com/Flowdalic/xeps/tree/master/draft-schmaus-kitten-sasl-ht",
        "https://github.com/flowdalic/XEPS",
        "https://github.com/flowdalic/xeps.git",
    ]
    github = FakeGitHub(GITHUB)
    assert inventory(monkeypatch, links, github) == ["Flowdalic/xeps"]
    assert len(github.gets) == 1


def test_expands_owners_without_checking_their_repos_again(monkeypatch):
    links = ["https://github.com/core-wg", "https://github.com/core-wg/yang-cbor"]
    github = FakeGitHub(GITHUB)
    assert inventory(monkeypatch, links, github) == ["core-wg/wg-materials", "core-wg/yang-cbor"]
    assert github.gets == []


def test_follows_renames_and_drops_missing(monkeypatch):
    links = ["https://github.com/DNSOP/wg-materials", "https://github.com/YourOrganization/YourRepo", "https://github.com/gone-user"]
    github = FakeGitHub(GITHUB, renamed={"dnsop/wg-materials": "ietf-wg-dnsop/wg-materials"})
    assert inventory(monkeypatch, links, github) == ["ietf-wg-dnsop/wg-materials"]


def test_other_api_errors_propagate(monkeypatch):
    class RateLimited(FakeGitHub):
        def get(self, path):
            raise HTTPError(path, 403, "rate limit exceeded", Message(), None)

    with pytest.raises(HTTPError):
        inventory(monkeypatch, ["https://github.com/core-wg/yang-cbor"], RateLimited(GITHUB))


def test_filters(monkeypatch):
    links = ["https://github.com/core-wg", "https://github.com/ietf-wg-dnsop"]
    github = FakeGitHub(GITHUB)
    assert inventory(monkeypatch, links, github, ONLY_OWNERS="IETF-WG-DNSOP") == [
        "ietf-wg-dnsop/draft-ietf-dnsop-3901bis",
        "ietf-wg-dnsop/wg-materials",
    ]
    assert inventory(monkeypatch, links, github, ONLY_REPOS="core-wg/yang-cbor") == ["core-wg/yang-cbor"]
    assert inventory(monkeypatch, links, github, EXCLUDE_REPOS="core-wg/wg-materials,ietf-wg-dnsop/wg-materials") == [
        "core-wg/yang-cbor",
        "ietf-wg-dnsop/draft-ietf-dnsop-3901bis",
    ]
    assert inventory(monkeypatch, [], github, EXTRA_REPOS="Flowdalic/xeps") == ["Flowdalic/xeps"]


def test_get_json_retries_server_errors(monkeypatch):
    calls = []

    class Response(io.BytesIO):
        headers = Message()

    def urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) < 3:
            raise HTTPError(request.full_url, 502, "Bad Gateway", Message(), None)
        return Response(b'{"ok": true}')

    monkeypatch.setattr(inv.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(inv.time, "sleep", lambda seconds: None)
    assert inv.get_json("https://api.github.com/x")[0] == {"ok": True}
    assert len(calls) == 3
