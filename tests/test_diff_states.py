"""Unit tests for serve.diff_states — the pure SSE-event diffing function.

diff_states(old, new) -> list[(event_name, data)] tuples. We exercise the
documented transitions (first load, no-op, add, remove, move, field edit) and
the column-level events, asserting the REAL event names/shapes observed by
running the function.
"""
import serve


def card(cid, column="c1", title="A", **extra):
    c = {"id": cid, "column": column, "title": title}
    c.update(extra)
    return c


def col(cid, name=None):
    return {"id": cid, "name": name if name is not None else cid}


def board(cards=None, columns=None):
    return {"cards": list(cards or []), "columns": list(columns or [])}


COLS = [col("c1", "Todo"), col("c2", "Done")]


def test_diff_states_first_load_emits_columns_then_cards():
    new = board([card("x")], COLS)
    events = serve.diff_states(None, new)

    names = [n for n, _ in events]
    assert names == ["column-added", "column-added", "card-added"]

    assert events[0][1] == {"column": col("c1", "Todo"), "index": 0}
    assert events[1][1] == {"column": col("c2", "Done"), "index": 1}
    assert events[2][1] == {"card": card("x")}


def test_diff_states_noop_returns_empty():
    s = board([card("x")], COLS)
    assert serve.diff_states(s, s) == []
    assert serve.diff_states(board([card("x")], COLS), board([card("x")], COLS)) == []


def test_diff_states_card_added():
    old = board([card("x")], COLS)
    new = board([card("x"), card("y", title="B")], COLS)
    events = serve.diff_states(old, new)
    assert events == [("card-added", {"card": card("y", title="B")})]


def test_diff_states_card_removed():
    old = board([card("x"), card("y", title="B")], COLS)
    new = board([card("x")], COLS)
    events = serve.diff_states(old, new)
    assert events == [("card-removed", {"id": "y"})]


def test_diff_states_card_moved_between_columns_is_card_updated():
    old = board([card("x", column="c1")], COLS)
    new = board([card("x", column="c2")], COLS)
    events = serve.diff_states(old, new)
    assert len(events) == 1
    name, data = events[0]
    assert name == "card-updated"
    assert data["fromColumn"] == "c1"
    assert data["toColumn"] == "c2"
    assert data["card"] == card("x", column="c2")


def test_diff_states_card_field_edit_emits_card_updated():
    old = board([card("x", title="A")], COLS)
    new = board([card("x", title="A2")], COLS)
    events = serve.diff_states(old, new)
    assert len(events) == 1
    name, data = events[0]
    assert name == "card-updated"
    assert data["card"]["title"] == "A2"
    assert data["fromColumn"] == "c1"
    assert data["toColumn"] == "c1"


def test_diff_states_untracked_field_change_is_ignored():
    old = board([card("x", description="old")], COLS)
    new = board([card("x", description="totally different")], COLS)
    assert serve.diff_states(old, new) == []


def test_diff_states_column_renamed_and_removed():
    old = board([], [col("c1", "Todo"), col("c2", "Done")])
    new = board([], [col("c1", "In Progress")])
    events = serve.diff_states(old, new)
    assert ("column-renamed", {"id": "c1", "name": "In Progress"}) in events
    assert ("column-removed", {"id": "c2"}) in events
    assert len(events) == 2


def test_diff_states_tags_reorder_is_order_sensitive():
    # Tags are compared via json.dumps(..., sort_keys=True). sort_keys only sorts
    # DICT keys, NOT list elements, so ["a","b"] vs ["b","a"] serialize differently
    # and DO emit a card-updated event. (Order-INsensitivity would require sorting
    # the list itself, which the code does not do.) Pin the real, order-sensitive
    # behavior so a future "fix" either way is a conscious, test-visible choice.
    old = board([card("x", tags=["a", "b"])], COLS)
    new = board([card("x", tags=["b", "a"])], COLS)
    events = serve.diff_states(old, new)
    assert len(events) == 1
    assert events[0][0] == "card-updated"
    assert events[0][1]["card"]["tags"] == ["b", "a"]


def test_diff_states_tags_changed_emits_card_updated():
    # A genuine tag change (different set) DOES surface as card-updated.
    old = board([card("x", tags=["a"])], COLS)
    new = board([card("x", tags=["a", "b"])], COLS)
    events = serve.diff_states(old, new)
    assert len(events) == 1
    assert events[0][0] == "card-updated"
    assert events[0][1]["card"]["tags"] == ["a", "b"]


def test_diff_states_column_reorder_is_noop():
    # diff_states tracks column add/rename/remove but NOT ordering: swapping the
    # order of the same column ids emits nothing.
    cols = [col("c1", "Todo"), col("c2", "Done")]
    rev = [col("c2", "Done"), col("c1", "Todo")]
    assert serve.diff_states(board([], cols), board([], rev)) == []
