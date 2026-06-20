"""Unit tests for hourly_common digest primitives (LLM-input builders).

Targets:
  build_digest(bucket_events, project, seen_heads=None) -> str
  parse_card_array(raw) -> list | None

Pure string/list building — NO LLM call, NO network, NO real FS outside tmp.
Imported by bare name; conftest.py puts scripts/ on sys.path.

Hermeticity note: build_digest's output depends on TWO process-global toggles
read from env:
  * hourly_common._DROP_ASST_PROSE  (env DIGEST_DROP_ASST, read at IMPORT time)
  * digest_compact.compact_enabled() (env DIGEST_COMPACT, read at CALL time)
A runner that happens to export either would otherwise change the golden
strings. The autouse `_pin_default_toggles` fixture forces BOTH to their
documented default (drop-prose ON, compact ON) so every test below is
deterministic regardless of the ambient environment. The one test that
exercises the non-default branch flips the relevant toggle explicitly.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import hourly_common as hc


# ---------- determinism: pin the env-driven toggles to their defaults ------

@pytest.fixture(autouse=True)
def _pin_default_toggles(monkeypatch):
    # _DROP_ASST_PROSE is a module constant resolved from DIGEST_DROP_ASST at
    # import time, so patch the resolved attribute (re-importing won't help).
    monkeypatch.setattr(hc, "_DROP_ASST_PROSE", True, raising=True)
    # compact_enabled() re-reads DIGEST_COMPACT on every call -> clearing the
    # env restores the documented default-on behaviour.
    monkeypatch.delenv("DIGEST_COMPACT", raising=False)


# ---------- small fixture builders ---------------------------------------

def _ev(kind: str, hh: int = 12, mm: int = 0, ss: int = 0, **kw) -> dict:
    """A minimal plain-dict event: a real datetime `ts` + kind + extras."""
    return {"kind": kind, "ts": datetime(2026, 6, 20, hh, mm, ss), **kw}


# ---------- build_digest: user-prompt truncation -------------------------

def test_build_digest_user_prompt_truncated_to_400(tmp_path: Path):
    """The documented user-prompt truncation: the USER text is capped at 400
    chars (the [:400] slice in build_digest)."""
    payload = "x" * 500
    out = hc.build_digest([_ev("user_prompt", text=payload)], tmp_path)
    assert "USER:" in out
    # The rendered user text is exactly 400 x's, not the full 500.
    rendered = out.split("USER:", 1)[1].strip()
    assert rendered == "x" * 400
    assert "x" * 401 not in out


def test_build_digest_user_prompt_newlines_flattened_with_timestamp(tmp_path: Path):
    """USER text has newlines replaced with spaces (single-line digest row),
    and the row carries the documented `  [HH:MM:SS] ` timestamp prefix."""
    out = hc.build_digest([_ev("user_prompt", hh=9, mm=5, ss=1,
                                text="line1\nline2")], tmp_path)
    # one event -> exactly one line (no embedded newline)
    assert out.count("\n") == 0
    # full contract: timestamp prefix + USER tag + flattened text
    assert out == "  [09:05:01] USER: line1 line2"


# ---------- build_digest: assistant prose dropped by default --------------

def test_build_digest_drops_assistant_prose_keeps_files(tmp_path: Path):
    """#321 DROP-ASST-PROSE (default on): the assistant's prose head is dropped,
    but the 'CLAUDE edited: <files>' files-touched signal is kept (basenames
    only)."""
    ev = _ev(
        "asst_msg",
        text="Here is a long narration about what I did that should be dropped",
        files=["/repo/scripts/foo.py", "/repo/scripts/bar.py"],
    )
    out = hc.build_digest([ev], tmp_path)
    assert "CLAUDE edited: foo.py, bar.py" in out
    # the prose head must NOT appear
    assert "narration" not in out
    assert "CLAUDE:" not in out


def test_build_digest_files_touched_capped_at_five_basenames(tmp_path: Path):
    """The files-touched signal keeps only the first 5 files (files[:5]) and
    renders BASENAMES, not full paths."""
    files = [f"/repo/scripts/f{i}.py" for i in range(7)]
    out = hc.build_digest([_ev("asst_msg", hh=9, mm=5, ss=1, text="", files=files)],
                          tmp_path)
    assert out == "  [09:05:01] CLAUDE edited: f0.py, f1.py, f2.py, f3.py, f4.py"
    # the 6th/7th files are dropped, and no directory component leaks through
    assert "f5.py" not in out
    assert "/repo" not in out


def test_build_digest_asst_prose_only_no_files_yields_nothing(tmp_path: Path):
    """An assistant turn that is pure prose (no files) contributes no line at
    all by default — prose is dropped and there's no files signal to keep."""
    ev = _ev("asst_msg", text="All wrapped up, everything looks good!")
    out = hc.build_digest([ev], tmp_path)
    assert out == ""


