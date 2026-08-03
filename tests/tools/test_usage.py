"""Tests for the `slop-usage` sprite-side tally helper."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from slop_salon.tools.usage import (
    PRICE_CACHE_CREATE,
    PRICE_CACHE_READ,
    PRICE_INPUT,
    PRICE_OUTPUT,
    app,
    session_cost,
    tally_dir,
    tally_session,
)

runner = CliRunner()


def _write_session(path: Path, lines: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def _assistant(in_new: int, cc: int, cr: int, output: int) -> dict:
    return {
        "type": "assistant",
        "message": {
            "usage": {
                "input_tokens": in_new,
                "cache_creation_input_tokens": cc,
                "cache_read_input_tokens": cr,
                "output_tokens": output,
            }
        },
    }


def test_tally_session_sums_assistant_usage(tmp_path):
    f = _write_session(
        tmp_path / "abcd1234.jsonl",
        [
            {"type": "queue-operation", "operation": "enqueue", "content": "tick"},
            _assistant(in_new=3, cc=1000, cr=0, output=50),
            {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
            _assistant(in_new=5, cc=0, cr=1000, output=30),
        ],
    )
    stats = tally_session(f)
    assert stats["session"] == "abcd1234"
    assert stats["turns"] == 2
    assert stats["in_new"] == 8
    assert stats["cache_create"] == 1000
    assert stats["cache_read"] == 1000
    assert stats["output"] == 80


def _block(mid: str, kind: str, in_new: int, output: int, stop: str | None = None) -> dict:
    """One transcript record: a single content block of the API call `mid`."""
    return {
        "type": "assistant",
        "message": {
            "id": mid,
            "stop_reason": stop,
            "content": [{"type": kind}],
            "usage": {
                "input_tokens": in_new,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": output,
            },
        },
    }


def test_one_api_call_split_across_blocks_is_counted_once(tmp_path):
    # The real shape from rahel's transcripts: Claude Code writes one record per
    # content block, each stamped with the call's full input_tokens and only the
    # last carrying output_tokens. Summing per record counted this 30k prompt
    # five times over --- 3.2x too high across the fleet.
    f = _write_session(
        tmp_path / "call1.jsonl",
        [
            _block("chatcmpl-aaa", "thinking", 30_000, 0),
            _block("chatcmpl-aaa", "text", 30_000, 0),
            _block("chatcmpl-aaa", "tool_use", 30_000, 0),
            _block("chatcmpl-aaa", "tool_use", 30_000, 0),
            _block("chatcmpl-aaa", "tool_use", 30_000, 159, stop="tool_use"),
        ],
    )
    stats = tally_session(f)
    assert stats["turns"] == 1, "five blocks are one API call"
    assert stats["blocks"] == 5, "raw record count stays visible"
    assert stats["in_new"] == 30_000, "the prompt is billed once, not five times"
    assert stats["output"] == 159, "max recovers output from the terminal record"


def test_distinct_calls_are_summed(tmp_path):
    f = _write_session(
        tmp_path / "call2.jsonl",
        [
            _block("chatcmpl-aaa", "thinking", 29_579, 0),
            _block("chatcmpl-aaa", "tool_use", 29_579, 159, stop="tool_use"),
            _block("chatcmpl-bbb", "text", 30_206, 0),
            _block("chatcmpl-bbb", "tool_use", 30_206, 236, stop="tool_use"),
        ],
    )
    stats = tally_session(f)
    assert stats["turns"] == 2
    assert stats["blocks"] == 4
    assert stats["in_new"] == 29_579 + 30_206
    assert stats["output"] == 159 + 236


def test_records_without_a_message_id_still_count(tmp_path):
    # Defensive: an id-less record must not be silently dropped (nor collapsed
    # together with other id-less records, which would undercount instead).
    f = _write_session(
        tmp_path / "noid.jsonl",
        [
            {"type": "assistant", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}},
            {"type": "assistant", "message": {"usage": {"input_tokens": 20, "output_tokens": 2}}},
        ],
    )
    stats = tally_session(f)
    assert stats["turns"] == 2
    assert stats["in_new"] == 30
    assert stats["output"] == 3


def test_tally_session_with_no_assistant_lines(tmp_path):
    f = _write_session(
        tmp_path / "empty.jsonl",
        [
            {"type": "queue-operation", "operation": "enqueue"},
            {"type": "user", "message": {"content": "hi"}},
        ],
    )
    stats = tally_session(f)
    assert stats["turns"] == 0
    assert stats["in_new"] == stats["cache_create"] == stats["cache_read"] == 0
    assert stats["output"] == 0


def test_tally_session_skips_malformed_lines(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text(
        "this is not json\n"
        + json.dumps(_assistant(in_new=10, cc=20, cr=30, output=40))
        + "\n{\n"  # truncated json
        + "{not-json-either}\n"
        + json.dumps(_assistant(in_new=1, cc=2, cr=3, output=4))
        + "\n"
    )
    stats = tally_session(path)
    assert stats["turns"] == 2
    assert stats["in_new"] == 11
    assert stats["cache_create"] == 22
    assert stats["cache_read"] == 33
    assert stats["output"] == 44


def test_tally_session_handles_missing_usage_fields(tmp_path):
    f = _write_session(
        tmp_path / "partial.jsonl",
        [
            {"type": "assistant", "message": {}},  # no usage at all
            {"type": "assistant", "message": {"usage": {}}},  # empty usage
            {"type": "assistant", "message": {"usage": {"output_tokens": 7}}},  # only output
            {"type": "assistant", "message": {"usage": {"input_tokens": None}}},  # null value
        ],
    )
    stats = tally_session(f)
    assert stats["turns"] == 4
    assert stats["output"] == 7
    assert stats["in_new"] == 0


def test_tally_dir_returns_sessions_sorted_by_mtime(tmp_path):
    proj = tmp_path / "-home-sprite-slop-salon-lou"
    proj.mkdir()
    a = _write_session(proj / "aaaa1111.jsonl", [_assistant(1, 0, 0, 1)])
    b = _write_session(proj / "bbbb2222.jsonl", [_assistant(2, 0, 0, 2)])
    import os

    os.utime(a, (1_700_000_000, 1_700_000_000))
    os.utime(b, (1_700_000_100, 1_700_000_100))

    rows = tally_dir("lou", root=tmp_path)
    assert [r["session"] for r in rows] == ["aaaa1111", "bbbb2222"]
    assert rows[0]["mtime"] == 1_700_000_000
    assert rows[1]["mtime"] == 1_700_000_100


def test_tally_dir_returns_empty_when_no_project(tmp_path):
    rows = tally_dir("ghost", root=tmp_path)
    assert rows == []


def test_session_cost_pricing_math():
    stats = {
        "in_new": 1_000_000,
        "cache_create": 1_000_000,
        "cache_read": 1_000_000,
        "output": 1_000_000,
    }
    expected = PRICE_INPUT + PRICE_CACHE_CREATE + PRICE_CACHE_READ + PRICE_OUTPUT
    assert session_cost(stats) == expected


def test_session_cost_zero_when_no_usage():
    stats = {"in_new": 0, "cache_create": 0, "cache_read": 0, "output": 0}
    assert session_cost(stats) == 0.0


def test_cli_tally_emits_jsonl(tmp_path, monkeypatch):
    proj = tmp_path / "-home-sprite-slop-salon-lou"
    proj.mkdir()
    _write_session(proj / "abcd1234.jsonl", [_assistant(in_new=3, cc=100, cr=200, output=50)])
    _write_session(proj / "efgh5678.jsonl", [_assistant(in_new=4, cc=110, cr=210, output=60)])

    monkeypatch.setattr("slop_salon.tools.usage.SPRITE_PROJECTS_ROOT", tmp_path)

    result = runner.invoke(app, ["tally", "lou"])
    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in result.output.strip().splitlines()]
    assert len(lines) == 2
    assert {line["session"] for line in lines} == {"abcd1234", "efgh5678"}
    for line in lines:
        assert line["agent"] == "lou"
        assert "cost_usd" in line
        assert line["turns"] == 1


# --- codex runner ---------------------------------------------------------
#
# Record shape verified against a real ~/.codex/sessions rollout file, not
# guessed: `payload.type == "token_count"` carrying `info.total_token_usage`
# (cumulative over the session) and `info.last_token_usage` (that one request).


def _token_count(total: dict, last: dict | None = None, rate: dict | None = None) -> dict:
    payload = {"type": "token_count", "info": {"total_token_usage": total}}
    if last is not None:
        payload["info"]["last_token_usage"] = last
    if rate is not None:
        payload["rate_limits"] = rate
    return {"type": "event_msg", "payload": payload}


def _totals(inp: int, cached: int, out: int, write: int = 0) -> dict:
    return {
        "input_tokens": inp,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": write,
        "output_tokens": out,
        "total_tokens": inp + out,
    }


def test_codex_tally_takes_the_last_total_not_a_sum(tmp_path):
    """The totals are cumulative, so summing counts the session once per request.

    Same class of error as the message.id overcount on the claude path, and just
    as plausible-looking in a table: three requests here, 300 input tokens, not
    600.
    """
    from slop_salon.tools.usage import tally_codex_session

    f = _write_session(
        tmp_path / "rollout-2026-08-01T10-00-00-abc12345.jsonl",
        [
            {"type": "session_meta", "payload": {"type": "session_meta"}},
            _token_count(_totals(100, 0, 10), last=_totals(100, 0, 10)),
            _token_count(_totals(200, 0, 20), last=_totals(100, 0, 10)),
            _token_count(_totals(300, 0, 30), last=_totals(100, 0, 10)),
        ],
    )
    stats = tally_codex_session(f)
    assert stats["in_new"] == 300
    assert stats["output"] == 30
    assert stats["turns"] == 3
    assert stats["runner"] == "codex"


def test_codex_input_tokens_are_inclusive_of_cached(tmp_path):
    """Codex reports total-plus-how-much-was-cached; claude reports disjoint buckets.

    Without the subtraction a cache-heavy session looks like it paid full price
    for the same tokens twice --- the real fleet ratio is ~40M cached of ~42M.
    """
    from slop_salon.tools.usage import tally_codex_session

    f = _write_session(
        tmp_path / "rollout-x-deadbeef.jsonl",
        [_token_count(_totals(1000, 900, 50, write=25), last=_totals(1000, 900, 50))],
    )
    stats = tally_codex_session(f)
    assert stats["in_new"] == 100
    assert stats["cache_read"] == 900
    assert stats["cache_create"] == 25


def test_codex_tally_surfaces_subscription_headroom(tmp_path):
    """The number that actually decides whether one plan can carry six agents."""
    from slop_salon.tools.usage import tally_codex_session

    f = _write_session(
        tmp_path / "rollout-y-cafe1234.jsonl",
        [
            _token_count(
                _totals(10, 0, 1),
                last=_totals(10, 0, 1),
                rate={
                    "primary": {"used_percent": 44.0, "window_minutes": 10080},
                    "plan_type": "team",
                },
            )
        ],
    )
    stats = tally_codex_session(f)
    assert stats["limit_pct"] == 44.0
    assert stats["plan_type"] == "team"


def test_codex_tally_survives_a_session_with_no_usage(tmp_path):
    from slop_salon.tools.usage import tally_codex_session

    f = _write_session(
        tmp_path / "rollout-z-00000000.jsonl", [{"payload": {"type": "session_meta"}}]
    )
    stats = tally_codex_session(f)
    assert stats["turns"] == 0
    assert stats["in_new"] == 0
    assert "limit_pct" not in stats


def test_tally_dir_reads_both_runners(tmp_path):
    """A provider swap must not blank the usage table either side of the change.

    tally_dir detects from disk rather than SLOP_RUNNER: `slop usage` runs via a
    bare `sprite exec`, which never sources ~/.slop-provider.
    """
    import os

    proj = tmp_path / "claude" / "-home-sprite-slop-salon-lou"
    proj.mkdir(parents=True)
    a = _write_session(proj / "aaaa1111.jsonl", [_assistant(5, 0, 0, 5)])

    codex = tmp_path / "codex" / "2026" / "08" / "01"
    codex.mkdir(parents=True)
    b = _write_session(
        codex / "rollout-2026-08-01T10-00-00-bbbb2222.jsonl",
        [_token_count(_totals(7, 0, 7), last=_totals(7, 0, 7))],
    )
    os.utime(a, (1_700_000_000, 1_700_000_000))
    os.utime(b, (1_700_000_100, 1_700_000_100))

    rows = tally_dir("lou", root=tmp_path / "claude", codex_root=tmp_path / "codex")
    assert [r["runner"] for r in rows] == ["claude", "codex"]
    assert [r["in_new"] for r in rows] == [5, 7]
