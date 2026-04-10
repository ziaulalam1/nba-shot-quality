# CLAUDE.md -- NBA Shot Quality API

## What this project is
Backend API that computes context-adjusted shot quality and decomposes player scoring
into shooting talent + shot selection value. Uses the expected value pattern:
event -> context -> expected -> actual vs expected.

## Data sources
1. **ShotChartDetail** -- per-shot zone data (SHOT_ZONE_BASIC, SHOT_MADE_FLAG).
   Also returns LeagueAverages (FG% by zone). No defender distance data.
2. **PlayerDashPtShots** -- ClosestDefenderShooting dataset with pre-bucketed
   FGA/FGM/FG_PCT by CLOSE_DEF_DIST_RANGE (0-2ft, 2-4ft, 4-6ft, 6+ft).
   Also has FG2A/FG2M/FG3A/FG3M per bucket (needed for point-value decomposition).
3. **LeagueDashPlayerPtShot** -- league-wide tracking data by defender distance.
   Summed across all players to get league baselines per bucket.

Per-shot tracking data was removed from the public NBA API ~2016-17.

## Value decomposition (core computation)
- Shooting Talent = actual points - expected points (league-avg shooting, same shots)
- Shot Selection = expected points at player distribution - expected at league distribution
- Total = Talent + Selection (invariant: additive)

## Stack
- Python 3.11, FastAPI (async), uvicorn, nba_api, pandas, pyarrow
- Pydantic response models
- File-based parquet + JSON cache in cache/
- Async endpoints with concurrent data fetching (thread pool executor)

## Run
```bash
.venv/bin/python3 -m uvicorn main:app --reload
```

## Tests
```bash
.venv/bin/python3 -m pytest tests/ -v -m "not network"
```

## Key files
- analysis.py -- data fetch, zone computation, tracking computation, value decomposition
- main.py -- FastAPI app (async), HTML demo, Pydantic models
- tests/test_analysis.py -- 5 invariant tests
- conftest.py -- pytest marker registration

## What NOT to add (v1 scope)
- No frontend framework (HTML demo is server-rendered)
- No ML model (conditional probability is sufficient)
- No Redis (file cache only)
- No player comparisons (one player per request)
