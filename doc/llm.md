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

## Per-user provider assignment

By default every user uses the provider named in `LLM_DEFAULT`. Override it per user:

```dotenv
LLM_DEFAULT=openrouter          # fallback for all users

LLM_USER_ADMIN=groq             # admin gets Groq
LLM_USER_BOB=ollama             # bob uses local Ollama
                                # alice (not listed) → default (openrouter)
```

The key format is `LLM_USER_<USERNAME_IN_UPPERCASE>`. Superusers and regular users can both be assigned.

To **disable** AI suggestions for a specific user — assign them a provider whose `MODEL` is blank:

```dotenv
LLM_USER_BOB=groq
LLM_GROQ_MODEL=               # ← blank disables it
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
| `LLM_DEFAULT` | `openrouter` | Provider used when no per-user override is set. Blank = disabled. |
| `LLM_USER_<USERNAME>` | *(none)* | Per-user provider override, e.g. `LLM_USER_ADMIN=groq` |
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
