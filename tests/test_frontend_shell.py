"""The 2.0 shell — cheap drift guards for what the browser can't cover in CI.

No JS harness exists in this repo (no-build is load-bearing, A2/D37), so the
browser walkthrough in docs/RELEASE-2.0-VERIFICATION.md is the behavioural
check. These tests hold the line on the things that silently rot: the shell
files the service worker precaches must exist, the verbatim microcopy the
governing rule requires must stay verbatim, and the doctrine strings that
carry the product's promises must not be paraphrased away.
"""
from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if not (FRONTEND / "core.js").exists():          # pre-cutover location
    FRONTEND = Path(__file__).resolve().parent.parent / "frontend2"


def read(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_every_precached_shell_file_exists():
    sw = read("sw.js")
    shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
    for m in re.finditer(r'"(/[^"]+)"', shell):
        path = m.group(1)
        if path == "/":
            continue
        assert (FRONTEND / path.lstrip("/")).exists(), f"sw.js precaches {path}, which does not exist"


def test_the_token_block_is_the_prototypes():
    css = read("tokens.css")
    # Spot values lifted from the prototype — if any drifts, the port drifted.
    for token in ("--bg:#EFEDE6", "--ac:#C7420A", "--er:#A9291D",
                  "--fd:'PlanWise Sans'", "--tap:36px", "--lbl:9.5px"):
        assert token in css, f"token {token} missing or changed"
    # Dark palette and the fixed --wn. The Devanagari-digit typo must not
    # return to a DECLARATION — the comment documenting it may name it, so
    # only non-comment lines are scanned.
    assert "--ac:#F97435" in css
    assert "--wn:#E7B44E" in css
    declarations = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert "४" not in declarations, \
        "the Devanagari digit is back in a CSS declaration"


def test_option_a_section_names_shipped():
    copy = read("copy.js")
    for name in ("Job overview", "Cost & contracts", "Schedule & planning", "Field records"):
        assert name in copy
    for abbrev in ('"JOB"', '"COST"', '"PLAN"', '"FIELD"'):
        assert abbrev in copy


def test_doctrine_microcopy_is_verbatim():
    """The lines that carry the product's promises, exactly as designed."""
    everything = read("copy.js") + read("ui.js") + read("app.js") + read("pages.js")
    for phrase in (
        "What PlanWise checked before offering this",
        "Set this from the schedule, not from hope",
        "One question per RFI. Two questions in one RFI get one answer.",
        # The 2.0.3 tour: an ENGINE over the sample project, not slides. These
        # lines are its spine — the offer, the invitation format, the close.
        "Learn it on a job that isn't real",
        "every number in it is fake, every mechanism real",
        "Exposure is money owed with nothing ordered",
        "Anything sent can be undone",
        "The log is append-only",
        "so the two screens can never disagree",
        "never sent outside the firm",
        "Tools and material stay internal; the customer sheet strips them out.",
        "True to the field",
    ):
        assert phrase in everything, f"verbatim microcopy lost: {phrase!r}"


def test_the_login_card_carries_the_owners_wording():
    """2026-08-19 owner verdicts: email is the identity users are told to
    use, and the Vista-permissions sentence is gone. The input must stay
    type="text" so a pre-email account is refused by the server's answer,
    never by the browser's @-validation."""
    ui = read("ui.js")
    assert '"Use your White Electrical account."' in ui
    assert "follow your Vista permissions" not in ui
    assert '"login-email", "Work email", "text"' in ui


def test_the_field_shells_promises_are_verbatim():
    """PlanWise Field (handoff: PlanWise Field.dc.html) — the lines that
    carry its doctrine, exactly as designed."""
    everything = read("copy.js") + read("field.js")
    for phrase in (
        "held on this phone first and sent when you have signal",
        "Nothing goes to the customer from this phone.",
        "created in the office app",
        "Nothing is holding up the work right now.",
        "Redlines you add stay internal until they go out on an RFI.",
    ):
        assert phrase in everything, f"field microcopy lost: {phrase!r}"
    html = read("index.html")
    assert html.index("app.js") < html.index("field.js"),         "field.js extends App and must load after it"


def test_no_native_prompts_survive():
    """1.x used prompt()/confirm() — including an unmasked password prompt.
    2.0's checked confirm replaces every one of them."""
    js = read("app.js") + read("ui.js") + read("core.js") + read("pages.js")
    assert not re.search(r"(?<![\w.])prompt\(", js)
    assert not re.search(r"(?<![\w.])confirm\(", js.replace("confirmShare", "").replace("confirmSched", "")
                         .replace("confirmReply", "").replace("confirmRemoveUser", "")
                         .replace("runConfirm", "").replace("closeConfirm", "")
                         .replace("buildConfirm", "").replace("confirmOpen", "")
                         .replace("confirm:", "").replace("confirmStagedImport", "")
                         .replace(".confirm", "").replace("confirm_", ""))


def test_the_shell_loads_scripts_in_dependency_order():
    html = read("index.html")
    order = [html.index(x) for x in
             ("morphdom-umd.min.js", "copy.js", "offline.js", "api.js",
              "core.js", "ui.js", "pages.js", "app.js")]
    assert order == sorted(order), "script order violates the dependency chain"


def test_the_nine_restored_1x_features_keep_their_surfaces():
    """The 2026-08-21 regression audit found nine 1.x features the migration
    had silently dropped; each was rebuilt in the 2.0 language. These strings
    are their anchor points — losing one means the surface fell out again."""
    everything = read("app.js") + read("ui.js") + read("pages.js")
    for phrase in (
        # CO documents on their own, both kinds and both formats
        "Download Word", "Sub-CO log PDF", "document.docx",
        # look-ahead sheet PDFs without a share
        "Customer PDF", "Crew PDF", "/pdf?audience=",
        # work areas can be renamed, recoloured and removed again
        "Renaming or recolouring applies to the grid",
        "Remove this work area",
        # the clarifications library can retire a line
        "Archived from the library. Letters that already carry it keep their text.",
        # purchase orders and invoice lines can be removed, undoably
        "Remove this order", "Remove this invoice",
        # per-device web push is reachable again
        "Notifications on this device", "Turn on for this device",
        # sent-vs-returned comparison on the record thread
        "compare with what we sent", "Sent vs returned",
        # schedule column widths drag and persist
        "planwise.schedCols", "Reset the column widths",
    ):
        assert phrase in everything, f"restored surface lost again: {phrase!r}"


# --- the owner's interface rules (2026-08-21) ---------------------------------
# Each of these was a defect he reported by screenshot. They are cheap to
# assert and expensive to rediscover.

def test_the_tour_card_never_loses_its_anchor():
    """Blanking left/top/right/bottom left a position:fixed card with no
    offsets, so it laid out at its static position — off the bottom of the
    screen — on every step that had no highlight target."""
    app = read("app.js")
    assert 'card.style.left = ""' not in app
    assert '{ left: "auto", top: "auto", right: "22px", bottom: "22px" }' in app


def test_the_tour_defers_to_anything_modal():
    app = read("app.js")
    assert "const tourOverlayOpen = (s) =>" in app
    # It holds its step rather than advancing while the person is inside
    # whatever it asked them to open.
    assert "_tourSatisfied" in app
    assert "if (this._tourSatisfied === t.i && this._tourAdvanced !== t.i && !covered)" in app


def test_close_this_panel_appears_once_in_the_drawer():
    """One close, in the header, which is pinned because the header is the
    non-scrolling part of the drawer."""
    assert 'btn2("Close this panel"' not in read("app.js")
    assert read("ui.js").count(">Close this panel<") == 1


def test_no_page_offers_the_same_action_twice():
    app = read("app.js")
    pages = read("pages.js")
    # "Compose a change order" is the CO page's scaffold action; the register
    # header must not repeat it.
    assert app.count('label: "Compose a change order"') == 0
    # The schedule's Add-a-task and Import live in the scaffold only.
    assert "Import an updated schedule</button>" not in pages
    assert "Add a task</button>" not in pages


def test_the_exposure_panel_offers_only_the_action_that_clears_it():
    """The panel exists BECAUSE an approved sub CO exists — offering to log
    one there was backwards."""
    app = read("app.js")
    assert "openSubCo" not in app
    assert "Issue the PO" in app


def test_the_schedule_wipe_is_hard_to_reach_and_typed():
    pages = read("pages.js")
    app = read("app.js")
    assert "Start this schedule over" in pages          # folded away at the page foot
    assert '<details' in pages
    assert 'typed: "DELETE"' in app                     # and it asks for the word
    assert "confirmTyped" in read("ui.js")


def test_gantt_links_cover_the_scrollable_chart_and_mark_both_ends():
    app = read("app.js")
    assert 'svg.setAttribute("viewBox"' in app          # scales with the zoomed chart
    assert "<circle" in app                             # the tail, on the predecessor
    assert "clipPath" in app                            # never over the frozen column
    assert 'z-index:3' in read("pages.js")              # above a row's hover fill


def test_every_companion_state_carries_a_way_out():
    app = read("app.js")
    for handler in ("recheckCompanion", "openPairPage", "openOutlook"):
        assert handler in app, handler
    assert "Open Outlook now" in app


def test_every_button_has_a_handler_behind_it():
    """`H(v.foo)` with no `foo` in the view-model renders a button that does
    nothing at all. That is how "Close this panel" was dead on every drawer
    for a whole release — it had a working duplicate in the footer hiding it
    (owner, 2026-08-21). This walks every handler binding in the markup and
    fails on the first one the view-model never defines."""
    markup = read("ui.js") + read("pages.js")
    app = read("app.js")
    used = sorted(set(re.findall(r"H\(v\.([A-Za-z_][A-Za-z0-9_]*)\)", markup)))
    assert used, "no handler bindings found — the scan is broken, not the app"
    dead = [k for k in used
            if not re.search(r"(^|[^A-Za-z0-9_.])" + k + r"\s*:", app, re.M)]
    assert not dead, f"buttons bound to nothing: {dead}"


def test_the_gantt_zoom_is_applied_as_a_real_width():
    """The chart's width was authored as a min-width that stopped being
    honoured after first paint: at 274% the attribute said 1976px while the
    element still rendered at the container's width, so the axis never spread
    and the dependency lines had nothing longer to span."""
    app = read("app.js")
    assert "canvas.style.width = px" in app
    assert "board.clientWidth" in app          # floored at the visible width


def test_a_drawing_page_can_still_be_put_on_a_record():
    """The viewer's picker mode survived the migration; the way IN did not,
    so an RFI could no longer carry a drawing page at all."""
    app = read("app.js")
    pages = read("pages.js")
    assert '"picker", { recordId: rec.id }' in app, "nothing opens the viewer in picker mode"
    assert "threadDocs" in app and "threadCanAttach" in app
    assert "Choose pages from" in app          # the label, built in the view-model
    assert "v.threadDocs.map" in pages          # and rendered on the thread page
    # and the record pages must load the library the picker lists
    assert 'want.add("records"); want.add("documents");' in app


def test_register_headers_wrap_so_the_table_fits():
    """Ten nowrap headers pushed the cost table past its container, which is
    where the horizontal scrollbar under the cost breakdown came from."""
    app = read("app.js")
    colstyle = [ln for ln in app.splitlines() if "const colStyle" in ln]
    assert colstyle, "colStyle not found"
    assert "white-space:normal" in colstyle[0]
    assert "white-space:nowrap" not in colstyle[0]
