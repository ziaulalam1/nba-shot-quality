"""
Shot quality analysis with expected value decomposition.

Two data sources:
  - ShotChartDetail: per-shot zone data + league zone averages
  - PlayerDashPtShots: pre-bucketed tracking stats by defender distance

Computes a two-part value decomposition:
  - Shooting Talent: points above expected if a league-avg shooter took the same shots
  - Shot Selection: points above/below expected from the player's shot distribution
    vs the league-average distribution

This is the expected value pattern applied to basketball: same framework used in
fintech (risk-adjusted returns), healthtech (risk scoring), adtech (click prediction).
"""

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from nba_api.stats.static import players
from nba_api.stats.endpoints import (
    ShotChartDetail,
    PlayerDashPtShots,
    LeagueDashPlayerPtShot,
)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

DEFENDER_RANGES_ORDERED = [
    "6+ Feet - Wide Open",
    "4-6 Feet - Open",
    "2-4 Feet - Tight",
    "0-2 Feet - Very Tight",
]

_executor = ThreadPoolExecutor(max_workers=4)


def get_player_id(name: str) -> int:
    """Return player_id for a given full name. Raises ValueError if not found."""
    results = players.find_players_by_full_name(name)
    if not results:
        raise ValueError(f"Player not found: {name!r}")
    active = [p for p in results if p.get("is_active")]
    match = active[0] if active else results[0]
    return match["id"]


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.parquet")


def _json_cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


# ---------------------------------------------------------------------------
# Data fetching (synchronous -- run via executor for async)
# ---------------------------------------------------------------------------


