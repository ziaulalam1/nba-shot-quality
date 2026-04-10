"""
NBA Shot Quality API
POST /api/player-analysis -- JSON API
GET  /                     -- HTML demo view
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests

from analysis import (
    get_player_id,
    get_shot_chart,
    get_shot_quality,
    compute_zone_breakdown,
    compute_shot_quality_profile,
)

app = FastAPI(title="NBA Shot Quality API", version="1.0.0")


class AnalysisRequest(BaseModel):
    player: str
    season: str = "2024-25"


def _run_analysis(player: str, season: str) -> dict:
    """Shared logic for both API and HTML endpoints."""
    try:
        player_id = get_player_id(player)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        player_df, league_df = get_shot_chart(player_id, season)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="nba_api request timed out. Try again.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"nba_api error: {e}")

    zones = compute_zone_breakdown(player_df, league_df)

    tracking_df = get_shot_quality(player_id, season)
    shot_quality = None
    if tracking_df is not None:
        shot_quality = compute_shot_quality_profile(tracking_df)

    return {
        "player": player,
        "player_id": player_id,
        "season": season,
        "total_attempts": len(player_df),
        "zones": zones,
        "shot_quality": shot_quality,
    }


@app.post("/api/player-analysis")
def player_analysis(req: AnalysisRequest):
    return _run_analysis(req.player, req.season)


@app.get("/", response_class=HTMLResponse)
def demo_page(
    player: str = Query(default="Stephen Curry"),
    season: str = Query(default="2024-25"),
):
    try:
        data = _run_analysis(player, season)
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
        .subtitle {{ color:#94a3b8; margin-bottom:1.5rem }}
        .search-form {{ display:flex; gap:8px; margin-bottom:2rem; flex-wrap:wrap }}
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
        .stat-cards {{ display:flex; gap:1rem; margin-bottom:2rem; flex-wrap:wrap }}
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

    <div class="section">
        <h2>Zone Breakdown</h2>
        <table>
            <thead><tr><th>Zone</th><th>Attempts</th><th>FG%</th><th>League Avg</th><th>vs League</th></tr></thead>
            <tbody>{zones_html}</tbody>
        </table>
    </div>

    <div class="section">
        <h2>Shot Quality Profile</h2>
        <p style="color:#64748b;font-size:0.85rem;margin-bottom:0.75rem">
            How open are this player's shots? Higher concentration in "Wide Open" = better shot selection.
        </p>
        <table>
            <thead><tr><th>Defender Distance</th><th>FGA</th><th>FG%</th><th>Share of Attempts</th></tr></thead>
            <tbody>{quality_html}</tbody>
        </table>
    </div>

    <div class="footer">
        <p>Data from <a href="https://www.nba.com/stats">NBA.com/stats</a> via nba_api.
           API endpoint: POST /api/player-analysis &middot;
           <a href="/docs">Interactive API docs</a></p>
    </div>
</body>
</html>"""
    return HTMLResponse(html)
