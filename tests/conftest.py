"""Shared pytest setup for the WorkBoard unit suite.

Puts scripts/ on sys.path so test files import the target modules by bare name
(import serve / import card_state / ...), portably — relative to this file, so
it works the same on a contributor's machine and in CI (no hardcoded paths).

Cardinal rule (inherited from skills/e2e/e2e_workboard.py): these are HERMETIC
unit tests — they never touch the live board, the server on 127.0.0.1:7891, the
real port registry, the network, or an LLM. State is isolated per-test via
tmp_path / monkeypatch. A test that needs any of those does not belong here.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
