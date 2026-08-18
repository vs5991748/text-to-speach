# Examples

Practical examples for both the CLI and the web interface.

---

## CLI examples

### Basic: Romanian ↔ English

```bash
python generate_audio.py \
  --input sentences.example.json \
  --learning-lang ro
```

Produces `sentences.example.mp3`. Each Romanian sentence is spoken once at 85% speed, followed by the English translation.

---

### Ramp from slow to normal speed (3 repetitions)

Good for early learning — hear the sentence slowly, then at normal pace:

```bash
python generate_audio.py \
  --input sentences.example.json \
  --learning-lang ro \
  --target-speeds 0.6 0.8 1.0
```

Each pair: Romanian at 0.6× → Romanian at 0.8× → Romanian at 1.0× → English translation.

---

### English ↔ Ukrainian

```bash
python generate_audio.py \
  --input sentences.example.en-uk.json \
  --learning-lang en
```

---

### Custom output path

```bash
python generate_audio.py \
  --input lists/baia_vocabular_fraze.csv \
  --learning-lang ro \
  --output ~/Desktop/romanian_lesson.mp3
```

---

### Longer pauses between pairs

Useful when you want more time to repeat out loud:

```bash
python generate_audio.py \
  --input sentences.example.csv \
  --learning-lang ro \
  --pause-after-target 2.0 \
  --pause-after-translation 3.0
```

---

### Learning language only — no translation

```bash
python generate_audio.py \
  --input sentences.example.json \
  --learning-lang ro \
  --no-translation \
  --target-speeds 0.75 1.0
```

---

### Split mode — one MP3 per sentence pair

Produce a ZIP archive where each sentence pair is its own file:

```bash
python generate_audio.py \
  --input sentences.example.csv \
  --learning-lang ro \
  --split
```

Outputs `sentences.example.zip`:

```
001_Bun_dimineata.mp3
002_Cum_te_sim_i_ast_zi.mp3
003_mi_place_foarte_mult_aceast_melodie.mp3
...
```

Custom output path and combined with other flags:

```bash
python generate_audio.py \
  --input sentences.example.json \
  --learning-lang ro \
  --split \
  --target-speeds 0.7 1.0 \
  --no-translation \
  --output ~/Desktop/lesson_cards.zip
```

---

### Override the default voice

List voices for a language, then use one:

```bash
# find voices for Romanian
edge-tts --list-voices | grep ro-RO

# use a different voice
python generate_audio.py \
  --input sentences.example.json \
  --learning-lang ro \
  --voice ro=ro-RO-AlinaNeural
```

Override both languages at once:

```bash
python generate_audio.py \
  --input sentences.example.en-uk.json \
  --learning-lang en \
  --voice en=en-US-GuyNeural \
  --voice uk=uk-UA-OstapNeural
```

---

### CSV input with a comma in a field

Quote the field:

```csv
ro,en
"Mulțumesc pentru ajutor, ești foarte amabil.","Thank you for your help, you are very kind."
```

```bash
python generate_audio.py --input my_list.csv --learning-lang ro
```

---

## Web interface examples

Start the server:

```bash
source venv/bin/activate
python app.py
# → http://localhost:5000
```

---

### Standard workflow (combined MP3)

1. Drop `sentences.example.csv` onto the upload zone.
2. The detected languages (`ro` / `en`) appear automatically; select `ro` as the learning language.
3. Set **Target speeds** to `0.7 0.85 1.0` — 1 to 3 values, each between `0.5` and `3.0`.
4. Leave pauses at their defaults (both capped at 3s max).
5. Click **Generate audio**.
6. When done, click **Download audio.mp3**.

> After a successful generation the **Generate audio** button shows a countdown (`Wait 60s…`) and re-enables automatically. Configurable via `GENERATION_COOLDOWN_SECONDS` in `.env`.

---

### Enter sentences manually (no file needed)

1. Click the **✎ Enter sentences** tab in Step 1.
2. Set **Learning language code** to `ro` and **Translation language code** to `en`.
3. Click **+ Add sentence pair** and type your pairs:
   - Learning: `Bună dimineața!` → Translation: `Good morning!`
   - Learning: `Cum te simți astăzi?` → Translation: `How are you feeling today?`
4. Click **Continue →** — the pairs are serialised to JSON and validated server-side.
5. Configure options and generate as normal.

