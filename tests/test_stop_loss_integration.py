"""
Isolated integration tests for position state lifecycle:
new_position -> enter_locked -> switch_1h -> stop_updated -> hold (no change).
"""

import time
from position_state import update_position_state, load_position_state, clear_position_state


def test_long_position_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("POSITION_STATE_FILE", str(tmp_path / "pos_state.json"))
    entry = 2010.0

    # 1. New position
    changed, action = update_position_state("long", "SURVIVAL", 2000.0, entry, time.time())
    assert changed is True
    assert action == "new_position"

    # 2. SURVIVAL -> LOCKED
    changed, action = update_position_state("long", "LOCKED", 2015.0, entry, time.time())
    assert changed is True
    assert action == "enter_locked"

    # 3. LOCKED -> HOURLY
    changed, action = update_position_state("long", "HOURLY", 2050.0, entry, time.time())
    assert changed is True
    assert action == "switch_1h"

    # 4. Stop updated within HOURLY
    changed, action = update_position_state("long", "HOURLY", 2080.0, entry, time.time())
    assert changed is True
    assert action == "stop_updated"

    # 5. Unchanged hold
    changed, action = update_position_state("long", "HOURLY", 2080.0, entry, time.time())
    assert changed is False
    assert action == ""


def test_short_and_parallel_position_tracking(tmp_path, monkeypatch):
    monkeypatch.setenv("POSITION_STATE_FILE", str(tmp_path / "pos_state_parallel.json"))

    changed, action = update_position_state("short", "SURVIVAL", 2100.0, 2050.0, time.time())
    assert changed is True
    assert action == "new_position"

    changed, action = update_position_state("short", "LOCKED", 2030.0, 2050.0, time.time())
    assert changed is True
    assert action == "enter_locked"

    update_position_state("long", "SURVIVAL", 2000.0, 2010.0, time.time())
    state = load_position_state()
    assert "long" in state and "short" in state
    assert state["long"]["phase"] == "SURVIVAL"
    assert state["short"]["phase"] == "LOCKED"

    clear_position_state("long")
    state_after = load_position_state()
    assert "long" not in state_after and "short" in state_after
