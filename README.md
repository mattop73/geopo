# Geopo — Geopolitics KPI Dashboard

Local-only dashboard that aggregates:

- **Commodities** — real-time prices + interactive charts (Yahoo Finance via `yfinance`)
- **News** — geopolitical headlines from GDELT, RSS feeds, NewsData.io, NewsAPI, The Guardian, New York Times
- **Polymarket** — prediction-market prices with anomaly detection
- **LLM Analysis** — Anthropic Claude, OpenAI GPT, or local Ollama models, with live dashboard data injected as context

## Architecture

```
React + Vite (5173)  ◄──REST/SSE──►  FastAPI (8000)  ──►  yfinance
                                                     ──►  GDELT / RSS / NewsData.io / NewsAPI / Guardian / NYT
                                                     ──►  Polymarket Gamma API
                                                     ──►  Anthropic / OpenAI / Ollama
                                                     │
                                                     ▼
                                                  SQLite
```

- Backend: FastAPI + SQLAlchemy (async) + APScheduler
- Frontend: React + Vite + Tailwind + lightweight-charts + React Query
- Storage: SQLite (`backend/geopo.db`)

## Setup

### 1. Install backend deps

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Install frontend deps

```bash
cd frontend
npm install
```

### 3. Configure API keys

```bash
cp .env.example .env
# edit .env and add your keys (all optional, but news needs at least one source)
```

Free news sources:
- GDELT: no key needed
- RSS feeds: no key needed; configure `NEWS_RSS_FEEDS` as comma-separated URLs
- NewsData.io: <https://newsdata.io/register>
- NewsAPI: <https://newsapi.org/register>
- Guardian: <https://open-platform.theguardian.com/access/>
- NYT: <https://developer.nytimes.com/get-started>
- Polymarket: no key needed
- Anthropic / OpenAI: from their respective consoles
- Ollama: install from <https://ollama.com>, then `ollama pull llama3.2`

### 4. Run

```bash
./start.sh
```

Then open <http://localhost:5173>.

## Project Layout

```
geopo/
├── backend/
│   ├── main.py               # FastAPI app + lifespan
│   ├── config.py             # env-based settings
│   ├── database.py           # SQLAlchemy async engine
│   ├── scheduler.py          # APScheduler periodic jobs
│   ├── models/               # SQLAlchemy models
│   ├── services/             # data fetching + business logic
│   │   ├── commodity_service.py
│   │   ├── news_service.py
│   │   ├── polymarket_service.py
│   │   └── llm_service.py    # multi-provider router
│   └── routers/              # FastAPI endpoints
├── frontend/
│   └── src/
│       ├── App.tsx
│       └── components/
│           ├── commodities/   # KPI grid + TradingView chart
│           ├── news/          # source-filtered article grid
│           ├── polymarket/    # markets with anomaly highlights
│           └── llm/           # streaming chat w/ context injection
├── .env.example
└── start.sh
```

## API

| Endpoint | Description |
|---|---|
| `GET /api/commodities/` | Latest prices for all tracked tickers |
| `POST /api/commodities/refresh` | Force-fetch from Yahoo Finance |
| `GET /api/commodities/{ticker}/history?period=3mo&interval=1d` | OHLCV history |
| `GET /api/news/?limit=60&source=Reuters` | Latest geopolitics news |
| `POST /api/news/refresh` | Force-fetch from all news APIs |
| `GET /api/polymarket/?anomalies_only=true` | Latest markets |
| `POST /api/polymarket/refresh` | Force-fetch from Polymarket |
| `GET /api/polymarket/{condition_id}/history` | Snapshot history |
| `GET /api/llm/models` | Available LLM models |
| `POST /api/llm/analyze` | Stream LLM response (auto-injects live data) |

Full OpenAPI docs at <http://localhost:8000/docs>.

## Anomaly Detection (Polymarket)

A market is flagged when:
- YES price moved ≥10% since the last snapshot
- 24h volume exceeds $50k

Both rules are tunable in `backend/services/polymarket_service.py`.

## Notes

- `yfinance` is unofficial and may rate-limit; commodity refresh defaults to 5 min.
- GDELT and RSS require no keys. NewsData.io, NewsAPI, Guardian, and NYT are optional free-tier enrichments.
- Polymarket Gamma API is public; no auth needed.
- LLM context injection adds ~1k tokens per request — keep that in mind for paid APIs.
