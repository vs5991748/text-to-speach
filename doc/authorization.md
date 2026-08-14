# Authorization

The web interface is protected by **HTTP Basic Authentication**. Every request — pages, uploads, downloads, status checks — requires a valid username and password.

There are two roles:

| Role | Configured via | Limits |
|---|---|---|
| **Superuser (SU)** | `SU_USERS` | None — all limits are bypassed |
| **Regular user** | `USERS` | All limits apply, tracked per username |

---

## Configuration

Users are defined in `.env` as comma-separated `username:password` pairs.
Passwords may contain `:` but not `,`.

```dotenv
# Superusers: no limits apply
SU_USERS=admin:changeme

# Regular users: all limits apply
USERS=alice:alicepass,bob:bobpass
```

Changes take effect after restarting `app.py`.

---

## Adding and removing users

Edit the appropriate variable in `.env` and restart the server:

```dotenv
# Add a second superuser
SU_USERS=admin:changeme,carol:carolpass

# Remove bob, add dave
USERS=alice:alicepass,dave:davepass
```

If the same username appears in both `USERS` and `SU_USERS`, the `SU_USERS` entry wins.

---

## Disabling authentication

Leave both variables empty (the server prints a warning on startup and treats every request as a superuser):

```dotenv
SU_USERS=
USERS=
```

Useful for local development or a fully private network, but **never do this on a public-facing server**.

---

## How it works

The server checks the `Authorization: Basic <credentials>` header on every incoming request using [`secrets.compare_digest`](https://docs.python.org/3/library/secrets.html#secrets.compare_digest) for both username and password — this prevents timing-based attacks.

If the header is missing or incorrect the server responds with:

```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Basic realm="TTS Generator"
```

This causes modern browsers to display their native login dialog automatically.
Once authenticated, the role (SU or regular user) is resolved from the parsed user list and attached to the request for the duration of that request.

---

## Security notes

- Basic Auth transmits credentials as base64 (not encrypted). **Always run behind HTTPS** when accessible from outside localhost.
- A simple nginx reverse-proxy with a Let's Encrypt certificate is the recommended setup for any non-local deployment.
- Avoid short or common passwords — there is no account lockout mechanism.

---

## Example: team setup

```dotenv
# Two admins, no limits
SU_USERS=alice:Tr0ub4dor&3,carol:C@rolPass9

# Three regular users, all limits apply
USERS=bob:bobpass123,dave:davepass456,eve:evepass789
```

---

## Example: testing with curl

```bash
# Superuser — should return 200
curl -u admin:changeme http://localhost:5000/

# Regular user — should return 200
curl -u alice:alicepass http://localhost:5000/

# Wrong password — should return 401
curl -u alice:wrongpassword http://localhost:5000/
```