def get_shot_chart(player_id: int, season: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch ShotChartDetail. Returns (player_df, league_avg_df)."""
    player_path = _cache_path(f"{player_id}_{season.replace('-', '_')}_shots")
    league_path = _cache_path(f"{player_id}_{season.replace('-', '_')}_league")

    if os.path.exists(player_path) and os.path.exists(league_path):
        return pd.read_parquet(player_path), pd.read_parquet(league_path)

    endpoint = ShotChartDetail(
        player_id=player_id, team_id=0, season_nullable=season,
        season_type_all_star="Regular Season", context_measure_simple="FGA",
    )
    frames = endpoint.get_data_frames()
    player_df, league_df = frames[0], frames[1]

    if player_df.empty:
        raise ValueError(f"No shot data for player_id={player_id}, season={season!r}")

    player_df.to_parquet(player_path, index=False)
    league_df.to_parquet(league_path, index=False)
    return player_df, league_df


def get_shot_quality(player_id: int, season: str) -> pd.DataFrame | None:
    """Fetch PlayerDashPtShots ClosestDefenderShooting data."""
    path = _cache_path(f"{player_id}_{season.replace('-', '_')}_tracking")
    if os.path.exists(path):
        return pd.read_parquet(path)

    try:
        endpoint = PlayerDashPtShots(
            player_id=player_id, team_id=0, season=season,
            per_mode_simple="Totals", season_type_all_star="Regular Season",
        )
        for ds in endpoint.get_dict()["resultSets"]:
            if ds["name"] == "ClosestDefenderShooting":
                df = pd.DataFrame(ds["rowSet"], columns=ds["headers"])
                if not df.empty:
                    df.to_parquet(path, index=False)
                    return df
        return None
    except Exception:
        return None


def get_league_tracking_averages(season: str) -> dict | None:
    """
    Fetch league-wide FG2%, FG3%, FGA totals per defender distance bucket.
    Queries LeagueDashPlayerPtShot once per bucket, sums across all players.
    Returns dict keyed by range name with fg2_pct, fg3_pct, fga, points_per_attempt, pct_of_total.
    """
    cache_key = f"league_tracking_{season.replace('-', '_')}"
    jpath = _json_cache_path(cache_key)

    if os.path.exists(jpath):
        with open(jpath) as f:
            return json.load(f)

    ranges = [
        "0-2 Feet - Very Tight",
        "2-4 Feet - Tight",
        "4-6 Feet - Open",
        "6+ Feet - Wide Open",
    ]
    result = {}
    grand_total_fga = 0

    try:
        for rng in ranges:
            time.sleep(0.6)  # rate limit
            resp = LeagueDashPlayerPtShot(
                season=season, per_mode_simple="Totals",
                season_type_all_star="Regular Season",
                close_def_dist_range_nullable=rng,
            )
            data = resp.get_dict()["resultSets"][0]
            headers = data["headers"]
            rows = data["rowSet"]

            idx = {h: i for i, h in enumerate(headers)}
            total_fga = sum(r[idx["FGA"]] for r in rows)
            total_fg2a = sum(r[idx["FG2A"]] for r in rows)
            total_fg2m = sum(r[idx["FG2M"]] for r in rows)
            total_fg3a = sum(r[idx["FG3A"]] for r in rows)
            total_fg3m = sum(r[idx["FG3M"]] for r in rows)

            fg2_pct = total_fg2m / total_fg2a if total_fg2a > 0 else 0.0
            fg3_pct = total_fg3m / total_fg3a if total_fg3a > 0 else 0.0

            points = total_fg2m * 2 + total_fg3m * 3
            pts_per_attempt = points / total_fga if total_fga > 0 else 0.0

            result[rng] = {
                "fga": total_fga, "fg2a": total_fg2a, "fg3a": total_fg3a,
                "fg2_pct": round(fg2_pct, 4), "fg3_pct": round(fg3_pct, 4),
                "points_per_attempt": round(pts_per_attempt, 4),
            }
            grand_total_fga += total_fga

        # Add distribution percentages
        for rng in result:
            result[rng]["pct_of_total"] = round(result[rng]["fga"] / grand_total_fga, 4) if grand_total_fga > 0 else 0.0

        with open(jpath, "w") as f:
            json.dump(result, f, indent=2)
        return result

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------


async def async_get_shot_chart(player_id: int, season: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, get_shot_chart, player_id, season)


async def async_get_shot_quality(player_id: int, season: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, get_shot_quality, player_id, season)


async def async_get_league_averages(season: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, get_league_tracking_averages, season)


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------


def compute_zone_breakdown(player_df: pd.DataFrame, league_df: pd.DataFrame) -> list[dict]:
    """Per-zone FG% with league average comparison."""
    player_df = player_df.copy()
    player_df["SHOT_MADE_FLAG"] = player_df["SHOT_MADE_FLAG"].astype(int)

    league_agg = (
        league_df.groupby("SHOT_ZONE_BASIC")
        .agg(FGA=("FGA", "sum"), FGM=("FGM", "sum"))
        .reset_index()
    )
    league_agg["FG_PCT"] = (league_agg["FGM"] / league_agg["FGA"]).round(3)
    league_lookup = dict(zip(league_agg["SHOT_ZONE_BASIC"], league_agg["FG_PCT"]))

    zones = []
    for zone, group in player_df.groupby("SHOT_ZONE_BASIC"):
        attempts = len(group)
        makes = int(group["SHOT_MADE_FLAG"].sum())
        fg_pct = round(makes / attempts, 3) if attempts > 0 else 0.0

        league_avg = league_lookup.get(zone)
        delta = None
        if league_avg is not None and attempts > 0:
            delta_raw = fg_pct - league_avg
            sign = "+" if delta_raw >= 0 else ""
            delta = f"{sign}{delta_raw * 100:.1f}%"

        zones.append({
            "zone": zone, "attempts": attempts, "makes": makes,
            "fg_pct": fg_pct, "league_avg": league_avg, "delta": delta,
        })

    zones.sort(key=lambda z: z["attempts"], reverse=True)
    return zones


def compute_shot_quality_profile(tracking_df: pd.DataFrame) -> list[dict]:
    """Transform ClosestDefenderShooting into ordered profile."""
    total_fga = int(tracking_df["FGA"].sum())

    profile = []
    for rng in DEFENDER_RANGES_ORDERED:
        row = tracking_df[tracking_df["CLOSE_DEF_DIST_RANGE"] == rng]
        if row.empty:
            profile.append({"range": rng, "fga": 0, "fgm": 0, "fg_pct": None, "pct_of_total": 0.0})
            continue

        r = row.iloc[0]
        fga = int(r["FGA"])
        fgm = int(r["FGM"])
        fg_pct = round(float(r["FG_PCT"]), 3) if fga > 0 else None
        pct = round(fga / total_fga, 3) if total_fga > 0 else 0.0

        profile.append({"range": rng, "fga": fga, "fgm": fgm, "fg_pct": fg_pct, "pct_of_total": pct})

    return profile


def compute_value_decomposition(
    tracking_df: pd.DataFrame,
    league_avgs: dict,
    games_played: int,
) -> dict | None:
    """
    Decompose player scoring into shooting talent + shot selection value.

    Shooting Talent = actual points - expected points if league-avg shooter took same shots
    Shot Selection  = expected points at player's distribution - expected at league distribution

    All values are season totals and per-game.
    """
    if tracking_df is None or league_avgs is None or games_played == 0:
        return None

    player_total_fga = 0
    actual_points = 0.0
    expected_points_same_shots = 0.0

    bucket_data = []

    for _, row in tracking_df.iterrows():
        rng = row["CLOSE_DEF_DIST_RANGE"]
        if rng not in league_avgs:
            continue

        la = league_avgs[rng]
        fga = int(row["FGA"])
        fg2a = int(row["FG2A"])
        fg2m = int(row["FG2M"])
        fg3a = int(row["FG3A"])
        fg3m = int(row["FG3M"])

        player_total_fga += fga

        # Actual points scored in this bucket
        actual_pts = fg2m * 2 + fg3m * 3
        actual_points += actual_pts

        # Expected points if league-avg shooter took same 2PA and 3PA
        expected_pts = fg2a * la["fg2_pct"] * 2 + fg3a * la["fg3_pct"] * 3
        expected_points_same_shots += expected_pts

        bucket_data.append({
            "range": rng, "fga": fga,
            "actual_pts": actual_pts, "expected_pts": round(expected_pts, 1),
        })

    if player_total_fga == 0:
        return None

    # Shooting talent: actual - expected (same shots, league avg shooting)
    shooting_talent = actual_points - expected_points_same_shots

    # Shot selection: expected pts at player's distribution - expected pts at league distribution
    # Both use league-average shooting rates
    # Player distribution already computed: expected_points_same_shots
    # League distribution: redistribute player's FGA across buckets per league pcts
    expected_league_dist = 0.0
    for rng, la in league_avgs.items():
        league_fga_share = la["pct_of_total"]
        allocated_fga = player_total_fga * league_fga_share
        expected_league_dist += allocated_fga * la["points_per_attempt"]

    shot_selection = expected_points_same_shots - expected_league_dist

    total_above_avg = shooting_talent + shot_selection

    return {
        "shooting_talent_pts": round(shooting_talent, 1),
        "shot_selection_pts": round(shot_selection, 1),
        "total_above_avg_pts": round(total_above_avg, 1),
        "per_game": {
            "shooting_talent": round(shooting_talent / games_played, 2),
            "shot_selection": round(shot_selection / games_played, 2),
            "total": round(total_above_avg / games_played, 2),
        },
        "actual_points": round(actual_points),
        "expected_points": round(expected_points_same_shots, 1),
        "games_played": games_played,
    }
