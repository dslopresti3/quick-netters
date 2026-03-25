# Quick Netters

Quick Netters is an NHL first-goal recommendation platform that combines model probabilities and live market odds into actionable betting insights.

Quick Netters helps you evaluate first-goal markets by surfacing three recommendation buckets per game—**Top 3 Plays**, **Best Bet**, and **Underdog Value Play**—with backend-calculated value metrics so you can quickly assess probability vs price.

## Key Features

- **Top 3 Plays** for each game (balanced blend of probability and value)
- **Best Bet** for each game (strongest strict value play)
- **Underdog Value Play** for each game (higher-odds positive-EV candidate when available)
- **Backend-computed betting metrics** in API responses:
  - `model_probability`
  - `market_odds`
  - `decimal_odds`
  - `implied_probability`
  - `edge`
  - `ev`

## Product Preview (Placeholders)

### Slate view

> Placeholder screenshot: daily slate listing games plus top recommendation context.

### Single-game recommendation view

> Placeholder screenshot: game detail with Top 3 Plays, Best Bet, and Underdog Value Play cards.


## How Recommendations Work

Quick Netters exposes three recommendation buckets per game:

1. **Top 3 Plays**
   - Ranked using a blended score of model confidence and value.
   - **Important:** Top 3 Plays are **not** simply the top model probabilities.
2. **Best Bet**
   - The strongest strict value play after tighter value filters.
3. **Underdog Value Play**
   - A higher-odds positive-value option (positive `edge` and positive `ev`).
   - May be `null` when no candidate qualifies.

## Architecture Overview

Quick Netters is a monorepo with clear frontend/backend separation:

- **Frontend (`apps/frontend`)**: Next.js app for browsing slate and game recommendations.
- **Backend (`apps/backend`)**: FastAPI API that fetches schedules/projections/odds and computes recommendations.
- **Modeling (`packages/modeling`)**: separate Python package for historical ingestion and model pipeline support.

### Backend vs Frontend responsibilities

- All betting math is computed in the backend, including:
  - `implied_probability`
  - `edge`
  - `ev`
- Frontend is display-only: it renders API outputs and does not calculate betting metrics.

## Monorepo Structure

```text
quick-netters/
├── apps/
│   ├── frontend/            # Next.js application
│   └── backend/             # FastAPI service
├── packages/
│   └── modeling/            # Modeling logic and pipelines
└── docs/                    # Product and technical documentation
```

### Workspace/package management note

- The Node workspace (`package.json` at repo root) manages the **frontend only**.
- The backend is managed separately with Python virtual environments and `requirements.txt`.

## Quick Start (Fast Path)

This is the shortest path to run the app locally.

### 1) Clone and enter repo

```bash
git clone <YOUR_REPO_URL>
cd quick-netters
```

### 2) Install frontend dependencies

```bash
npm install
```

### 3) Configure environment files

```bash
cp .env.example .env
cp apps/frontend/.env.example apps/frontend/.env.local
cp apps/backend/.env.example apps/backend/.env
```

### 4) Create backend virtual environment and install dependencies

```bash
cd apps/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ../..
```

### 5) Run backend

```bash
cd apps/backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend: http://localhost:8000
OpenAPI docs: http://localhost:8000/docs

### 6) Run frontend (new terminal)

```bash
cd quick-netters
npm run dev:frontend
```

Frontend: http://localhost:3000

## API Overview

Base URL (local): `http://localhost:8000`

- `GET /availability/date?date=YYYY-MM-DD`
- `GET /games?date=YYYY-MM-DD&timezone=America/New_York`
- `GET /recommendations/daily?date=YYYY-MM-DD`
- `GET /recommendations/game?game_id=...&date=YYYY-MM-DD&timezone=America/New_York`

Game recommendation responses include:

- `top_plays`
- `best_bet`
- `underdog_value_play` (nullable)

Compatibility note:

- `recommendations` is also returned and currently maps to `top_plays` for compatibility.

## Testing

### Backend tests

```bash
cd apps/backend
source .venv/bin/activate
python -m pytest tests
```

### Frontend lint

```bash
npm run lint:frontend
```

## Limitations

- Recommendations depend on external schedule, projection, and odds availability.
- `underdog_value_play` may be `null` on slates with no qualifying higher-odds positive-EV candidate.
- Placeholder screenshots are included; real product images can be added later.

## Roadmap

- Add real README screenshots/GIF walkthroughs.
- Publish a hosted demo link.
- Expand model and recommendation explainability in API docs.

## Additional Documentation

- `docs/odds-value-layer.md`
- `docs/historical-data-pipeline.md`
- `docs/first-goal-modeling-pipeline.md`
- `apps/backend/docs/date-availability-metadata.md`
