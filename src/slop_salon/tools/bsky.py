"""Single `bsky` CLI: a thin wrapper over the ATProto XRPC API.

Three subcommands cover everything Bluesky can do:

- `bsky get <nsid> [--param k=v ...]` — call a query method (GET)
- `bsky post <nsid> [--json '<body>' | --file <path>]` — call a procedure (POST)
- `bsky whoami` — print {did, handle, pds} as JSON

Auth via BSKY_HANDLE / BSKY_PASSWORD env vars. Each invocation runs
createSession against bsky.social, then follows didDoc to find the user's
real PDS, so every call hits the right server even when AppView is lagging
on a freshly-changed handle.

We ship no record-shape helpers — the agent constructs JSON bodies itself
(typically with `jq`). The reasoning: a single thin wrapper is easier for an
agent to model than a fleet of per-operation tools, and the agent's
`CLAUDE.md` plus `bsky --help` carry the recipes for everything common.
"""

from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
import typer

DEFAULT_PDS = "https://bsky.social"
DEFAULT_TIMEOUT = 20.0
UPLOAD_TIMEOUT = 60.0


COOKBOOK = """\
Recipes (the agent reaches for these most often).

Every action is composed from three primitives: `bsky get <nsid>` for queries,
`bsky post <nsid>` for procedures, `bsky whoami` for your identity. The
agent constructs JSON bodies with `jq`. Look up any NSID at
https://docs.bsky.app/docs/api/.

  # Who am I?
  bsky whoami                                                  # → {"did": "...", "handle": "...", "pds": "..."}

  # Read your home feed / notifications.
  bsky get app.bsky.feed.getTimeline --param limit=20
  bsky get app.bsky.notification.listNotifications --param limit=20

  # Read someone else's feed.
  bsky get app.bsky.feed.getAuthorFeed --param actor=mina.slopsalon.art --param limit=20

  # Post text.
  DID=$(bsky whoami | jq -r .did)
  NOW=$(date -u +%Y-%m-%dT%H:%M:%S.000Z)
  bsky post com.atproto.repo.createRecord --json "$(jq -nc --arg did "$DID" --arg now "$NOW" \\
    '{repo:$did, collection:"app.bsky.feed.post",
      record:{"$type":"app.bsky.feed.post", text:"hello", createdAt:$now, langs:["en"]}}')"

  # Post with an image. Alt text is mandatory (editorial norm).
  BLOB=$(bsky post com.atproto.repo.uploadBlob --file ./assets/sketch.png | jq -c .blob)
  bsky post com.atproto.repo.createRecord --json "$(jq -nc --arg did "$DID" --arg now "$NOW" --argjson blob "$BLOB" \\
    '{repo:$did, collection:"app.bsky.feed.post",
      record:{"$type":"app.bsky.feed.post", text:"today", createdAt:$now, langs:["en"],
              embed:{"$type":"app.bsky.embed.images", images:[{alt:"sketch of a hand", image:$blob}]}}}')"

  # Reply in a thread. The reply ref must trace back to the THREAD ROOT —
  # if the parent is itself a reply, copy its root; otherwise parent IS root.
  # Getting this wrong silently breaks threading.
  PARENT_URI="at://did:plc:.../app.bsky.feed.post/abc"
  PARENT=$(bsky get app.bsky.feed.getPosts --param "uris=$PARENT_URI" | jq -c '.posts[0]')
  REPLY=$(jq -nc --argjson p "$PARENT" \\
    '{parent:{uri:$p.uri, cid:$p.cid},
      root:($p.record.reply.root // {uri:$p.uri, cid:$p.cid})}')
  bsky post com.atproto.repo.createRecord --json "$(jq -nc --arg did "$DID" --arg now "$NOW" --argjson reply "$REPLY" \\
    '{repo:$did, collection:"app.bsky.feed.post",
      record:{"$type":"app.bsky.feed.post", text:"agreed", createdAt:$now, langs:["en"], reply:$reply}}')"

  # Quote-post (commentary on another post).
  QUOTED=$(bsky get app.bsky.feed.getPosts --param "uris=$PARENT_URI" | jq -c '.posts[0] | {uri, cid}')
  bsky post com.atproto.repo.createRecord --json "$(jq -nc --arg did "$DID" --arg now "$NOW" --argjson q "$QUOTED" \\
    '{repo:$did, collection:"app.bsky.feed.post",
      record:{"$type":"app.bsky.feed.post", text:"see also", createdAt:$now, langs:["en"],
              embed:{"$type":"app.bsky.embed.record", record:$q}}}')"

  # Follow a handle.
  SUBJ=$(bsky get com.atproto.identity.resolveHandle --param handle=mina.slopsalon.art | jq -r .did)
  bsky post com.atproto.repo.createRecord --json "$(jq -nc --arg did "$DID" --arg subj "$SUBJ" --arg now "$NOW" \\
    '{repo:$did, collection:"app.bsky.graph.follow",
      record:{"$type":"app.bsky.graph.follow", subject:$subj, createdAt:$now}}')"

  # Unfollow. Find the follow record's rkey, then deleteRecord.
  RKEY=$(bsky get com.atproto.repo.listRecords --param "repo=$DID" --param collection=app.bsky.graph.follow --param limit=100 \\
         | jq -r --arg subj "$SUBJ" '.records[] | select(.value.subject == $subj) | .uri | split("/") | last')
  bsky post com.atproto.repo.deleteRecord --json "$(jq -nc --arg did "$DID" --arg rkey "$RKEY" \\
    '{repo:$did, collection:"app.bsky.graph.follow", rkey:$rkey}')"

  # Set avatar / displayName / description. Read existing profile first so
  # you don't clobber the other fields. The profile record's rkey is always "self".
  AVATAR=$(bsky post com.atproto.repo.uploadBlob --file ./assets/pfp.jpg | jq -c .blob)
  PROFILE=$(bsky get com.atproto.repo.getRecord --param "repo=$DID" --param collection=app.bsky.actor.profile --param rkey=self \\
            | jq -c '.value // {}')
  bsky post com.atproto.repo.putRecord --json "$(jq -nc --arg did "$DID" --argjson prof "$PROFILE" --argjson av "$AVATAR" \\
    '{repo:$did, collection:"app.bsky.actor.profile", rkey:"self",
      record:($prof + {"$type":"app.bsky.actor.profile", avatar:$av})}')"
"""

