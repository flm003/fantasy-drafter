import math

import numpy as np
import pandas as pd
import pytest

from draft_tracker import config, scoring

CATS = config.CATEGORIES
TO = CATS.index("TO")


def make_pool(rows, plain=False):
    """rows: list of (name, [7 totals]) -> PlayerPool. plain=True sets every G-score factor to 1."""
    df = pd.DataFrame([{"name": n, "GP": "70", **dict(zip(CATS, vals))} for n, vals in rows])
    if plain:
        return scoring.build_pool(df, g_factor=np.ones(7))
    return scoring.build_pool(df)


@pytest.fixture
def random_pool():
    rng = np.random.default_rng(0)
    return make_pool([(f"P{i}", rng.integers(0, 2000, size=7)) for i in range(200)])


def test_zscores_are_standardised(random_pool):
    z = random_pool.z
    assert np.allclose(z.mean(axis=0), 0)
    assert np.allclose(z.std(axis=0), 1)


def test_turnovers_are_flipped(random_pool):
    most_to = random_pool.totals[:, TO].argmax()
    assert random_pool.z[most_to, TO] == random_pool.z[:, TO].min()


def weights_for(pool, mine, taken=(), **kw):
    drafted = set(mine) | set(taken)
    avail = [i for i in range(len(pool)) if i not in drafted]
    return scoring.matchup_weights(pool.value, mine, taken, avail, **kw)


def test_weights_before_any_pick_are_one_except_to_cap(random_pool):
    w, me, opp, edge = weights_for(random_pool, [])
    assert np.allclose(edge, 0)
    assert w == pytest.approx([1] * 6 + [config.WEIGHT_MAX_BY_CAT["TO"]])


def test_weights_stay_in_range(random_pool):
    rng = np.random.default_rng(1)
    for _ in range(200):
        picks = rng.choice(len(random_pool), size=rng.integers(1, 60), replace=False)
        k = rng.integers(0, min(13, len(picks)) + 1)
        w, *_ = weights_for(random_pool, picks[:k], picks[k:])
        assert np.all(w > 0) and np.all(w <= 1)
        assert w[TO] <= config.WEIGHT_MAX_BY_CAT["TO"]


def test_big_lead_is_discounted_and_deficit_is_not(random_pool):
    reb = CATS.index("REB")
    by_reb = np.argsort(-random_pool.value[:, reb])
    w, *_ = weights_for(random_pool, by_reb[:6])           # six best rebounders
    assert w[reb] < 0.6
    w, *_ = weights_for(random_pool, by_reb[-6:])          # six worst rebounders
    assert w[reb] == 1.0                                   # behind: never punted


def test_opponent_projection_uses_what_others_took():
    # Two players, two teams, roster of one each: the opponent is exactly what
    # they took, and I am exactly what I took.
    pool = make_pool([("A", [5] * 7), ("B", [1] * 7)], plain=True)
    w, me, opp, edge = weights_for(pool, [0], [1], teams=2, roster_size=1, hi=np.ones(7))
    assert me == pytest.approx(pool.value[0])
    assert opp == pytest.approx(pool.value[1])
    assert edge == pytest.approx((pool.value[0] - pool.value[1]) / np.sqrt(2))


def test_score_matches_hand_calculation():
    # Each category is 1, 2, 3 across the players: mean 2, std sqrt(2/3),
    # so z = -k, 0, +k with k = 1 / sqrt(2/3). TO is flipped.
    pool = make_pool([("Low", [1] * 7), ("Mid", [2] * 7), ("High", [3] * 7)], plain=True)
    k = 1 / math.sqrt(2 / 3)

    # No picks yet: every edge is 0, weights 1 except TO at its 0.8 cap.
    ev = scoring.evaluate(pool, mine=[], taken=[])
    assert ev.scores[2] == pytest.approx(6 * k - 0.8 * k)
    assert ev.available == [2, 1, 0]

    # Drafting High (12 teams, 13 slots): open slots are filled with the average
    # of Low and Mid (-k/2; +k/2 for TO). Me = High + 12 * filler; the opponent
    # has no picks yet, so 13 * filler. Edge = (High - filler) / sqrt(26):
    # +1.5k / sqrt(26) in six categories (ahead, so discounted), -1.5k / sqrt(26)
    # in TO (behind, so 1, then capped at 0.8).
    ev = scoring.evaluate(pool, mine=[2], taken=[])
    w = math.exp(-(1.5 * k / math.sqrt(26)) ** 2 / 2)
    assert ev.edge == pytest.approx([1.5 * k / math.sqrt(26)] * 6 + [-1.5 * k / math.sqrt(26)])
    assert ev.weights == pytest.approx([w] * 6 + [0.8])
    assert ev.scores[0] == pytest.approx(6 * w * -k + 0.8 * k)
    assert ev.available == [1, 0]


