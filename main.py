"""
NBA Shot Quality API with Expected Value Decomposition

POST /api/player-analysis  -- JSON API
GET  /                      -- HTML demo view
"""

import asyncio

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests

from analysis import (
    get_player_id,
    async_get_shot_chart,
    async_get_shot_quality,
    async_get_league_averages,
    compute_zone_breakdown,
    compute_shot_quality_profile,
    compute_value_decomposition,
)

app = FastAPI(title="NBA Shot Quality API", version="2.0.0")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AnalysisRequest(BaseModel):
    player: str
    season: str = "2024-25"


class ZoneResult(BaseModel):
    zone: str
    attempts: int
    makes: int
    fg_pct: float
    league_avg: float | None
    delta: str | None


class ShotQualityBucket(BaseModel):
    range: str
    fga: int
    fgm: int
    fg_pct: float | None
    pct_of_total: float


class PerGameValues(BaseModel):
    shooting_talent: float
    shot_selection: float
    total: float


class ValueDecomposition(BaseModel):
    shooting_talent_pts: float
    shot_selection_pts: float
    total_above_avg_pts: float
    per_game: PerGameValues
    actual_points: int
    expected_points: float
    games_played: int


class AnalysisResponse(BaseModel):
    player: str
    player_id: int
    season: str
    total_attempts: int
    zones: list[ZoneResult]
    shot_quality: list[ShotQualityBucket] | None
    value_decomposition: ValueDecomposition | None
    summary: str | None


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