app = typer.Typer(
    add_completion=False,
    help=(
        "Thin wrapper over the Bluesky / ATProto XRPC API. Run `bsky cookbook` "
        "for worked recipes (post, reply, follow, set avatar, ...)."
    ),
    no_args_is_help=True,
)


@dataclass(frozen=True)
class Session:
    did: str
    handle: str
    access_jwt: str
    pds: str

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_jwt}"}


def _xrpc_error(resp: httpx.Response, endpoint: str) -> None:
    """Print an XRPC error and exit. Bluesky returns JSON {error, message} on failure."""
    try:
        body = resp.json()
        detail = f"{body.get('error', '?')}: {body.get('message', resp.text)}"
    except ValueError:
        detail = resp.text
    typer.echo(f"error: {endpoint} returned {resp.status_code}: {detail}", err=True)
    raise typer.Exit(code=1)


def _get_session() -> Session:
    """Authenticate against bsky.social and point future calls at the user's real PDS.

    bsky.social is the auth entry point; the actual PDS endpoint (where the
    repo lives) is in the returned didDoc's `AtprotoPersonalDataServer`
    service entry. For accounts on bsky.social's hosting fleet, that's
    typically `https://<shard>.us-west.host.bsky.network`.
    """
    handle = os.environ.get("BSKY_HANDLE")
    password = os.environ.get("BSKY_PASSWORD")
    if not handle:
        typer.echo("error: BSKY_HANDLE env var is required", err=True)
        raise typer.Exit(code=1)
    if not password:
        typer.echo("error: BSKY_PASSWORD env var is required", err=True)
        raise typer.Exit(code=1)
    resp = httpx.post(
        f"{DEFAULT_PDS}/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code != 200:
        _xrpc_error(resp, "createSession")
    data = resp.json()
    pds = DEFAULT_PDS
    for svc in data.get("didDoc", {}).get("service") or []:
        if svc.get("type") == "AtprotoPersonalDataServer":
            pds = svc["serviceEndpoint"]
            break
    return Session(did=data["did"], handle=data["handle"], access_jwt=data["accessJwt"], pds=pds)


def _parse_params(items: list[str]) -> list[tuple[str, str]]:
    """Parse repeatable `--param k=v` into ordered (key, value) pairs.

    Kept as a list rather than a dict so the same key can appear more than
    once (e.g. `--param uris=at://x --param uris=at://y` for getPosts,
    which takes an array per ATProto's URL-encoding convention).
    """
    pairs: list[tuple[str, str]] = []
    for item in items:
        if "=" not in item:
            typer.echo(f"error: --param must be key=value, got {item!r}", err=True)
            raise typer.Exit(code=1)
        key, value = item.split("=", 1)
        pairs.append((key, value))
    return pairs


def _mime_of(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


@app.command()
def get(
    nsid: str = typer.Argument(..., help="XRPC method NSID, e.g. app.bsky.feed.getTimeline"),
    param: list[str] = typer.Option(None, "--param", help="Query param as key=value; repeatable"),
):
    """GET an XRPC query method; prints the JSON response to stdout."""
    pairs = _parse_params(param or [])
    session = _get_session()
    resp = httpx.get(
        f"{session.pds}/xrpc/{nsid}",
        params=pairs,
        headers=session.auth_headers,
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code != 200:
        _xrpc_error(resp, nsid)
    typer.echo(resp.text)


@app.command()
def post(
    nsid: str = typer.Argument(..., help="XRPC method NSID, e.g. com.atproto.repo.createRecord"),
    json_body: str = typer.Option(
        None, "--json", help="JSON body as a string. Mutually exclusive with --file."
    ),
    file: Path = typer.Option(
        None, "--file", help="Binary file to upload (e.g. for com.atproto.repo.uploadBlob)"
    ),
):
    """POST to an XRPC procedure; prints the JSON response to stdout.

    With --json: Content-Type is application/json and the body is the
    given JSON string. With --file: Content-Type is auto-detected from
    the file extension and the body is the raw bytes (use for uploadBlob).
    With neither: an empty POST (most procedures need a body, so this is
    rarely what you want).
    """
    if json_body is not None and file is not None:
        typer.echo("error: --json and --file are mutually exclusive", err=True)
        raise typer.Exit(code=1)
    parsed: object = None
    if json_body is not None:
        try:
            parsed = json.loads(json_body)
        except json.JSONDecodeError as e:
            typer.echo(f"error: --json is not valid JSON: {e}", err=True)
            raise typer.Exit(code=1) from e
    session = _get_session()
    url = f"{session.pds}/xrpc/{nsid}"
    if file is not None:
        resp = httpx.post(
            url,
            headers={**session.auth_headers, "Content-Type": _mime_of(file)},
            content=file.read_bytes(),
            timeout=UPLOAD_TIMEOUT,
        )
    elif json_body is not None:
        resp = httpx.post(url, headers=session.auth_headers, json=parsed, timeout=DEFAULT_TIMEOUT)
    else:
        resp = httpx.post(url, headers=session.auth_headers, timeout=DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        _xrpc_error(resp, nsid)
    typer.echo(resp.text)


@app.command()
def whoami():
    """Print {did, handle, pds} for the current credentials as JSON."""
    session = _get_session()
    typer.echo(json.dumps({"did": session.did, "handle": session.handle, "pds": session.pds}))


@app.command()
def cookbook():
    """Print worked recipes for the common Bluesky operations.

    Lives as its own subcommand (not in `--help`) because typer's help
    renderer collapses whitespace and would mangle the shell snippets.
    """
    typer.echo(COOKBOOK)
