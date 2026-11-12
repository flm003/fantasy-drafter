"""Pick log and notes, saved as JSON. No Qt imports.

The pick log is the only mutable draft state; everything else (available
list, roster, weights, scores) is derived from it, so undo is just a pop.
"""
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

MINE = "mine"
TAKEN = "taken"
RESULTS = (MINE, TAKEN)


@dataclass(frozen=True)
class Pick:
    player: str
    result: str
    batch: int | None = None  # picks added together (one paste) share a batch and undo together


class DraftState:
    def __init__(self, picks=(), notes=None):
        self.picks: list[Pick] = list(picks)
        self.notes: dict[str, str] = dict(notes or {})

    def __eq__(self, other):
        return isinstance(other, DraftState) and (self.picks, self.notes) == (other.picks, other.notes)

    def picked(self):
        return {p.player for p in self.picks}

    def mine(self):
        return [p.player for p in self.picks if p.result == MINE]

    def taken(self):
        return [p.player for p in self.picks if p.result == TAKEN]

    def add(self, player, result, batch=None):
        if result not in RESULTS:
            raise ValueError(f"result must be one of {RESULTS}, not {result!r}")
        if player in self.picked():
            raise ValueError(f"{player} has already been picked")
        self.picks.append(Pick(player, result, batch))

    def new_batch(self):
        """An id for a group of picks that should undo together."""
        return max((p.batch for p in self.picks if p.batch is not None), default=0) + 1

    def undo(self):
        """Remove the last pick, or the whole last batch. Returns the removed picks, last first."""
        if not self.picks:
            return []
        removed = [self.picks.pop()]
        batch = removed[0].batch
        while batch is not None and self.picks and self.picks[-1].batch == batch:
            removed.append(self.picks.pop())
        return removed

    def clear(self):
        """Start a new draft. Notes are kept, since they are about players, not picks."""
        self.picks.clear()

    def set_note(self, player, text):
        text = text.strip()
        if text:
            self.notes[player] = text
        else:
            self.notes.pop(player, None)

    # ------------------------------------------------------------ JSON ----
    def to_dict(self):
        return {"version": 1, "picks": [asdict(p) for p in self.picks], "notes": self.notes}

    @classmethod
    def from_dict(cls, data, known_players=None):
        """Build a state from saved data. Returns (state, problems)."""
        problems, state = [], cls()
        for entry in data.get("picks", []):
            player, result = entry.get("player"), entry.get("result")
            if known_players is not None and player not in known_players:
                problems.append(f"Saved pick {player!r} is not in the player list; dropped.")
                continue
            try:
                state.add(player, result, entry.get("batch"))
            except ValueError as e:
                problems.append(f"Saved pick dropped: {e}.")
        for player, text in data.get("notes", {}).items():
            if isinstance(text, str):
                state.set_note(player, text)
        return state, problems

    def save(self, path):
        """Write atomically, so a crash mid-write never leaves a half-written file."""
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path, known_players=None):
        """Load saved state, or start empty if there is none. Returns (state, problems).

        An unreadable file is moved aside rather than overwritten by the next save.
        """
        path = Path(path)
        if not path.exists():
            return cls(), []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("top level is not an object")
            return cls.from_dict(data, known_players)
        except (ValueError, AttributeError, TypeError) as e:
            backup = path.with_name(f"{path.stem}.corrupt-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
            os.replace(path, backup)
            return cls(), [f"Could not read {path.name} ({e}); moved it to {backup.name} "
                           f"and started a new draft."]
