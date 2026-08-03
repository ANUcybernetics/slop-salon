"""Tests for `slop-prompt`, which renders CLAUDE.md for the codex runner."""

from __future__ import annotations

from typer.testing import CliRunner

from slop_salon.tools.prompt import MAX_DEPTH, app, expand_imports

runner = CliRunner()


def _reader(files: dict[str, str]):
    return lambda path: files.get(path)


def test_imports_are_inlined():
    out = expand_imports("before\n@SOUL.md\nafter", _reader({"SOUL.md": "constitution"}))
    assert out == "before\nconstitution\nafter"


def test_imports_nest():
    files = {"CLAUDE.md": "top\n@a.md", "a.md": "middle\n@b.md", "b.md": "bottom"}
    assert expand_imports(files["CLAUDE.md"], _reader(files)) == "top\nmiddle\nbottom"


def test_missing_import_is_dropped_silently():
    """Matching Claude Code, which skips a missing @ import without complaint.

    The runners must see the same prompt shape, or a codex tick would differ
    from a claude tick for a reason nobody could see in the file.
    """
    assert expand_imports("a\n@gone.md\nb", _reader({})) == "a\nb"


def test_only_whole_line_imports_are_expanded():
    """Prose in these files mentions handles and decorators.

    Inlining a whole constitution into the middle of a sentence is a worse
    failure than not inlining it at all.
    """
    files = {"SOUL.md": "SOUL"}
    text = "email me @SOUL.md now\n@SOUL.md"
    assert expand_imports(text, _reader(files)) == "email me @SOUL.md now\nSOUL"


def test_cycles_terminate_and_stay_visible():
    files = {"a.md": "A\n@b.md", "b.md": "B\n@a.md"}
    # Seeded with the root's own path, as `agents-md` does --- otherwise a file
    # that imports its own importer takes an extra lap before the guard bites.
    out = expand_imports(files["a.md"], _reader(files), frozenset({"a.md"}))
    assert out == "A\nB\n@a.md"  # the unexpanded line marks where it stopped


def test_depth_is_bounded():
    files = {f"{i}.md": f"L{i}\n@{i + 1}.md" for i in range(MAX_DEPTH + 3)}
    out = expand_imports(files["0.md"], _reader(files))
    assert out.count("\n") <= MAX_DEPTH + 1


def test_agents_md_is_written_with_a_do_not_edit_header(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# gert\n\n@SOUL.md\n\n@MEMORY.md\n")
    (tmp_path / "SOUL.md").write_text("constitution")
    (tmp_path / "MEMORY.md").write_text("what gert knows")

    result = runner.invoke(app, ["agents-md", "--root", str(tmp_path)])
    assert result.exit_code == 0

    out = (tmp_path / "AGENTS.md").read_text()
    assert "constitution" in out
    assert "what gert knows" in out
    assert "@SOUL.md" not in out
    # It is a build artifact of CLAUDE.md, and an agent editing it would lose the
    # edit on the next tick without ever being told.
    assert "Do not edit" in out
    assert "CLAUDE.md" in out.splitlines()[0]


def test_missing_claude_md_is_not_an_error(tmp_path):
    """slop-tick runs this ahead of every codex tick; it must never block one."""
    result = runner.invoke(app, ["agents-md", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert not (tmp_path / "AGENTS.md").exists()
