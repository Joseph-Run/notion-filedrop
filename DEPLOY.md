# Deploying the file drop

Everything is prepared; the remaining steps need an account login that only you can
perform. Total time: about three minutes.

## 1. Prerequisites (already done on this machine)

- Public GitHub repo: <https://github.com/Joseph-Run/notion-filedrop>
- Notion integration + database, with `NOTION_DATA_SOURCE_ID` in
  `.streamlit/secrets.toml` (never commit that file — `.gitignore` covers it)

## 2. Streamlit Community Cloud (free)

1. Go to <https://share.streamlit.io> → **Continue to sign-in** → authorize with GitHub.
2. **Create app** → **Deploy a public app from GitHub**.
3. Fill in:
   - Repository: `Joseph-Run/notion-filedrop`
   - Branch: `main`
   - Main file path: `Upload.py`
4. Open **Advanced settings → Secrets** and paste:

   ```toml
   NOTION_API_KEY = "ntn_your_integration_token"
   NOTION_DATA_SOURCE_ID = "your-data-source-id"
   REQUIRE_APPROVAL = true
   MAX_UPLOAD_MB = 50
   ```

   Optional: `UPLOAD_PASSCODE = "shared-word"` to stop drive-by uploads,
   `SITE_NAME = "Your Drop Name"`, `ALLOWED_EXTENSIONS = "pdf,docx,xlsx,csv"`.

5. **Deploy**. First build takes a couple of minutes; you get a
   `https://<app-name>.streamlit.app` URL for both pages (`/` uploads, `/Download`).

## 3. After it is live

- Open the app URL, upload a file, confirm it says it is pending review.
- In Notion, open the **Community File Drop** database and tick **Approved** —
  the file appears on the download page.
- Re-run the local end-to-end check any time (it exercises the real API):
  `python scripts/live_check.py` or `python scripts/live_check.py --big 50`.

## Things to expect on the free tier

- The app **sleeps after ~12 hours idle**; the first visitor clicks to wake it.
- Uploaded files pass through Streamlit's servers on their way to Notion.
- Editing a secret in the dashboard restarts the app.
- The free host has its own per-file upload cap (~200 MB), so `MAX_UPLOAD_MB = 50`
  stays well inside it.

## Alternatives if you outgrow it

| Host | Why | Catch |
|---|---|---|
| Cloudflare Workers + R2 | Always on, custom domain, files never transit a third party | Needs adapters (the app's core calls Notion directly; only the UI layer would change) |
| Fly.io / Render | Always on, real server, custom domain | Free tiers are limited or gone; a card may be required |
| Hugging Face Spaces | Free CPU tier | Creating a Docker/Gradio Space now requires a paid plan |
| Your own box + Tailscale Funnel | Full control, no sleep | You keep the lights on |
