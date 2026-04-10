# NBA Shot Quality API

A backend API that computes context-adjusted shot quality for NBA players. Raw field goal percentage lies without context -- this API surfaces the distinction between a good shooter taking bad shots and a bad shooter taking good ones.

## The core insight

A player shooting 38% from three sounds mediocre. But if 60% of those attempts come with a defender within 2 feet, and their wide-open 3PT percentage is 44%, the problem is shot selection, not shooting ability. That distinction only appears when you condition on defender proximity.

This is the expected value pattern:

```
event (shot) -> contextual features (zone + defender distance) -> expected outcome -> actual vs expected
```

The same pattern appears in fintech (transaction fraud scoring), healthtech (patient risk assessment), and adtech (click prediction). Basketball is the cleanest public dataset to build it on because the ground truth (made/missed) is immediately verifiable.

## Stack

- Python 3.11, FastAPI, uvicorn
- nba_api (free, no API key)
- pandas + pyarrow
- File-based parquet cache
- pytest for invariant tests
- GitHub Actions CI

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn main:app --reload
```

## API

### POST /api/player-analysis

```bash
curl -X POST http://localhost:8000/api/player-analysis \
  -H "Content-Type: application/json" \
  -d '{"player": "Stephen Curry", "season": "2024-25"}'
```

**Response:**

```json
{
  "player": "Stephen Curry",
  "player_id": 201939,
  "season": "2024-25",
  "total_attempts": 1247,
  "zones": [
    {
      "zone": "Above the Break 3",
      "attempts": 412,
      "makes": 159,
      "fg_pct": 0.386,
      "league_avg": 0.362,
      "delta": "+2.4%"
    }
  ],
  "shot_quality": [
    {
      "range": "6+ Feet - Wide Open",
      "fga": 380,
      "fgm": 189,
      "fg_pct": 0.497,
      "pct_of_total": 0.305
    },
    {
      "range": "4-6 Feet - Open",
      "fga": 310,
      "fgm": 130,
      "fg_pct": 0.419,
      "pct_of_total": 0.249
    },
    {
      "range": "2-4 Feet - Tight",
      "fga": 340,
      "fgm": 128,
      "fg_pct": 0.376,
      "pct_of_total": 0.273
    },
    {
      "range": "0-2 Feet - Very Tight",
      "fga": 217,
      "fgm": 68,
      "fg_pct": 0.313,
      "pct_of_total": 0.174
    }
  ]
}
```

### Response fields

**zones** (from NBA ShotChartDetail endpoint):

| Field | Description |
|---|---|
| `zone` | Court zone (e.g. "Above the Break 3", "Restricted Area") |
| `attempts` / `makes` | Raw shot counts |
| `fg_pct` | Player's FG% in this zone |
| `league_avg` | League average FG% in this zone (same season) |
| `delta` | Player minus league average |

**shot_quality** (from NBA PlayerDashPtShots tracking endpoint):

| Field | Description |
|---|---|
| `range` | Closest defender distance bucket |
| `fga` / `fgm` | Attempts and makes at this defender proximity |
| `fg_pct` | FG% at this defender proximity |
| `pct_of_total` | Share of all attempts -- the shot selection signal |

A player with a high `pct_of_total` in the "6+ Feet - Wide Open" bucket is getting good looks. A player concentrated in "0-2 Feet - Very Tight" is forcing shots. The FG% gap between open and contested shots quantifies how much shot selection costs them.

`shot_quality` is `null` for seasons where tracking data is unavailable (pre-2013).

## Tests

```bash
pytest tests/ -v
```

Four invariant checks:
1. Zone attempt counts sum to total attempts
2. `fg_pct` = makes / attempts for every zone (math integrity)
3. `get_player_id("Stephen Curry")` returns a valid positive int
4. Shot quality profile has all 4 defender distance ranges, `pct_of_total` sums to ~1.0

## Architecture decisions

**Two data sources, not one.** ShotChartDetail gives per-shot zone data but no defender proximity. PlayerDashPtShots gives defender distance breakdowns but only as pre-bucketed aggregates. The NBA removed per-shot tracking data from the public API around 2016-17. Using both endpoints together provides the fullest picture available from public data.

**File cache (parquet), not Redis.** v1 scope. Parquet is columnar, compressed, and zero-dependency beyond pyarrow. A player-season query hits the NBA API once, then all subsequent requests read from disk in <5ms. Redis adds operational complexity with no benefit at this scale.

**Invariant tests, not mocks.** The tests verify mathematical properties (zone attempts sum to total, FG% = makes/attempts) rather than mocking API responses. Mocks test that your test setup matches your code. Invariant tests catch real bugs in the computation regardless of where the data comes from.

## What's next

All extensions use data already available from the same PlayerDashPtShots endpoint:

- **Shot clock analysis**: `ShotClockShooting` dataset -- voluntary vs forced shots by time remaining
- **Dribble-before-shot**: `DribbleShooting` dataset -- off-movement vs pull-up efficiency
- **Touch time**: `TouchTimeShooting` dataset -- rhythm shots vs slow possessions
- **Cross-player comparison**: batch endpoint for comparing shot quality profiles
