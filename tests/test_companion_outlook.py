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


def _stub_user32(monkeypatch, handle: int):
    """Replace the FindWindowW probe with a known answer."""
    calls = []

    class FakeUser32:
        class FindWindowW:                        # noqa: N801 — mimics a C func
            argtypes = None
            restype = None

            def __new__(cls, cls_name, title):
                calls.append(cls_name)
                return handle

    monkeypatch.setattr(c, "ctypes",
                        types.SimpleNamespace(
                            windll=types.SimpleNamespace(user32=FakeUser32),
                            c_wchar_p=object(), c_void_p=object()))
    return calls


def test_outlook_is_open_reads_the_window_not_the_running_object_table(monkeypatch):
    """Outlook does not register in the ROT — measured, twice, on both ProgIDs:
    GetActiveObject raised MK_E_UNAVAILABLE while Outlook sat open on screen
    with window handle 1510426. The window is the only honest signal."""
    calls = _stub_user32(monkeypatch, handle=1510426)

    assert c.outlook_is_open() is True
    assert calls == ["rctrl_renwnd32"]


def test_outlook_is_open_is_false_when_no_window_exists(monkeypatch):
    _stub_user32(monkeypatch, handle=0)

    assert c.outlook_is_open() is False
