#!/usr/bin/env python3
"""Flask web interface for the TTS audio generator."""

import base64
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, Response, abort, g, jsonify, render_template, request, send_file

load_dotenv()

def _limit(var: str, default: int) -> int:
    """Return 0 (disabled) for blank/zero values, otherwise the parsed int."""
    raw = os.getenv(var, "").strip()
    if not raw:
        return default
    val = int(raw)
    return val  # 0 explicitly disables the limit


MAX_ROWS = _limit("MAX_ROWS", 200)
MAX_ROWS_PER_WINDOW = _limit("MAX_ROWS_PER_WINDOW", 1000)
MAX_STRING_LENGTH = _limit("MAX_STRING_LENGTH", 500)
RATE_LIMIT_REQUESTS = _limit("RATE_LIMIT_REQUESTS", 10)
RATE_LIMIT_WINDOW = _limit("RATE_LIMIT_WINDOW_SECONDS", 60)
GENERATION_TIMEOUT = _limit("GENERATION_TIMEOUT_SECONDS", 600)
GENERATION_COOLDOWN = _limit("GENERATION_COOLDOWN_SECONDS", 60)
LLM_SUGGEST_COOLDOWN = _limit("LLM_SUGGEST_COOLDOWN_SECONDS", 60)

# Default provider for all users; SU users can get a separate default
LLM_DEFAULT = os.getenv("LLM_DEFAULT", "openrouter").strip().lower()
LLM_SU_DEFAULT = os.getenv("LLM_SU_DEFAULT", "").strip().lower()
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", 600) or 600)
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", 60) or 60)
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", 3) or 3)

# Built-in base URLs; override with LLM_<PROVIDER>_BASE_URL
_LLM_DEFAULT_URLS = {
    "openrouter": "https://openrouter.ai/api",
    "groq": "https://api.groq.com/openai",
    "ollama": "http://localhost:11434",
}
_LLM_DEFAULT_MODELS = {
    "openrouter": "google/gemma-2-9b-it:free",
    "groq": "llama-3.1-8b-instant",
    "ollama": "llama3.2",
}


def _resolve_provider(name: str) -> Optional[dict]:
    """Resolve a named provider to its {model, api_key, base_url} config, or None."""
    if not name:
        return None
    prefix = f"LLM_{name.upper()}"
    model = os.getenv(f"{prefix}_MODEL", _LLM_DEFAULT_MODELS.get(name, "")).strip()
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    base_url = os.getenv(f"{prefix}_BASE_URL", _LLM_DEFAULT_URLS.get(name, "")).rstrip("/")
    return {"model": model, "api_key": api_key, "base_url": base_url} if model and base_url else None


def _llm_config_for(username, is_su: bool = False) -> Optional[dict]:
    """Resolve LLM config: per-user override → role default → global default."""
    # 1. Optional per-user override (edge cases only)
    if username:
        override = os.getenv(f"LLM_USER_{username.upper()}", "").strip().lower()
        if override:
            cfg = _resolve_provider(override)
            if cfg:
                return cfg
    # 2. Role-based default
    if is_su and LLM_SU_DEFAULT:
        cfg = _resolve_provider(LLM_SU_DEFAULT)
        if cfg:
            return cfg
    # 3. Global default
    return _resolve_provider(LLM_DEFAULT)


def _parse_users(env_var: str, is_su: bool) -> dict:
    """Parse 'user1:pass1,user2:pass2' into {username: {password, is_su}}."""
    result = {}
    for entry in os.getenv(env_var, "").split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        username, _, password = entry.partition(":")
        result[username.strip()] = {"password": password, "is_su": is_su}
    return result


# Regular users first, then SU — SU entry wins if same username appears in both
_users: dict = {}
_users.update(_parse_users("USERS", False))
_users.update(_parse_users("SU_USERS", True))

if not _users:
    import warnings
    warnings.warn("No users configured (USERS / SU_USERS) — authentication is disabled.", stacklevel=1)

from generate_audio import build_split_tracks, build_track, load_pairs, parse_voice_overrides, resolve_voice, _slugify, _slice_pairs, write_split_transcript, write_split_transcript_csv
from tts_engines import LANG_VOICES, LANG_NAMES

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB upload limit


@app.before_request
def _check_auth():
    if not _users:
        g.username = None
        g.is_su = True  # no users configured = unrestricted
        return
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8", errors="strict")
            username, _, password = decoded.partition(":")
            user = _users.get(username)
            if user and secrets.compare_digest(password.encode(), user["password"].encode()):
                g.username = username
                g.is_su = user["is_su"]
                return
        except Exception:
            pass
    return Response(
        "Authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="TTS Generator"'},
    )

