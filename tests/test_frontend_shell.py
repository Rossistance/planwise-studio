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
                  "--fd:'Barlow Semi Condensed'", "--tap:36px", "--lbl:9.5px"):
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
        "Anything you send can be undone",
        "The log is append-only",
        "so the two screens can never disagree",
        "never sent outside the firm",
        "Tools and material stay internal; the customer sheet strips them out.",
        "True to the field",
    ):
        assert phrase in everything, f"verbatim microcopy lost: {phrase!r}"


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