def test_value_is_z_times_g_factor():
    g = np.linspace(0.5, 0.9, 7)
    df = pd.DataFrame([{"name": n, "GP": "70", **dict(zip(CATS, v))} for n, v in
                       [("A", [1, 2, 3, 4, 5, 6, 7]), ("B", [7, 6, 5, 4, 3, 2, 1]), ("C", [3] * 7)]])
    pool = scoring.build_pool(df, g_factor=g)
    assert pool.value == pytest.approx(pool.z * g)


def test_g_factors_penalise_noisy_categories():
    # Category 0: big spread between players, so weekly luck matters little.
    # Category 1: same mean, tiny spread, so a Poisson week swamps any edge.
    rng = np.random.default_rng(2)
    pg = np.column_stack([rng.uniform(1, 9, 200), rng.uniform(4.5, 5.5, 200)] + [rng.uniform(1, 9, 200)] * 5)
    f = scoring.g_factors(pg, games=3.4, games_var=0.0, poisson_mult={}, pts_cv=0.35)
    assert np.all((f > 0) & (f < 1))
    assert f[1] < f[0]


def test_game_count_swing_adds_noise():
    rng = np.random.default_rng(3)
    pg = rng.uniform(1, 9, (200, 7))
    steady = scoring.g_factors(pg, games_var=0.0)
    swingy = scoring.g_factors(pg, games_var=0.5)
    assert np.all(swingy < steady)


def test_yahoo_rank_never_affects_scoring():
    rng = np.random.default_rng(4)
    rows = [{"name": f"P{i}", "GP": "70", **dict(zip(CATS, rng.integers(0, 2000, size=7)))}
            for i in range(50)]
    plain = scoring.build_pool(pd.DataFrame(rows))
    ranked = scoring.build_pool(pd.DataFrame([{**r, "PreRank": str(50 - i)} for i, r in enumerate(rows)]))
    assert np.array_equal(plain.value, ranked.value)
    a = scoring.evaluate(plain, mine=[3, 7], taken=[1])
    b = scoring.evaluate(ranked, mine=[3, 7], taken=[1])
    assert a.available == b.available and np.array_equal(a.scores, b.scores)


def test_ties_break_on_zsum_then_name():
    scores = np.array([1.0, 1.0, 1.0, 2.0])
    zsum = np.array([0.5, 0.9, 0.5, 0.0])
    names = ["bob", "Zed", "Al", "Top"]
    assert scoring.rank(range(4), scores, zsum, names) == [3, 1, 2, 0]


def test_evaluate_excludes_drafted(random_pool):
    ev = scoring.evaluate(random_pool, mine=[0, 5], taken=[3])
    assert len(ev.available) == 197
    assert not {0, 3, 5} & set(ev.available)
    assert ev.mine == [0, 5]


def test_load_reports_bad_rows(tmp_path):
    path = tmp_path / "players.csv"
    path.write_text(
        "name,team,positions,GP," + ",".join(CATS) + "\n"
        "Good,BOS,PG,70,1,2,3,4,5,6,7\n"
        "Bad,BOS,PG,70,1,x,3,4,5,,7\n"
        "Good,NYK,C,70,1,2,3,4,5,6,7\n",
        encoding="utf-8",
    )
    df, problems = scoring.load_players(path)
    assert df["name"].tolist() == ["Good"]
    text = "\n".join(problems)
    assert f"Expected {config.EXPECTED_PLAYERS} players, found 3" in text
    assert "Line 3 (Bad): PTS, BLK not numeric" in text
    assert "Line 4: duplicate of 'Good'" in text


def test_load_rejects_missing_columns(tmp_path):
    path = tmp_path / "players.csv"
    path.write_text("name,PTS\nA,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing column"):
        scoring.load_players(path)
