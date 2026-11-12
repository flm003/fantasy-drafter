"""Player values, need weights and scores.

A player's value in a category is his z-score times the category's G-score
factor (how reliably a projected edge wins a week). Yahoo's pre-rank is carried
for display only and never affects values, weights or order.

No Qt imports, so everything here can be tested with plain pytest.
Run as a script to print the G-score factors and the top 20 by value:

    uv run python -m draft_tracker.scoring [players.csv]
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

CATS = config.CATEGORIES
# +1 where more is better, -1 where fewer is better (TO).
SIGNS = np.array([-1.0 if c in config.LOWER_IS_BETTER else 1.0 for c in CATS])
WEIGHT_MAX = np.array([config.WEIGHT_MAX_BY_CAT.get(c, 1.0) for c in CATS])


@dataclass
class PlayerPool:
    """The loaded players plus their fixed values. Read-only after load."""
    names: list[str]
    teams: list[str]
    positions: list[str]
    pre_rank: list[str]     # Yahoo pre-season rank: display only
    gp: np.ndarray          # (n,) projected games played, display only
    totals: np.ndarray      # (n, 7) projected season totals
    per_game: np.ndarray    # (n, 7) totals / GP, rounded to 2 places
    z: np.ndarray           # (n, 7) z-scores, TO flipped so higher is better
    g_factor: np.ndarray    # (7,) G-score multiplier per category
    value: np.ndarray       # (n, 7) z * g_factor: what scoring uses
    value_sum: np.ndarray   # (n,) unweighted value sum, the tie-break
    index: dict[str, int]   # name -> row

    def __len__(self):
        return len(self.names)


@dataclass
class Evaluation:
    """Everything derived from the pick log; recomputed after every pick."""
    weights: np.ndarray        # (7,) need weight per category
    contributions: np.ndarray  # (n, 7) weight * value for every player
    scores: np.ndarray         # (n,) weighted score for every player
    available: list[int]       # undrafted players, best first
    mine: list[int]            # my roster in pick order
    projected_me: np.ndarray   # (7,) my projected full-roster value per category
    projected_opp: np.ndarray  # (7,) a typical opponent's, same units
    edge: np.ndarray           # (7,) (me - opp) in weekly-spread units; > 0 = ahead


def load_players(path):
    """Read and validate the CSV. Returns (DataFrame of usable rows, problems)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    missing = [c for c in ("name", *CATS) if c not in df.columns]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")

    problems = []
    if len(df) != config.EXPECTED_PLAYERS:
        problems.append(f"Expected {config.EXPECTED_PLAYERS} players, found {len(df)}.")

    df["name"] = df["name"].str.strip()
    numeric = pd.DataFrame({
        c: pd.to_numeric(df[c].str.replace(",", "").str.strip(), errors="coerce") for c in CATS
    })
    bad = numeric.isna()
    for i in df.index[bad.any(axis=1)]:
        cols = ", ".join(c for c in CATS if bad.at[i, c])
        problems.append(f"Line {i + 2} ({df.at[i, 'name'] or 'no name'}): "
                        f"{cols} not numeric; row skipped.")
    no_name = (df["name"] == "") & ~bad.any(axis=1)
    for i in df.index[no_name]:
        problems.append(f"Line {i + 2}: no player name; row skipped.")

    df = df.assign(**{c: numeric[c] for c in CATS})
    df = df[~bad.any(axis=1) & (df["name"] != "")]
    dup = df["name"].duplicated()
    for i in df.index[dup]:
        problems.append(f"Line {i + 2}: duplicate of {df.at[i, 'name']!r}; row skipped.")
    return df[~dup].reset_index(drop=True), problems


def zscores(totals):
    """Per-category z-scores over the whole pool, with TO flipped."""
    mean = totals.mean(axis=0)
    std = totals.std(axis=0)
    std = np.where(std > 0, std, 1.0)
    return (totals - mean) / std * SIGNS


def g_factors(per_game, games=config.GAMES_PER_WEEK, games_var=config.GAMES_PER_WEEK_VAR,
              poisson_mult=config.WITHIN_POISSON_MULT, pts_cv=config.PTS_GAME_CV):
    """G-score multiplier per category: 1 / sqrt(1 + weekly within / weekly between).

    Within-player variance per game is modelled, not measured: Poisson (variance =
    mean) times a per-category multiplier, except points, which use a fixed
    coefficient of variation. A week's total over G games then has variance
    E[G]*per-game variance + Var(G)*mean^2 (the second term is the swing from
    2-to-5-game weeks, larger for high-volume players). Between-player variance
    of a week's total is E[G]^2 times the variance of the per-game averages.
    """
    mu = per_game
    within_game = np.array([
        ((pts_cv * mu[:, c]) ** 2).mean() if cat == "PTS"
        else poisson_mult.get(cat, 1.0) * mu[:, c].mean()
        for c, cat in enumerate(CATS)
    ])
    within_week = games * within_game + games_var * (mu ** 2).mean(axis=0)
    between_week = games ** 2 * mu.var(axis=0)
    ratio = np.divide(within_week, between_week, out=np.zeros(len(CATS)), where=between_week > 0)
    return 1 / np.sqrt(1 + ratio)