async def _run_analysis(player: str, season: str) -> dict:
    """Shared analysis logic for both API and HTML endpoints."""
    try:
        player_id = get_player_id(player)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Fetch all three data sources concurrently
    try:
        (player_df, league_df), tracking_df, league_avgs = await asyncio.gather(
            async_get_shot_chart(player_id, season),
            async_get_shot_quality(player_id, season),
            async_get_league_averages(season),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="nba_api request timed out. Try again.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"nba_api error: {e}")

    zones = compute_zone_breakdown(player_df, league_df)

    shot_quality = None
    value_decomp = None
    if tracking_df is not None:
        shot_quality = compute_shot_quality_profile(tracking_df)

        games_played = int(tracking_df.iloc[0]["GP"]) if "GP" in tracking_df.columns else 0
        value_decomp = compute_value_decomposition(tracking_df, league_avgs, games_played)

    summary = _generate_summary(player, shot_quality, value_decomp)

    return {
        "player": player,
        "player_id": player_id,
        "season": season,
        "total_attempts": len(player_df),
        "zones": zones,
        "shot_quality": shot_quality,
        "value_decomposition": value_decomp,
        "summary": summary,
    }


def _generate_summary(player: str, shot_quality: list | None, decomp: dict | None) -> str | None:
    """One-line natural language insight from the numbers."""
    if not shot_quality or not decomp:
        return None

    # Find wide open percentage
    wide_open = next((q for q in shot_quality if "Wide Open" in q["range"]), None)
    open_shot = next((q for q in shot_quality if q["range"] == "4-6 Feet - Open"), None)

    open_pct = 0.0
    if wide_open:
        open_pct += wide_open["pct_of_total"]
    if open_shot:
        open_pct += open_shot["pct_of_total"]

    talent = decomp["per_game"]["shooting_talent"]
    selection = decomp["per_game"]["shot_selection"]
    total = decomp["per_game"]["total"]

    first_name = player.split()[-1]

    parts = []
    parts.append(f"{first_name} takes {open_pct:.0%} of shots with 4+ feet of space")

    if talent > 0:
        parts.append(f"converts at +{talent:.1f} pts/game above expected from shooting talent")
    else:
        parts.append(f"converts at {talent:.1f} pts/game vs expected from shooting talent")

    if selection > 0:
        parts.append(f"gains +{selection:.1f} from shot selection")
    else:
        parts.append(f"loses {abs(selection):.1f} from shot selection vs league-average distribution")

    return ". ".join(parts) + f". Net: {'+' if total >= 0 else ''}{total:.1f} pts/game above average."


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/player-analysis", response_model=AnalysisResponse)
async def player_analysis(req: AnalysisRequest):
    return await _run_analysis(req.player, req.season)


@app.get("/", response_class=HTMLResponse)
async def demo_page(
    player: str = Query(default="Stephen Curry"),
    season: str = Query(default="2024-25"),
):
    try:
        data = await _run_analysis(player, season)
    except HTTPException as e:
        return HTMLResponse(f"<h1>Error</h1><p>{e.detail}</p>", status_code=e.status_code)

    zones_html = ""
    for z in data["zones"]:
        delta_color = "#22c55e" if z["delta"] and z["delta"].startswith("+") else "#ef4444"
        delta_val = z["delta"] or "--"
        league_val = f"{z['league_avg']:.1%}" if z["league_avg"] is not None else "--"
        zones_html += f"""
        <tr>
            <td>{z['zone']}</td>
            <td>{z['attempts']}</td>
            <td><strong>{z['fg_pct']:.1%}</strong></td>
            <td>{league_val}</td>
            <td style="color:{delta_color};font-weight:600">{delta_val}</td>
        </tr>"""

    quality_html = ""
    if data["shot_quality"]:
        for q in data["shot_quality"]:
            bar_width = int(q["pct_of_total"] * 300)
            fg_str = f"{q['fg_pct']:.1%}" if q["fg_pct"] is not None else "--"
            quality_html += f"""
            <tr>
                <td>{q['range']}</td>
                <td>{q['fga']}</td>
                <td><strong>{fg_str}</strong></td>
                <td>
                    <div style="display:flex;align-items:center;gap:8px">
                        <div style="background:#3b82f6;height:18px;width:{bar_width}px;border-radius:3px"></div>
                        <span>{q['pct_of_total']:.1%}</span>
                    </div>
                </td>
            </tr>"""
    else:
        quality_html = '<tr><td colspan="4">Tracking data unavailable for this season</td></tr>'

    decomp_html = ""
    if data["value_decomposition"]:
        d = data["value_decomposition"]
        pg = d["per_game"]

        def val_color(v):
            return "#22c55e" if v >= 0 else "#ef4444"

        def fmt_val(v):
            return f"+{v:.1f}" if v >= 0 else f"{v:.1f}"

        decomp_html = f"""
        <div class="section">
            <h2>Expected Value Decomposition</h2>
            <p style="color:#94a3b8;font-size:0.85rem;margin-bottom:0.75rem">
                How much scoring comes from making tough shots vs taking easy ones?
                Compares to a league-average shooter taking league-average shots.
            </p>
            <div class="stat-cards">
                <div class="stat-card">
                    <div class="label">Shooting Talent</div>
                    <div class="value" style="color:{val_color(pg['shooting_talent'])}">{fmt_val(pg['shooting_talent'])}</div>
                    <div class="label">pts/game above expected</div>
                </div>
                <div class="stat-card">
                    <div class="label">Shot Selection</div>
                    <div class="value" style="color:{val_color(pg['shot_selection'])}">{fmt_val(pg['shot_selection'])}</div>
                    <div class="label">pts/game from distribution</div>
                </div>
                <div class="stat-card">
                    <div class="label">Total</div>
                    <div class="value" style="color:{val_color(pg['total'])}">{fmt_val(pg['total'])}</div>
                    <div class="label">pts/game above average</div>
                </div>
            </div>
            <p style="color:#64748b;font-size:0.85rem">
                Season totals: {fmt_val(d['shooting_talent_pts'])} pts from talent,
                {fmt_val(d['shot_selection_pts'])} from selection,
                {fmt_val(d['total_above_avg_pts'])} total over {d['games_played']} games.
                Actual: {d['actual_points']} pts. League-expected on same shots: {d['expected_points']:.0f} pts.
            </p>
        </div>"""

    summary_html = ""
    if data.get("summary"):
        summary_html = f"""
        <div style="background:#1e293b;border-left:3px solid #3b82f6;padding:1rem;margin-bottom:2rem;border-radius:0 6px 6px 0">
            <p style="font-size:0.9rem;line-height:1.5">{data['summary']}</p>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>NBA Shot Quality -- {data['player']}</title>
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
               background:#0f172a; color:#e2e8f0; padding:2rem; max-width:900px; margin:0 auto }}
        h1 {{ font-size:1.5rem; margin-bottom:0.25rem }}
        .subtitle {{ color:#94a3b8; margin-bottom:1rem }}
        .search-form {{ display:flex; gap:8px; margin-bottom:1.5rem; flex-wrap:wrap }}
        .search-form input {{ padding:8px 12px; border-radius:6px; border:1px solid #334155;
                              background:#1e293b; color:#e2e8f0; font-size:0.9rem }}
        .search-form button {{ padding:8px 16px; border-radius:6px; border:none;
                               background:#3b82f6; color:white; cursor:pointer; font-size:0.9rem }}
        .search-form button:hover {{ background:#2563eb }}
        .section {{ margin-bottom:2rem }}
        .section h2 {{ font-size:1.1rem; color:#94a3b8; margin-bottom:0.75rem; text-transform:uppercase;
                       letter-spacing:0.05em; font-weight:500 }}
        table {{ width:100%; border-collapse:collapse }}
        th, td {{ padding:8px 12px; text-align:left; border-bottom:1px solid #1e293b }}
        th {{ color:#64748b; font-weight:500; font-size:0.8rem; text-transform:uppercase }}
        tr:hover {{ background:#1e293b }}
        .stat-cards {{ display:flex; gap:1rem; margin-bottom:1rem; flex-wrap:wrap }}
        .stat-card {{ background:#1e293b; border-radius:8px; padding:1rem 1.25rem; flex:1; min-width:140px }}
        .stat-card .label {{ color:#64748b; font-size:0.75rem; text-transform:uppercase; margin-bottom:4px }}
        .stat-card .value {{ font-size:1.5rem; font-weight:700 }}
        .footer {{ color:#475569; font-size:0.8rem; margin-top:2rem; padding-top:1rem; border-top:1px solid #1e293b }}
        a {{ color:#3b82f6; text-decoration:none }}
    </style>
</head>
<body>
    <h1>{data['player']}</h1>
    <p class="subtitle">{data['season']} Regular Season &middot; {data['total_attempts']} shot attempts</p>

    <form class="search-form" action="/" method="get">
        <input type="text" name="player" placeholder="Player name" value="{data['player']}">
        <input type="text" name="season" placeholder="Season (e.g. 2024-25)" value="{data['season']}" style="width:140px">
        <button type="submit">Analyze</button>
    </form>

    {summary_html}

    {decomp_html}

    <div class="section">
        <h2>Shot Quality Profile</h2>
        <p style="color:#64748b;font-size:0.85rem;margin-bottom:0.75rem">
            How open are this player's shots? Higher share in "Wide Open" = better shot selection.
        </p>
        <table>
            <thead><tr><th>Defender Distance</th><th>FGA</th><th>FG%</th><th>Share of Attempts</th></tr></thead>
            <tbody>{quality_html}</tbody>
        </table>
    </div>

    <div class="section">
        <h2>Zone Breakdown</h2>
        <table>
            <thead><tr><th>Zone</th><th>Attempts</th><th>FG%</th><th>League Avg</th><th>vs League</th></tr></thead>
            <tbody>{zones_html}</tbody>
        </table>
    </div>

    <div class="footer">
        <p>Data from <a href="https://www.nba.com/stats">NBA.com/stats</a> via nba_api.
           API: POST /api/player-analysis &middot;
           <a href="/docs">Interactive docs</a> &middot;
           <a href="https://github.com/ziaulalam1/nba-shot-quality">Source</a></p>
    </div>
</body>
</html>"""
    return HTMLResponse(html)
