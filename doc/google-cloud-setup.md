# Registering the App in Google Cloud Console

Step-by-step instructions for creating the OAuth 2.0 credentials
(`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`) that the Google Drive upload
feature needs. This is done once per deployment, entirely in Google's own
console — nothing here touches this repo.

See [google-drive.md](google-drive.md) for how the feature behaves once
these credentials are in place.

---

## Prerequisites

- A Google account (any regular Google/Gmail account works — you don't
  need Google Workspace).
- Know the URL(s) this app will run on: at minimum your local dev URL
  (`http://localhost:5000`) and, once deployed, your production URL (e.g.
  `https://your-app.onrender.com`).

---

## Step 1 — Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and
   sign in.
2. Click the project dropdown at the top of the page (next to "Google
   Cloud") → **New Project**.
3. Give it a name (e.g. "TTS Listening Track Generator") and click
   **Create**.
4. Wait for the notification that the project was created, then select it
   from the project dropdown so it's the active project.

If you already have a project you want to reuse, just select it instead of
creating a new one — skip to Step 2.

---

## Step 2 — Enable the Google Drive API

1. In the left sidebar (☰), go to **APIs & Services → Library**.
2. Search for **Google Drive API**.
3. Click it, then click **Enable**.

Without this step, every Drive API call the app makes will fail with an
error like "Google Drive API has not been used in project ... before or it
is disabled."

---

## Step 3 — Configure the OAuth consent screen

This is the screen your users (or you, testing) will see when they click
"Connect Google Drive."

1. **APIs & Services → OAuth consent screen**.
2. **User Type**:
   - **External** — works for any Google account, including yours. Choose
     this unless you're on Google Workspace and want to restrict the app
     to your organization only.
   - **Internal** — only available if the project belongs to a Google
     Workspace organization; restricts sign-in to that organization's
     accounts, and skips the "Testing" restrictions below entirely.
3. Click **Create**, then fill in the required fields on the next screen:
   - **App name** — shown on the consent screen (e.g. "TTS Listening
     Track Generator").
   - **User support email** — your email.
   - **Developer contact information** — your email again.
   - Leave the logo, app domain, and other optional fields blank unless
     you want them.
4. Click **Save and Continue**.
5. **Scopes** screen: click **Add or Remove Scopes**, and in the filter
   box paste:
   ```
   https://www.googleapis.com/auth/drive.file
   ```
   Check it in the list, click **Update**, then **Save and Continue**.
6. **Test users** screen (External + Testing mode only — skipped for
   Internal): click **Add Users** and add the Google account email(s) that
   should be able to connect Drive from this app — including your own, if
   you'll be testing it. **Any Google account not listed here will get an
   "Access blocked" error when they try to connect**, until you either add
   them here or publish the app (see Troubleshooting below).
7. Click **Save and Continue**, review the summary, then **Back to
   Dashboard**.

---

## Step 4 — Create the OAuth Client ID

1. **APIs & Services → Credentials**.
2. Click **+ Create Credentials → OAuth client ID**.
3. **Application type**: **Web application**.
4. **Name**: anything recognizable (e.g. "TTS web app").
5. **Authorized redirect URIs** — click **+ Add URI** and add the exact
   callback URL this app uses, for every environment you'll run it in:
   - Local dev: `http://localhost:5000/auth/google/callback`
   - Production, once deployed: `https://your-app.onrender.com/auth/google/callback`
     (replace with your actual domain)

   These must match **exactly** — same scheme (`http`/`https`), same host,
   same path, no trailing slash — or Google will reject the redirect with
   `redirect_uri_mismatch`.
6. Click **Create**.
7. A dialog shows your **Client ID** and **Client Secret** — copy both
   now. You can always come back to **APIs & Services → Credentials** and
   click the credential's name to see the Client ID again, but the Client
   Secret is only fully shown a limited number of times before you'd need
   to reset it, so save it somewhere safe (e.g. directly into `.env`) right
   away.

---

## Step 5 — Put the credentials in `.env`

```dotenv
GOOGLE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-secret-here
GOOGLE_REDIRECT_URI=http://localhost:5000/auth/google/callback
```

Use the redirect URI matching whichever environment you're running right
now — switch it (and re-check it's in the Authorized redirect URIs list
from Step 4) when you move from local dev to production.

Restart the app so it picks up the new environment variables. The
"Connect Google Drive" button should now appear on the result page after
generating a track.

---

## Troubleshooting

**"Access blocked: this app's request is invalid" / "Error 403:
access_denied"** — the signed-in Google account isn't in the Test users
list (Step 3.6) and the app isn't published. Either add that account as a
test user, or publish the OAuth consent screen (App → **Publish App** —
note this may trigger Google's verification process if you request
sensitive scopes, though `drive.file` is a narrow, low-sensitivity scope
that's less likely to require full verification).

**"Error 400: redirect_uri_mismatch"** — the `GOOGLE_REDIRECT_URI` in
`.env` doesn't exactly match an entry in the OAuth client's Authorized
redirect URIs (Step 4.5). Check for `http` vs `https`, a trailing slash,
or a different port.

**Consent screen appears but no refresh token comes back, or you get
stuck reconnecting** — this app always requests `prompt=consent`
specifically so Google re-issues a refresh token every time, but if you
still hit this, revoke the app's access from
[myaccount.google.com/permissions](https://myaccount.google.com/permissions)
and try connecting again from a clean state.

**"This app isn't verified" warning screen** — expected in Testing mode
for External apps; click **Advanced → Go to (app name) (unsafe)** to
proceed. This warning is about Google not having reviewed the app, not
about anything being actually wrong with it.
