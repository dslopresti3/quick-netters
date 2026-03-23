# Quick Netters Monorepo

Initial scaffold for a mock-first tennis decision support platform.

## Monorepo structure

```text
quick-netters/
├── .env.example
├── apps/
│   ├── backend/               # FastAPI app with placeholder endpoints
│   │   ├── .env.example
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── api/routes.py
│   │       ├── services/
│   │       │   ├── interfaces.py
│   │       │   └── mock_services.py
│   │       └── utils/date_validation.py
│   └── frontend/              # Next.js app with mock components/pages
│       ├── .env.example
│       ├── app/
│       ├── components/
│       └── lib/
└── packages/
    └── modeling/              # Python package for future modeling workflows
```

## Local development setup

### 1) Prerequisites

- Node.js 20+
- Python 3.11+

### 2) Configure environment variables

Copy examples into local env files:

```bash
cp .env.example .env
cp apps/frontend/.env.example apps/frontend/.env.local
cp apps/backend/.env.example apps/backend/.env
```

### 3) Run frontend (Next.js)

```bash
cd apps/frontend
npm install
npm run dev
```

Open http://localhost:3000.

### 4) Run backend (FastAPI)

```bash
cd apps/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API available at http://localhost:8000 and docs at http://localhost:8000/docs.

## Notes

- No real external APIs are implemented yet.
- Schedule, projections, odds, and recommendations all use mock services/interfaces.
- Date input is validated: selected dates more than 1 day ahead are rejected with HTTP 422.
- PostgreSQL is planned and represented by `DATABASE_URL` examples only.
