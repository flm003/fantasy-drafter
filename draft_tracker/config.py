"""Tunable settings for the draft tracker."""
from pathlib import Path

# The seven head-to-head categories, in display order.
CATEGORIES = ["3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
LOWER_IS_BETTER = {"TO"}

ROSTER_SIZE = 13
EXPECTED_PLAYERS = 250
TEAMS = 12
# Drafter names that mean "me" in a pasted pick list: mock drafts show "You", the
# live draft shows the fantasy team's name. Case and accents don't matter.
# Put your own team name in config_local.py (untracked), e.g.
#     MY_TEAM_NAMES = ["You", "My Team Name"]
MY_TEAM_NAMES = ["You"]

# --- Need weights: how much one more unit in a category helps win it -------
# After every pick, project my final team and a typical opponent's at full roster
# size: players already drafted (opponents: everyone taken by other teams, split
# across TEAMS - 1 teams) plus open slots filled with the average of the players
# still likely to be drafted. Then
#     edge_c = (me_c - opponent_c) / (MATCHUP_SCALE * sqrt(2 * ROSTER_SIZE))
#     weight_c = exp(-edge_c^2 / 2) when ahead, 1 when level or behind.
# A big lead (wasted surplus) earns little weight; a deficit is never discounted,
# so no category is punted. The sqrt(2 * ROSTER_SIZE) is the spread of a weekly
# team-vs-team difference in G-score units. Replaced weights measured against the
# whole player pool's average, which every real roster beats, so assists looked fine while
# a mock team ran 10th of 12 in them.
MATCHUP_SCALE = 1.0
# Per-category ceilings on the need weight. Turnovers are cheap to fix with
# low-usage bigs, so an uncapped TO weight buys surplus TO wins at the cost of PTS
# and AST. 0.8 was best or level in every simulation; 0.5 is effectively a TO punt.
WEIGHT_MAX_BY_CAT = {"TO": 0.8}

# --- G-score: shrink each category by how noisy it is week to week ----------
# multiplier_c = 1 / sqrt(1 + weekly within-player variance / weekly between-player variance)
# Per-game variance of a player's stat, as a multiple of Poisson (variance = mean).
WITHIN_POISSON_MULT = {"3PTM": 1.0, "REB": 1.3, "AST": 1.3, "ST": 1.0, "BLK": 1.0, "TO": 1.0}
# Points: per-game standard deviation as a fraction of the player's average
# (about 30% for stars, 40%+ for role players).
PTS_GAME_CV = 0.35
GAMES_PER_WEEK = 3.4
# Weeks have 2 to 5 games; that swing adds noise in proportion to a player's volume.
GAMES_PER_WEEK_VAR = 0.5
# No separate scarcity adjustment: in simulated drafts, scarcity multipliers (fixed
# or recomputed from the remaining players after every pick) added nothing on top
# of the G-score, which already shifts value toward PTS/AST and away from ST.

# Default CSV is the one yahoo_to_csv.py writes in the project root.
CSV_PATH = Path(__file__).resolve().parent.parent / "players.csv"
# The draft state is saved next to whichever CSV is loaded.
STATE_FILENAME = "draft_state.json"
# Every draft-room paste is appended here (same folder), raw text plus result,
# so a missed pick can be traced to the exact text that was pasted.
PASTE_LOG_FILENAME = "paste_log.txt"

try:  # personal overrides that stay out of version control
    from .config_local import *  # noqa: F401,F403
except ImportError:
    pass
