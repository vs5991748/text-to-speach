# Limits

All limits are configured in `.env` and applied only to **regular users** (`USERS`). **Superusers** (`SU_USERS`) bypass all limits entirely. The CLI has no enforced limits — they only apply to web requests.

Active limits are shown in the page subtitle for regular users. Superusers see a "★ Superuser — no limits applied" badge instead.

---

## Disabling a limit

Set any numeric limit to **`0`** to disable it entirely:

```dotenv
MAX_ROWS=0               # accept files of any size
MAX_STRING_LENGTH=0      # accept strings of any length
MAX_ROWS_PER_WINDOW=0    # no row-throughput cap
RATE_LIMIT_REQUESTS=0    # no request-frequency cap
GENERATION_TIMEOUT_SECONDS=0  # jobs run until they finish
```

Leaving a variable **blank** keeps the built-in default (same as omitting the line). Setting it to `0` is the explicit opt-out.

---

## Reference

| Variable | Default | Applies to |
|---|---|---|
| `MAX_ROWS` | `200` | Maximum sentence pairs per uploaded file |
| `MAX_ROWS_PER_WINDOW` | `1000` | Total rows one user may process within the rate-limit window |
| `MAX_STRING_LENGTH` | `500` | Maximum characters in any single sentence string |
| `RATE_LIMIT_REQUESTS` | `10` | Maximum `/generate` calls per user within the rate-limit window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Width of the sliding time window (seconds) used by request and row-throughput limits |
| `GENERATION_TIMEOUT_SECONDS` | `600` | Maximum seconds a generation job may run before it is aborted |

---

## MAX_ROWS — rows per file

Rejects any uploaded file that contains more sentence pairs than this value. The check runs during upload (before generation starts), so the user gets immediate feedback.

**.env**
```dotenv
MAX_ROWS=50
```

**What the user sees when exceeded:**
```
File has 80 rows; maximum allowed is 50.
```

---

## MAX_STRING_LENGTH — characters per sentence

Each cell in the uploaded file (both the learning-language column and the translation column) must not exceed this many characters. Checked during upload.

**.env**
```dotenv
MAX_STRING_LENGTH=200
```

**What the user sees when exceeded:**
```
Row 3 [ro] is 215 chars; maximum allowed is 200.
```

**Example pair that would be rejected** (with limit 200):
```csv
ro,en
"Aceasta este o propoziție extrem de lungă care depășește limita de caractere stabilită în fișierul de configurare al aplicației și va fi respinsă de server.",Short English sentence.
```

---

## MAX_ROWS_PER_WINDOW — row throughput per user

Tracks how many total rows each **user** has submitted for generation within the current time window. If a new request would push the running total over this limit, it is rejected with `429 Too Many Requests`.

The window slides — as time passes, older requests leave the window and free up quota.

**.env**
```dotenv
MAX_ROWS_PER_WINDOW=200
RATE_LIMIT_WINDOW_SECONDS=60
```

**Scenario with the above settings:**

| Time | User request | Rows in request | Running total | Result |
|---|---|---|---|---|
| 0 s | generate | 80 | 80 | ✅ accepted |
| 15 s | generate | 80 | 160 | ✅ accepted |
| 30 s | generate | 80 | 240 | ❌ rejected (240 > 200) |
| 61 s | generate | 80 | 80 | ✅ accepted (first entry expired) |

**What the user sees when exceeded:**
```
Row throughput limit exceeded: max 200 rows per 60s.
```

---

## RATE_LIMIT_REQUESTS — requests per user

Limits the number of times one **user** can call `/generate` regardless of row count. Useful as a coarse guard against automated abuse.

**.env**
```dotenv
RATE_LIMIT_REQUESTS=3
RATE_LIMIT_WINDOW_SECONDS=60
```

With this config a user can start at most 3 generation jobs per minute.

**What the user sees when exceeded:**
```
Rate limit exceeded: max 3 requests per 60s.
```

---

## GENERATION_TIMEOUT_SECONDS — job time limit

Each generation job runs in a background thread. A watchdog timer fires after this many seconds and marks the job as failed if it hasn't finished.

**.env**
```dotenv
GENERATION_TIMEOUT_SECONDS=120
```

Useful for preventing runaway jobs from holding server resources indefinitely. Set it comfortably above the expected generation time for your typical file size.

**Rough estimate:** with default Edge TTS latency, a 50-pair file with 3 speed repetitions takes roughly 60–90 seconds.

**What the user sees when exceeded:**
```
Generation timed out after 120s.
```

---

## Example: strict public configuration

`.env` for a server shared with multiple users where you want tight guardrails:

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

## Example: relaxed local-only configuration

`.env` for a single developer running locally:

```dotenv
SU_USERS=dev:devpass

USERS=

MAX_ROWS=500
MAX_ROWS_PER_WINDOW=5000
MAX_STRING_LENGTH=1000
RATE_LIMIT_REQUESTS=50
RATE_LIMIT_WINDOW_SECONDS=60
GENERATION_TIMEOUT_SECONDS=1800
```
