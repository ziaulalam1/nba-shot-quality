"""
Invariant tests for analysis.py

1. Zone attempt counts sum to total attempts
2. Zone FG% = makes / attempts (math integrity)
3. get_player_id("Stephen Curry") returns a valid int
4. Shot quality profile covers all 4 defender distance ranges
5. Value decomposition: shooting_talent + shot_selection = total_above_avg
"""

import pandas as pd
import pytest
from analysis import (
    get_player_id,
    compute_zone_breakdown,
    compute_shot_quality_profile,
    compute_value_decomposition,
    DEFENDER_RANGES_ORDERED,
)


# ---------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------

SHOT_ROWS = [
    {"SHOT_ZONE_BASIC": "Above the Break 3", "SHOT_MADE_FLAG": 1},
    {"SHOT_ZONE_BASIC": "Above the Break 3", "SHOT_MADE_FLAG": 1},
    {"SHOT_ZONE_BASIC": "Above the Break 3", "SHOT_MADE_FLAG": 0},
    {"SHOT_ZONE_BASIC": "Above the Break 3", "SHOT_MADE_FLAG": 0},
    {"SHOT_ZONE_BASIC": "Above the Break 3", "SHOT_MADE_FLAG": 0},
    {"SHOT_ZONE_BASIC": "In The Paint (Non-RA)", "SHOT_MADE_FLAG": 1},
    {"SHOT_ZONE_BASIC": "In The Paint (Non-RA)", "SHOT_MADE_FLAG": 0},
    {"SHOT_ZONE_BASIC": "Restricted Area", "SHOT_MADE_FLAG": 1},
    {"SHOT_ZONE_BASIC": "Restricted Area", "SHOT_MADE_FLAG": 1},
    {"SHOT_ZONE_BASIC": "Restricted Area", "SHOT_MADE_FLAG": 0},
]

LEAGUE_ROWS = [
    {"SHOT_ZONE_BASIC": "Above the Break 3", "SHOT_ZONE_AREA": "Center(C)", "SHOT_ZONE_RANGE": "24+ ft.", "FGA": 1000, "FGM": 362, "FG_PCT": 0.362},
    {"SHOT_ZONE_BASIC": "In The Paint (Non-RA)", "SHOT_ZONE_AREA": "Center(C)", "SHOT_ZONE_RANGE": "8-16 ft.", "FGA": 800, "FGM": 336, "FG_PCT": 0.420},
    {"SHOT_ZONE_BASIC": "Restricted Area", "SHOT_ZONE_AREA": "Center(C)", "SHOT_ZONE_RANGE": "Less Than 8 ft.", "FGA": 1200, "FGM": 756, "FG_PCT": 0.630},
]

TRACKING_ROWS = [
    {"CLOSE_DEF_DIST_RANGE": "6+ Feet - Wide Open", "FGA": 40, "FGM": 20, "FG_PCT": 0.500, "FGA_FREQUENCY": 0.40, "GP": 10, "FG2A": 5, "FG2M": 3, "FG3A": 35, "FG3M": 17},
    {"CLOSE_DEF_DIST_RANGE": "4-6 Feet - Open", "FGA": 25, "FGM": 10, "FG_PCT": 0.400, "FGA_FREQUENCY": 0.25, "GP": 10, "FG2A": 10, "FG2M": 5, "FG3A": 15, "FG3M": 5},
    {"CLOSE_DEF_DIST_RANGE": "2-4 Feet - Tight", "FGA": 20, "FGM": 7, "FG_PCT": 0.350, "FGA_FREQUENCY": 0.20, "GP": 10, "FG2A": 15, "FG2M": 5, "FG3A": 5, "FG3M": 2},
    {"CLOSE_DEF_DIST_RANGE": "0-2 Feet - Very Tight", "FGA": 15, "FGM": 4, "FG_PCT": 0.267, "FGA_FREQUENCY": 0.15, "GP": 10, "FG2A": 14, "FG2M": 3, "FG3A": 1, "FG3M": 1},
]

