# Community File Drop

A two-page website where **anyone can upload a document** and **anyone can download it** —
with Notion as the filing cabinet and the moderator's console.

| Page | URL | Who uses it |
|---|---|---|
| Upload | `/` (`Upload.py`) | Anyone. Type a name, pick one **or several** files, submit. |
| Download | `/Download` (`pages/1_Download.py`) | Anyone. Browse approved documents, pull a copy of each file. |

Once a file is submitted it is **out of the uploader's hands**: there is no edit,
replace or delete path anywhere in the app, and no uploader identity is recorded
that could be used to hand control back. Moderation happens in Notion, not on the
site.

---

## Why there is an app in front of Notion

Notion alone cannot be this site. Three limits decide the architecture:

1. **Public Notion pages are view-only.** "Share to web" grants viewing and
   commenting; it never grants anonymous editing, so a public page cannot be the
   upload form. Notion *forms* can collect anonymous uploads, but a form cannot be
   the download page with a moderation gate (see the alternative below).
2. **Download links expire after one hour.** A file attached through the API comes
   back as a signed `file` url valid for an hour. A static page cannot hold those
   links, so the app re-reads the row and streams fresh bytes on every request —
   the visitor never sees a Notion url.
3. **Notion has no per-row permissions.** Filters on a published database are not a
   security boundary (visitors can switch views), so "hide until approved" has to be
   enforced by the code that queries the database. The app only ever asks for rows
   where `Approved` is ticked.

```
visitor ──▶ Streamlit app ──▶ Notion API ──▶ file storage
                 │                              ▲
                 └── serves the bytes ──────────┘   (fresh signed url, every download)
moderator ──▶ Notion database (tick Approved / delete a row)
```

## What Notion stores

`scripts/setup_notion.py` creates one database with exactly three properties:

| Property | Type | Purpose |
|---|---|---|
| `Name` | title | the label the uploader typed — one row can hold several files |
| `Document` | files | the uploaded file(s), one upload per file |
| `Approved` | checkbox | your moderation switch |

Rename them and set `NOTION_FILE_PROPERTY` / `NOTION_TITLE_PROPERTY` /
`NOTION_APPROVED_PROPERTY` to match — the app reads the names from config.

## Setup

```bash
# 1. Notion integration: https://www.notion.so/my-integrations, copy the token
# 2. Share a page with the integration (page menu  ...  → Connect to → your integration)
export NOTION_API_KEY=ntn_...

python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
# python3 -m venv .venv && .venv/bin/pip install -r requirements.txt    # macOS / Linux

python scripts/setup_notion.py --list-parents          # pages you can build inside
python scripts/setup_notion.py --workspace-parent --title "Community File Drop" \
       --write-secrets .streamlit/secrets.toml

python scripts/live_check.py                           # prove it against the real API
python -m streamlit run Upload.py                      # http://localhost:8501
```

`live_check.py` uploads a small test PDF, confirms the moderation gate holds it
back, approves it over the API, downloads it and compares the bytes, then archives
the test row. It leaves your workspace as it found it.

## Configuration

`.streamlit/secrets.toml` (gitignored; see `secrets.toml.example`):

| Key | Default | Meaning |
|---|---|---|
| `NOTION_API_KEY` | – | integration token (required) |
| `NOTION_DATA_SOURCE_ID` | – | the database to use (required) |
| `REQUIRE_APPROVAL` | `true` | `false` publishes uploads instantly |
| `MAX_UPLOAD_MB` | `50` | per file; above 20 MB the file is sent in parts, hard-capped at Notion's 5 GB |
| `MAX_FILES_PER_UPLOAD` | `10` | how many files one label may carry |
| `MAX_TOTAL_UPLOAD_MB` | `150` | per submission — every chosen file is held in memory at once |
| `ALLOWED_EXTENSIONS` | documents + images + zip | allowlist, extension based |
| `UPLOAD_PASSCODE` | empty | if set, uploading needs a shared word |
| `SITE_NAME` | `Community File Drop` | shown in the UI |
| `NOTION_API_BASE` | `https://api.notion.com` | only for tests |

Notion secrets win over environment variables. Note that in Streamlit ≥ 1.6x
merely *reading* `st.secrets` mirrors the whole `secrets.toml` into `os.environ`,
so an "environment overrides secrets" rule would not actually hold — the tests
therefore inject settings directly instead of relying on env vars.

## Moderating

1. Open the database in Notion.
2. New uploads sit there with `Approved` unticked — invisible to the site.
3. Tick `Approved` to publish, untick to unpublish, delete the row to remove the
   document from the listing.

Deleting a row stops the file being listed, but Notion's API has **no way to
delete an uploaded file** — treat removal as "no longer served", not "erased".

## Deploying it for free

Streamlit Community Cloud (free tier) needs a **public** GitHub repo:

```bash
gh repo create notion-filedrop --public --source . --push   # .gitignore already excludes secrets
```

Then, in the Streamlit Cloud dashboard: new app → pick the repo → main file
`app.py` → paste the same two keys into **Secrets**. Example:
<https://notion-filedrop.streamlit.app>.

Two things to expect on the free tier: the app **sleeps after ~12 hours idle** and
needs someone to click to wake it, and visitors' files pass through the host's
servers.

## Limits worth knowing before you share the link

- **Files up to 50 MB each, 10 per label, 150 MB per submission** out of the box.
  Notion's single-part upload stops at 20 MB, so anything larger is split into 10 MB
  parts and finished with a `/complete` call — the exact same file comes back out on
  download, as the byte-for-byte tests show. Raise `MAX_UPLOAD_MB` up to Notion's 5 GB
  ceiling if you have a paid workspace (the free plan caps uploads at 5 MB regardless),
  and raise the other two caps to match.
- **~3 requests/second** against Notion. Fine for a small drop, not for a crowd.
- **Anonymous uploads are public content.** Nothing stops someone uploading
  something illegal or malicious. The allowlist blocks executables and scripts, and
  `UPLOAD_PASSCODE` stops drive-by uploads, but the real control is the approval
  gate plus the fact that you review every row before it is served.
- **No abuse telemetry**: this app records no IPs or identities, by design. If you
  need that, it has to be added deliberately.

## Testing

```bash
python -m pytest tests -q          # 56 tests: no network, real HTTP against a local fake
python scripts/live_check.py       # the same path, against your actual workspace
python scripts/live_check.py --files 3      # several files under one label
python scripts/live_check.py --big 50       # a 50 MB file, forcing the multi-part path
```

- `tests/fake_notion.py` reproduces Notion's documented request/response shapes,
  including the write-only `file_upload` that returns as a signed, expiring `file`
  url, the 401 on a bad token, the 400 when a send's content type disagrees with the
  one declared at creation, multi-part part/size rules, and query pagination.
- `tests/test_app.py` runs both pages through `AppTest`. `st.file_uploader` has no
  AppTest API, which is why the browser-side upload was verified separately.

## Alternative: no code at all

If you would rather not run an app: Notion **forms** (all plans) include a
*Files & Media* question type and can be shared with *Anyone on the web*, with
anonymous responses — that is a working upload page with zero code, and the
submitter cannot edit their submission. Publish the same database to the web and
that is your download page.

The trade-offs, which is why this app exists: visitors see Notion's branding and a
`notion.site` url rather than your own; the public database exposes *every* view, so
a filter cannot hide pending uploads (you would need a second database for
approved-only rows); and download links are regenerated by Notion on each page load
with no way to control or log them.
