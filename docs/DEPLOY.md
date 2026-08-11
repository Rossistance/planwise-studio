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

**Give your own account an email address** right after this, under
**Settings → Users → Add email**. The bootstrap account is created with a name
only, which still works — one sign-in field accepts either — but everything
else (and the companion) assumes an address.

## 2a. How everyone else gets in

They don't need anything from you. Send them the URL; they choose **Create an
account** (work email, first and last name, a password), and land on a waiting
screen. You get a push notification, approve them under **Settings → Users**,
and their screen lets them through within a few seconds — no reload, no second
sign-in.

Approval is not a formality. PlanWise is on a public URL carrying Vista
financials for every job, and there is no email verification anywhere in the
system — no server-side mail exists to send one. **The approval screen is the
verification**, which is why the pending list shows the email address rather
than the name someone typed. Approve addresses you recognise.

Everything else in that list is there too: disable an account (its sessions die
immediately), reset a password (they're made to change it), grant or remove
admin, or remove someone entirely. You cannot remove or demote the last
administrator, and you cannot remove yourself.

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

## 4. The companion, on each person's PC — optional

Mail still flows through each person's own Outlook (D10) — the *browser* calls
`http://127.0.0.1:8772`, so it does not care that PlanWise is now hosted. It is
also what makes detection fast: it watches Outlook's own events, so a customer
reply reaches PlanWise in about a second (D35).

**Nobody has to install it.** PlanWise is a URL, and sharing works without it:
every share button offers **Download email (.eml)** — a file with recipients,
subject, body and the PDF already in place that opens in that PC's own Outlook
as an editable draft. Review, press Send. That is the path for a coworker's
machine, a conference room, or a demo.

What you lose without a companion: drafting directly into Outlook in one click,
and automatic reply capture. A `.eml` sent by hand isn't seen by PlanWise, so
its RFI stays "sent" until someone marks it. Install the companion on the
machines where RFI and submittal correspondence actually happens; skip it
everywhere else.

Two notes on the `.eml` files. **Classic** Outlook opens them for editing —
"new" Outlook and OWA may open them read-only; classic is the company standard
anyway, since COM requires it. And a downloaded file stays in that machine's
Downloads folder, so treat an internal look-ahead on a shared PC like any other
downloaded document.

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
2. It opens a page at `http://127.0.0.1:8772/pair`.
3. They sign in with **their own PlanWise email and password**.

That's the whole thing. There is no token to copy, and nothing for you to send
them: the password is relayed to PlanWise to prove who they are and is never
written to disk here — what lands on this PC is a token scoped to the two
endpoints a companion writes to, belonging to that one person.

It starts with Windows from then on. If they run it again it says it's already
running rather than starting a second copy — two would double-file every reply
and fight each other for Outlook.

To check on it: the companion chip in PlanWise reports whether Outlook is
connected, whether the live watch is up, and — if the companion belongs to
someone else — says so plainly, because drafting from that PC would put your
mail in their Sent Items. Its log is at `~/.planwise/companion.log`.

### Re-pairing

Run `PlanWiseCompanion.exe --pair` (or delete `~/.planwise/companion_auth.json`)
and the sign-in page comes back. The `/pair` endpoint only accepts a **first**
pairing and refuses cross-origin callers, so a page someone happens to visit
cannot silently re-point a working companion at another server.

A companion still holding the pre-2026-08-10 `companion_token.txt` reads as
**unpaired** on purpose, so upgrading a PC sends it to the sign-in page instead
of telling it that it is already set up. The old file is deleted once the new
pairing succeeds.

**One-time cutover.** The server still accepts that old company-wide token so
installed companions keep filing replies until each PC re-pairs. Once everyone
has signed in — check `~/.planwise/companion_auth.json` exists on each machine —
remove `_legacy_companion_token_ok` and its two call sites in `backend/app.py`,
along with `ai.companion_token()`. Until then a leaked copy of the old token
still buys those two endpoints.

## What lives where

Everything PlanWise owns is under `PLANWISE_DATA_DIR` (`/var/data` on Render),
which is the disk:

```
/var/data/
  planwise.db              SQLite — jobs, COs, POs, records, schedule, look aheads,
                           accounts and their per-user companion tokens
  documents/               uploaded drawings
  replies/                 returned attachments from customer replies
  vista/                   the pushed extract, plus one previous copy
  setup_token.txt          first-run only, deleted once claimed
  vapid_key.json           push-notification keypair — regenerating orphans
                           every subscribed device
  companion_token.txt      legacy company-wide pairing token; delete after the
                           cutover above
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
