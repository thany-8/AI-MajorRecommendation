# AI-MajorRecommendation

[![CI](https://github.com/thany-8/AI-MajorRecommendation/actions/workflows/ci.yml/badge.svg)](https://github.com/thany-8/AI-MajorRecommendation/actions/workflows/ci.yml)
![Coverage](docs/coverage.svg)

**MajorMatch** is a web app that recommends the university majors a student is
most likely to enjoy and thrive in. Students describe their interests, hobbies
and strengths, get instant AI-powered major matches, and then refine the results
through a short chat-style Q&A with an AI advisor.

Powered by the Google Gemini API (free tier).

## Demo

![MajorMatch demo — filling the profile form, seeing ranked major matches, and refining them by chat](docs/demo.gif)

*A student describes their interests and hobbies, gets ranked major matches with
fit percentages, then refines the results by answering a few follow-up questions
from the AI advisor.*

## Features

- 🎨 **Visual web interface** – a profile form, ranked major cards with match
  percentages, an animated trait profile, and a refine-by-chat panel.
- 🧠 **AI recommendations** – majors are scored from the student's interests,
  hobbies, favourite subjects and strengths (not limited to a fixed list).
- 💬 **Refine with follow-up questions** – the advisor asks a few targeted
  questions and updates the recommendations live.
- 💾 **Remembers you** – profiles, past recommendation sessions and your
  "was this major helpful?" feedback are saved to a database (SQLite out of the
  box, or PostgreSQL), so returning visitors can revisit their earlier matches.
- 🔐 **Accounts** – optional email/password sign-up so your history **syncs
  across devices** (guest history is adopted when you register); write endpoints
  are protected against CSRF.
- ⚡ **Fast & resilient** – repeated profiles are served from an in-process
  cache (no repeat Gemini calls), per-user/session **rate limiting** protects
  the API, and **structured JSON logs**, request ids and a `/healthz` endpoint
  make it observable.
- 📊 **Grounded in real data** – recommendations are sanity-checked and gently
  re-ranked against a real U.S. Census / FiveThirtyEight majors dataset, and
  each card shows real **median earnings** and **employment rate**.

## Requirements

- Python 3.10+
- A free [Google Gemini API key](https://aistudio.google.com/apikey) (no billing required)

## Setup

```bash
# 1. Clone and enter the project
git clone https://github.com/thany-8/AI-MajorRecommendation.git
cd AI-MajorRecommendation

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your free Gemini API key
cp .env.example .env
# then open .env and set GEMINI_API_KEY=...
```

## Run the web app

```bash
python app.py
```

Then open <http://127.0.0.1:5000> in your browser. A live deployment is also
available at <https://ai-majorrecommendation.onrender.com/>.

### Run without an API key (demo mode)

No API key yet? Run the app in free offline **demo mode**, which serves
realistic canned recommendations with no API calls:

```bash
DEMO_MODE=1 python app.py
```

(or set `DEMO_MODE=1` in your `.env`). Great for exploring the UI or presenting
the app. Switch back to real recommendations by removing it / setting `DEMO_MODE=0`.

## Configuration

Set these in your `.env` file (see `.env.example`):

| Variable            | Required | Default        | Description                                            |
| ------------------- | -------- | -------------- | ------------------------------------------------------ |
| `GEMINI_API_KEY`     | yes\* | –                  | Your free Gemini API key (\*not needed in demo mode).          |
| `DEMO_MODE`          | no    | `0`                | Set to `1` to run free offline demo mode (no API key).         |
| `AUTO_DEMO_FALLBACK` | no    | `1`                | Auto-switch to demo mode if Gemini is rate-limited/over quota. |
| `GEMINI_MODEL`       | no    | `gemini-3.5-flash` | Gemini model used for recommendations.                         |
| `DATABASE_URL`       | no    | SQLite file        | Where to store profiles, sessions & feedback (see below).      |
| `FLASK_SECRET_KEY`   | no    | dev fallback       | Secret used to sign session cookies.                           |
| `CSRF_ENABLED`       | no    | `1`                | CSRF protection on state-changing API requests.                |
| `CACHE_ENABLED` / `CACHE_TTL` / `CACHE_MAXSIZE` | no | `1` / `3600` / `512` | In-process cache of initial recommendations.        |
| `RATELIMIT_ENABLED` / `RATELIMIT_START` / `RATELIMIT_CHAT` | no | `1` / `15 per minute` / `40 per minute` | Per-user/session API rate limits. |
| `RATELIMIT_STORAGE_URI` | no | `memory://`     | Rate-limit counter store (use `redis://…` for multi-process).  |
| `LOG_LEVEL` / `LOG_FORMAT` | no | `INFO` / `json` | Log verbosity and format (`json` or `plain`).                  |
| `DATASET_ENABLED`    | no    | `1`                | Ground recommendations in `data/majors.json` (see below).      |
| `SENTRY_DSN`         | no    | –                  | Enable Sentry error monitoring (needs `pip install sentry-sdk`). |

### Data storage

Profiles, past recommendation sessions and "was this major helpful?" feedback
are persisted so returning visitors see their earlier matches.

- **SQLite (default):** no setup — a database file is created automatically at
  `instance/majormatch.db`.
- **PostgreSQL:** set `DATABASE_URL`, e.g.
  `DATABASE_URL=postgresql://user:password@localhost:5432/majormatch`.
  The bundled `psycopg2-binary` driver handles the connection; tables are
  created automatically on first run.

Persistence is best-effort: if the database can't be reached, the app logs a
warning and keeps working (feedback/history features are simply disabled).

## Performance & operations

- **Caching** – the initial recommendation for a profile is cached in-process
  (`src/cache.py`), keyed by a normalised form of the profile, so repeated or
  effectively-identical submissions don't re-hit Gemini. Configure with
  `CACHE_ENABLED` / `CACHE_TTL` / `CACHE_MAXSIZE`. Demo-mode and quota-fallback
  results are never cached.
- **Rate limiting** – [Flask-Limiter](https://flask-limiter.readthedocs.io/)
  applies per-user/session limits (keyed by the visitor's cookie token, falling
  back to IP). Exceeding a limit returns **429** with a JSON error. Counters use
  in-memory storage by default; set `RATELIMIT_STORAGE_URI=redis://…` for a
  multi-process deployment.
- **Structured logging** – one JSON object per log line (`LOG_FORMAT=plain` for
  human-readable output), each request tagged with an id that is echoed back as
  the `X-Request-ID` header for tracing.
- **Error monitoring** – unhandled exceptions are logged with a traceback and
  returned as a clean JSON `500`. Set `SENTRY_DSN` (and `pip install sentry-sdk`)
  to forward errors to Sentry.
- **Health check** – `GET /healthz` returns status plus a metrics, cache and
  config snapshot (handy for load balancers and dashboards).

## Data-driven grounding

The model's recommendations are cross-checked against a **real dataset** of
college majors so they aren't taken purely on trust:

- **Sanity-check** – each recommended major is matched (exact → synonym → fuzzy
  → field-category) against the dataset. Majors that match nothing (e.g. an
  invented or mis-named major) are flagged (`data.grounded = false`) and logged.
- **Gentle re-rank** – grounded majors keep their score while weaker/unmatched
  ones are mildly demoted, so well-established majors float up.
- **Real numbers on every card** – each recommendation carries real **median
  earnings** and **employment rate**, shown in the UI and returned in the API
  (`recommendation.data`).

The dataset lives in `data/majors.json` and is (re)built from source with:

```bash
python scripts/build_major_dataset.py
```

**Data source:** [FiveThirtyEight "College Majors"](https://github.com/fivethirtyeight/data/tree/master/college-majors),
derived from the U.S. Census Bureau's American Community Survey (ACS) PUMS
(public domain; FiveThirtyEight's compilation is CC BY 4.0).

## Tests & linting

The test-suite uses **pytest** and mocks every Gemini call, so it runs fast and
offline (no API key required):

```bash
pip install -r requirements-dev.txt
pytest
```

This runs unit tests for `src/recommender.py` and `src/utils.py` and integration
tests for the Flask routes (via Flask's test client), and prints a coverage
report. To refresh the coverage badge in `docs/coverage.svg`:

```bash
pytest
python scripts/make_coverage_badge.py
```

Linting uses **[ruff](https://docs.astral.sh/ruff/)** (configured in
`ruff.toml`):

```bash
ruff check .          # report issues
ruff check --fix .    # auto-fix what it can
```

Continuous integration (`.github/workflows/ci.yml`) runs both **ruff** and the
**pytest** suite on every push and pull request.

## Troubleshooting

**`Gemini API error ... RESOURCE_EXHAUSTED` (429)** — you've hit the free-tier
rate limit or daily quota. Wait a minute and retry, check your limits at
[aistudio.google.com](https://aistudio.google.com/apikey), or rely on the
built-in demo fallback (`AUTO_DEMO_FALLBACK=1`, on by default) that serves free
demo results automatically. You can also force demo mode with `DEMO_MODE=1`.

## Architecture

```mermaid
flowchart TD
    Browser["Browser SPA<br/>(index.html + app.js)"]

    subgraph Flask["Flask app - app.py + flask-openapi3"]
        direction TB
        Limiter["Rate limiting<br/>Flask-Limiter (per user/session)"]
        Routes["Validated /api/v1 routes<br/>Pydantic schemas → OpenAPI + Swagger"]
        Obs["Structured logging · metrics · errors<br/>(observability.py)"]
        Limiter --> Routes
        Routes -.-> Obs
    end

    Browser -->|"JSON / HTTPS"| Limiter

    Routes --> Rec["Recommendation engine<br/>(recommender.py)"]
    Rec -->|"1 · cache lookup"| Cache["Profile cache<br/>(cache.py — TTL, in-process)"]
    Rec -->|"2 · LLM call"| Gemini["Google Gemini API"]
    Gemini -.->|"quota / rate-limit"| Demo["Offline demo engine<br/>(demo.py · AUTO_DEMO_FALLBACK)"]
    Rec -->|"3 · ground + re-rank"| Data["Real-data grounding<br/>(dataset.py + data/majors.json)"]

    Routes --> DB[("Profiles · sessions · feedback<br/>SQLite / PostgreSQL (database.py)")]
    Obs --> Health["GET /healthz"]
```

At a glance: the browser talks only to the versioned JSON API. Every request
passes through **rate limiting** and **structured logging**, is **validated** by
Pydantic, and is handled by the **recommendation engine**, which (1) checks the
**profile cache**, (2) calls **Gemini** — degrading to the **offline demo
engine** on quota errors — and (3) **grounds and re-ranks** the result against a
**real majors dataset**. Profiles, sessions and feedback are persisted (SQLite
or Postgres), and `/healthz` exposes metrics, cache and dataset status.

## Project structure

```
AI-MajorRecommendation/
├── app.py                     # OpenAPI app: SPA route + versioned JSON API (/api/v1)
├── requirements.txt
├── requirements-dev.txt       # Test/dev dependencies (pytest, coverage, ruff)
├── pytest.ini                 # Pytest + coverage configuration
├── ruff.toml                  # Ruff linter configuration
├── .env.example
├── .github/workflows/ci.yml   # CI: runs the test-suite on push/PR
├── scripts/
│   ├── make_coverage_badge.py # Regenerates docs/coverage.svg from coverage data
│   └── build_major_dataset.py # Pulls the real majors dataset into data/majors.json
├── data/
│   └── majors.json            # Real college-majors data (Census ACS / FiveThirtyEight)
├── templates/
│   └── index.html             # Single-page UI
├── static/
│   ├── css/style.css
│   └── js/app.js
├── tests/                     # Pytest unit + integration tests (Gemini mocked)
│   ├── conftest.py
│   ├── test_utils.py
│   ├── test_recommender.py
│   ├── test_cache.py
│   ├── test_dataset.py
│   ├── test_observability.py
│   ├── test_auth.py
│   └── test_app.py
└── src/
    ├── recommender.py         # Recommendation engine: one JSON call per turn
    ├── demo.py                # Offline demo engine (used when DEMO_MODE=1)
    ├── database.py            # Persistence: profiles, sessions & feedback (SQLite/Postgres)
    ├── cache.py               # In-process cache of initial recommendations
    ├── dataset.py             # Real-data grounding: sanity-check & re-rank majors
    ├── observability.py       # Structured logging, metrics & error handling
    ├── schemas.py             # Pydantic request/response models (validation + OpenAPI docs)
    └── utils.py               # Gemini client + shared config
```

## API

The browser talks to a **versioned JSON API** under `/api/v1`, described by an
OpenAPI 3 specification and browsable with **Swagger UI**:

| Method & path             | Description                                           |
| ------------------------- | ----------------------------------------------------- |
| `POST /api/v1/start`      | Start a session from the profile form.               |
| `POST /api/v1/chat`       | Refine the recommendation with the student's answer. |
| `POST /api/v1/feedback`   | Record "was this major helpful?" feedback.           |
| `GET  /api/v1/history`    | List the current user's past sessions.               |
| `GET  /api/v1/auth/me`    | Current auth state + CSRF token.                     |
| `POST /api/v1/auth/register` | Create an account (adopts guest history).         |
| `POST /api/v1/auth/login`    | Sign in.                                          |
| `POST /api/v1/auth/logout`   | Sign out.                                         |

Interactive documentation (with request/response schemas and "Try it out"),
once the app is running:

- **Swagger UI:** <http://127.0.0.1:5000/api/docs/swagger>
- **OpenAPI spec:** <http://127.0.0.1:5000/api/docs/openapi.json>

Requests are validated against [Pydantic](https://docs.pydantic.dev/) models in
`src/schemas.py`. A malformed body returns **422** with an
`{ "error", "details" }` envelope; semantic problems (e.g. an expired session or
unknown feedback target) return **400/404**.

### Accounts & CSRF

Accounts are optional email/password (server-side sessions, passwords hashed
with Werkzeug PBKDF2). Registering while browsing as a guest **adopts** that
guest's saved history, so signing in on another device shows the same sessions.

State-changing API requests (all `POST`s) are protected with a **double-submit
CSRF token**: the token is issued in the session, exposed via a `<meta>` tag and
`GET /api/v1/auth/me`, and must be echoed in the `X-CSRFToken` header. The SPA
does this automatically; programmatic clients should read the token first.

## How it works

1. The student submits the profile form → `POST /api/v1/start`.
2. `recommender.start_session()` sends the profile to Gemini and gets back trait
   scores, ranked major recommendations, a friendly message and a follow-up
   question — all as strict JSON. The profile and new session are saved via
   `database.record_start()`.
3. Each answer → `POST /api/v1/chat` → `recommender.refine_session()` updates the
   scores and recommendations (and the stored session) until the advisor has
   enough information.
4. When done, the student can rate each major (`POST /api/v1/feedback`), and
   returning visitors see their past sessions (`GET /api/v1/history`).

> Recommendations are guidance to explore, not a guarantee.

## Design decisions

- **Why Flask?** The app is a small server-rendered shell plus a handful of JSON
  endpoints and one blocking external call. Flask keeps that footprint tiny and
  its ecosystem carried the weight — `flask-openapi3` adds FastAPI-style Pydantic
  validation and auto-generated OpenAPI/Swagger *without* a rewrite, and
  `Flask-Limiter` / signed-cookie sessions dropped straight in. Django was more
  framework than a single-model app needs; FastAPI's async model would add
  concurrency overhead for no real gain, since the Gemini SDK call is synchronous.
- **Why this fallback strategy?** The free Gemini tier regularly hits
  quota/rate limits. Instead of surfacing errors, the engine distinguishes a
  `CapacityError` from other failures and, only for capacity, degrades to a
  deterministic **offline demo engine** (`AUTO_DEMO_FALLBACK`). This keeps the app
  always demoable (no key needed), keeps CI/tests offline and fast, and stays
  honest — fallback results are labelled and **never cached**, so real
  recommendations return the moment quota recovers.
- **Why one strict-JSON call per turn?** Each turn is a single request that must
  return strict JSON, which is then validated and normalised. That avoids fragile
  string parsing (and the original skeleton's `eval`), keeps a predictable shape
  for the UI, and makes the model easy to mock in tests.
- **Why grounding on outcomes data?** A cheap, real, public dataset (U.S. Census
  ACS via FiveThirtyEight) is enough to **catch hallucinated/mis-named majors**
  and attach concrete numbers. The re-rank is deliberately gentle so the model's
  personality-fit stays the primary signal — data is a sanity check, not the boss.
- **Why in-process cache & rate-limit stores?** Zero-config and correct for a
  single worker, behind small interfaces so a multi-process deployment can swap in
  Redis via `RATELIMIT_STORAGE_URI` without touching call sites.
- **Why SQLite by default (Postgres optional)?** Local dev needs no setup; the
  same SQLAlchemy code runs on Postgres via `DATABASE_URL`. Persistence is
  **best-effort** — a database outage disables history/feedback but never breaks
  the core recommendation flow.
- **Why session auth + double-submit CSRF?** The app already uses signed,
  `HttpOnly`, `SameSite=Lax` session cookies, so server-side sessions are the
  natural fit (no token storage in JS). Passwords are hashed with Werkzeug
  PBKDF2 — no extra dependency. CSRF uses a hand-rolled double-submit token
  (issued in the session, echoed in `X-CSRFToken`) rather than pulling in
  Flask-WTF/WTForms just for one check.

## What I'd do with more time

- **Scale out state:** move the cache, rate-limit counters and in-memory
  conversation store to **Redis** so the app runs across multiple workers/hosts.
- **Smarter caching:** an **embeddings-based** semantic cache so genuinely
  *similar* profiles (not just normalised-identical ones) reuse results.
- **Richer grounding:** add **O*NET** interest/skill profiles for a personality-
  *fit* re-rank to complement outcomes, and a fresher, major-complete dataset
  (e.g. College Scorecard via CIP codes); show earnings ranges (P25–P75).
- **Accounts polish:** build on the new email/password accounts with social
  login (OAuth), email verification and password reset.
- **Quality harness:** a set of golden profiles with regression tests on
  recommendation quality to catch prompt/model drift over time.
- **Delivery:** containerise, add a CI/CD deploy (Fly/Render) with a Gunicorn
  config and managed secrets, and wire up Sentry in production.
- **UX polish:** streaming responses, a full accessibility/mobile pass, and
  internationalisation.
