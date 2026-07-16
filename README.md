# AI-MajorRecommendation

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

Then open <https://ai-majorrecommendation.onrender.com/> in your browser.

## Demo Mode

The deployed version uses the Gemini API for real recommendations.

For local testing without an API key, the app can run in offline demo mode:

```bash
DEMO_MODE=1 python app.py
```

You can also add this setting to your local `.env` file:

```env
DEMO_MODE=1
```

To use live Gemini recommendations again, remove the variable or set:

```env
DEMO_MODE=0
```

Demo mode uses predefined sample recommendations and does not make API calls.

## Configuration

Set these variables in your `.env` file. See `.env.example` for placeholders.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes for live mode | None | Gemini API key used for live recommendations |
| `DEMO_MODE` | No | `0` | Set to `1` to force offline demo mode |
| `AUTO_DEMO_FALLBACK` | No | `1` | Automatically use demo mode when the Gemini API is unavailable |
| `GEMINI_MODEL` | No | Your configured model | Gemini model used by the app |
| `FLASK_SECRET_KEY` | Yes in production | Development fallback | Secret used to protect Flask sessions |

> Never place your real API key or Flask secret in the README or `.env.example`.

## Troubleshooting

### Gemini API error: `RESOURCE_EXHAUSTED` or `429`

This usually means the Gemini free-tier rate limit or daily quota was reached.

You can:

- Wait and try again later.
- Review your Gemini API usage limits.
- Let the app use its automatic demo fallback.
- Force demo mode locally with `DEMO_MODE=1`.

When `AUTO_DEMO_FALLBACK=1`, the app automatically serves sample recommendations if the Gemini API is temporarily unavailable.
```
AI-MajorRecommendation/
├── app.py                     # Flask web server (routes + session state)
├── requirements.txt
├── .env.example
├── templates/
│   └── index.html             # Single-page UI
├── static/
│   ├── css/style.css
│   └── js/app.js
└── src/
    ├── recommender.py         # Recommendation engine: one JSON call per turn
    ├── demo.py                # Offline demo engine (used when DEMO_MODE=1)
    └── utils.py               # Gemini client + shared config
```

## How it works

1. The student submits the profile form → `POST /api/start`.
2. `recommender.start_session()` sends the profile to Gemini and gets back trait
   scores, ranked major recommendations, a friendly message and a follow-up
   question — all as strict JSON.
3. Each answer → `POST /api/chat` → `recommender.refine_session()` updates the
   scores and recommendations until the advisor has enough information.

> Recommendations are guidance to explore, not a guarantee.
