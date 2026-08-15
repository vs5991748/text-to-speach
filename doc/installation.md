# Installation

## Requirements

- Python **3.12** (pinned via `.python-version`; `pydub` is not compatible with Python 3.13+)
- `ffmpeg` on your PATH (used by `pydub` to stitch audio clips)

---

## 1. Install ffmpeg

**macOS**
```bash
brew install ffmpeg
```

**Ubuntu / Debian**
```bash
sudo apt install ffmpeg
```

---

## 2. Create a virtual environment

```bash
cd /path/to/Text-to-speech
python3 -m venv venv
```

Activate it — you must do this in every new terminal session before running any project commands:

```bash
source venv/bin/activate   # macOS / Linux
# venv\Scripts\activate    # Windows
```

---

## 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` installs:

| Package | Purpose |
|---|---|
| `edge-tts` | Microsoft Edge neural TTS (no API key needed) |
| `pydub` | Audio stitching and MP3 export |
| `flask` | Web interface server |
| `python-dotenv` | Loads `.env` configuration at startup |
| `gunicorn` | Production WSGI server (used by Render and similar platforms) |

---

## 4. Configure the environment

Copy the example and edit it:

```bash
cp .env .env.local    # optional — .env is already usable as-is
```

At minimum, add your users before exposing the web interface to anyone:

```dotenv
# Superuser (no limits)
SU_USERS=yourname:a-strong-password

# Optional regular users
USERS=alice:alicepass
```

See [authorization.md](authorization.md) and [limits.md](limits.md) for all available settings.

---

## 5. Run the CLI

```bash
python generate_audio.py --input sentences.example.json --learning-lang ro
```

The output MP3 is written next to the input file (`sentences.example.mp3`) unless `--output` is specified.

---

## 6. Run the web interface

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser. The page will prompt for credentials if any users are configured in `SU_USERS` or `USERS` in `.env`.

To bind to a specific host or port:

```bash
# example: listen on all interfaces, port 8080
flask --app app run --host 0.0.0.0 --port 8080
```

> **Do not expose the server to the public internet without HTTPS** — Basic Auth sends credentials in base64, which is trivially decoded without TLS.

---

## 7. Deploy to Render (or similar)

The repo includes `.python-version` (3.12) and `gunicorn` in `requirements.txt`, so Render detects and runs it automatically.

Set environment variables in the Render dashboard (same keys as `.env`) — do **not** commit your real `.env` file.

Render's default start command:
```
gunicorn app:app
```

> The in-memory job store works fine on a single-worker instance. If you scale to multiple workers or instances, replace it with a shared store (Redis etc.).
