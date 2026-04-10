# CLAUDE.md -- NBA Shot Quality API

## What this project is
Backend API that computes context-adjusted shot quality for NBA players.
Core insight: raw FG% lies without context. A 38% 3PT shooter taking 60% contested shots
is a different player than one taking 60% open looks. This API surfaces that distinction.

## Expected value pattern
event (shot) -> contextual features (zone, defender distance) -> expected outcome ->
actual vs expected. Same primitive used in fintech, healthtech, adtech.

## Data sources
1. **ShotChartDetail** -- per-shot data with SHOT_ZONE_BASIC, SHOT_MADE_FLAG, LOC_X/Y.
   Also returns LeagueAverages (FG% by zone). No defender distance data.
2. **PlayerDashPtShots** -- ClosestDefenderShooting dataset with pre-bucketed
   FGA/FGM/FG_PCT by CLOSE_DEF_DIST_RANGE (0-2ft, 2-4ft, 4-6ft, 6+ft).
   Per-shot tracking data was removed from the public API ~2016-17.

## Stack
- Python 3.11, FastAPI, uvicorn, nba_api, pandas, pyarrow
- Single endpoint: POST /api/player-analysis
- File-based parquet cache in cache/

## Run
```bash
.venv/bin/python3 -m uvicorn main:app --reload
```

## Tests
```bash
.venv/bin/python3 -m pytest tests/ -v
# Skip network-dependent tests:
.venv/bin/python3 -m pytest tests/ -v -m "not network"
```

## Key files
- analysis.py -- data fetch + zone/tracking computation
- main.py -- FastAPI app
- tests/test_analysis.py -- 4 invariant tests
- conftest.py -- pytest marker registration

## What NOT to add (v1 scope)
- No frontend/visualizations
- No player comparisons
- No ML model (conditional probability is enough)
- No Redis (file cache only)
- One endpoint only
