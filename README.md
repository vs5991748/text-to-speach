# Language Listening Track Generator

Turns a list of sentence pairs into a single MP3 listening track: the
sentence in the language you're learning is spoken (at whatever speed and
however many times you want), then its translation, with pauses between —
good for listen-and-repeat language practice. Works for any language pair
Edge TTS has voices for — e.g. Romanian↔English, English↔Ukrainian.

Uses [Edge TTS](https://github.com/rany2/edge-tts) (Microsoft's free neural
voices, no API key required) for natural-sounding speech.

## Documentation

| Topic | File |
|---|---|
| General information & concepts | [doc/general.md](doc/general.md) |
| Installation & setup | [doc/installation.md](doc/installation.md) |
| Web authentication | [doc/authorization.md](doc/authorization.md) |
| Rate limits & quotas | [doc/limits.md](doc/limits.md) |
| LLM / AI phrase generation | [doc/llm.md](doc/llm.md) |
| Google Drive upload | [doc/google-drive.md](doc/google-drive.md) |
| Google Cloud Console registration (Client ID/Secret) | [doc/google-cloud-setup.md](doc/google-cloud-setup.md) |
| Examples | [doc/examples.md](doc/examples.md) |

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Also requires `ffmpeg` on your PATH (used by `pydub` to stitch clips together):

```bash
brew install ffmpeg
```

> Every command below assumes the venv is activated in your current shell
> (`source venv/bin/activate`). If you open a new terminal tab/window, you'll
> need to activate it again there too — otherwise you'll see errors like
> `command not found: edge-tts` or `ModuleNotFoundError`.

## Usage

```bash
source venv/bin/activate
python generate_audio.py --input sentences.example.json --learning-lang ro
```

`--learning-lang` is the one required flag: it tells the tool which language
in the file is the one you're learning (spoken first, repeated, sped up).
The other language present in the file is treated as the translation
automatically — no need to name it separately.

Since `--output` was omitted, this writes `sentences.example.mp3` (same name
as the input file, `.mp3` extension) next to it. Pass `--output` to write
somewhere else instead:

```bash
python generate_audio.py --input sentences.example.json --learning-lang ro --output lesson.mp3
```

Same idea for English→Ukrainian:

```bash
python generate_audio.py --input sentences.example.en-uk.json --learning-lang en
```

## Input file format

Provide sentence pairs as either JSON or CSV, with each language keyed by its
code (e.g. `ro`, `en`, `uk`) rather than by role — that's what `--learning-lang`
is for.

**JSON** — a list of objects, each with exactly two language-code keys:

```json
[
  { "ro": "Bună dimineața!", "en": "Good morning!" },
  { "ro": "Cum te simți astăzi?", "en": "How are you feeling today?" }
]
```

See [sentences.example.json](sentences.example.json) (Romanian/English) and
[sentences.example.en-uk.json](sentences.example.en-uk.json) (English/Ukrainian).

**CSV** — two columns, header row required (the header cells are the
language codes):

```csv
ro,en
Bună dimineața!,Good morning!
Cum te simți astăzi?,How are you feeling today?
```

Quote any field that contains a comma. See
[sentences.example.csv](sentences.example.csv) (Romanian/English) and
[sentences.example.en-uk.csv](sentences.example.en-uk.csv) (English/Ukrainian).

## Options

| Flag | Default | Description |
|---|---|---|
| `--input` | *(required)* | Path to a `.json` or `.csv` file of sentence pairs |
| `--learning-lang` | *(required)* | Language code (must match a key in `--input`) that you're learning. It goes first and gets repeated/sped up; the other language in the file becomes the translation. |
| `--output` | same path/name as `--input`, `.mp3` or `.zip` depending on `--split` | Output file path |
| `--voice` | *(none — falls back to language defaults)* | Override the voice for a language, `LANG=VOICE_ID`. Repeatable, e.g. `--voice uk=uk-UA-OstapNeural --voice en=en-US-GuyNeural`. |
| `--target-speeds` | `0.85` | One or more speed multipliers, space-separated. The learning-language sentence repeats once per value, at that exact speed, in order. `1.0` = normal speed, `0.8` = 20% slower. |
| `--pause-after-target` | `1.0` | Seconds of silence after each learning-language repetition |
| `--pause-after-translation` | `1.5` | Seconds of silence after the translation, before the next pair |
| `--no-translation` | off | Skip the translation audio entirely (learning language only) |
| `--split` | off | Write one MP3 per sentence pair and collect them in a ZIP archive instead of one combined track |

### Supported languages out of the box

Default voices, used unless overridden with `--voice`:

| Code | Language | Default voice |
|---|---|---|
| `ro` | Romanian | `ro-RO-EmilNeural` |
| `en` | English | `en-US-AriaNeural` |
| `uk` | Ukrainian | `uk-UA-PolinaNeural` |
| `ru` | Russian | `ru-RU-SvetlanaNeural` |
| `pl` | Polish | `pl-PL-ZofiaNeural` |
| `pt` | Portuguese | `pt-BR-FranciscaNeural` |

These live in [`tts_engines.py`](tts_engines.py)'s `LANG_VOICES` dict — add a
language there, or just pass `--voice <code>=<voice-id>` for anything not
listed (run `edge-tts --list-voices` to browse options).

### `--target-speeds` examples

Say each sentence once, slowed down:

```bash
python generate_audio.py --input sentences.example.json --learning-lang ro --target-speeds 0.7
```

Say each sentence three times, ramping from slow to normal speed — useful for
gradually training your ear:

```bash
python generate_audio.py --input sentences.example.json --learning-lang ro --target-speeds 0.6 0.8 1.0
```

### Changing voices

List available Edge TTS voices for a language, e.g. Ukrainian:

```bash
edge-tts --list-voices | grep uk-UA
```

Then override it:

```bash
python generate_audio.py --input sentences.example.en-uk.json --learning-lang en --voice uk=uk-UA-OstapNeural
```

## Files

| File | Purpose |
|---|---|
| `generate_audio.py` | Main CLI tool — reads sentence pairs, builds the audio track |
| `tts_engines.py` | Edge TTS wrapper (speed control, mp3 output, `LANG_VOICES` defaults) |
| `app.py` | Flask web interface |
| `google_drive.py` | Google Drive OAuth + upload helpers (see [doc/google-drive.md](doc/google-drive.md)) |
| `prompts/grammatical_forms/<lang>.txt`, `prompts/noun_forms/<lang>.txt` | Per-language instructions for the "Show grammatical forms" / "Noun forms" AI-generator options |
| `.env` | Runtime configuration (credentials, limits) |
| `.google_tokens.json` | Per-user Google Drive refresh tokens (created at runtime, never committed) |
| `sentences.example.json` | Example input file, Romanian/English (JSON) |
| `sentences.example.csv` | Example input file, Romanian/English (CSV) |
| `sentences.example.en-uk.json` | Example input file, English/Ukrainian (JSON) |
| `sentences.example.en-uk.csv` | Example input file, English/Ukrainian (CSV) |
| `requirements.txt` | Python dependencies (`edge-tts`, `pydub`, `flask`, `python-dotenv`, `gunicorn`) |
| `.python-version` | Pins Python to 3.12 for `pydub` compatibility |
