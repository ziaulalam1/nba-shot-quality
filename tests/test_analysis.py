"""
Invariant tests for analysis.py

1. Zone attempt counts sum to total attempts
2. Zone FG% = makes / attempts (math integrity)
3. get_player_id("Stephen Curry") returns a valid int
4. Shot quality profile covers all 4 defender distance ranges
"""

import pandas as pd
import pytest
from analysis import (
    get_player_id,
    compute_zone_breakdown,
    compute_shot_quality_profile,
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
    {"CLOSE_DEF_DIST_RANGE": "6+ Feet - Wide Open", "FGA": 40, "FGM": 20, "FG_PCT": 0.500, "FGA_FREQUENCY": 0.40},
    {"CLOSE_DEF_DIST_RANGE": "4-6 Feet - Open", "FGA": 25, "FGM": 10, "FG_PCT": 0.400, "FGA_FREQUENCY": 0.25},
    {"CLOSE_DEF_DIST_RANGE": "2-4 Feet - Tight", "FGA": 20, "FGM": 7, "FG_PCT": 0.350, "FGA_FREQUENCY": 0.20},
    {"CLOSE_DEF_DIST_RANGE": "0-2 Feet - Very Tight", "FGA": 15, "FGM": 4, "FG_PCT": 0.267, "FGA_FREQUENCY": 0.15},
]


def test_zone_attempts_sum_to_total():
    """Zone attempt counts must sum to total rows in the DataFrame."""
    df = pd.DataFrame(SHOT_ROWS)
    league_df = pd.DataFrame(LEAGUE_ROWS)
    zones = compute_zone_breakdown(df, league_df)
    zone_total = sum(z["attempts"] for z in zones)
    assert zone_total == len(df), (
        f"Zone totals ({zone_total}) != DataFrame length ({len(df)})"
    )


def test_zone_fg_pct_math():
    """fg_pct must equal makes / attempts for every zone."""
    df = pd.DataFrame(SHOT_ROWS)
    league_df = pd.DataFrame(LEAGUE_ROWS)
    zones = compute_zone_breakdown(df, league_df)

    for z in zones:
        if z["attempts"] > 0:
            expected = round(z["makes"] / z["attempts"], 3)
            assert z["fg_pct"] == expected, (
                f"Zone {z['zone']!r}: fg_pct={z['fg_pct']} but makes/attempts={expected}"
            )


@pytest.mark.network
def test_get_player_id_curry():
    """get_player_id('Stephen Curry') must return a positive integer."""
    pid = get_player_id("Stephen Curry")
    assert isinstance(pid, int), f"Expected int, got {type(pid)}"
    assert pid > 0, f"Expected positive int, got {pid}"


def test_shot_quality_profile_completeness():
    """Shot quality profile must have all 4 defender distance ranges, pct_of_total sums to ~1.0."""
    tracking_df = pd.DataFrame(TRACKING_ROWS)
    profile = compute_shot_quality_profile(tracking_df)

    ranges_returned = [p["range"] for p in profile]
    assert ranges_returned == DEFENDER_RANGES_ORDERED, (
        f"Expected {DEFENDER_RANGES_ORDERED}, got {ranges_returned}"
    )

    pct_sum = sum(p["pct_of_total"] for p in profile)
    assert abs(pct_sum - 1.0) < 0.01, f"pct_of_total sums to {pct_sum}, expected ~1.0"

    # Math check: fg_pct = fgm / fga
    for p in profile:
        if p["fga"] > 0 and p["fg_pct"] is not None:
            expected = round(p["fgm"] / p["fga"], 3)
            assert p["fg_pct"] == expected, (
                f"Range {p['range']!r}: fg_pct={p['fg_pct']} but fgm/fga={expected}"
            )
