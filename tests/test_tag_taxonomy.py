"""Unit tests for card_state._check_tags and card_state._detect_urgency.

Behavior was captured by actually running the functions in scripts/card_state.py;
expected values below are the REAL outputs, not assumptions.
"""
import pytest

import card_state


def _board(main=None, sub=None):
    """Build a minimal board dict carrying a tagTaxonomy."""
    return {
        "tagTaxonomy": {
            "main": [{"name": n} for n in (main or [])],
            "sub": [{"name": n} for n in (sub or [])],
        }
    }


# ---------------------------------------------------------------------------
# _check_tags
# ---------------------------------------------------------------------------

def test_check_tags_canonical_kept():
    d = _board(main=["bug"], sub=["frontend", "backend"])
    assert card_state._check_tags(["bug", "frontend"], d, False) == ["bug", "frontend"]


def test_check_tags_unknown_dropped_without_force():
    d = _board(main=["bug"], sub=["frontend"])
    # 'wibble' is unknown -> silently dropped (warning to stderr), 'bug' kept.
    assert card_state._check_tags(["bug", "wibble"], d, False) == ["bug"]


def test_check_tags_unknown_kept_with_force():
    d = _board(main=["bug"], sub=["frontend"])
    assert card_state._check_tags(["bug", "wibble"], d, True) == ["bug", "wibble"]


def test_check_tags_is_case_sensitive():
    # Real behavior: matching is exact/case-sensitive, so 'Bug'/'BUG' are unknown
    # and get dropped without force.
    d = _board(main=["bug"])
    assert card_state._check_tags(["Bug", "BUG"], d, False) == []


def test_check_tags_does_not_dedup_and_preserves_order():
    # Captured behavior: NO dedup. Duplicate canonical tags pass through twice,
    # and original ordering is preserved.
    d = _board(main=["bug"], sub=["frontend", "backend"])
    assert card_state._check_tags(["frontend", "bug", "bug", "backend"], d, False) == [
        "frontend",
        "bug",
        "bug",
        "backend",
    ]


def test_check_tags_structural_tags_always_pass():
    # 'phase'/'discovered' bypass taxonomy validation even when not listed.
    d = _board(main=["bug"])
    assert card_state._check_tags(["phase", "discovered", "bug"], d, False) == [
        "phase",
        "discovered",
        "bug",
    ]


def test_check_tags_empty_and_none_input():
    d = _board(main=["bug"])
    assert card_state._check_tags([], d, False) == []
    assert card_state._check_tags(None, d, False) == []


def test_check_tags_empty_taxonomy_is_passthrough():
    # No taxonomy at all -> back-compat pass-through (everything accepted).
    assert card_state._check_tags(["anything", "x"], {}, False) == ["anything", "x"]
    empty_tt = {"tagTaxonomy": {"main": [], "sub": []}}
    assert card_state._check_tags(["x"], empty_tt, False) == ["x"]


# ---------------------------------------------------------------------------
# _detect_urgency
# ---------------------------------------------------------------------------

def test_detect_urgency_strong_marker_fires_unconditionally():
    assert card_state._detect_urgency("Please fix ASAP") == "asap"
    assert card_state._detect_urgency("p0 incident") == "p0"
    assert card_state._detect_urgency("this is a blocker") == "blocker"


def test_detect_urgency_weak_marker_needs_framing():
    # Bare weak marker with no framing -> None.
    assert card_state._detect_urgency("the link is broken somewhere") is None
    # Framed weak markers fire: explicit "this is", ALL-CAPS, or nearby '!'.
    assert card_state._detect_urgency("this is urgent") == "urgent"
    assert card_state._detect_urgency("URGENT please look") == "urgent"
    assert card_state._detect_urgency("its broken!") == "broken"


def test_detect_urgency_none_and_empty_default():
    assert card_state._detect_urgency("just a normal task") is None
    assert card_state._detect_urgency("") is None
    assert card_state._detect_urgency() is None
    # Strong marker in a later source still fires across multiple texts.
    assert card_state._detect_urgency("normal", "emergency here") == "emergency"
