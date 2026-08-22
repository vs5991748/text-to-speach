# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this project is

Language Listening Track Generator — turns a list of sentence pairs (learning
language + translation) into an MP3 listening track for language practice.
Each pair: the learning-language sentence is spoken (optionally at multiple
speeds/repetitions), then the translation, with configurable pauses between.
Works for any language pair Edge TTS has voices for.

Speech synthesis uses [Edge TTS](https://github.com/rany2/edge-tts)
(Microsoft's free neural voices, no API key required).

There are two interfaces to the same core logic:
- **CLI** (`generate_audio.py`) — reads a local file, writes an MP3/ZIP to disk.
- **Web app** (`app.py`, Flask) — upload/enter/AI-generate sentence pairs in
  the browser, with auth, rate limits, and an optional LLM-backed phrase
  generator.

## Repo layout

| Path | Purpose |
|---|---|
| `generate_audio.py` | Main CLI tool — reads sentence pairs, builds the audio track |
| `tts_engines.py` | Edge TTS wrapper (speed control, mp3 output, `LANG_VOICES` defaults) |
| `app.py` | Flask web interface — routes, auth, rate limiting, job handling, LLM phrase generation |
| `google_drive.py` | Google Drive OAuth + upload helpers (see `doc/google-drive.md`) |
| `templates/index.html` | Web UI (single-page form) |
| `prompts/grammatical_forms/<lang>.txt`, `prompts/noun_forms/<lang>.txt` | Per-language clarifying instructions for the "Show grammatical forms" / "Noun forms" AI-generator options (see `doc/llm.md`) |
| `.env.example` | Template for runtime configuration (copy to `.env`) |
| `sentences.example*.{json,csv}` | Example input files (Romanian/English, English/Ukrainian) |
| `requirements.txt` | Python dependencies |
| `.python-version` | Pins Python to 3.12 (`pydub` is not compatible with 3.13+) |
| `Procfile`, `gunicorn.conf.py` | Production deployment (Render or similar) via gunicorn |
| `doc/general.md` | Concepts, both interfaces, input format, supported languages |
| `doc/installation.md` | Setup, running CLI/web, deploying to Render |
| `doc/authorization.md` | HTTP Basic Auth, `SU_USERS`/`USERS` roles |
| `doc/limits.md` | All rate/row/timeout limits, env vars, examples |
| `doc/llm.md` | LLM provider config for the AI phrase generator |
| `doc/google-drive.md` | Google Drive upload: how it works, env vars, token storage |
| `doc/google-cloud-setup.md` | Step-by-step Google Cloud Console registration (Client ID/Secret) |
| `doc/examples.md` | Worked CLI and web-UI examples |

Read the relevant `doc/*.md` file before changing behavior in that area —
they are the source of truth for documented behavior and env var defaults.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Requires `ffmpeg` on PATH (used by `pydub`). Requires Python 3.12 specifically.

Activate the venv in every new shell before running project commands.

## Running

```bash
# CLI
python generate_audio.py --input sentences.example.json --learning-lang ro

# Web app
python app.py
# → http://localhost:5000
```

No `.env` present in a fresh checkout beyond `.env.example` — copy it to
`.env` and configure before running the web app for real use. Without any
users configured (`SU_USERS`/`USERS` both empty), the server treats every
request as an unauthenticated superuser and prints a startup warning — fine
for local dev, never for a public-facing deployment.

## Testing

There is no automated test suite in this repo. Verify changes manually:
- CLI: run `generate_audio.py` against the example input files and confirm
  the resulting MP3/ZIP is produced and sounds correct.
- Web app: start `python app.py`, exercise the affected flow in a browser
  (upload / manual entry / AI generator / split mode as relevant), and check
  both a superuser and a regular-user account if the change touches auth or
  limits.

## Key conventions and gotchas

- **Input format**: sentence pairs are keyed by language code (e.g. `ro`,
  `en`, `uk`), not by role (`source`/`target`). `--learning-lang` (CLI) or
  the learning-language field (web) determines which column is spoken first;
  the other key present is treated as the translation automatically.
- **Default voices** live in `tts_engines.py`'s `LANG_VOICES` dict. Add a
  language there, or pass `--voice LANG=VOICE_ID` (CLI) / a voice override
  (web) for anything not listed.
- **Limits** (`MAX_ROWS`, `MAX_STRING_LENGTH`, `MAX_ROWS_PER_WINDOW`,
  `RATE_LIMIT_REQUESTS`, `GENERATION_TIMEOUT_SECONDS`,
  `GENERATION_COOLDOWN_SECONDS`, `LLM_SUGGEST_COOLDOWN_SECONDS`) apply only
  to regular users (`USERS`) in the web app; superusers (`SU_USERS`) bypass
  all of them. The CLI has no enforced limits. Setting a numeric limit to `0`
  disables it; leaving it blank keeps the built-in default.
- **Auth**: HTTP Basic Auth on every web request, compared with
  `secrets.compare_digest` to avoid timing attacks. If a username appears in
  both `USERS` and `SU_USERS`, the `SU_USERS` entry wins.
- **LLM phrase generation**: all providers (OpenRouter, Groq, Ollama, or any
  custom OpenAI-compatible endpoint) go through the same
  `/v1/chat/completions`-shaped call. Provider is resolved per role
  (`LLM_USER_<USERNAME>` → `LLM_SU_DEFAULT` → `LLM_DEFAULT`), not per
  username directly. `LLM_MAX_TOKENS` is a *floor*; actual tokens sent scale
  as `max(LLM_MAX_TOKENS, count × 200)` — reasoning/thinking models need a
  higher floor to survive their internal reasoning overhead.
- **Prompt options** for the AI phrase generator (tenses, negative/mixed,
  questions, grammatical forms, register, reflexive form, custom
  instruction) live in the prompt-building logic in `app.py`. "One sentence
  per tense" and "Show grammatical forms" force `count=0` (LLM decides
  quantity) and hide the count input client-side.
- **Split mode** (`--split` / "One file per record") produces a ZIP of one
  MP3 per sentence pair instead of a single combined track; the ZIP is
  rebuilt per request.
- **Deployment**: the web app's in-memory job store assumes a single
  gunicorn worker (see `gunicorn.conf.py`, `Procfile`). Scaling to multiple
  workers/instances requires swapping in a shared store (e.g. Redis).
- **Google Drive upload** (`google_drive.py`, optional — blank
  `GOOGLE_CLIENT_ID`/`SECRET`/`REDIRECT_URI` disables it): each web-app
  user connects their own Google account (`drive.file` scope — the app can
  only create/manage files it created itself). Per-user refresh tokens
  persist to `.google_tokens.json` (never committed), which carries the
  same single-worker/single-machine assumption as the in-memory stores
  above. See `doc/google-drive.md`, and `doc/google-cloud-setup.md` for the
  Google Cloud Console registration steps.
- Never commit a real `.env` (or `.google_tokens.json`) with credentials or
  API keys — only `.env.example` should be tracked.

## Anti-Patterns (Forbidden)

- ❌ **YAGNI violations (You Aren't Gonna Need It)**: Don't add functionality
  until it's actually needed.
  - No "just in case" features, configurations, or abstractions.
  - No future-proofing for hypothetical requirements.
  - No generic solutions when a specific one solves the current problem.
- ❌ **Hardcoded credentials or endpoints**: All secrets and URLs must come
  from environment variables (see `.env.example`), never literals in code.
- ❌ **Swallowing exceptions silently**: Log all exceptions.
- ❌ **Logging sensitive payment data**.
