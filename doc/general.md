# General Information

## What it does

Turns a list of sentence pairs into a single MP3 listening track designed for language practice. For each pair:

1. The sentence in the **learning language** is spoken one or more times, optionally at different speeds (slow → normal), with a pause after each repetition.
2. The **translation** sentence is spoken once, followed by another pause before the next pair.

The result is a track you can listen to during a walk, commute, or any hands-free activity.

Speech synthesis is powered by [Edge TTS](https://github.com/rany2/edge-tts) — Microsoft's free neural voices, no API key required.

---

## Two ways to use it

### 1. Command-line interface (CLI)

Processes a local file and writes an MP3 (or a ZIP of per-pair MP3s with `--split`) directly to disk.

```bash
# combined track
python generate_audio.py --input sentences.example.json --learning-lang ro

# one file per sentence pair → sentences.example.zip
python generate_audio.py --input sentences.example.json --learning-lang ro --split
```

See [installation.md](installation.md) for setup and the main [README](../README.md) for the full flag reference.

### 2. Web interface

A browser-based UI with two source modes, set options through a form, wait for generation, and download the result.

```bash
python app.py
# → open http://localhost:5000
```

**Source modes:**
- **Upload file** — drag & drop or browse a `.csv` / `.json` file
- **Enter sentences** — type pairs directly into the form; no file needed. Specify language codes, add as many pairs as you need, translation column is optional.
- **AI phrase generator** — type a single word or collocation and let an LLM write a natural sentence and its translation for you. Supports **prompt options** (verb tenses, negative forms, reflexive, grammatical forms, register) and a free-text custom instruction field. Requires an LLM provider to be configured (see [llm.md](llm.md)).

The web interface supports all the same options as the CLI (speeds, pauses, voice overrides, skip-translation, split mode, row range) plus server-side [limits](limits.md) and [authentication](authorization.md).
In **split mode** the download is a ZIP archive instead of a single MP3.
When split mode is off and the sentences came from the **AI phrase generator**, the downloaded MP3 is named after the word/collocation you typed (e.g. `commute.mp3`) instead of the generic `audio.mp3`.

---

## Input format

Sentence pairs are provided as either **JSON** or **CSV**, keyed by language code:

**JSON**
```json
[
  { "ro": "Bună dimineața!", "en": "Good morning!" },
  { "ro": "Cum te simți astăzi?", "en": "How are you feeling today?" }
]
```

**CSV** (header row = language codes)
```csv
ro,en
Bună dimineața!,Good morning!
Cum te simți astăzi?,How are you feeling today?
```

`--learning-lang` (CLI) / the *Learning language* dropdown (web) picks which column is the one being learned. The other column is treated as the translation automatically.

---

## Supported languages (out of the box)

| Code | Language | Default voice |
|---|---|---|
| `ro` | Română | `ro-RO-EmilNeural` |
| `en` | English | `en-US-AriaNeural` |
| `uk` | Українська | `uk-UA-PolinaNeural` |
| `ru` | Русский | `ru-RU-SvetlanaNeural` |
| `pl` | Polski | `pl-PL-ZofiaNeural` |
| `pt` | Português | `pt-BR-FranciscaNeural` |

Default voices are defined in `tts_engines.py → LANG_VOICES`. Add any language there, or pass a custom voice at runtime:

```bash
# CLI
python generate_audio.py ... --voice uk=uk-UA-OstapNeural

# List all available voices for a language
edge-tts --list-voices | grep uk-UA
```

In the web UI, use the *Voice overrides* section in the form.