# In-memory store: job_id -> {status, result_path, error, filename}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

# Uploaded files awaiting generation: file_id -> {path, count}
_uploads: dict[str, dict] = {}
_uploads_lock = threading.Lock()

# Rate limiting: username -> list of request timestamps
_rate_limit: dict = {}
_rate_limit_lock = threading.Lock()

# Row throughput tracking: username -> list of (timestamp, row_count)
_throughput: dict = {}
_throughput_lock = threading.Lock()

# Per-user split output dirs, cleaned at start of each new request
_user_outdirs: dict = {}
_user_outdirs_lock = threading.Lock()

# Per-user last generation timestamp (monotonic)
_last_gen_time: dict = {}
_last_gen_time_lock = threading.Lock()

# Per-user last AI suggest timestamp (monotonic)
_last_suggest_time: dict = {}
_last_suggest_time_lock = threading.Lock()

# Background suggest jobs: suggest_id -> {status, pairs, error}
_suggest_jobs: dict = {}
_suggest_jobs_lock = threading.Lock()

ALLOWED_EXTENSIONS = {".csv", ".json"}

# Substrings (lowercase) unique to the "auto-count" prompt-option instructions in
# templates/index.html — these options make the LLM decide quantity, so count must
# be forced to 0 server-side even if the client sends something else.
_AUTO_COUNT_MARKERS = (
    "one sentence per major verb tense",
    "grammatical form of the word or phrase itself",
    "form of the noun or noun phrase itself",
)


def _make_fragment_loader(subdir: str):
    """Build a loader for per-language clarifying fragments in prompts/<subdir>/<lang>.txt.
    Returns None (caller falls back to the generic instruction) for an unrecognized language
    code or one with no fragment file yet."""
    base = Path(__file__).parent / "prompts" / subdir

    def _load(learning_lang: str) -> Optional[str]:
        if learning_lang not in LANG_VOICES:
            return None
        try:
            text = (base / f"{learning_lang}.txt").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    return _load


# The exact checkbox value from templates/index.html for each option that has per-language
# clarifying fragments (see doc/spikes/architecture-per-language-grammatical-forms-spike.md) —
# the language-agnostic instruction it sends by default. When a per-language fragment exists,
# this text is swapped out for it; otherwise it's left as-is and serves as the fallback.
_GRAMMATICAL_FORMS_MARKER = "grammatical form of the word or phrase itself"
_GRAMMATICAL_FORMS_GENERIC_TEXT = (
    "Each sentence must clearly demonstrate a different grammatical form of the word or phrase "
    "itself. If it is a noun, pronoun, or adjective, produce one sentence for EACH combination of "
    "gender (masculine, feminine, neuter — skip genders the language lacks) and number (singular, "
    "plural), correctly declined. If it is a verb, produce one sentence for EACH of the six "
    "grammatical persons (I, you-singular, he/she/it, we, you-plural, they), correctly conjugated "
    "for that person — six sentences minimum, one per person, do not stop early or skip any."
)
_load_grammatical_forms_fragment = _make_fragment_loader("grammatical_forms")

_NOUN_FORMS_MARKER = "form of the noun or noun phrase itself"
_NOUN_FORMS_GENERIC_TEXT = (
    "Each sentence must clearly demonstrate a different form of the noun or noun phrase itself: "
    "singular indefinite, singular definite, plural indefinite, and plural definite — one sentence "
    "per applicable form, correctly inflected/declined for that form. Skip any form the language "
    "lacks (e.g. no indefinite article, or no plural for the word) rather than forcing an unnatural "
    "sentence."
)
_load_noun_forms_fragment = _make_fragment_loader("noun_forms")

# (marker, generic checkbox text, loader) for each option with per-language fragments —
# checked in order against the client's raw instructions string in the /suggest route.
_FORM_FRAGMENT_SPECS = (
    (_GRAMMATICAL_FORMS_MARKER, _GRAMMATICAL_FORMS_GENERIC_TEXT, _load_grammatical_forms_fragment),
    (_NOUN_FORMS_MARKER, _NOUN_FORMS_GENERIC_TEXT, _load_noun_forms_fragment),
)


