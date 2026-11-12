# Fantasy Drafter

A desktop draft assistant for a Yahoo head-to-head **categories** basketball league
(3PTM, PTS, REB, AST, ST, BLK, TO; TO is lower-is-better; 12 teams, 13 roster spots,
snake draft). It lists every undrafted player ranked by how much he helps *your* team
given who has been picked, and re-ranks after every pick. Built with Python, PySide6,
numpy and pandas.

## Coming back for next year's draft

1. **Save the player pages.** In Yahoo's player list, pick the *Remaining Games (proj)*
   stat view and save each page of 25 as `.htm`
   (10 pages = 250 players; later pages arrive as JSON-wrapped HTML and are handled).
2. **Convert them:** `uv run yahoo_to_csv.py players*.htm -o players.csv`
3. **Check `draft_tracker/config.py`:** `EXPECTED_PLAYERS`, `TEAMS`, `ROSTER_SIZE` and
   `CATEGORIES`. If the league settings changed, change them here.
4. **Set your team name** in `draft_tracker/config_local.py` (untracked, so it stays out
   of git). Create it if missing:
   ```python
   MY_TEAM_NAMES = ["You", "Your Team Name"]
   ```
   "You" is what mock drafts call you; the live draft uses your team name.
5. **Run it:** `uv run python -m draft_tracker`
6. Click **New draft…** to clear last year's saved picks (`draft_state.json`), and do a
   mock draft first to make sure paste still works (Yahoo's draft-room markup changes).
7. Tests: `uv run pytest`

`players.csv`, `draft_state.json`, `paste_log.txt`, `*.htm` and `config_local.py` are
git-ignored on purpose (personal data, league mates' names).

## Using it during the draft

- Type a name to search. **Enter** marks the top match *taken*, **Shift+Enter** marks it
  *mine*. Double-click a row = mine, right-click = taken. **Ctrl+Z** undoes.
- **Paste box:** select the draft room's pick list, paste, press **Ctrl+Enter**. Every
  pick is marked taken, or mine if the drafter is in `MY_TEAM_NAMES`. Re-pasting the whole
  list is safe, since picks already marked are skipped. One paste undoes as one step.
- Every paste is appended to `paste_log.txt` with what the parser did with it. If a pick
  is missed, that file has the exact text to debug from.
- A notes column is saved with the draft, for your own injury or role reminders.
- Picks autosave to `draft_state.json` after every change, so a crash loses nothing.

## How it works

**Pipeline:** `yahoo_to_csv.py` (saved Yahoo pages to `players.csv`) →
`scoring.py` (values and weights, no Qt) → `ui.py` / `model.py` (PySide6 window) with
`state.py` (pick log, JSON, undo, no Qt) and `names.py` (paste parsing, no Qt).

**Scoring** (`scoring.py`):

1. Take Yahoo's **projected season totals** per category (these already include projected
   games played) and turn each into a z-score over the whole pool, flipping TO.
2. Multiply by a **G-score factor** per category, `1 / sqrt(1 + weekly within-player
   variance / weekly between-player variance)`. A category that is noisy week to week
   (steals, blocks, 3s) is a less reliable way to win a week, so it counts for less than
   one that is steady (points, rebounds). The within-player variance is modeled (Poisson
   scaled by `WITHIN_POISSON_MULT`; points use a coefficient of variation), not measured.
3. **Need weights**, recomputed after every pick: project my full 13-man roster and a
   typical opponent's (everything other teams have taken, split across 11 teams), filling
   open slots with the average of the best players still likely to be drafted. For each
   category, `edge = (me - opponent) / sqrt(2 * roster_size)`. If I'm behind or level the
   weight is 1; if I'm ahead it decays as `exp(-edge^2 / 2)`. So surplus in a category
   earns little, but a deficit is never discounted and nothing is ever punted.
4. A player's score is the sum of weight × value over the seven categories. Ties break on
   the unweighted value sum, then name. Yahoo's pre-rank is shown but never used.

The first pick is a plain value sum since every edge is zero.

## Decisions and what we learned

- **Weights compare against a typical opponent, not the whole player pool.** The first
  version measured my team against the pool average. Every real roster beats that, so
  assists looked fine while a mock team actually ranked 10th of 12 in them. Projecting a
  real opponent fixed it.
- **Turnover weight is capped at 0.8** (`WEIGHT_MAX_BY_CAT`). Turnovers are cheap to
  fix with low-usage bigs, and an uncapped TO weight bought surplus TO wins at the cost of
  PTS and AST. 0.8 was best or level in every simulation; 0.5 is effectively a TO punt.
- **No separate scarcity or position adjustment.** In simulated drafts, scarcity
  multipliers added nothing on top of the G-score, which already shifts value toward
  PTS/AST and away from steals. Roster slots are plain; positions are display only.
- **No injury or games-played adjustment**, because projected totals already include
  games played. Judge injuries yourself and use the notes column.
- **Paste parsing reads blocks, not brackets.** It works on mock-draft and live-draft
  layouts (the live draft shows `Team name / Player / TEAM - POS / 5th`). A pick is
  anchored on its positions-and-team lines, so chat, "joined" and "left the draft" lines
  can't be mistaken for picks. The team code resolves look-alikes (e.g. two D. Mitchells).
  Unrecognized names and ambiguous ones are reported in the result box, never guessed.
- **Header sorting is three-state** (ascending, descending, back to score order).
- **Everything is derived from one pick log**, so undo is just removing the last entry
  and nothing can drift out of sync. The whole list is recomputed after each pick; at 250
  players that is instant.

## Ideas not built

- Tracking the two C slots or exact position eligibility.
- Estimating who will still be available at my next pick, or showing picks until my turn.
- Learning the G-score variances from real weekly data instead of modeling them.
