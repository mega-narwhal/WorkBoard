"""Tests for hourly_reconcile._autoship_block_reason — the guard that stops the
background reconcile from auto-shipping a card to `done` on weak evidence.

Regression: the sweep once moved an OPEN bug ("Fix /archive…") straight to done
because recent activity merely mentioned "archive" (a noun-cluster match). Open
bugs and cards with unchecked subtasks must NOT be auto-shipped — they need an
explicit fix by the in-session agent. These pin that contract on the pure helper.
"""
from __future__ import annotations

import hourly_reconcile as hr


def test_open_bug_is_blocked():
    assert hr._autoship_block_reason({"tags": ["bug", "security"]}) is not None


def test_bug_tag_is_case_insensitive():
    assert hr._autoship_block_reason({"tags": ["BUG"]}) is not None


def test_unchecked_subtask_blocks():
    card = {"tags": ["feature"], "subtasks": [{"text": "do x", "done": False}]}
    assert hr._autoship_block_reason(card) is not None


def test_bug_blocks_even_when_subtasks_done():
    # An open bug stays blocked regardless of subtask state — the tag is the signal.
    card = {"tags": ["bug"], "subtasks": [{"done": True}]}
    reason = hr._autoship_block_reason(card)
    assert reason is not None and "bug" in reason.lower()


def test_clean_task_is_allowed():
    # No bug tag, all subtasks done → the sweep may auto-ship it.
    card = {"tags": ["feature", "infra"], "subtasks": [{"done": True}, {"done": True}]}
    assert hr._autoship_block_reason(card) is None


def test_bare_card_is_allowed():
    # No tags, no subtasks → nothing blocks auto-ship.
    assert hr._autoship_block_reason({}) is None


def test_missing_subtask_done_key_treated_as_open():
    # A subtask with no `done` key is unfinished (defensive) → blocked.
    assert hr._autoship_block_reason({"subtasks": [{"text": "x"}]}) is not None