def _split_multiline_pairs(parsed: list) -> list:
    """Split any pair whose 'learning'/'translation' field wrongly bundles multiple
    newline-joined sentences into separate pairs, one sentence per pair."""
    result = []
    for item in parsed:
        learning_lines = [l.strip() for l in str(item.get("learning", "")).split("\n") if l.strip()]
        if len(learning_lines) <= 1:
            result.append(item)
            continue
        translation = item.get("translation")
        if translation is not None:
            translation_lines = [l.strip() for l in str(translation).split("\n") if l.strip()]
            if len(translation_lines) == len(learning_lines):
                result.extend(
                    {"learning": l, "translation": t} for l, t in zip(learning_lines, translation_lines)
                )
                continue
            # Mismatched line counts — can't safely pair them up, leave item untouched.
            result.append(item)
            continue
        result.extend({"learning": l} for l in learning_lines)
    return result


def _call_llm(cfg: dict, word: str, learning_lang: str, translation_lang: str, count: int = 1, instructions: str = "") -> list:
    """Call an OpenAI-compatible LLM with retry/backoff. Returns list of {learning, translation}."""
    url = f"{cfg['base_url']}/v1/chat/completions"
    print(f"[LLM] POST {url} model={cfg['model']} word={word!r} count={count}", file=sys.stderr, flush=True)
    extra = f" Additional requirements: {instructions.strip()}" if instructions.strip() else ""
    sentence_style = (
        "a natural, medium-length sentence that describes a small situation in context — who is "
        "involved, and when, where, or why it happens — rather than a short, bare statement"
    )
    if count == 0:
        # Unconstrained — quantity driven entirely by the extra instruction
        trans_part = (
            f', each with a translation into the language with code "{translation_lang}"'
            if translation_lang else ""
        )
        trans_field = ', "translation": "<translation>"' if translation_lang else ""
        prompt = (
            f'You are a language learning assistant. '
            f'Your task: {extra} '
            f'Use the word or phrase "{word}" in every sentence, written in the language with code "{learning_lang}"{trans_part}. '
            f'Two hard rules for every sentence: '
            f'(1) The target word or phrase appears EXACTLY ONCE — never twice, even in a different form or '
            f'inside a subordinate clause. NOT "They forget that they forgot to pay the bill." NOT "Să uităm '
            f'să nu uita să verificăm documentele" — both illegally use the word twice. '
            f'(2) The sentence must be something a real person would actually say: {sentence_style}, '
            f'grammatically correct, and logically coherent — never artificial, redundant, or '
            f'self-contradictory. A command or wish form ("let us…", "do…!") only makes sense for something '
            f'the speaker can actually control — if the word describes an involuntary action (forgetting, '
            f'losing, failing), phrase it as advice or a warning addressed to someone else, or a common '
            f'idiom, instead of an illogical self-command. '
            f'(3) The target word or phrase itself must carry the required grammatical form directly — do '
            f'not dodge this by leaving it in its infinitive/base form and conjugating a DIFFERENT verb '
            f'around it instead. NOT "Eu am un plan de a uita…" / "I have a plan to forget…" repeated for '
            f'every person with only "have" changing — that never actually conjugates "uita"/"forget" '
            f'itself, so it fails to demonstrate the required person at all, and produces an unnatural, '
            f'oddly self-destructive-sounding sentence ("a plan to forget you are happy") in the process. '
            f'Each sentence must demonstrate EXACTLY ONE of the required variations — never combine two or '
            f'more variations (e.g. two different grammatical persons, or an indicative and an imperative) '
            f'into a single sentence. '
            f'You MUST produce MULTIPLE sentences — one per required variation. '
            f'Each variation MUST be its own separate array element. '
            f'Never combine more than one sentence into a single "learning" or "translation" string '
            f'(e.g. do not join sentences with newlines, semicolons, or numbering) — one sentence per element only. '
            f'Respond with ONLY a valid JSON array containing ALL generated sentences as separate elements, no extra text: '
            f'[{{"learning": "<sentence 1>"{trans_field}}}, {{"learning": "<sentence 2>"{trans_field}}}, {{"learning": "<sentence 3>"{trans_field}}}, ...]'
        )
        base_max_tokens = max(LLM_MAX_TOKENS * 3, 3000)
    elif count == 1:
        trans_part = (
            f' Then translate the sentence into the language with code "{translation_lang}".'
            if translation_lang else ""
        )
        trans_field = ', "translation": "<translation>"' if translation_lang else ""
        prompt = (
            f'You are a language learning assistant. '
            f'Write one sentence in the language with code "{learning_lang}" '
            f'that uses or illustrates the word or phrase "{word}". '
            f'The sentence should be {sentence_style}.'
            f'{trans_part}{extra} '
            f'Respond with ONLY valid JSON, no extra text: '
            f'{{"learning": "<sentence>"{trans_field}}}'
        )
    else:
        trans_part = (
            f', each with a translation into the language with code "{translation_lang}"'
            if translation_lang else ""
        )
        trans_field = ', "translation": "<translation>"' if translation_lang else ""
        prompt = (
            f'You are a language learning assistant. '
            f'Write {count} different sentences in the language with code "{learning_lang}" '
            f'that each use or illustrate the word or phrase "{word}"{trans_part}. '
            f'Each sentence should be {sentence_style}.{extra} '
            f'Respond with ONLY a valid JSON array, no extra text: '
            f'[{{"learning": "<sentence 1>"{trans_field}}}, ...]'
        )
    base_max_tokens = max(LLM_MAX_TOKENS, count * 200) if count > 0 else max(LLM_MAX_TOKENS * 3, 3000)
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    else:
        print(f"[LLM] WARNING: no API key set for {cfg['base_url']}", file=sys.stderr, flush=True)

    last_exc: Exception = RuntimeError("No attempts made")
    current_max_tokens = base_max_tokens
    for attempt in range(LLM_MAX_RETRIES + 1):
        if attempt > 0:
            wait = 2 ** (attempt - 1)  # 1 s, 2 s, 4 s …
            print(f"[LLM] retry {attempt}/{LLM_MAX_RETRIES} in {wait}s max_tokens={current_max_tokens}", file=sys.stderr, flush=True)
            time.sleep(wait)
        payload = json.dumps({
            "model": cfg["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": current_max_tokens,
        }).encode()
        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            print(f"[LLM] attempt {attempt+1} HTTP {e.code} {e.reason}: {body}", file=sys.stderr, flush=True)
            last_exc = e
            if e.code == 429:
                # honour Retry-After if provided
                retry_after = e.headers.get("Retry-After")
                try:
                    wait = int(retry_after)
                except (TypeError, ValueError):
                    wait = 2 ** attempt
                print(f"[LLM] rate-limited — waiting {wait}s", file=sys.stderr, flush=True)
                time.sleep(wait)
                continue
            if e.code >= 500:
                continue  # retry on server errors
            raise  # 4xx (non-429) are client errors — don't retry
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"[LLM] attempt {attempt+1} transient error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            last_exc = e
            continue  # retry on network/timeout errors
        else:
            # successful HTTP response — parse and return (inside else so parse errors also retry)
            try:
                choice = data["choices"][0]
                finish = choice.get("finish_reason")
                msg = choice["message"]
                raw_content = msg.get("content") or msg.get("reasoning")
                if not raw_content:
                    print(f"[LLM] null content finish_reason={finish}", file=sys.stderr, flush=True)
                    hint = " (token limit hit during reasoning — raise LLM_MAX_TOKENS)" if finish == "length" else ""
                    raise ValueError(f"LLM returned no usable content{hint}.")
                print(f"[LLM] attempt {attempt+1} raw content: {raw_content!r}", file=sys.stderr, flush=True)
                content = raw_content.strip()
                if "```" in content:
                    content = re.sub(r"```(?:json)?", "", content).strip()
                # Extract outermost [...] or {...}
                arr_start = content.find("[")
                obj_start = content.find("{")
                if arr_start != -1 and (obj_start == -1 or arr_start < obj_start):
                    end = content.rfind("]")
                    parsed = json.loads(content[arr_start:end + 1]) if end > arr_start else json.loads(content)
                    if isinstance(parsed, dict):
                        parsed = [parsed]
                else:
                    end = content.rfind("}")
                    parsed = json.loads(content[obj_start:end + 1] if obj_start != -1 and end > obj_start else content)
                    if isinstance(parsed, dict):
                        parsed = [parsed]
                if not parsed or "learning" not in parsed[0]:
                    raise ValueError("LLM response missing 'learning' field.")
                parsed = _split_multiline_pairs(parsed)
                # Reject template/placeholder responses — retry so the model gives real content
                _placeholders = {"", "...", "<sentence>", "<sentence 1>", "<sentence 2>"}
                if all(str(p.get("learning", "")).strip() in _placeholders for p in parsed):
                    raise ValueError("LLM returned placeholder text. Retrying.")
                print(f"[LLM] attempt {attempt+1} success: {len(parsed)} pair(s)", file=sys.stderr, flush=True)
                return parsed
            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
                print(f"[LLM] attempt {attempt+1} parse error: {type(e).__name__}: {e} | full response: {data!r}", file=sys.stderr, flush=True)
                last_exc = e
                # Double token budget on length cutoff so next attempt has more room
                if data.get("choices") and data["choices"][0].get("finish_reason") == "length":
                    current_max_tokens *= 2
                    print(f"[LLM] length cutoff — doubling max_tokens to {current_max_tokens}", file=sys.stderr, flush=True)
                continue  # retry on bad/truncated output

    raise last_exc


def _is_rate_limited(username: str) -> bool:
    if not RATE_LIMIT_REQUESTS:
        return False
    now = time.monotonic()
    with _rate_limit_lock:
        timestamps = [t for t in _rate_limit.get(username, []) if now - t < RATE_LIMIT_WINDOW]
        if len(timestamps) >= RATE_LIMIT_REQUESTS:
            _rate_limit[username] = timestamps
            return True
        timestamps.append(now)
        _rate_limit[username] = timestamps
        return False


def _exceeds_row_throughput(username: str, row_count: int) -> bool:
    """Returns True if adding row_count would exceed the per-user row budget for the current window."""
    if not MAX_ROWS_PER_WINDOW:
        return False
    now = time.monotonic()
    with _throughput_lock:
        entries = [(t, n) for t, n in _throughput.get(username, []) if now - t < RATE_LIMIT_WINDOW]
        if sum(n for _, n in entries) + row_count > MAX_ROWS_PER_WINDOW:
            _throughput[username] = entries
            return True
        entries.append((now, row_count))
        _throughput[username] = entries
        return False


def _check_extension(filename: str) -> Optional[str]:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in ALLOWED_EXTENSIONS else None


@app.route("/")
def index():
    return render_template("index.html",
                           known_langs=sorted(LANG_VOICES.keys()),
                           lang_names=LANG_NAMES,
                           known_voices=LANG_VOICES,
                           is_su=g.is_su,
                           llm_enabled=bool(_llm_config_for(g.username, g.is_su)),
                           llm_suggest_cooldown=LLM_SUGGEST_COOLDOWN,
                           llm_lock_reason=(
                               None if _llm_config_for(g.username, g.is_su)
                               else ("No LLM provider is configured on this server."
                                     if not LLM_DEFAULT
                                     else "AI phrase generation is not configured for your role.")
                           ),
                           max_rows=MAX_ROWS,
                           max_rows_per_window=MAX_ROWS_PER_WINDOW,
                           max_string_length=MAX_STRING_LENGTH,
                           rate_limit_window=RATE_LIMIT_WINDOW,
                           generation_timeout=GENERATION_TIMEOUT,
                           cooldown_seconds=GENERATION_COOLDOWN)


@app.route("/upload", methods=["POST"])
def upload():
    """Save uploaded file; return detected language codes and pair count."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file provided."}), 400

    suffix = _check_extension(f.filename)
    if suffix is None:
        return jsonify({"error": "Only .csv and .json files are supported."}), 400

    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        f.save(tmp.name)
        tmp.close()
        try:
            langs, pairs = load_pairs(tmp.name)
        except SystemExit as e:
            os.unlink(tmp.name)
            return jsonify({"error": str(e)}), 422
    except Exception as e:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        return jsonify({"error": str(e)}), 500

    if not pairs:
        os.unlink(tmp.name)
        return jsonify({"error": "No sentence pairs found in the file."}), 422

    if not g.is_su and MAX_ROWS and len(pairs) > MAX_ROWS:
        os.unlink(tmp.name)
        return jsonify({"error": f"File has {len(pairs)} rows; maximum allowed is {MAX_ROWS}."}), 422

    if not g.is_su and MAX_STRING_LENGTH:
        for i, pair in enumerate(pairs, 1):
            for lang, text in pair.items():
                if len(text) > MAX_STRING_LENGTH:
                    os.unlink(tmp.name)
                    return jsonify({
                        "error": f"Row {i} [{lang}] is {len(text)} chars; maximum allowed is {MAX_STRING_LENGTH}."
                    }), 422

    # Optional: the AI generator's word/collocation, if that's how these pairs were produced —
    # used to name the downloaded file (MP3 or split-mode ZIP) instead of the generic name.
    word = request.form.get("word", "").strip()[:100]

    file_id = str(uuid.uuid4())
    with _uploads_lock:
        _uploads[file_id] = {"path": tmp.name, "count": len(pairs), "word": word}

    return jsonify({"file_id": file_id, "langs": langs, "count": len(pairs),
                    "first_pairs": pairs[:10],
                    "limits": {"max_rows": MAX_ROWS, "max_string_length": MAX_STRING_LENGTH}})


@app.route("/generate", methods=["POST"])
def generate():
    """Start a background generation job. Returns {job_id}."""
    if not g.is_su and _is_rate_limited(g.username):
        return jsonify({"error": f"Rate limit exceeded: max {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW}s."}), 429

    if not g.is_su and GENERATION_COOLDOWN:
        user_key_cd = g.username or "_anon_"
        now_cd = time.monotonic()
        with _last_gen_time_lock:
            last = _last_gen_time.get(user_key_cd, 0)
            remaining = GENERATION_COOLDOWN - (now_cd - last)
        if remaining > 0:
            return jsonify({"error": f"Please wait {int(remaining) + 1}s before generating again.",
                            "retry_after": int(remaining) + 1}), 429

    # Clean up the previous split output dir for this user
    user_key = g.username or "_anon_"
    with _user_outdirs_lock:
        old_dir = _user_outdirs.pop(user_key, None)
    if old_dir:
        shutil.rmtree(old_dir, ignore_errors=True)

    data = request.get_json(silent=True) or {}

    file_id = data.get("file_id", "").strip()
    with _uploads_lock:
        upload_entry = _uploads.pop(file_id, None)

    if not upload_entry or not os.path.exists(upload_entry["path"]):
        return jsonify({"error": "Upload not found. Please re-upload the file."}), 400

    input_path = upload_entry["path"]
    row_count = upload_entry["count"]
    word = upload_entry.get("word", "")

    if not g.is_su and _exceeds_row_throughput(g.username, row_count):
        os.unlink(input_path)
        return jsonify({"error": f"Row throughput limit exceeded: max {MAX_ROWS_PER_WINDOW} rows per {RATE_LIMIT_WINDOW}s."}), 429

    learning_lang = data.get("learning_lang", "").strip()
    if not learning_lang:
        return jsonify({"error": "learning_lang is required."}), 400

    try:
        target_speeds = [float(x) for x in str(data.get("target_speeds", "0.85")).split()]
    except ValueError:
        target_speeds = [0.85]
    if not target_speeds:
        target_speeds = [0.85]
    if len(target_speeds) > 3:
        return jsonify({"error": "Maximum 3 speed repetitions allowed."}), 400
    if any(s < 0.5 or s > 3.0 for s in target_speeds):
        return jsonify({"error": "Each speed must be between 0.5 and 3.0."}), 400

    pause_after_target = float(data.get("pause_after_target", 1.0))
    pause_after_translation = float(data.get("pause_after_translation", 1.5))
    if pause_after_target > 3.0:
        return jsonify({"error": "Pause after target must not exceed 3s."}), 400
    if pause_after_translation > 3.0:
        return jsonify({"error": "Pause after translation must not exceed 3s."}), 400
    no_translation = bool(data.get("no_translation", False))
    split = bool(data.get("split", False))
    rows_spec = str(data.get("rows", "")).strip()
    voice_overrides_raw = str(data.get("voice_overrides", "")).strip()
    voice_override_pairs = [v.strip() for v in voice_overrides_raw.split(",") if "=" in v]

    # For split mode create a persistent output dir that survives until next request
    output_dir = None
    if split:
        output_dir = tempfile.mkdtemp()
        with _user_outdirs_lock:
            _user_outdirs[user_key] = output_dir

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "pending", "result_path": None, "error": None, "format": None, "download_name": None}

    thread = threading.Thread(
        target=_run_generation,
        args=(job_id, input_path, learning_lang, target_speeds,
              pause_after_target, pause_after_translation, no_translation, voice_override_pairs,
              split, output_dir, rows_spec, word),
        daemon=True,
    )
    thread.start()

    # Record generation time for cooldown tracking
    if not g.is_su and GENERATION_COOLDOWN:
        with _last_gen_time_lock:
            _last_gen_time[g.username or "_anon_"] = time.monotonic()

    return jsonify({"job_id": job_id})


def _run_generation(job_id, input_path, learning_lang, target_speeds,
                    pause_after_target_s, pause_after_translation_s, no_translation, voice_override_pairs,
                    split, output_dir, rows_spec, word=""):
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"

    def _on_timeout():
        with _jobs_lock:
            if _jobs[job_id]["status"] == "running":
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = f"Generation timed out after {GENERATION_TIMEOUT}s."

    watchdog = None
    if GENERATION_TIMEOUT:
        watchdog = threading.Timer(GENERATION_TIMEOUT, _on_timeout)
        watchdog.daemon = True
        watchdog.start()

    output_tmp = None
    try:
        langs, pairs = load_pairs(input_path)
        if not pairs:
            raise ValueError("No sentence pairs found.")
        if learning_lang not in langs:
            raise ValueError(f"Learning language {learning_lang!r} not in file languages {langs!r}.")

        if rows_spec:
            pairs = _slice_pairs(rows_spec, pairs)
            if not pairs:
                raise ValueError(f"Row range {rows_spec!r} selected 0 rows.")

        translation_lang = next(l for l in langs if l != learning_lang)
        overrides = parse_voice_overrides(voice_override_pairs)
        learning_voice = resolve_voice(learning_lang, overrides)
        translation_voice = resolve_voice(translation_lang, overrides)
        pause_ms = int(pause_after_target_s * 1000)
        trans_pause_ms = int(pause_after_translation_s * 1000)
        include_translation = not no_translation

        with tempfile.TemporaryDirectory() as workdir:
            if split:
                build_split_tracks(
                    pairs, learning_lang, translation_lang, learning_voice, translation_voice,
                    target_speeds,
                    pause_ms,
                    trans_pause_ms,
                    include_translation,
                    workdir,
                    output_dir,
                )
                write_split_transcript(pairs, learning_lang, translation_lang, output_dir)
                write_split_transcript_csv(pairs, learning_lang, translation_lang, output_dir)
                zip_path = os.path.join(output_dir, "audio_pack.zip")
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fname in sorted(f for f in os.listdir(output_dir) if f.endswith((".mp3", ".txt", ".csv"))):
                        zf.write(os.path.join(output_dir, fname), fname)
                result_path = zip_path
                result_format = "zip"
            else:
                track = build_track(
                    pairs, learning_lang, translation_lang, learning_voice, translation_voice,
                    target_speeds,
                    pause_ms,
                    trans_pause_ms,
                    include_translation,
                    workdir,
                )
                output_tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                output_tmp.close()
                track.export(output_tmp.name, format="mp3")
                result_path = output_tmp.name
                result_format = "mp3"

        # Downloads are named after the AI generator's word/collocation when the pairs came
        # from there, regardless of split mode; otherwise they keep the generic name.
        download_name = f"{_slugify(word)}.{result_format}" if word else None

        with _jobs_lock:
            if _jobs[job_id]["status"] != "error":  # not already timed out
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result_path"] = result_path
                _jobs[job_id]["format"] = result_format
                _jobs[job_id]["download_name"] = download_name

    except (SystemExit, ValueError, Exception) as e:
        if output_tmp:
            try:
                os.unlink(output_tmp.name)
            except OSError:
                pass
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        if watchdog:
            watchdog.cancel()
        try:
            os.unlink(input_path)
        except OSError:
            pass


@app.route("/status/<job_id>")
def status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job ID."}), 404
    return jsonify({"status": job["status"], "error": job.get("error"), "format": job.get("format")})


@app.route("/suggest", methods=["POST"])
def suggest():
    cfg = _llm_config_for(g.username, g.is_su)
    if not cfg:
        return jsonify({"error": "AI suggestions are not configured for your account."}), 503
    if not g.is_su and _is_rate_limited(g.username):
        return jsonify({"error": "Rate limit exceeded."}), 429
    if not g.is_su and LLM_SUGGEST_COOLDOWN:
        user_key = g.username or "_anon_"
        now_s = time.monotonic()
        with _last_suggest_time_lock:
            remaining = LLM_SUGGEST_COOLDOWN - (now_s - _last_suggest_time.get(user_key, 0))
        if remaining > 0:
            secs = int(remaining) + 1
            return jsonify({"error": f"Please wait {secs}s before generating another phrase.",
                            "retry_after": secs}), 429
    data = request.get_json(silent=True) or {}
    word = str(data.get("word", "")).strip()
    learning_lang = str(data.get("learning_lang", "")).strip()
    translation_lang = str(data.get("translation_lang", "")).strip()
    try:
        count = int(data.get("count", 1))
    except (TypeError, ValueError):
        count = 1
    count = max(0, min(5, count))  # 0 = unconstrained (LLM decides)
    raw_instructions = str(data.get("instructions", "")).strip()
    lower_raw = raw_instructions.lower()
    # Both markers are checked on the raw string, not the capped one below, so a long
    # combination of other checked options can't truncate a marker away unnoticed — the
    # 543-char generic grammatical-forms text alone already exceeds the 500-char cap.
    if count and any(marker in lower_raw for marker in _AUTO_COUNT_MARKERS):
        count = 0  # these options are unconstrained regardless of what the client sent
    # Swap each selected option's generic instruction for its per-language fragment (if one
    # exists for learning_lang), then cap only the remaining client-supplied text (other
    # options / custom instruction) — fragments are trusted, server-authored content, so they
    # aren't subject to that cap.
    rest = raw_instructions
    fragments_to_append = []
    for marker, generic_text, load_fragment in _FORM_FRAGMENT_SPECS:
        if marker not in lower_raw:
            continue
        fragment = load_fragment(learning_lang)
        if not fragment:
            continue  # no fragment for this language — leave the generic text as the fallback
        if generic_text in rest:
            rest = rest.replace(generic_text, "")
        fragments_to_append.append(fragment)
    instructions = rest.strip()[:500]  # cap to prevent prompt injection
    for fragment in fragments_to_append:
        instructions = f"{instructions} {fragment}".strip()
    if not word or not learning_lang:
        return jsonify({"error": "word and learning_lang are required."}), 400

    suggest_id = str(uuid.uuid4())
    with _suggest_jobs_lock:
        _suggest_jobs[suggest_id] = {"status": "pending", "pairs": None, "error": None}

    # user_key passed to worker so cooldown is recorded at completion, not at launch
    user_key_for_cooldown = (g.username or "_anon_") if (not g.is_su and LLM_SUGGEST_COOLDOWN) else None

    threading.Thread(
        target=_run_suggest,
        args=(suggest_id, cfg, word, learning_lang, translation_lang, count, instructions, user_key_for_cooldown),
        daemon=True,
    ).start()
    return jsonify({"suggest_id": suggest_id})


def _run_suggest(suggest_id, cfg, word, learning_lang, translation_lang, count, instructions, user_key_for_cooldown):
    with _suggest_jobs_lock:
        _suggest_jobs[suggest_id]["status"] = "running"
    try:
        pairs = _call_llm(cfg, word, learning_lang, translation_lang, count, instructions)
        if user_key_for_cooldown:
            with _last_suggest_time_lock:
                _last_suggest_time[user_key_for_cooldown] = time.monotonic()
        with _suggest_jobs_lock:
            _suggest_jobs[suggest_id]["status"] = "done"
            _suggest_jobs[suggest_id]["pairs"] = pairs
    except Exception as e:
        print(f"[LLM] suggest job failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        with _suggest_jobs_lock:
            _suggest_jobs[suggest_id]["status"] = "error"
            _suggest_jobs[suggest_id]["error"] = f"{type(e).__name__}: {e}"


@app.route("/suggest/status/<suggest_id>")
def suggest_status(suggest_id):
    with _suggest_jobs_lock:
        job = _suggest_jobs.get(suggest_id)
    if not job:
        return jsonify({"error": "Unknown suggest ID."}), 404
    return jsonify({"status": job["status"], "pairs": job.get("pairs"), "error": job.get("error")})


@app.route("/limits")
def limits_info():
    if g.is_su:
        return jsonify({"is_su": True})
    username = g.username
    now = time.monotonic()
    with _rate_limit_lock:
        req_used = len([t for t in _rate_limit.get(username, []) if now - t < RATE_LIMIT_WINDOW])
    with _throughput_lock:
        rows_used = sum(n for t, n in _throughput.get(username, []) if now - t < RATE_LIMIT_WINDOW)
    with _last_gen_time_lock:
        last_gen = _last_gen_time.get(username or "_anon_", 0)
    remaining = max(0, int(GENERATION_COOLDOWN - (now - last_gen)) + 1) if GENERATION_COOLDOWN and last_gen else 0
    return jsonify({
        "is_su": False,
        "window_seconds": RATE_LIMIT_WINDOW,
        "cooldown_seconds": GENERATION_COOLDOWN,
        "cooldown_remaining": remaining,
        "limits": {
            "max_rows": MAX_ROWS,
            "max_rows_per_window": MAX_ROWS_PER_WINDOW,
            "max_string_length": MAX_STRING_LENGTH,
            "rate_limit_requests": RATE_LIMIT_REQUESTS,
            "generation_timeout": GENERATION_TIMEOUT,
        },
        "used": {
            "requests": req_used,
            "rows": rows_used,
        },
    })


@app.route("/download/<job_id>")
def download(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or job["status"] != "done" or not job.get("result_path"):
        abort(404)
    if job.get("format") == "zip":
        return send_file(
            job["result_path"],
            as_attachment=True,
            download_name=job.get("download_name") or "audio_pack.zip",
            mimetype="application/zip",
        )
    return send_file(
        job["result_path"],
        as_attachment=True,
        download_name=job.get("download_name") or "audio.mp3",
        mimetype="audio/mpeg",
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
