# Google Drive Upload

After generating a listening track, the web UI can upload the result (the
single MP3, or the ZIP in split mode) straight to the user's own Google
Drive, in addition to the regular download link. Each web-app user
(`USERS`/`SU_USERS`) connects their **own** Google account separately —
there is no shared/admin Drive.

The app only ever creates a folder and uploads files into it. This isn't
just an app-level convention: the OAuth scope requested
(`drive.file`) technically limits the app to files/folders it created
itself — it cannot see, list, or modify anything else in the user's Drive,
even if the code had a bug that tried to.

---

## Google Cloud Console setup (one-time, per deployment)

You need this before the feature can be used at all — it can't be created
from inside this repo, it's external Google account configuration. Full
step-by-step instructions (with troubleshooting for the errors you're
most likely to hit) are in
**[google-cloud-setup.md](google-cloud-setup.md)**.

The short version: enable the Drive API, configure the OAuth consent
screen with the `drive.file` scope, create a Web application OAuth
client with your callback URL(s) as Authorized redirect URIs, then put
the resulting Client ID/Secret in `.env`:

```dotenv
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:5000/auth/google/callback
```

Leaving any of these three blank disables the feature entirely — the
"Connect Google Drive" / "Upload to Google Drive" UI simply doesn't appear.

---

## How the connection works

1. On the result page, after a job finishes, a user who hasn't connected
   Drive sees **Connect Google Drive**. Clicking it redirects to Google's
   consent screen (`/auth/google` → Google → back to
   `/auth/google/callback`).
2. On success, the app stores that user's refresh token (keyed by their
   web-app username) and redirects back to `/` with a confirmation banner.
3. From then on, **Upload to Google Drive** is shown instead. Clicking it
   uploads the current job's file into a top-level folder named
   `GOOGLE_DRIVE_FOLDER_NAME` (default `TTS Audio`) in that user's Drive —
   created once, reused for every later upload.

Access tokens are refreshed automatically using the stored refresh token
when they expire; the user never has to reconnect unless they explicitly
disconnect (`POST /auth/google/disconnect`) or revoke access from their
Google Account settings.

---

## Token storage and its limits

Per-user refresh tokens are stored in `.google_tokens.json` next to
`app.py` (never committed — see `.gitignore`). This is deliberately more
durable than the in-memory job stores elsewhere in the app (see
`AGENTS.md`'s deployment note), since a refresh token is meant to be a
long-lived credential — but it's still a single flat file on one machine:

- **Single gunicorn worker / single instance only**, same assumption as
  the rest of the app's in-memory state (`Procfile`, `gunicorn.conf.py`).
  Multiple workers writing to this file concurrently isn't safe.
- If you redeploy to a fresh filesystem (e.g. most PaaS deploys), the file
  is gone and every user needs to reconnect. Persisting it across deploys
  would need the same kind of shared store called out in `AGENTS.md` for
  scaling beyond one worker — out of scope for this feature.

---

## Full reference

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_CLIENT_ID` | *(blank = disabled)* | OAuth client ID from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | *(blank = disabled)* | OAuth client secret |
| `GOOGLE_REDIRECT_URI` | *(blank = disabled)* | Must exactly match an Authorized redirect URI on the OAuth client |
| `GOOGLE_DRIVE_FOLDER_NAME` | `TTS Audio` | Top-level folder name created in each user's Drive |
