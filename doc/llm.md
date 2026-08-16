# LLM Configuration

The web interface can generate natural sentence pairs on demand using a large language model. Type a word or collocation in the **✨ AI phrase generator** box (inside the *Enter sentences* tab) and the LLM produces a sentence that uses it, plus its translation.

Three providers are supported out of the box. All use the OpenAI-compatible `/v1/chat/completions` API, so adding any other compatible provider requires only setting the right env vars.

---

## Supported providers

| Provider | Cost | Best for |
|---|---|---|
| **OpenRouter** | Free models available | Cloud / Render deployment |
| **Groq** | Free tier (~14 400 req/day) | Cloud / Render deployment |
| **Ollama** | Completely free | Local use only |

---

## Quick-start: OpenRouter (recommended for cloud)

1. Create a free account at [openrouter.ai](https://openrouter.ai).
2. Go to **Keys** → **Create key** → copy the key (starts with `sk-or-`).
3. Add to `.env`:

```dotenv
LLM_DEFAULT=openrouter
LLM_OPENROUTER_API_KEY=sk-or-your-key-here
LLM_OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free
```

The `meta-llama/llama-3.1-8b-instruct:free` model is free with no credit card. Browse more models at [openrouter.ai/models](https://openrouter.ai/models) — filter by *Free* to find others.

---

## Quick-start: Groq

1. Create a free account at [console.groq.com](https://console.groq.com).
2. Go to **API Keys** → **Create API Key** → copy it (starts with `gsk_`).
3. Add to `.env`:

```dotenv
LLM_DEFAULT=groq
LLM_GROQ_API_KEY=gsk_your-key-here
LLM_GROQ_MODEL=llama-3.1-8b-instant
```

Other free Groq models: `llama-3.3-70b-versatile`, `gemma2-9b-it`, `mixtral-8x7b-32768`.
Check the full list at [console.groq.com/docs/models](https://console.groq.com/docs/models).

---

## Quick-start: Ollama (local)

1. Install Ollama from [ollama.com](https://ollama.com/download).
2. Pull a model:

```bash
ollama pull llama3.2
```

3. Ollama starts automatically on `http://localhost:11434`. Add to `.env`:

```dotenv
LLM_DEFAULT=ollama
LLM_OLLAMA_MODEL=llama3.2
# LLM_OLLAMA_BASE_URL=http://localhost:11434   ← default, only needed if changed
```

No API key required. The app calls Ollama's OpenAI-compatible endpoint locally.

> **Note:** Ollama only works when the app runs on the same machine as Ollama. It will not work on Render's free tier.

---

## Per-role provider assignment

LLM providers are assigned by **role**, not by username — so adding or removing users from `USERS`/`SU_USERS` never requires touching LLM config.

```dotenv
LLM_DEFAULT=openrouter      # all regular users (USERS)
LLM_SU_DEFAULT=groq         # all superusers (SU_USERS); falls back to LLM_DEFAULT if blank
```

**Resolution order for each request:**
1. `LLM_USER_<USERNAME>` — optional per-user override (edge cases only)
2. `LLM_SU_DEFAULT` — if the user is a superuser and this is set
3. `LLM_DEFAULT` — global fallback

### Example: admins get Groq, everyone else gets OpenRouter

```dotenv
LLM_DEFAULT=openrouter
LLM_OPENROUTER_API_KEY=sk-or-...
LLM_OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free

LLM_SU_DEFAULT=groq
LLM_GROQ_API_KEY=gsk_...
LLM_GROQ_MODEL=llama-3.1-8b-instant
```

### Example: disable AI for regular users, enable only for admins

```dotenv
LLM_DEFAULT=           # blank = disabled for regular users
LLM_SU_DEFAULT=groq
LLM_GROQ_API_KEY=gsk_...
LLM_GROQ_MODEL=llama-3.1-8b-instant
```

---

## Disabling AI suggestions entirely

Leave `LLM_DEFAULT` blank (or remove it). The **✨ AI phrase generator** UI section will not appear:

```dotenv
LLM_DEFAULT=
```

---

## Full reference

| Variable | Default | Description |
|---|---|---|
| `LLM_DEFAULT` | `openrouter` | Provider for all regular users (`USERS`). Blank = disabled. |
| `LLM_SU_DEFAULT` | *(blank)* | Provider for superusers (`SU_USERS`). Falls back to `LLM_DEFAULT` if blank. |
| `LLM_USER_<USERNAME>` | *(none)* | Per-user override (edge cases). Takes priority over role defaults. |
| `LLM_OPENROUTER_MODEL` | `meta-llama/llama-3.1-8b-instruct:free` | OpenRouter model ID |
| `LLM_OPENROUTER_API_KEY` | *(required)* | OpenRouter API key |
| `LLM_OPENROUTER_BASE_URL` | `https://openrouter.ai/api` | Override only if using a proxy |
| `LLM_GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model ID |
| `LLM_GROQ_API_KEY` | *(required)* | Groq API key |
| `LLM_GROQ_BASE_URL` | `https://api.groq.com/openai` | Override only if using a proxy |
| `LLM_OLLAMA_MODEL` | `llama3.2` | Ollama model name (must be pulled locally) |
| `LLM_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server address |

---

## Adding any other OpenAI-compatible provider

The pattern is universal: pick a provider name (e.g. `myprovider`) and set:

```dotenv
LLM_DEFAULT=myprovider
LLM_MYPROVIDER_MODEL=the-model-id
LLM_MYPROVIDER_API_KEY=your-key
LLM_MYPROVIDER_BASE_URL=https://api.myprovider.com/v1-without-the-path
```

The app appends `/v1/chat/completions` to `BASE_URL` when making requests.

---

## Deploying to Render

Set the env vars in the Render dashboard (**Environment** tab of your service) — do not commit your `.env` file with real keys.

Recommended setup for Render:

```dotenv
LLM_DEFAULT=openrouter
LLM_OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free
LLM_OPENROUTER_API_KEY=sk-or-your-key-here
```

Or use Groq for faster responses:

```dotenv
LLM_DEFAULT=groq
LLM_GROQ_MODEL=llama-3.1-8b-instant
LLM_GROQ_API_KEY=gsk_your-key-here
```
