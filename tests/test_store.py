"""SQLite store: PO register, change orders, meta, users, activity, and the
committed-cost derivation (decision D8)."""
from __future__ import annotations

import pytest

from backend import db, store


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANWISE_DATA_DIR", str(tmp_path))
    db.reset_for_tests()
    yield
    db.reset_for_tests()


# --- POs --------------------------------------------------------------------

def test_po_crud_round_trip():
    po = store.add_po("24-003", {"po_number": "24-003113", "vendor": "SENSEHAWK INC.",
                                 "adjusted_amount": "2000", "cost_type": "Subcontractor"},
                      actor="Ross")
    # 2.0: mutations also return their activity_id (the undo bar reverses by
    # it); the stored row itself is everything else.
    stored = {k: v for k, v in po.items() if k != "activity_id"}
    assert store.list_pos("24-003") == [stored]
    assert po["adjusted_amount"] == 2000.0  # string in, number stored
    assert po["created_by"] == "Ross"

    store.update_po("24-003", po["id"], {"vendor": "SenseHawk"}, actor="Ross")
    assert store.list_pos("24-003")[0]["vendor"] == "SenseHawk"

    assert store.delete_po("24-003", po["id"], actor="Ross") is True
    assert store.list_pos("24-003") == []


def test_unknown_fields_are_dropped_not_stored():
    po = store.add_po("24-003", {"po_number": "1", "evil": "x", "id": "hijack"})
    assert "evil" not in po
    assert po["id"] != "hijack"


def test_invoices_reduce_remaining_and_cascade_on_po_delete():
    po = store.add_po("24-003", {"po_number": "1", "adjusted_amount": 2000,
                                 "cost_type": "Subcontractor"})
    store.add_invoice("24-003", po["id"], {"invoice_number": "A", "amount": 500})
    po = store.list_pos("24-003")[0]
    assert store.po_invoiced(po) == 500
    assert store.po_remaining(po) == 1500

    store.delete_po("24-003", po["id"])
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) c FROM invoices").fetchone()["c"] == 0


# --- committed derivation (D8) ----------------------------------------------

def test_committed_derivation_matches_the_vista_report_shape():
    """Recreate 24-003's Feb truth: $2,000 sub + $0.06 equip = $2,000.06."""
    store.add_po("24-003", {"po_number": "24-003113", "adjusted_amount": 2000,
                            "cost_type": "Subcontractor"})
    po2 = store.add_po("24-003", {"po_number": "24-003092", "adjusted_amount": 1509.82,
                                  "cost_type": "Equipment"})
    store.add_invoice("24-003", po2["id"], {"amount": 1509.76})

    committed = store.open_committed_by_cost_type("24-003")
    assert committed["Subcontractor"] == pytest.approx(2000.0)
    assert committed["Equipment"] == pytest.approx(0.06)


def test_closed_pos_do_not_commit():
    po = store.add_po("24-003", {"po_number": "1", "adjusted_amount": 500,
                                 "cost_type": "Material", "status": "Closed"})
    assert store.open_committed_by_cost_type("24-003") == {}
    store.update_po("24-003", po["id"], {"status": "Open"})
    assert store.open_committed_by_cost_type("24-003") == {"Material": 500.0}


def test_unpriced_po_is_not_a_zero_commitment():
    store.add_po("24-003", {"po_number": "1", "cost_type": "Material"})
    assert store.open_committed_by_cost_type("24-003") == {}


def test_po_without_cost_type_rolls_into_unassigned():
    store.add_po("24-003", {"po_number": "1", "adjusted_amount": 750})
    assert store.open_committed_by_cost_type("24-003") == {"Unassigned": 750.0}


def test_jobs_are_isolated():
    store.add_po("24-003", {"po_number": "A", "adjusted_amount": 1})
    store.add_po("26-006", {"po_number": "B", "adjusted_amount": 2})
    assert len(store.list_pos("24-003")) == 1
    assert len(store.list_pos("26-006")) == 1
    assert store.list_pos("no-such-job") == []


# --- change orders ----------------------------------------------------------

def test_co_two_kinds_and_kind_is_immutable():
    cust = store.add_co("24-003", {"kind": "customer", "co_number": "1",
                                   "amount_approved": 21000}, actor="Ross")
    sub = store.add_co("24-003", {"kind": "subcontractor", "co_number": "S-1",
                                  "subcontractor": "Gregory Electric",
                                  "amount_approved": -4500}, actor="Ross")
    by_id = {c["id"]: c for c in store.list_cos("24-003")}
    assert {c["kind"] for c in by_id.values()} == {"customer", "subcontractor"}
    # negative (credit) amounts survive
    assert by_id[sub["id"]]["amount_approved"] == -4500.0

    # newest first, so the sub CO (created second) leads the register
    assert [c["id"] for c in store.list_cos("24-003")] == [sub["id"], cust["id"]]

    store.update_co("24-003", cust["id"], {"kind": "subcontractor", "description": "x"})
    again = {c["id"]: c for c in store.list_cos("24-003")}
    assert again[cust["id"]]["kind"] == "customer"  # kind cannot flip
    assert again[cust["id"]]["description"] == "x"

    assert store.delete_co("24-003", sub["id"]) is True
    assert len(store.list_cos("24-003")) == 1


def test_co_bad_kind_defaults_to_customer():
    co = store.add_co("24-003", {"kind": "martian", "co_number": "9"})
    assert co["kind"] == "customer"


# --- meta -------------------------------------------------------------------

def test_meta_patch_merges_and_clears():
    store.patch_meta("24-003", {"superintendent": "J. Smith", "bond_required": "Yes"},
                     actor="Ross")
    store.patch_meta("24-003", {"bond_required": ""})  # empty clears
    assert store.get_meta("24-003") == {"superintendent": "J. Smith"}
    assert store.get_meta("other-job") == {}


# --- users + activity -------------------------------------------------------

def test_users_are_created_once():
    a = store.ensure_user("Ross Hixon")
    b = store.ensure_user("Ross Hixon")
    assert a["id"] == b["id"]
    assert [u["name"] for u in store.list_users()] == ["Ross Hixon"]
    with pytest.raises(ValueError):
        store.ensure_user("   ")


def test_activity_records_actor_and_action():
    po = store.add_po("24-003", {"po_number": "1"}, actor="Field Leader")
    store.delete_po("24-003", po["id"], actor="Ross")
    acts = store.list_activity("24-003")
    assert [a["action"] for a in acts] == ["po.delete", "po.create"]
    assert acts[0]["actor"] == "Ross"
    assert acts[1]["actor"] == "Field Leader"
    # global feed sees it too
    assert len(store.list_activity()) == 2
