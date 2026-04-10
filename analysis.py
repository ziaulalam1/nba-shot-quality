"""
Shot quality analysis: fetch shot chart + tracking data, compute zone and defender-distance breakdowns.

Two data sources:
  - ShotChartDetail: per-shot data with zone classification (SHOT_ZONE_BASIC) + league averages
  - PlayerDashPtShots: pre-bucketed tracking stats by defender distance (ClosestDefenderShooting)

Per-shot defender distance (CLOSE_DEF_DIST as raw floats) was removed from the public NBA API
around 2016-17. Only bucketed aggregates are available via PlayerDashPtShots.
"""

import os
import pandas as pd
from nba_api.stats.static import players
from nba_api.stats.endpoints import ShotChartDetail, PlayerDashPtShots

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Defender distance ranges returned by PlayerDashPtShots, ordered open -> tight
DEFENDER_RANGES_ORDERED = [
    "6+ Feet - Wide Open",
    "4-6 Feet - Open",
    "2-4 Feet - Tight",
    "0-2 Feet - Very Tight",
]


def get_player_id(name: str) -> int:
    """Return player_id for a given full name. Raises ValueError if not found."""
    results = players.find_players_by_full_name(name)
    if not results:
        raise ValueError(f"Player not found: {name!r}")
    active = [p for p in results if p.get("is_active")]
    match = active[0] if active else results[0]
    return match["id"]


def _cache_path(player_id: int, season: str, suffix: str = "") -> str:
    key = f"{player_id}_{season.replace('-', '_')}{suffix}.parquet"
    return os.path.join(CACHE_DIR, key)


def get_shot_chart(player_id: int, season: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetch shot chart for player_id + season.
    Returns (player_df, league_avg_df).
    Uses file-based parquet cache; hits nba_api on cache miss.
    """
    player_path = _cache_path(player_id, season, "_shots")
    league_path = _cache_path(player_id, season, "_league")

    if os.path.exists(player_path) and os.path.exists(league_path):
        return pd.read_parquet(player_path), pd.read_parquet(league_path)

    endpoint = ShotChartDetail(
        player_id=player_id,
        team_id=0,
        season_nullable=season,
        season_type_all_star="Regular Season",
        context_measure_simple="FGA",
    )
    frames = endpoint.get_data_frames()
    player_df = frames[0]  # Shot_Chart_Detail
    league_df = frames[1]  # LeagueAverages

    if player_df.empty:
        raise ValueError(f"No shot data for player_id={player_id}, season={season!r}")

    player_df.to_parquet(player_path, index=False)
    league_df.to_parquet(league_path, index=False)
    return player_df, league_df


def get_shot_quality(player_id: int, season: str) -> pd.DataFrame | None:
    """
    Fetch defender-distance tracking data from PlayerDashPtShots.
    Returns the ClosestDefenderShooting DataFrame, or None if unavailable.
    """
    path = _cache_path(player_id, season, "_tracking")

    if os.path.exists(path):
        return pd.read_parquet(path)

    try:
        endpoint = PlayerDashPtShots(
            player_id=player_id,
            team_id=0,
            season=season,
            per_mode_simple="Totals",
            season_type_all_star="Regular Season",
        )
        # get_data_frames() returns datasets in order of expected_data keys
        # ClosestDefenderShooting is the second dataset (index 1)
        data_sets = endpoint.get_dict()["resultSets"]
        for ds in data_sets:
            if ds["name"] == "ClosestDefenderShooting":
                df = pd.DataFrame(ds["rowSet"], columns=ds["headers"])
                if not df.empty:
                    df.to_parquet(path, index=False)
                    return df
        return None
    except Exception:
        return None


def compute_zone_breakdown(player_df: pd.DataFrame, league_df: pd.DataFrame) -> list[dict]:
    """
    Group player shots by SHOT_ZONE_BASIC, compute FG% per zone,
    join with league average FG% from the LeagueAverages dataset.
    """
    player_df = player_df.copy()
    player_df["SHOT_MADE_FLAG"] = player_df["SHOT_MADE_FLAG"].astype(int)

    # Build league avg lookup: zone -> FG_PCT
    # LeagueAverages has multiple rows per zone (by area/range). Aggregate to zone level.
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
            "zone": zone,
            "attempts": attempts,
            "makes": makes,
            "fg_pct": fg_pct,
            "league_avg": league_avg,
            "delta": delta,
        })

    zones.sort(key=lambda z: z["attempts"], reverse=True)
    return zones


def compute_shot_quality_profile(tracking_df: pd.DataFrame) -> list[dict]:
    """
    Transform the ClosestDefenderShooting DataFrame into a list of dicts
    ordered from wide open to very tight.

    Columns used: CLOSE_DEF_DIST_RANGE, FGA, FGM, FG_PCT, FGA_FREQUENCY
    """
    total_fga = int(tracking_df["FGA"].sum())

    profile = []
    for rng in DEFENDER_RANGES_ORDERED:
        row = tracking_df[tracking_df["CLOSE_DEF_DIST_RANGE"] == rng]
        if row.empty:
            profile.append({
                "range": rng,
                "fga": 0,
                "fgm": 0,
                "fg_pct": None,
                "pct_of_total": 0.0,
            })
            continue

        row = row.iloc[0]
        fga = int(row["FGA"])
        fgm = int(row["FGM"])
        fg_pct = round(float(row["FG_PCT"]), 3) if fga > 0 else None
        pct_of_total = round(fga / total_fga, 3) if total_fga > 0 else 0.0

        profile.append({
            "range": rng,
            "fga": fga,
            "fgm": fgm,
            "fg_pct": fg_pct,
            "pct_of_total": pct_of_total,
        })

    return profile