LEAGUE_AVGS = {
    "6+ Feet - Wide Open": {"fga": 54260, "fg2a": 7312, "fg3a": 46948, "fg2_pct": 0.66, "fg3_pct": 0.389, "points_per_attempt": 1.188, "pct_of_total": 0.2477},
    "4-6 Feet - Open": {"fga": 65508, "fg2a": 29680, "fg3a": 35828, "fg2_pct": 0.563, "fg3_pct": 0.341, "points_per_attempt": 1.070, "pct_of_total": 0.2989},
    "2-4 Feet - Tight": {"fga": 84603, "fg2a": 75472, "fg3a": 9131, "fg2_pct": 0.542, "fg3_pct": 0.293, "points_per_attempt": 1.062, "pct_of_total": 0.3861},
    "0-2 Feet - Very Tight": {"fga": 14748, "fg2a": 14356, "fg3a": 392, "fg2_pct": 0.465, "fg3_pct": 0.293, "points_per_attempt": 0.929, "pct_of_total": 0.0673},
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_zone_attempts_sum_to_total():
    """Zone attempt counts must sum to total rows in the DataFrame."""
    df = pd.DataFrame(SHOT_ROWS)
    league_df = pd.DataFrame(LEAGUE_ROWS)
    zones = compute_zone_breakdown(df, league_df)
    zone_total = sum(z["attempts"] for z in zones)
    assert zone_total == len(df)


def test_zone_fg_pct_math():
    """fg_pct must equal makes / attempts for every zone."""
    df = pd.DataFrame(SHOT_ROWS)
    league_df = pd.DataFrame(LEAGUE_ROWS)
    zones = compute_zone_breakdown(df, league_df)
    for z in zones:
        if z["attempts"] > 0:
            expected = round(z["makes"] / z["attempts"], 3)
            assert z["fg_pct"] == expected, f"Zone {z['zone']!r}: {z['fg_pct']} != {expected}"


@pytest.mark.network
def test_get_player_id_curry():
    """get_player_id('Stephen Curry') must return a positive integer."""
    pid = get_player_id("Stephen Curry")
    assert isinstance(pid, int) and pid > 0


def test_shot_quality_profile_completeness():
    """Profile must have all 4 ranges, pct_of_total sums to ~1.0, math checks."""
    tracking_df = pd.DataFrame(TRACKING_ROWS)
    profile = compute_shot_quality_profile(tracking_df)

    assert [p["range"] for p in profile] == DEFENDER_RANGES_ORDERED
    assert abs(sum(p["pct_of_total"] for p in profile) - 1.0) < 0.01

    for p in profile:
        if p["fga"] > 0 and p["fg_pct"] is not None:
            assert p["fg_pct"] == round(p["fgm"] / p["fga"], 3)


def test_value_decomposition_additivity():
    """shooting_talent + shot_selection must equal total_above_avg (within rounding)."""
    tracking_df = pd.DataFrame(TRACKING_ROWS)
    decomp = compute_value_decomposition(tracking_df, LEAGUE_AVGS, games_played=10)

    assert decomp is not None
    talent = decomp["shooting_talent_pts"]
    selection = decomp["shot_selection_pts"]
    total = decomp["total_above_avg_pts"]

    assert abs((talent + selection) - total) < 0.2, (
        f"talent({talent}) + selection({selection}) = {talent+selection} != total({total})"
    )

    # Per-game values must equal season totals / games
    assert decomp["per_game"]["shooting_talent"] == round(talent / 10, 2)
    assert decomp["per_game"]["total"] == round(total / 10, 2)

    # Actual points must be verifiable from raw data
    expected_actual = sum(r["FG2M"] * 2 + r["FG3M"] * 3 for r in TRACKING_ROWS)
    assert decomp["actual_points"] == expected_actual
