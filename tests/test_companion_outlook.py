"""The companion attaches to Outlook. It does not conjure one.

This is a behaviour test rather than a unit test, because the defect it guards
against was invisible in every unit: `Dispatch("Outlook.Application")` succeeds
whether or not Outlook is running, because when it isn't, COM STARTS IT. Every
call site looked correct and worked in development — the machine always had
Outlook open. On a PC where the user had closed Outlook, the 15-second sweep,
the watcher's re-attach and even /health each started a fresh, WINDOWLESS
Outlook, which then synced the mailbox, ran Search indexing and loaded every
add-in with nothing on screen to explain it. Closing Outlook did not help,
because the next sweep started it again.

Dispatch cannot express the distinction, so the code makes it explicitly:
background work asks whether Outlook is open and does nothing when it isn't,
and only a path a human triggered may bring one into being.
"""
from __future__ import annotations

import sys
import threading
import time
import types

import pytest
from fastapi import HTTPException

from companion import companion as c


class FakeCom:
    """Stands in for win32com.client, counting Dispatch calls.

    Dispatch is the only door COM offers, and it both attaches and creates —
    so "was Dispatch called while Outlook was closed" is exactly "did we start
    Outlook".
    """

    def __init__(self):
        self.dispatch_calls = 0

    def Dispatch(self, prog_id):                 # noqa: N802 — COM's name
        self.dispatch_calls += 1
        return FakeApp()


class FakeExplorers:
    def __init__(self):
        self.Count = 0
        self.added = []

    def Add(self, folder, mode):                 # noqa: N802 — COM's name
        self.added.append(folder)
        return types.SimpleNamespace(Display=lambda: None)


class FakeApp:
    def __init__(self):
        self.Explorers = FakeExplorers()

    def GetNamespace(self, _kind):               # noqa: N802 — COM's name
        return types.SimpleNamespace(GetDefaultFolder=lambda _n: object())


@pytest.fixture
def com(monkeypatch, request):
    """Fake COM, plus a stated answer to "is Outlook open?"."""
    outlook_open = getattr(request, "param", True)
    fake = FakeCom()
    client_mod = types.ModuleType("win32com.client")
    client_mod.Dispatch = fake.Dispatch
    parent = types.ModuleType("win32com")
    parent.client = client_mod
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: None
    monkeypatch.setitem(sys.modules, "win32com", parent)
    monkeypatch.setitem(sys.modules, "win32com.client", client_mod)
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setattr(c, "outlook_is_open", lambda: outlook_open)
    return fake


@pytest.mark.parametrize("com", [False], indirect=True)
def test_closed_outlook_is_never_started_by_default(com):
    """The whole bug in one assertion: no Dispatch, therefore no ghost Outlook."""
    with pytest.raises(HTTPException) as raised:
        c._outlook()

    assert com.dispatch_calls == 0, "background work must never START Outlook"
    assert raised.value.status_code == 503
    # And it says so in words a person can act on, not a COM HRESULT.
    assert "isn't open" in raised.value.detail


@pytest.mark.parametrize("com", [False], indirect=True)
def test_an_explicit_request_may_start_outlook_but_shows_it(com):
    """Pressing "Draft in Outlook" with Outlook closed is a request to open it.

    The window is the condition. An Outlook we started that nobody can see is
    precisely the thing that made a machine slow for reasons its owner could
    not find.
    """
    app_, _ns = c._outlook(start_if_needed=True)

    assert com.dispatch_calls == 1
    assert app_.Explorers.added, "an Outlook we started must be given a window"


@pytest.mark.parametrize("com", [True], indirect=True)
def test_a_running_outlook_is_attached_to_and_left_alone(com):
    """Dispatch against a running Outlook attaches; it must not add a window."""
    app_, _ns = c._outlook()

    assert com.dispatch_calls == 1
    assert not app_.Explorers.added, \
        "the user's own Outlook window must not be rearranged"


class _Buffer:
    """Stands in for a ctypes unicode buffer."""
    value = ""


def _stub_windows(monkeypatch, windows):
    """Present a desktop made of `windows` — a list of (class_name, visible)."""
    handles = {i + 1: w for i, w in enumerate(windows)}
    buf = _Buffer()

    def is_visible(hwnd):
        return handles[hwnd][1]

    def get_class(hwnd, into, _size):
        into.value = handles[hwnd][0]
        return len(into.value)

    def enum_windows(proc, _lparam):
        for hwnd in handles:
            if not proc(hwnd, None):
                return False
        return True

    monkeypatch.setattr(c, "_ENUM_PROC", lambda fn: fn)
    monkeypatch.setattr(c, "ctypes", types.SimpleNamespace(
        windll=types.SimpleNamespace(user32=types.SimpleNamespace(
            IsWindowVisible=is_visible,
            GetClassNameW=get_class,
            EnumWindows=enum_windows)),
        create_unicode_buffer=lambda _n: buf,
        c_void_p=object(), c_wchar_p=object(),
        c_int=object(), c_bool=object()))


