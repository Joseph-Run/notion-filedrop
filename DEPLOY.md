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
4. Open **Advanced settings → Secrets** and paste the contents of
   `deploy-secrets.toml` from this project (it holds the real values — replace
   nothing, but do not commit it; `.gitignore` covers it). Format:

   ```toml
   NOTION_API_KEY = "ntn_..."          # the whole token, quotes included, no more
   NOTION_DATA_SOURCE_ID = "..."
   REQUIRE_APPROVAL = true
   MAX_UPLOAD_MB = 50
   ```

   Optional: `UPLOAD_PASSCODE = "shared-word"` to stop drive-by uploads,
   `SITE_NAME = "Your Drop Name"`, `ALLOWED_EXTENSIONS = "pdf,docx,xlsx,csv"`.

5. **Deploy**. First build takes a couple of minutes; you get a
   `https://<app-name>.streamlit.app` URL for both pages (`/` uploads, `/Download`).

## Troubleshooting

**`AttributeError` naming something that exists in the repo (e.g. `settings.max_total_upload_bytes`)**
— the running instance is serving a *new* entrypoint with *old* imported modules.
Streamlit Cloud pulls new files into `/mount/src/<repo>` and re-reads the entrypoint
on every rerun, but `sys.modules` stays cached until the Python process restarts; a
browser reload does **not** clear it. Fix: **Manage app** (lower right) → ⋮ →
**Reboot app**. Any push to `main` usually triggers a clean rebuild too.

**"Upload failed: Notion 401 unauthorized ... API token is invalid"** — the app is
holding a token that is not a real one. The most common causes, in order:

1. The literal placeholder from these docs was pasted instead of the token. If the
   value inside the quotes starts with anything other than `ntn_`/`secret_`, it is
   wrong.
2. A second pair of quotes, so the value literally is `"ntn_..."` including the
   quote characters.
3. A truncated paste, or a token from an integration that was rotated/revoked.

Fix: dashboard → your app → **Settings → Secrets**, replace the values, save (the
app restarts itself). Confirm from this machine with:

```bash
python scripts/live_check.py        # 200s everywhere means the token in
                                    # .streamlit/secrets.toml is good
```

**"Upload failed: A Notion integration token is required"** — no secrets reached
the app at all. On Streamlit Cloud that means the Secrets box is empty; locally it
means `streamlit run` was started outside the project folder.

**404 `object_not_found` on a page or data source** — the token is valid but the
integration was never given access: in Notion open the page → `...` → *Connect to*
→ your integration.

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
