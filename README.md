# Quick Netters

Quick Netters is an NHL first-goal recommendation app built as a monorepo. It combines model-generated player scoring probabilities with market odds to produce clear, game-level betting recommendations.

## Overview

For a selected UTC date, the platform:

1. fetches the NHL schedule,
2. loads first-goal projection candidates,
3. matches eligible players to market odds snapshots,
4. computes value metrics in the backend service layer,
5. returns recommendation buckets for each game.

## Feature Summary

- **API-backed slate and game detail views** (no hardcoded UI picks).
- **Single-game recommendation buckets**:
  - **Top 3 Plays**
  - **Best Bet**
  - **Underdog Value Play**
- **Date availability metadata** for frontend picker bounds and empty states.
- **Top projected scorer per team** shown on game cards/details.
- **Modeling package** for historical data prep and first-goal probability generation.

## Architecture at a Glance

| Layer | Location | Responsibility |
|---|---|---|
| Frontend | `apps/frontend` | Next.js UI for date selection, slate browsing, and game detail recommendations |
| Backend API | `apps/backend/app/api` | FastAPI routes for availability, games, daily recommendations, game recommendations |
| Recommendation Service | `apps/backend/app/services/recommendation_service.py` | Computes recommendation math and selects bucket outputs |
| Modeling Pipelines | `packages/modeling` | Historical ingestion + first-goal model pipeline support |
| Product/Tech Docs | `docs/` and `apps/backend/docs/` | Odds/value formulas, pipeline docs, API metadata contracts |

## Current Recommendation Logic

### Buckets

Quick Netters uses three distinct bucket outputs for single-game recommendations:

1. **Top 3 Plays**
   - Broader blended ranking of best overall candidates.
   - **Not** simply top 3 by raw model probability.
2. **Best Bet**
   - Strongest strict value play after tighter eligibility filters.
3. **Underdog Value Play**
   - Higher-odds positive-value option (positive edge + positive EV).
   - Can be `null` when no candidate qualifies.

### Recommendation Metrics

Each recommendation includes:

- `model_probability`
- `market_odds`
- `decimal_odds`
- `implied_probability`
- `edge`
- `ev`

Recommendation math and bucket selection are computed in `ValueRecommendationService` (backend/service layer).

## API Snapshot

Local backend base URL: `http://localhost:8000`

- `GET /availability/date?date=YYYY-MM-DD`
- `GET /games?date=YYYY-MM-DD&timezone=America/New_York`
- `GET /recommendations/daily?date=YYYY-MM-DD`
- `GET /recommendations/game?game_id=...&date=YYYY-MM-DD&timezone=America/New_York`

Single-game response shape includes:

- `top_plays`
- `best_bet`
- `underdog_value_play`

`recommendations` is still returned for compatibility and currently aligns with `top_plays`.

## Local Setup

### Prerequisites

- Node.js 20+
- Python 3.11+

### Environment Configuration

From repo root:

```bash
cp .env.example .env
cp apps/frontend/.env.example apps/frontend/.env.local
cp apps/backend/.env.example apps/backend/.env
```

## Run Locally

### Frontend (Next.js)

From repo root:

```bash
npm install
npm run dev:frontend
```

Alternative:

```bash
cd apps/frontend
npm install
npm run dev
```

Frontend: `http://localhost:3000`

### Backend (FastAPI)

```bash
cd apps/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend: `http://localhost:8000` (OpenAPI: `http://localhost:8000/docs`)

## Testing and Checks

### Backend Tests

```bash
cd apps/backend
source .venv/bin/activate
python -m pytest tests
```

If needed:

```bash
pip install pytest
```

### Frontend Lint

From repo root:

```bash
npm run lint:frontend
```

## Repository Structure

```text
quick-netters/
├── apps/
│   ├── backend/
│   │   ├── app/
│   │   └── docs/
│   └── frontend/
├── docs/
└── packages/
    └── modeling/
```

## Additional Documentation

- Odds and value layer: `docs/odds-value-layer.md`
- Historical data pipeline: `docs/historical-data-pipeline.md`
- First-goal modeling pipeline: `docs/first-goal-modeling-pipeline.md`
- Date availability contract: `apps/backend/docs/date-availability-metadata.md`

## Current Status

Active focus areas:

- stable API-backed recommendation delivery,
- consistent Top 3 / Best Bet / Underdog semantics,
- resilient data-availability signaling,
- iterative modeling pipeline improvements.