def test_outlook_is_open_reads_the_window_not_the_running_object_table(monkeypatch):
    """Outlook does not register in the ROT — measured, twice, on both ProgIDs:
    GetActiveObject raised MK_E_UNAVAILABLE while Outlook sat open on screen
    with window handle 1510426. The window is the only honest signal."""
    _stub_windows(monkeypatch, [("Shell_TrayWnd", True),
                                ("rctrl_renwnd32", True)])

    assert c.outlook_is_open() is True


def test_a_hidden_outlook_window_does_not_count_as_open(monkeypatch):
    """The trap that FindWindowW fell into.

    A live Outlook owns hidden `rctrl_renwnd32` windows as well as real ones —
    measured on this machine with Outlook open: four in total, two visible. An
    Outlook held open by an automation client after the user closed it keeps
    exactly the hidden kind, so a probe that ignores visibility reports "still
    open" for precisely the state that means "let go of me", and the companion
    never would.
    """
    _stub_windows(monkeypatch, [("rctrl_renwnd32", False),
                                ("OutlookAcctMgrNotificationWindow", False),
                                ("rctrl_renwnd32", False)])

    assert c.outlook_is_open() is False


def test_an_open_draft_counts_as_outlook_being_open(monkeypatch):
    """A message window is `rctrl_renwnd32` too, and while one is on screen
    Outlook is plainly still in use — so any visible one counts, not just the
    Inbox explorer."""
    _stub_windows(monkeypatch, [("rctrl_renwnd32", False),   # the hidden one
                                ("rctrl_renwnd32", True)])   # a draft

    assert c.outlook_is_open() is True


def test_outlook_is_open_is_false_when_no_window_exists(monkeypatch):
    _stub_windows(monkeypatch, [("Shell_TrayWnd", True), ("Chrome_WidgetWin_1", True)])

    assert c.outlook_is_open() is False


def test_the_watcher_lets_go_when_the_user_closes_outlook(monkeypatch):
    """Not starting Outlook was necessary and not sufficient.

    An automation client holding a reference also stops Outlook CLOSING: the
    user clicks the X, Outlook cannot exit, and it retreats to the tray with
    "Another program is using Outlook". What is left is the same windowless
    Outlook, still syncing and running every add-in.

    The trap this pins is that the condition was self-sustaining. The watcher
    proved Outlook was alive by asking it for `Items.Count` — which succeeded,
    because Outlook was only alive BECAUSE THE WATCHER HELD IT. So the check
    could never fail and the references were never dropped. Hence the fake
    below keeps answering `Items.Count` perfectly throughout: the watcher must
    let go on the window's absence alone, with Outlook still replying happily.
    """
    open_now = {"yes": True}
    closed = threading.Event()

    def folder(_n):
        return types.SimpleNamespace(Items=types.SimpleNamespace(Count=7))

    fake_com = types.ModuleType("win32com.client")
    fake_com.Dispatch = lambda _p: types.SimpleNamespace(
        GetNamespace=lambda _k: types.SimpleNamespace(GetDefaultFolder=folder))
    fake_com.DispatchWithEvents = lambda items, sink: object()
    parent = types.ModuleType("win32com")
    parent.client = fake_com
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: None
    pythoncom.CoUninitialize = lambda: None
    pythoncom.PumpWaitingMessages = lambda: None

    monkeypatch.setitem(sys.modules, "win32com", parent)
    monkeypatch.setitem(sys.modules, "win32com.client", fake_com)
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setattr(c, "outlook_is_open", lambda: open_now["yes"])
    monkeypatch.setattr(c, "WATCH_WINDOW_CHECK", 0.05)
    monkeypatch.setattr(c, "WATCH_RETRY", 0.05)

    c._watch_stop.clear()
    thread = threading.Thread(target=c._watch_loop, daemon=True)
    thread.start()
    try:
        for _ in range(100):                       # wait for it to attach
            if c.watch_state.get("running"):
                break
            time.sleep(0.05)
        assert c.watch_state["running"], "the watcher never attached"
        assert c._sinks, "no COM references were taken"

        open_now["yes"] = False                    # the user clicks the X
        state_when_released = {}
        for _ in range(100):
            if not c._sinks:
                state_when_released = dict(c.watch_state)
                closed.set()
                break
            time.sleep(0.05)
    finally:
        c._watch_stop.set()
        thread.join(timeout=5)

    assert closed.is_set(), \
        "the watcher kept its grip on Outlook after the window closed"
    assert state_when_released["running"] is False
    assert state_when_released["error"] == "Outlook is not open"
