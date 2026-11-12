import json

import pandas as pd
import pytest

from draft_tracker import config, scoring
from draft_tracker.state import MINE, TAKEN, DraftState, Pick


@pytest.fixture
def pool():
    rows = [{"name": f"P{i}", "GP": "70", **{c: str(i * 10 + j) for j, c in enumerate(config.CATEGORIES)}}
            for i in range(10)]
    return scoring.build_pool(pd.DataFrame(rows))


def available(pool, state):
    ev = scoring.evaluate(pool, [pool.index[n] for n in state.mine()],
                          [pool.index[n] for n in state.taken()])
    return ev.available


def test_undo_restores_previous_list(pool):
    state = DraftState()
    state.add("P9", MINE)
    before = available(pool, state)
    state.add("P8", TAKEN)
    assert available(pool, state) != before
    assert state.undo() == [Pick("P8", TAKEN)]
    assert available(pool, state) == before


def test_undo_on_empty_log():
    assert DraftState().undo() == []


def test_undo_removes_a_whole_batch(tmp_path):
    state = DraftState()
    state.add("P1", MINE)
    batch = state.new_batch()
    for name in ("P2", "P3", "P4"):
        state.add(name, TAKEN, batch)
    state.add("P5", TAKEN, state.new_batch())
    assert [p.player for p in state.undo()] == ["P5"]
    path = tmp_path / "s.json"
    state.save(path)
    state = DraftState.load(path)[0]
    assert [p.player for p in state.undo()] == ["P4", "P3", "P2"]
    assert state.picks == [Pick("P1", MINE)]


def test_add_rejects_repeats_and_bad_results():
    state = DraftState()
    state.add("P1", MINE)
    with pytest.raises(ValueError):
        state.add("P1", TAKEN)
    with pytest.raises(ValueError):
        state.add("P2", "maybe")


def test_mine_and_taken_keep_pick_order():
    state = DraftState()
    for name, result in [("A", TAKEN), ("B", MINE), ("C", TAKEN), ("D", MINE)]:
        state.add(name, result)
    assert state.mine() == ["B", "D"]
    assert state.taken() == ["A", "C"]


def test_save_and_reload_is_identical(tmp_path):
    path = tmp_path / "draft_state.json"
    state = DraftState()
    state.add("Nikola Jokić", MINE)
    state.add("P2", TAKEN)
    state.set_note("P3", "  back injury  ")
    state.save(path)
    loaded, problems = DraftState.load(path)
    assert problems == []
    assert loaded == state
    assert loaded.notes == {"P3": "back injury"}


def test_clear_keeps_notes():
    state = DraftState()
    state.add("P1", MINE)
    state.set_note("P1", "note")
    state.clear()
    assert state.picks == [] and state.notes == {"P1": "note"}


def test_load_missing_file_starts_empty(tmp_path):
    assert DraftState.load(tmp_path / "nope.json") == (DraftState(), [])


def test_load_drops_unknown_players(tmp_path):
    path = tmp_path / "draft_state.json"
    path.write_text(json.dumps({"picks": [{"player": "P1", "result": "mine"},
                                          {"player": "Ghost", "result": "taken"}]}))
    state, problems = DraftState.load(path, known_players={"P1"})
    assert state.picks == [Pick("P1", MINE)]
    assert "Ghost" in problems[0]


def test_corrupt_file_is_moved_aside(tmp_path):
    path = tmp_path / "draft_state.json"
    path.write_text("{not json")
    state, problems = DraftState.load(path)
    assert state == DraftState()
    assert not path.exists()
    assert len(list(tmp_path.glob("draft_state.corrupt-*.json"))) == 1
    assert "moved it" in problems[0]
