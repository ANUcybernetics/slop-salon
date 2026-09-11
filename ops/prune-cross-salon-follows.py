#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "typer"]
# ///
"""Remove Bluesky follows that cross a salon boundary.

A salon is the set of agents that know of each other, so an agent should
follow exactly its derived siblings and nobody else in the collective.
`test_registry_salons_are_closed` keeps the *config* closed; nothing keeps the
*live follow graph* closed, and agents re-follow each other from notifications
and their timeline. This is the repair for that.

Only follows of other slop-salon agents are touched. A follow of an account
outside the collective is the agent's own business and is reported, never
removed.

Removing the follow does not by itself keep the graph closed: an agent whose
SIBLINGS.md still names a cross-salon artist will follow them again. Clean the
file too (a rite is the channel for that) or this comes back.

    uv run ops/prune-cross-salon-follows.py            # dry run
    uv run ops/prune-cross-salon-follows.py --apply
    uv run ops/prune-cross-salon-follows.py --apply --agent mina
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from slop_salon.config import load_config
from slop_salon.provision import resolve_secrets
from slop_salon.tools.bsky import DEFAULT_TIMEOUT, create_session

FOLLOW_COLLECTION = "app.bsky.graph.follow"
PUBLIC_API = "https://public.api.bsky.app"

app = typer.Typer(add_completion=False)


def _resolve_dids(handles: dict[str, str]) -> dict[str, str]:
    """handle -> did, via the public AppView (no auth needed)."""
    out: dict[str, str] = {}
    with httpx.Client(base_url=PUBLIC_API, timeout=DEFAULT_TIMEOUT) as client:
        for name, handle in handles.items():
            resp = client.get("/xrpc/com.atproto.identity.resolveHandle", params={"handle": handle})
            if resp.status_code != 200:
                raise SystemExit(f"could not resolve {handle}: {resp.status_code} {resp.text}")
            out[name] = resp.json()["did"]
    return out


def _follow_records(client: httpx.Client, did: str) -> list[tuple[str, str]]:
    """[(rkey, subject_did)] for every follow in the repo, across pages."""
    records: list[tuple[str, str]] = []
    cursor: str | None = None
    while True:
        params: dict[str, str] = {"repo": did, "collection": FOLLOW_COLLECTION, "limit": "100"}
        if cursor:
            params["cursor"] = cursor
        resp = client.get("/xrpc/com.atproto.repo.listRecords", params=params)
        if resp.status_code != 200:
            raise SystemExit(f"listRecords returned {resp.status_code}: {resp.text}")
        page = resp.json()
        records.extend(
            (rec["uri"].rsplit("/", 1)[-1], rec["value"]["subject"])
            for rec in page.get("records", [])
        )
        cursor = page.get("cursor")
        if not cursor or not page.get("records"):
            return records


@app.command()
def main(
    apply: bool = typer.Option(False, "--apply", help="Actually delete; default is a dry run."),
    agent: str = typer.Option("", "--agent", help="Only this agent; default is every live one."),
    config: str = typer.Option("slop_salon.toml", "--config"),
) -> None:
    cfg = load_config(Path(config))
    live = {n: a for n, a in cfg.agents.items() if a.live and (not agent or n == agent)}
    if not live:
        raise SystemExit(f"no live agents matched {agent!r}")

    dids = _resolve_dids({n: a.handle for n, a in cfg.agents.items() if a.live})
    by_did = {did: name for name, did in dids.items()}

    removed = kept = external = 0
    for name, cfg_agent in live.items():
        password = resolve_secrets(name, list(cfg.agents.keys())).get("BSKY_PASSWORD")
        if not password:
            raise SystemExit(f"no bsky_password for {name} in secrets.toml")
        session = create_session(cfg_agent.handle, password)
        siblings = set(cfg_agent.siblings)

        with httpx.Client(
            base_url=session.pds, headers=session.auth_headers, timeout=DEFAULT_TIMEOUT
        ) as client:
            follows = _follow_records(client, session.did)
            stale = []
            for rkey, subject in follows:
                other = by_did.get(subject)
                if other is None:
                    external += 1
                elif other in siblings:
                    kept += 1
                else:
                    stale.append((rkey, other))

            missing = siblings - {by_did.get(s) for _, s in follows}
            note = f"  (missing sibling follows: {', '.join(sorted(missing))})" if missing else ""
            print(f"{name:<9} salon={cfg_agent.salon:<11} follows={len(follows)}{note}")

            for rkey, other in stale:
                verb = "removing" if apply else "would remove"
                print(f"  {verb} {name} -> {other}  (salon {cfg.agents[other].salon})")
                if apply:
                    resp = client.post(
                        "/xrpc/com.atproto.repo.deleteRecord",
                        json={
                            "repo": session.did,
                            "collection": FOLLOW_COLLECTION,
                            "rkey": rkey,
                        },
                    )
                    if resp.status_code != 200:
                        raise SystemExit(f"deleteRecord failed: {resp.status_code} {resp.text}")
                removed += 1

    verb = "removed" if apply else "would remove"
    print(f"\n{verb} {removed} cross-salon follow(s); kept {kept} sibling, {external} external")
    if not apply and removed:
        print("dry run --- pass --apply to act")


if __name__ == "__main__":
    app()
