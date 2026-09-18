# Two sites, one repo

The live drop and a test drop run the same code from different branches, against
**different Notion databases**, so experimenting can never touch real uploads.

| | Live | Staging |
|---|---|---|
| Streamlit app | `remotefiles.streamlit.app` | `remotefiles-staging.streamlit.app` |
| Branch | `main` | `dev` |
| Notion database | Community File Drop (`c6fc84e8-df91-4bcb-9afa-0dc640c43438`) | Community File Drop (staging) (`1cd887cc-3090-4605-b5b2-64550092faa3`) |
| Secrets file in repo | `deploy-secrets.toml` (gitignored) | `deploy-secrets.staging.toml` (gitignored) |
| Extra secret | — | `STAGING = true` (shows a banner on every page) |
| Local working copy | `~/notion-filedrop` | `~/notion-filedrop-dev` |

The `STAGING = true` flag is the safety belt: both sites show which one you are
looking at, and the staging database is a separate database with the same schema.

## Day-to-day workflow

```bash
cd ~/notion-filedrop-dev          # the copy you experiment in
git switch dev                    # staging branch

# ... edit, then prove it locally before anything is pushed ...
python -m pytest tests -q
python scripts/live_check.py --files 2     # talks to the STAGING database

git commit -am "try out the new thing"
git push                          # staging app rebuilds itself (branch dev)
```

Check `remotefiles-staging.streamlit.app` with a real upload. When it behaves:

```bash
git switch main
git merge dev
git push                          # live app rebuilds
```

Rolling back is `git revert <sha>` on `main` and pushing — the host redeploys on
any push.

## Creating the staging app (once)

<https://share.streamlit.io> → **Create app** → same repository
`Joseph-Run/notion-filedrop`, but:

- Branch: **`dev`**
- Main file path: `Upload.py`
- Advanced settings → Secrets: paste `deploy-secrets.staging.toml`
- Name it `remotefiles-staging`

Two independent apps on the free tier, each sleeping after ~12h idle.

## Which database am I looking at?

The staging app's sidebar shows the same two pages; the difference is the warning
banner at the top of both. In Notion, the staging database has "(staging)" in its
title and lives on its own page, so an unlucky upload is obvious and easy to
delete. To reset staging, delete every row in the staging database — the live
database is untouched.
