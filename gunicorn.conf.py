import os

# Worker timeout — must be longer than LLM_TIMEOUT_SECONDS * (LLM_MAX_RETRIES + 1) + overhead
timeout = int(os.getenv("GUNICORN_TIMEOUT", 180))
workers = int(os.getenv("WEB_CONCURRENCY", 1))
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