def build_pool(df, g_factor=None):
    """Build the pool. Pass a g_factor array to override the computed one."""
    if df.empty:
        raise ValueError("no usable player rows")

    def text(col):
        return df[col].tolist() if col in df.columns else [""] * len(df)

    totals = df[CATS].to_numpy(dtype=float)
    gp = pd.to_numeric(pd.Series(text("GP")), errors="coerce").fillna(0).to_numpy(dtype=float)
    per_game = np.zeros_like(totals)
    np.divide(totals, gp[:, None], out=per_game, where=gp[:, None] > 0)
    z = zscores(totals)
    g_factor = g_factors(per_game) if g_factor is None else np.asarray(g_factor, dtype=float)
    value = z * g_factor
    names = df["name"].tolist()
    return PlayerPool(
        names=names,
        teams=text("team"),
        positions=text("positions"),
        pre_rank=text("PreRank"),
        gp=gp,
        totals=totals,
        per_game=per_game.round(2),
        z=z,
        g_factor=g_factor,
        value=value,
        value_sum=value.sum(axis=1),
        index={n: i for i, n in enumerate(names)},
    )


def matchup_weights(value, mine, taken, available, teams=config.TEAMS,
                    roster_size=config.ROSTER_SIZE, scale=config.MATCHUP_SCALE, hi=WEIGHT_MAX):
    """Need weight per category from how my team projects against a typical opponent.

    Both teams are projected to a full roster: drafted players plus open slots
    filled with the average of the players still likely to be drafted (the best
    remaining by value, as many as there are open slots in the league). The
    typical opponent splits everything other teams have taken across teams - 1.
    edge = (me - opponent) / (scale * sqrt(2 * roster_size)); the weight is
    exp(-edge^2 / 2) when ahead and 1 when level or behind, capped by `hi`.

    Returns (weights, projected_me, projected_opp, edge). Before any pick every
    edge is 0 and every weight is 1 (TO is still capped), so the first pick is a
    plain value sum.
    """
    mine, taken, available = list(mine), list(taken), list(available)
    open_slots = max(teams * roster_size - len(mine) - len(taken), 1)
    likely = sorted(available, key=lambda i: -value[i].sum())[:open_slots]
    filler = value[likely].mean(axis=0) if likely else np.zeros(value.shape[1])

    me = value[mine].sum(axis=0) + max(roster_size - len(mine), 0) * filler
    opp_open = max((teams - 1) * roster_size - len(taken), 0)
    opp = (value[taken].sum(axis=0) + opp_open * filler) / max(teams - 1, 1)
    edge = (me - opp) / (scale * np.sqrt(2 * roster_size))
    weights = np.where(edge > 0, np.exp(-edge ** 2 / 2), 1.0)
    return np.minimum(weights, hi), me, opp, edge


def rank(candidates, scores, tiebreak, names):
    """Best first: score, then the unweighted value sum, then name."""
    return sorted(candidates, key=lambda i: (-scores[i], -tiebreak[i], names[i].casefold()))


def evaluate(pool, mine, taken):
    mine, taken = list(mine), list(taken)
    drafted = set(mine) | set(taken)
    undrafted = [i for i in range(len(pool)) if i not in drafted]
    weights, me, opp, edge = matchup_weights(pool.value, mine, taken, undrafted)
    contributions = pool.value * weights
    scores = contributions.sum(axis=1)
    available = rank(undrafted, scores, pool.value_sum, pool.names)
    return Evaluation(weights, contributions, scores, available, mine, me, opp, edge)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Print the G-score factors and the top players by value.")
    ap.add_argument("csv", nargs="?", type=Path, default=config.CSV_PATH)
    ap.add_argument("-n", type=int, default=20, help="how many players to show")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    df, problems = load_players(args.csv)
    for p in problems:
        print("warning:", p)
    pool = build_pool(df)
    print(f"{'':33}" + "".join(f"{c:>7}" for c in CATS))
    print(f"{'G-score factor':<33}" + "".join(f"{v:>7.2f}" for v in pool.g_factor))
    print()
    print(f"{'#':>3}  {'Name':<22}{'Yahoo':>6}{'value':>7}" + "".join(f"{c:>7}" for c in CATS))
    for r, i in enumerate(rank(range(len(pool)), pool.value_sum, pool.value_sum, pool.names)[:args.n], 1):
        print(f"{r:>3}  {pool.names[i]:<22}{pool.pre_rank[i]:>6}{pool.value_sum[i]:>7.2f}"
              + "".join(f"{v:>7.2f}" for v in pool.value[i]))


if __name__ == "__main__":
    main()
