"""Google Drive OAuth + upload helpers.

Uses the `drive.file` scope only — the app can create files/folders and
manage the ones it created, but cannot see or touch anything else in the
user's Drive. No Google client library; plain urllib requests, matching
the style already used for LLM provider calls in app.py.
"""
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Optional

TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"

SCOPE = "https://www.googleapis.com/auth/drive.file"


class DriveError(RuntimeError):
    pass


def _post_form(url: str, fields: dict, timeout: int = 30) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise DriveError(f"HTTP {e.code}: {body}") from e


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # ensures a refresh_token is returned even on re-auth
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> dict:
    """Returns {access_token, refresh_token, expires_in, ...}."""
    return _post_form(TOKEN_URL, {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    """Returns {access_token, expires_in, ...} — no new refresh_token is issued."""
    return _post_form(TOKEN_URL, {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    })


def revoke_token(token: str) -> None:
    try:
        _post_form(REVOKE_URL, {"token": token})
    except DriveError:
        pass  # best-effort — token may already be invalid/expired


def _api_request(method: str, url: str, access_token: str, body: Optional[bytes] = None,
                  content_type: Optional[str] = None, timeout: int = 30) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:500]
        raise DriveError(f"HTTP {e.code}: {body_text}") from e


def find_or_create_folder(access_token: str, folder_name: str) -> str:
    """Returns the folder's file ID, reusing an existing top-level folder with this
    exact name if one (created by this app) already exists."""
    escaped = folder_name.replace("\\", "\\\\").replace("'", "\\'")
    query = (
        f"mimeType='application/vnd.google-apps.folder' and name='{escaped}' "
        f"and trashed=false and 'root' in parents"
    )
    params = urllib.parse.urlencode({"q": query, "fields": "files(id,name)", "spaces": "drive"})
    result = _api_request("GET", f"{DRIVE_FILES_URL}?{params}", access_token)
    files = result.get("files") or []
    if files:
        return files[0]["id"]

    metadata = json.dumps({"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}).encode()
    created = _api_request("POST", DRIVE_FILES_URL, access_token, body=metadata,
                            content_type="application/json; charset=UTF-8")
    return created["id"]


def upload_file(access_token: str, folder_id: str, file_path: str, filename: str) -> dict:
    """Uploads file_path into folder_id, named `filename`. Returns {id, name, webViewLink}."""
    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        media = f.read()

    boundary = uuid.uuid4().hex
    metadata = json.dumps({"name": filename, "parents": [folder_id]}).encode()
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode() + metadata + (
        f"\r\n--{boundary}\r\n"
        f"Content-Type: {mimetype}\r\n\r\n"
    ).encode() + media + f"\r\n--{boundary}--".encode()

    params = urllib.parse.urlencode({"uploadType": "multipart", "fields": "id,name,webViewLink"})
    return _api_request(
        "POST", f"{DRIVE_UPLOAD_URL}?{params}", access_token, body=body,
        content_type=f"multipart/related; boundary={boundary}",
        timeout=120,
    )
