"""Unit tests for need_detect.py — the multi-need text heuristics.

Pins the REAL (regex-driven, brittle) behavior of:
  • looks_multi_need(text) -> bool
  • count_needs(text) -> int

Bare import: conftest.py puts WorkBoard/scripts on sys.path.
"""
import need_detect as nd


# --- looks_multi_need -------------------------------------------------------

def test_multi_need_single_simple_request_is_false():
    # A plain single ask with no list signals must NOT fire (avoid nagging).
    assert nd.looks_multi_need("Please fix the login bug") is False


def test_multi_need_numbered_list_fires():
    # >=2 numbered items is a strong signal -> True.
    assert nd.looks_multi_need("1. fix login 2. add logout 3. write tests") is True


def test_multi_need_semicolon_join_fires():
    # A "; <something>" list joiner fires.
    assert nd.looks_multi_need("fix the parser; update the docs") is True


def test_multi_need_comma_and_join_fires():
    # The ", and <word>" joiner fires (strong list signal).
    assert nd.looks_multi_need("Refactor the auth module, and write integration tests") is True


def test_multi_need_single_also_addon_does_not_fire():
    # CONSERVATIVE: a single "also" add-on ask (and no other signal) does NOT
    # fire — needs >=2 add-on asks. "and also ... add pagination" has exactly
    # one _ALSO_RE match and no ;/,-and joiner.
    assert nd.looks_multi_need("Add a search box and also add pagination") is False


def test_multi_need_two_addon_asks_fire():
    # Two prose add-on asks ("also" + "additionally") cross the >=2 threshold.
    assert nd.looks_multi_need("do this and also do that and additionally do other") is True


def test_multi_need_empty_and_whitespace_are_false():
    assert nd.looks_multi_need("") is False
    assert nd.looks_multi_need("   ") is False
    assert nd.looks_multi_need(None) is False  # None is tolerated -> "" -> False


# --- count_needs ------------------------------------------------------------

def test_count_needs_single_request_is_one():
    assert nd.count_needs("Please fix the login bug") == 1


def test_count_needs_numbered_list_counts_distinct_numbers():
    # Numbered path: count of distinct item numbers (1,2,3) -> 3.
    assert nd.count_needs("1. fix login 2. add logout 3. write tests") == 3


def test_count_needs_numbered_dedupes_repeated_numbers():
    # The numbered path uses a SET of item numbers, so a repeated number is not
    # double-counted: distinct {1, 2} -> 2 (NOT 3). Pins the dedup, making the
    # "distinct numbers" claim non-tautological.
    assert nd.count_needs("1. fix login 2. add logout 1. fix login again") == 2


def test_count_needs_semicolon_compound_segments():
    # Split on ";" then keep segments with >=2 words -> 2.
    assert nd.count_needs("fix the parser; update the docs") == 2


def test_count_needs_empty_and_whitespace_floor_to_one():
    # Returns >=1 always.
    assert nd.count_needs("") == 1
    assert nd.count_needs("   ") == 1


def test_count_needs_short_word_segments_filtered_out():
    # "do A, do B, do C": the ", and" joiner is absent, ", " alone is NOT a
    # split boundary, so the whole string is one segment -> 1. This is the
    # documented >=2-word / segment-based conservativeness, NOT a per-comma count.
    assert nd.count_needs("do A, do B, do C") == 1


# --- divergence between the two functions (the interesting contract edge) ---

def test_addon_count_can_exceed_multi_need_threshold():
    # The two functions use DIFFERENT logic: bare "also ... plus ..." (no
    # leading and/./;/\n boundary before each) does NOT satisfy _ALSO_RE's >=2,
    # so looks_multi_need is False, yet count_needs SPLITS on bare also/plus and
    # returns 3. Pin this asymmetry — it is exactly the brittle bit to catch.
    text = "Build the API also write docs plus add tests"
    assert nd.looks_multi_need(text) is False
    assert nd.count_needs(text) == 3