def test_build_digest_legacy_keeps_prose_head_when_toggle_off(tmp_path: Path,
                                                              monkeypatch):
    """Legacy path (DIGEST_DROP_ASST=0): with drop-prose OFF, a pure-prose
    assistant turn renders a 'CLAUDE: <head>' line truncated at the first
    newline. Exercises the `if not _DROP_ASST_PROSE` branch."""
    monkeypatch.setattr(hc, "_DROP_ASST_PROSE", False, raising=True)
    ev = _ev("asst_msg", hh=9, mm=5, ss=1,
             text="first line head\nsecond line dropped")
    out = hc.build_digest([ev], tmp_path)
    assert out == "  [09:05:01] CLAUDE: first line head"


# ---------- build_digest: other protected line types ----------------------

def test_build_digest_commit_line_includes_short_sha(tmp_path: Path):
    """git_commit events render a COMMIT line with the meta shaShort and the
    message (truncated to 120 chars)."""
    ev = _ev("git_commit", text="fix the freeze", meta={"shaShort": "abc1234"})
    out = hc.build_digest([ev], tmp_path)
    assert "COMMIT abc1234: fix the freeze" in out


# ---------- parse_card_array ----------------------------------------------

def test_parse_card_array_clean_array():
    """Fast path: an already-clean JSON array parses straight through."""
    assert hc.parse_card_array('[{"title": "a"}, {"title": "b"}]') == [
        {"title": "a"},
        {"title": "b"},
    ]


def test_parse_card_array_empty_array_is_empty_list_not_none():
    """A clean empty array returns [] (a falsey-but-not-None list) — the
    documented 'possibly empty []' contract, distinct from the None signal."""
    res = hc.parse_card_array("[]")
    assert res == []
    assert res is not None


def test_parse_card_array_fenced_with_prose_salvages_cards():
    """The model wraps the array in a ```json fence plus conversational prose;
    parse_card_array still recovers the cards via the bracket-walk salvage."""
    raw = 'Here are the cards:\n```json\n[{"title": "x"}]\n```'
    assert hc.parse_card_array(raw) == [{"title": "x"}]


def test_parse_card_array_truncated_tail_salvages_complete_objects():
    """A cut-off final object is tolerated: complete top-level {...} objects are
    salvaged, the incomplete trailing one is dropped."""
    assert hc.parse_card_array('[{"a": 1}, {"b": 2') == [{"a": 1}]


def test_parse_card_array_none_object_scalar_and_garbage_return_none():
    """Everything that is not a recoverable ARRAY collapses to None:
    None / empty / unrecoverable garbage / a bare JSON object / a bare JSON
    scalar. (Scalar and object are distinct non-list fast-path branches.)"""
    assert hc.parse_card_array(None) is None
    assert hc.parse_card_array("") is None
    assert hc.parse_card_array("totally not json at all") is None
    # a JSON OBJECT (not an array) is not a card list -> None
    assert hc.parse_card_array('{"a": 1}') is None
    # a JSON SCALAR (valid JSON, but not a list) -> None
    assert hc.parse_card_array("42") is None
    assert hc.parse_card_array('"hello"') is None
