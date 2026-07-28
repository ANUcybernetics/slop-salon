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
