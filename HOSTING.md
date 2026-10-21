# Hosting

The app runs on Streamlit Community Cloud and reads a PostgreSQL database on Neon. Neither holds anything private:
the data is synthetic, and the app connects with a role that can only read.

## What to expect

- **The first visit after a quiet spell is slow.** Streamlit's free tier puts idle apps to sleep, and Neon's free tier
  suspends an idle database after about 5 minutes. A sleeping app shows a "wake up" button; the first page then takes
  roughly 10 to 30 seconds. After that it is fast. The app reconnects on its own if the database dropped the connection.
- **Credentials never live in the repo.** The app's connection string is in Streamlit's Secrets box. The admin
  connection string is only ever typed into a local terminal.

## One-time setup

1. **Neon:** create a project and a database. Copy the *admin* connection string (Connect > pick the role that owns the database).
2. **Load the data** (admin string stays in your shell, not in a file):
   ```
   read -s DATABASE_URL; export DATABASE_URL     # paste, press Enter (nothing is shown)
   make create-readonly-role                     # asks for a new password (16+ characters)
   make build-remote                             # builds the tables and views and lets app_readonly read them
   ```
   Create the role with this command, **not** in Neon's console: console-created roles are members of `neon_superuser`
   and can write.
3. **Verify the read-only role:**
   ```
   read -s APP_DATABASE_URL; export APP_DATABASE_URL    # paste the app_readonly connection string
   make verify-hosting
   ```
   Every line must say PASS.
4. **Streamlit Community Cloud:** New app, this repo, branch `main`, main file `app/Home.py`, Python 3.12 or 3.13.
   Under Advanced settings > Secrets paste (see `.streamlit/secrets.toml.example`):
   ```
   DATABASE_URL = "postgresql://app_readonly:...@...neon.tech/...?sslmode=require"
   ```
5. Open the live link in a private window and click through all five pages.

## Rebuilding

`make build-remote` drops and recreates every table, then re-grants read access. `make build` (no `--remote`) refuses to
run against anything but a local database.
