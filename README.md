# NBA Shot Quality API

A backend API that computes context-adjusted shot quality for NBA players. Raw field goal percentage hides the real story -- this API separates good shooters taking bad shots from bad shooters taking good ones, then quantifies the difference.

Humanized: YES

## The core insight

A player shooting 38% from three looks mediocre on paper. But when you account for the fact that 60% of those attempts come with a defender less than two feet away, and their wide-open 3PT percentage is 44%, the problem isn't shooting ability. It's shot selection. That distinction only shows up when you condition on defender proximity.

The general model: start with raw events (shots), add contextual features (court zone, defender distance), compute expected outcomes, then compare actual results to expected. This pattern shows up across industries -- fintech uses it for fraud scoring, healthtech for patient risk, adtech for click prediction. Basketball happens to be the cleanest public dataset for building it because the ground truth (made or missed) is immediately verifiable.

## What it computes

**Value decomposition** -- the headline feature. For each player, the API decomposes scoring into two independent components:

- **Shooting Talent**: points above expected if a league-average shooter took the exact same shots. Isolates pure shooting ability.
- **Shot Selection**: points gained or lost from the player's shot distribution compared to how the rest of the league distributes their attempts. Isolates decision-making.

`Shooting Talent + Shot Selection = Total Points Above Average`

This is structurally identical to alpha decomposition in portfolio analysis (stock selection vs sector allocation) and is the same framework NBA teams pay Second Spectrum millions to access with full tracking data.

## Stack

- Python 3.11, FastAPI (async), uvicorn
- nba_api (free, no API key)
- pandas + pyarrow
- File-based parquet cache
- Pydantic response models
- pytest invariant tests
- GitHub Actions CI

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn main:app --reload
# Browser: http://localhost:8000 (interactive HTML demo)
# API docs: http://localhost:8000/docs
```

## API

### POST /api/player-analysis

```bash
curl -X POST http://localhost:8000/api/player-analysis \
  -H "Content-Type: application/json" \
  -d '{"player": "Stephen Curry", "season": "2024-25"}'
```

**Response** (real data, 2024-25 season):

```json
{
  "player": "Stephen Curry",
  "player_id": 201939,
  "season": "2024-25",
  "total_attempts": 1258,
  "zones": [
    {
      "zone": "Above the Break 3",
      "attempts": 693,
      "makes": 269,
      "fg_pct": 0.388,
      "league_avg": 0.353,
      "delta": "+3.5%"
    }
  ],
  "shot_quality": [
    {
      "range": "6+ Feet - Wide Open",
      "fga": 229,
      "fgm": 104,
      "fg_pct": 0.454,
      "pct_of_total": 0.182
    },
    {
      "range": "4-6 Feet - Open",
      "fga": 546,
      "fgm": 247,
      "fg_pct": 0.452,
      "pct_of_total": 0.434
    },
    {
      "range": "2-4 Feet - Tight",
      "fga": 425,
      "fgm": 184,
      "fg_pct": 0.433,
      "pct_of_total": 0.338
    },
    {
      "range": "0-2 Feet - Very Tight",
      "fga": 57,
      "fgm": 29,
      "fg_pct": 0.509,
      "pct_of_total": 0.045
    }
  ],
  "value_decomposition": {
    "shooting_talent_pts": 114.3,
    "shot_selection_pts": -40.6,
    "total_above_avg_pts": 73.7,
    "per_game": {
      "shooting_talent": 1.63,
      "shot_selection": -0.58,
      "total": 1.05
    },
    "actual_points": 1439,
    "expected_points": 1324.7,
    "games_played": 70
  },
  "summary": "Curry takes 62% of shots with 4+ feet of space. Converts at +1.6 pts/game above expected from shooting talent. Loses 0.6 from shot selection vs league-average distribution. Net: +1.1 pts/game above average."
}
```

### Reading Curry's numbers

Curry scored 1,439 points on 1,257 tracked shots in 2024-25. A league-average shooter taking those exact same shots would have scored 1,324.7 -- meaning Curry's pure shooting talent is worth **+114.3 points** over the season (+1.63/game).

But his shot distribution is slightly below average: he takes 43% of shots in the 4-6 foot range (defenders closing out) rather than the higher-value wide-open bucket. That costs him **-40.6 points** in shot selection compared to league average distribution.

Net: **+73.7 total points above average** (+1.05/game). The takeaway: Curry's entire value comes from making tough shots at absurd rates, not from getting easy looks.

### Response fields

**zones** (from ShotChartDetail):

| Field | Description |
|---|---|
| `zone` | Court zone (e.g. "Above the Break 3", "Restricted Area") |
| `fg_pct` / `league_avg` / `delta` | Player vs league efficiency by zone |

**shot_quality** (from PlayerDashPtShots tracking):

| Field | Description |
|---|---|
| `range` | Closest defender distance bucket |
| `fg_pct` | FG% at this defender proximity |
| `pct_of_total` | Share of all attempts -- the shot selection signal |

If a player shoots a large share in "Wide Open" zones they're getting good looks. If they're concentrated in "Very Tight" they're being forced into bad shots. The FG% gap between those buckets is the cost of shot selection.

**value_decomposition** (computed from tracking + league baselines):

| Field | Description |
|---|---|
| `shooting_talent_pts` | Season total points above expected (same shots, league-avg shooting) |
| `shot_selection_pts` | Points from player's distribution vs league-avg distribution |
| `total_above_avg_pts` | Talent + selection combined |
| `per_game` | All three values divided by games played |

`shot_quality` and `value_decomposition` are `null` for seasons where tracking data doesn't exist (pre-2013).

## Tests

```bash
pytest tests/ -v
```

Five invariant checks:
1. Zone attempt counts sum to total attempts
2. `fg_pct` = makes / attempts per zone (math integrity)
3. `get_player_id("Stephen Curry")` returns a valid positive int
4. Shot quality profile has all 4 defender distance ranges, `pct_of_total` sums to ~1.0
5. `shooting_talent + shot_selection = total_above_avg` (decomposition additivity)

## Architecture decisions

**Two data sources, not one.** ShotChartDetail provides per-shot zone data but nothing about defender proximity. PlayerDashPtShots provides defender distance breakdowns but only as pre-bucketed aggregates. The NBA stopped providing individual shot-level tracking data through its public API during the 2016-17 season. Combining both endpoints provides the fullest picture available from public data.

**File cache (parquet), not Redis.** Parquet is columnar, compressed, and only requires pyarrow as a dependency. After a player-season query hits the NBA API once, all subsequent requests read from disk in under 5ms. Redis would add operational overhead with no benefit at this scale.

**Invariant tests, not mocks.** Tests validate mathematical properties (zone totals sum correctly, FG% matches raw counts, decomposition is additive) instead of mocking API responses. Mock tests verify that your test setup matches your code. Invariant tests catch real computation bugs regardless of where the input data comes from.

**Async endpoints with concurrent fetching.** The API fetches three data sources (ShotChartDetail, PlayerDashPtShots, league averages) concurrently using asyncio. The NBA API client is synchronous, so calls run in a thread pool executor. This cuts cold-request latency roughly in half versus sequential fetching.

## What's next

All extensions use data already available from the same PlayerDashPtShots endpoint:

- **Shot clock analysis**: `ShotClockShooting` dataset -- voluntary vs forced shots by time remaining
- **Dribble-before-shot**: `DribbleShooting` dataset -- off-movement vs pull-up efficiency
- **Touch time**: `TouchTimeShooting` dataset -- rhythm shots vs slow possessions
- **Position-adjusted baselines**: compare against guards/forwards/centers instead of league-wide
