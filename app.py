#!/usr/bin/env python3
"""Flask web interface for the TTS audio generator."""

import base64
import json
import os
import re
import secrets
import shutil
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

# Default provider for all users; SU users can get a separate default
LLM_DEFAULT = os.getenv("LLM_DEFAULT", "openrouter").strip().lower()
LLM_SU_DEFAULT = os.getenv("LLM_SU_DEFAULT", "").strip().lower()

# Built-in base URLs; override with LLM_<PROVIDER>_BASE_URL
_LLM_DEFAULT_URLS = {
    "openrouter": "https://openrouter.ai/api",
    "groq": "https://api.groq.com/openai",
    "ollama": "http://localhost:11434",
}
_LLM_DEFAULT_MODELS = {
    "openrouter": "meta-llama/llama-3.1-8b-instruct:free",
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

from generate_audio import build_split_tracks, build_track, load_pairs, parse_voice_overrides, resolve_voice, _slugify, _slice_pairs
from tts_engines import LANG_VOICES

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

ALLOWED_EXTENSIONS = {".csv", ".json"}


def _call_llm(cfg: dict, word: str, learning_lang: str, translation_lang: str) -> dict:
    """Call an OpenAI-compatible LLM and return {learning, translation} pair."""
    trans_part = (
        f' Then translate the sentence into the language with code "{translation_lang}".'
        if translation_lang else ""
    )
    trans_field = ', "translation": "<translation>"' if translation_lang else ""
    prompt = (
        f'You are a language learning assistant. '
        f'Write one short, natural, everyday sentence in the language with code "{learning_lang}" '
        f'that uses or illustrates the word or phrase "{word}".'
        f'{trans_part} '
        f'Respond with ONLY valid JSON, no extra text: '
        f'{{"learning": "<sentence>"{trans_field}}}'
    )
    payload = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8,
        "max_tokens": 150,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(
        f"{cfg['base_url']}/v1/chat/completions", data=payload, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"].strip()
    if "```" in content:
        content = re.sub(r"```(?:json)?", "", content).strip()
    m = re.search(r"\{[^}]+\}", content, re.DOTALL)
    return json.loads(m.group() if m else content)


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
                           known_voices=LANG_VOICES,
                           is_su=g.is_su,
                           llm_enabled=bool(_llm_config_for(g.username, g.is_su)),
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

    file_id = str(uuid.uuid4())
    with _uploads_lock:
        _uploads[file_id] = {"path": tmp.name, "count": len(pairs)}

    return jsonify({"file_id": file_id, "langs": langs, "count": len(pairs),
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
        _jobs[job_id] = {"status": "pending", "result_path": None, "error": None, "format": None}

    thread = threading.Thread(
        target=_run_generation,
        args=(job_id, input_path, learning_lang, target_speeds,
              pause_after_target, pause_after_translation, no_translation, voice_override_pairs,
              split, output_dir, rows_spec),
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
                    split, output_dir, rows_spec):
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
                zip_path = os.path.join(output_dir, "audio_pack.zip")
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fname in sorted(f for f in os.listdir(output_dir) if f.endswith(".mp3")):
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

        with _jobs_lock:
            if _jobs[job_id]["status"] != "error":  # not already timed out
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result_path"] = result_path
                _jobs[job_id]["format"] = result_format

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
    data = request.get_json(silent=True) or {}
    word = str(data.get("word", "")).strip()
    learning_lang = str(data.get("learning_lang", "")).strip()
    translation_lang = str(data.get("translation_lang", "")).strip()
    if not word or not learning_lang:
        return jsonify({"error": "word and learning_lang are required."}), 400
    try:
        result = _call_llm(cfg, word, learning_lang, translation_lang)
        if "learning" not in result:
            raise ValueError("LLM response missing 'learning' field.")
        return jsonify(result)
    except urllib.error.URLError as e:
        return jsonify({"error": f"Cannot reach LLM: {e.reason}"}), 502
    except Exception as e:
        return jsonify({"error": f"LLM error: {e}"}), 500


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
            download_name="audio_pack.zip",
            mimetype="application/zip",
        )
    return send_file(
        job["result_path"],
        as_attachment=True,
        download_name="audio.mp3",
        mimetype="audio/mpeg",
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
