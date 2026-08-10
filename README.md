# PlanWise (v3)

Per-job project controls for WECC / AXIS work, sourced from the shared Vista
extract. This is the ground-up rebuild — see `docs/DECISIONS.md` for what
changed from the 2.0 line and why.

> **Status: scaffold.** The Vista data layer and Cost Breakdown are wired and
> tested. The remaining pages are still being specified in the walkthrough, so
> there is deliberately no navigation yet and the visual design is placeholder.

## Run it

```bat
run.bat
```

Then open <http://127.0.0.1:8771>.

Manually:

```bash
.venv/Scripts/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8771
```

Tests:

```bash
.venv/Scripts/python -m pytest
```

## Where the data comes from

```
Power BI  BIQLDataModelVista        refreshed daily ~3:37 AM
      |
      v   Power Automate flow (cloud, no PC involved)
Vista Model 2026 - Data.xlsx        values-only tables + Meta.as_of
  OneDrive - <tenant>/Company Share - Documents/Vista Model 2026- RH/
      |
      v   read-only open, ~5 s, no sign-in
PlanWise
```

No Entra app registration, no Graph, no admin approval, no credentials.
PlanWise opens the workbook read-only and never writes to it. The same file
feeds the 1910 Legacy Financial Studio, so all three apps agree by construction.

Override the location with `PLANWISE_VISTA_WORKBOOK` (an empty string disables
canonical lookup — that is how the tests isolate).

### The five sheets (schema v2, 2026-08-08)

| Sheet | Grain | Rows (2026-08-08) |
|---|---|---|
| `Pivot Data` | one row per job | 9,318 |
| `WRH Phase Detail` | job x phase x cost type | 127,491 |
| `WRH Job Status` | job -> status / contract type | 9,189 |
| `WRH Contract AR` | contract -> billed / collected / retainage | 9,329 |
| `Meta` | `as_of` stamp + `schema_version` | — |

Schema v2 added MTD cost/hours/billed and unapproved AP to `Pivot Data`,
MTD cost to the phase detail, and the Contract AR sheet. All additive; a v1
workbook still loads with those fields reading *not reported*.

### What Vista does *not* carry

**Open/committed cost** is absent from the Power BI model entirely — all 44
tables were enumerated 2026-08-08; there are no PO tables, and the PO-typed
fact rows carry zero amounts. It is PM-entered until the model owner adds
Vista's PO commitment data. It is the *only* remaining gap: MTD, unapproved
AP, collected, and retainage all landed in schema v2.

## Two rules the code holds to

Both are scar tissue from the 2.0 line:

1. **Blank is not zero.** A blank Vista cell means nothing was reported; zero
   means zero was reported. They stay distinct end to end, and the UI prints
   *not reported*.
2. **Cost types are data, not a constant.** 2.0 hardcoded nine cost types and
   discarded the rest. Here they come from whatever `Cost Type Desc` holds for
   the job in front of you — job 24-003 has seven, another job may have three
   or twelve.

## Layout

| Path | What |
|---|---|
| `backend/config.py` | Workbook discovery, data dir, staleness threshold |
| `backend/vista.py` | The Vista reader — sheet contract, cache, rollups |
| `backend/app.py` | FastAPI: `/api/health`, `/api/jobs`, `/api/jobs/{n}` |
| `frontend/` | No-build SPA (placeholder styling) |
| `tests/` | 12 tests, synthetic workbooks — never reads the real file |

## Related apps

Same Vista source, different scope. The three converge into one shell later.

| App | Scope | Owns |
|---|---|---|
| 1910 Legacy Financial Studio | all 9,298 jobs | portfolio financials, discovery |
| SiteScope | all history | documents, email, lessons learned, ask |
| **PlanWise** | **one job, deep** | schedule, COs, POs, subs, RFIs, field |