Leave **Translation language code** blank to skip translation audio automatically (the *Skip translation audio* toggle will be pre-checked).

---

### AI phrase generator

Requires an LLM provider configured in `.env` (see [llm.md](llm.md)).

1. In the *Enter sentences* tab, select **Română** as the learning language and **Українська** as the translation language.
2. In the **✨ AI phrase generator** box, type a word or collocation, e.g. `a uita`.
3. Set the count to `3` and click **Generate** — the LLM fills three rows.
4. Repeat for other words, adjust any pairs manually, then click **Continue →**.

#### Prompt options (expand ▶ Prompt options)

| Option | What it does | Locks count? |
|---|---|---|
| One sentence per tense | Generates present/past/future/conditional/imperative — one each | Yes → auto |
| Only negative sentences | All sentences use negation | No |
| Mix negative/affirmative | Mixed positive and negative | No |
| Include questions | Some sentences are questions | No |
| Show grammatical forms | One sentence per gender/case/number combination | Yes → auto |
| Formal register | Polite, official language | No |
| Informal/colloquial | Everyday speech, contractions | No |
| Reflexive form | Forces reflexive verb construction (ro: *a se uita*, ru: *учиться*) | No |
| Custom instruction | Free-text field — any additional requirement | No |

When **One sentence per tense** or **Show grammatical forms** is checked, the count input is hidden and the LLM decides how many sentences to generate.

---

### Split mode — one file per sentence pair

Enable **One file per record** before generating. Instead of a single track you receive a ZIP archive where each sentence pair is its own MP3:

```
audio_pack.zip
├── 001_Bun_dimineata.mp3
├── 002_Cum_te_sim_i_ast_zi.mp3
├── 003_mi_place_foarte_mult_aceast_melodie.mp3
└── ...
```

The ZIP is rebuilt on each new request; the previous one is discarded automatically.

---

### Custom voice in the web UI

In the **Voice overrides** section, click **+ Add voice override**, select the language from the dropdown, and type the voice ID (e.g. `ro-RO-AlinaNeural`). Multiple overrides can be added.

---

### Superuser vs regular user behaviour

| | `admin` (SU) | `alice` (regular) |
|---|---|---|
| Row limit per file | ∞ | 200 |
| Rows per 60 s | ∞ | 1 000 |
| Requests per 60 s | ∞ | 10 |
| String length limit | ∞ | 500 chars |
| Page shows | ★ Superuser — no limits | limits bar |

---

## Input file examples

### JSON — Romanian / English

```json
[
  { "ro": "Bună dimineața!", "en": "Good morning!" },
  { "ro": "Cum te simți astăzi?", "en": "How are you feeling today?" },
  { "ro": "Îmi place foarte mult această melodie.", "en": "I really like this song." }
]
```

### JSON — English / Ukrainian

```json
[
  { "en": "Good morning!", "uk": "Доброго ранку!" },
  { "en": "Where is the nearest pharmacy?", "uk": "Де найближча аптека?" }
]
```

### CSV — Romanian / English

```csv
ro,en
Bună dimineața!,Good morning!
Cum te simți astăzi?,How are you feeling today?
"Mulțumesc pentru ajutor, ești foarte amabil.","Thank you for your help, you are very kind."
```

> Quote any field that contains a comma. The header row must use language codes (e.g. `ro`, `en`, `uk`).

---

## .env configuration examples

### Strict public server

```dotenv
SU_USERS=admin:Tr0ub4dor&3

USERS=alice:alicepass,bob:bobpass

MAX_ROWS=30
MAX_ROWS_PER_WINDOW=100
MAX_STRING_LENGTH=300
RATE_LIMIT_REQUESTS=5
RATE_LIMIT_WINDOW_SECONDS=60
GENERATION_TIMEOUT_SECONDS=180
```

### Relaxed local setup

```dotenv
SU_USERS=dev:devpass
USERS=

MAX_ROWS=0
MAX_ROWS_PER_WINDOW=0
MAX_STRING_LENGTH=0
RATE_LIMIT_REQUESTS=0
RATE_LIMIT_WINDOW_SECONDS=60
GENERATION_TIMEOUT_SECONDS=0
```

All `0` values disable every limit — useful when you're the only user and trust your own files.
