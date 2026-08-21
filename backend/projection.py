"""PlanWise's own cost-at-completion — arithmetic, not augury.

The owner's ask (2026-08-20): the forecast chart should be able to say where
the job LANDS using what the app already knows — contract, open change
orders, open purchase orders — with no AI anywhere in the math. Vista carries
its own Projected Cost, but on many jobs that field is zero or just echoes
the estimate; this figure exists so the chart's endpoint is never blank and
always explainable.

Two independent readings, and the projection is the LARGER — costs at
completion are ratcheted by commitments, not averaged with hopes:

* the COMMITTED FLOOR — cost already on the books, plus every dollar already
  promised out (open PO value not yet invoiced), plus approved subcontractor
  change orders that have no PO yet (the exposure column). Nothing modeled:
  each term is a register total.
* the BURN READING — actual cost divided by Vista's percent complete: where
  the job lands if the rest costs what the done part did. Skipped below 5%
  complete, where the ratio is one mobilization invoice pretending to be a
  trend.

Every component ships with the number so the UI can show its work.
"""
from __future__ import annotations

from typing import Any

from . import store

# Below this, percent-complete is noise and the burn reading abstains.
MIN_PCT_FOR_BURN = 0.05


def for_job(job_number: str, job: dict[str, Any]) -> dict[str, Any]:
    """The projection and its ledger of components.

    `job` is the Vista snapshot row (actual_cost, pct_complete,
    projected_cost, current_estimate, current_contract) — passed in so this
    stays a pure derivation over already-loaded facts plus two register
    sums, and tests can hand it any world they like.
    """
    actual = float(job.get("actual_cost") or 0)
    open_po = round(sum(store.open_committed_by_cost_type(job_number).values()), 2)
    exposure = round(float((store.approved_no_po(job_number) or {}).get("total") or 0), 2)
    committed_floor = round(actual + open_po + exposure, 2)

    pct = float(job.get("pct_complete") or 0)
    if pct > 1:                    # tolerate 74.22 and 0.7422 alike
        pct = pct / 100.0
    burn = round(actual / pct, 2) if pct >= MIN_PCT_FOR_BURN and actual > 0 else None

    pw = max(committed_floor, burn or 0)
    basis = "burn" if burn is not None and burn > committed_floor else "committed"

    return {
        "pw_projected": round(pw, 2),
        "basis": basis,
        "components": {
            "actual_cost": round(actual, 2),
            "open_po_commitment": open_po,
            "approved_co_no_po": exposure,
            "committed_floor": committed_floor,
            "burn_projection": burn,
            "pct_complete": round(pct, 4),
        },
        "vista_projected": job.get("projected_cost"),
        "current_estimate": job.get("current_estimate"),
        "current_contract": job.get("current_contract"),
    }
