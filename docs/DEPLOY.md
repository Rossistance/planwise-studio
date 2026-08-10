# Deploying PlanWise to Render

Decision D27 moved PlanWise off "a PC on the LAN" onto a hosted service. This
is the whole procedure. It takes about twenty minutes, most of which is
waiting for a build.

## Before you start

**PlanWise needs a paid Render instance type.** Not for CPU — for a *persistent
disk*. Render's container filesystem is ephemeral: on the free plan every
deploy and every restart would wipe the database and every uploaded drawing.
There is no version of this app that works without a disk.

**Render deploys from a Git repository**, and this folder isn't one yet:

```bash
git init && git add -A && git commit -m "PlanWise v3"
```

Check `.gitignore` did its job before you push anywhere — `git status` should
show no `.xlsx`, no `*.db`, and no `.planwise/`. The Vista extract is 7.6MB of
company financials and must never be committed; it arrives by push instead
(Phase 5b).

## 1. Create the service

Point Render at the repository. `render.yaml` in the root is a Blueprint, so
Render reads the service definition, the disk, and the environment variables
from it — you shouldn't need to fill much in by hand.

Two settings in that file are load-bearing and should not be changed:

- **`numInstances: 1`.** PlanWise keeps everything in SQLite on the disk (D9:
  one shared database, 5–6 concurrent writers). SQLite is perfectly happy with
  that from one process and thoroughly unhappy shared between instances. A
  Render disk can only attach to one instance anyway, so this mostly documents
  the constraint — but do not raise it.
- **`--proxy-headers --forwarded-allow-ips '*'`** in the start command. Render
  terminates TLS at its edge and forwards plain HTTP into the container.
  Without these the app believes every request arrived over HTTP, and the
  session cookie silently loses its `Secure` flag on the one deployment where
  it matters. (`backend/app.py::_is_https` also reads `X-Forwarded-Proto`
  directly, so this is belt and braces.)

If the build fails on the Python version, `PYTHON_VERSION` in `render.yaml` and
`.python-version` are the one knob — they're pinned to 3.12.7, which is
conservative; local development runs 3.14.

## 2. Claim the instance

Open the service URL. Because no account exists yet you'll get **Set up
PlanWise**, which asks for a setup token.

That token is written to the data directory and printed to the log, so having
it proves you can reach the machine rather than merely knowing its address.
Find it in Render's **Logs** tab:

```
[PlanWise] No administrator yet. Setup token: <token>
```

Enter it with your name and a password. That creates the first administrator
and signs you in. The token is spent immediately — a second attempt is refused.

Then add the rest of the team under **Settings → Users**. Each person gets a
temporary password they're required to change on first sign-in, so you never
know their password afterwards.

## 3. Feed it the Vista extract

The app has no financial data until the daily extract reaches it, and a Linux
container has no OneDrive to sync. `vista_pull.py` — which already runs daily
on Ross's PC and already uploads to SharePoint — pushes it as well, given two
environment variables on **that machine**:

| Variable | Value |
|---|---|
| `PLANWISE_URL` | `https://planwise-xxxx.onrender.com` |
| `PLANWISE_INGEST_TOKEN` | copy from Render → Environment → `PLANWISE_INGEST_TOKEN` |

Set them for the scheduled task's account, not just your interactive shell, or
the unattended run won't see them. Then force a run and watch for:

```
pushed to PlanWise: 9,298 jobs, 127,549 phase rows, as_of ...
```

`/api/health` should flip from `workbook_found: false` to a live job count.

A push that doesn't parse is **refused** and the previous workbook stays live,
so a bad extract fails loudly for the pull run instead of quietly breaking the
app for six people. A push failure fails the whole pull run on purpose: a
hosted app serving yesterday's numbers while the run reports success is the
exact failure mode the dead SharePoint sync mount taught us to refuse.

## 4. The companion, on each person's PC

Mail still flows through each person's own Outlook (D10) — the *browser* calls
`http://127.0.0.1:8772`, so it does not care that PlanWise is now hosted. It is
also what makes detection fast: it watches Outlook's own events, so a customer
reply reaches PlanWise in about a second (D35).

**This is the only thing teammates install.** PlanWise itself is a URL.

### Building it

```bash
python -m PyInstaller planwise-companion.spec --noconfirm
```

That produces `dist/PlanWiseCompanion.exe` — about 18MB, one self-contained
file with the interpreter and every dependency inside, so it needs no Python,
no pip and no admin rights. Handing someone that file is a complete install:
on first run it registers itself in Startup and opens its own pairing page.

For a proper installer (Start-menu entry, uninstall, pairing collected during
setup), install [Inno Setup 6](https://jrsoftware.org/isdl.php) and run:

```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\companion.iss
```

which writes `dist/PlanWiseCompanion-1.0.0-Setup.exe`. It's a **per-user**
install by design — no admin, and the companion drafts into the mailbox of
whoever is signed in, so a per-machine install would be wrong anyway.

### What a teammate does

1. Run it. There's no window — it's a background service.
2. It opens a pairing page at `http://127.0.0.1:8772/pair`.
3. Paste the PlanWise address and the pairing token from **Settings**.

That's it. It starts with Windows from then on. If they run it again it says
it's already running rather than starting a second copy — two would double-file
every reply and fight each other for Outlook.

To check on it: the companion chip in PlanWise reports whether Outlook is
connected and whether the live watch is up. Its log is at
`~/.planwise/companion.log`.

### Re-pairing

Deleting `~/.planwise/companion_token.txt` un-pairs it, and the pairing page
comes back. The `/pair` endpoint only accepts a **first** pairing and refuses
cross-origin callers, so a page someone happens to visit cannot silently
re-point a working companion at another server.

## What lives where

Everything PlanWise owns is under `PLANWISE_DATA_DIR` (`/var/data` on Render),
which is the disk:

```
/var/data/
  planwise.db              SQLite — jobs, COs, POs, records, schedule, look aheads
  documents/               uploaded drawings
  replies/                 returned attachments from customer replies
  vista/                   the pushed extract, plus one previous copy
  setup_token.txt          first-run only, deleted once claimed
  companion_token.txt      the companion pairing secret
```

About 4MB today, so the 1GB disk is years of headroom. The extract itself needs
no backup — the next pull regenerates it.

### Backing up the database

**Copying `planwise.db` is not a backup.** SQLite runs in WAL mode, so recent
commits live in `planwise.db-wal` until a checkpoint folds them back in. On a
working instance that file is routinely *larger than the database itself* — it
was 1.3MB against a 270KB `.db` when this was written, i.e. copying just the
`.db` would have silently lost almost everything recent. (Found the hard way:
a copied database came up with the look-ahead empty.)

Either copy all three files (`planwise.db`, `-wal`, `-shm`) with the app
stopped, or — better, and safe while it's running — let SQLite do it:

```bash
python -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" /var/data/planwise.db /tmp/planwise-backup.db
```

A Render disk snapshot captures the whole filesystem and is therefore fine as
it stands.
