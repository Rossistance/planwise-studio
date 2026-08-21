"""PlanWise's own cost-at-completion — arithmetic the UI can show its work on.

The rule: the LARGER of the committed floor and the burn reading. Costs at
completion ratchet with commitments; they are never averaged with hopes.
"""
from __future__ import annotations

import pytest

from backend import db, projection, store


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLANWISE_VISTA_WORKBOOK", "")
    db.reset_for_tests()
    yield
    db.reset_for_tests()


def job(**kw):
    base = {"actual_cost": 0, "pct_complete": 0, "projected_cost": None,
            "current_estimate": None, "current_contract": None}
    base.update(kw)
    return base


def test_the_committed_floor_is_register_totals_not_hope():
    po = store.add_po("24-003", {"po_number": "P-1", "vendor": "Axis",
                                 "original_amount": 100_000, "cost_type": "Material"}, actor="pm")
    store.add_invoice("24-003", po["id"], {"amount": 30_000}, actor="pm")
    store.add_co("24-003", {"kind": "subcontractor", "co_number": "S1",
                            "amount_approved": 50_000}, actor="pm")

    out = projection.for_job("24-003", job(actual_cost=200_000, pct_complete=0.5))
    c = out["components"]
    assert c["open_po_commitment"] == 70_000, "PO value minus what's invoiced"
    assert c["approved_co_no_po"] == 50_000
    assert c["committed_floor"] == 320_000
    # burn: 200k at 50% -> 400k, larger than the floor
    assert c["burn_projection"] == 400_000
    assert out["pw_projected"] == 400_000 and out["basis"] == "burn"


def test_commitments_ratchet_the_projection_above_a_gentle_burn():
    store.add_po("24-003", {"po_number": "P-2", "vendor": "Duke",
                            "original_amount": 900_000, "cost_type": "Subcontract"}, actor="pm")
    out = projection.for_job("24-003", job(actual_cost=100_000, pct_complete=0.5))
    assert out["components"]["burn_projection"] == 200_000
    assert out["pw_projected"] == 1_000_000 and out["basis"] == "committed", \
        "900k already promised out cannot be projected away"


def test_early_jobs_abstain_from_the_burn_reading():
    out = projection.for_job("24-003", job(actual_cost=80_000, pct_complete=0.02))
    assert out["components"]["burn_projection"] is None, \
        "2% complete is one mobilization invoice pretending to be a trend"
    assert out["pw_projected"] == 80_000 and out["basis"] == "committed"


def test_percent_tolerates_both_conventions():
    a = projection.for_job("24-003", job(actual_cost=100_000, pct_complete=0.25))
    b = projection.for_job("24-003", job(actual_cost=100_000, pct_complete=25.0))
    assert a["components"]["burn_projection"] == b["components"]["burn_projection"] == 400_000
