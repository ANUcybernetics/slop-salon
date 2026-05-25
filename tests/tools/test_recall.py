"""Tests for `slop-recall`, the ambient-memory recall helper."""

from __future__ import annotations

from pathlib import Path

from slop_salon.tools.recall import TOP_K, rank


def _write_notes(notes_dir: Path, files: dict[str, str]) -> None:
    notes_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (notes_dir / name).write_text(content)


def test_rank_returns_matching_lines(tmp_path: Path) -> None:
    _write_notes(
        tmp_path,
        {
            "2026-05-01.md": "Tried sepia masks today, looked muddy.\nWill revisit ochre next.",
            "2026-05-02.md": "Drafted a thread about Vita's roses.",
        },
    )
    hits = rank("sepia masks for next thread", tmp_path)
    snippets = [s for s, _ in hits]
    assert any("sepia masks" in s for s in snippets)


def test_rank_orders_by_overlap(tmp_path: Path) -> None:
    _write_notes(
        tmp_path,
        {
            "high.md": "ochre indigo crimson saffron strong match",
            "low.md": "ochre only",
        },
    )
    hits = rank("ochre indigo crimson saffron", tmp_path)
    assert hits[0][1].name == "high.md"


def test_rank_dedupes_identical_snippets(tmp_path: Path) -> None:
    _write_notes(
        tmp_path,
        {
            "a.md": "ochre indigo crimson saffron lapis",
            "b.md": "ochre indigo crimson saffron lapis",
        },
    )
    hits = rank("ochre indigo crimson saffron lapis", tmp_path)
    assert len(hits) == 1


def test_rank_respects_top_k(tmp_path: Path) -> None:
    _write_notes(
        tmp_path,
        {f"{i}.md": f"ochre indigo crimson saffron line{i}" for i in range(10)},
    )
    hits = rank("ochre indigo crimson saffron", tmp_path, top_k=TOP_K)
    assert len(hits) == TOP_K


def test_rank_empty_query_returns_nothing(tmp_path: Path) -> None:
    _write_notes(tmp_path, {"a.md": "ochre indigo"})
    assert rank("", tmp_path) == []
    assert rank("a b c", tmp_path) == []  # all tokens below MIN_TOKEN_LEN


def test_rank_skips_lines_with_no_overlap(tmp_path: Path) -> None:
    _write_notes(tmp_path, {"a.md": "completely unrelated marginalia"})
    assert rank("ochre indigo crimson", tmp_path) == []


def test_rank_truncates_long_snippets(tmp_path: Path) -> None:
    long_line = "ochre indigo " + " ".join(f"word{i}" for i in range(50))
    _write_notes(tmp_path, {"a.md": long_line})
    hits = rank("ochre indigo", tmp_path)
    assert hits, "expected a hit"
    snippet, _ = hits[0]
    assert len(snippet.split()) <= 12
