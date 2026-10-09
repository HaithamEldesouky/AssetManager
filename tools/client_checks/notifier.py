r"""The Notifier: its Pending decisions, its windows, and the one way out of
it.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import json
import os

from client_checks.stage import (C, NP, NR, NT, R, SK, SRC, SRC_FILES,
                                 _enclosing_functions, _offline, bad, close,
                                 controls, eq, head, ok, opened, quiesce, run,
                                 tk_or_skip, widgets)


def check_the_notifier_decides_below_the_window():
    """The Pending decisions, driven with no root window and no display (#208).

    Everything below is `notifier_pending`, which imports no tkinter and opens
    no socket. While the same logic lived inside the Notifier's Tk callbacks -
    `_confirm` and `_reject` calling `_send_answer`, which performed the request
    and mutated the popup queue in one act - the only way to assert any of it
    was to open a real window and measure it, and that reading is the one this
    file is worst at. `docs/CODING_STANDARDS.md` records the cost: #204 ran one
    unchanged group three times for green, red, green and read 67, 64, 60, 58
    and 56px off unchanged code, with the **green** runs hiding a real clipped
    control.

    So `tk_or_skip()` is deliberately not called and no app is built. This group
    runs whole on a machine with no desktop, and if it ever needs a root window
    the seam is in the wrong place.
    """
    head("the Notifier decides below the window")

    P = NP

    class _Reply(object):
        """What a request answered with. `body=None` is an answer that is not
        JSON at all, which is the half a reader written round `.json()` drops."""

        def __init__(self, status, body=None):
            self.status_code, self._body = status, body

        def json(self):
            if self._body is None:
                raise ValueError("not JSON")
            return self._body

    def row(tid):
        return {"id": tid}

    # ── the seam itself ───────────────────────────────────────────────────
    # An exact list rather than a `not in`: what this module must not import is
    # the whole of why it exists, and a reader asserting only the absence of
    # tkinter would report a clean run against a file it failed to parse.
    _imports = set()
    for _n in ast.walk(ast.parse(io.open(
            os.path.join(R, "notifier_pending.py"),
            encoding="utf-8").read())):
        if isinstance(_n, ast.Import):
            _imports.update(_a.name for _a in _n.names)
        elif isinstance(_n, ast.ImportFrom):
            _imports.add(_n.module or "")
    eq("the module imports what it needs and nothing else",
       sorted(_imports), ["collections", "common", "time"])
    eq("  which is no tkinter, at any depth",
       [_m for _m in _imports if "tkinter" in _m], [])

    # ── what one answer is, and where it goes ─────────────────────────────
    eq("a Confirm is the id and carries no body",
       P.request(P.confirm(7)), ("/confirm/7", None))
    eq("a Reject carries the reason",
       P.request(P.reject(8, "wrong asset")),
       ("/reject/8", {"reason": "wrong asset"}))
    eq("  and carries an empty one rather than no body",
       P.request(P.reject(8))[1], {"reason": ""})

    # ── what came back ───────────────────────────────────────────────────
    busy = {"code": C.MAINTENANCE_CODE,
            "error": "The server is busy with a backup."}
    eq("a request that raised is held", P.classify(None), (P.HOLD, ""))
    eq("200 and 201 are sent",
       [P.classify(_Reply(_s))[0] for _s in (200, 201)], [P.SENT, P.SENT])
    eq("409 is sent too - the server already has the record",
       P.classify(_Reply(409, {"code": "not_pending"}))[0], P.SENT)
    _out, _why = P.classify(_Reply(503, busy))
    eq("a maintenance hold is held rather than lost", _out, P.HOLD)
    eq("  in the server's own words", "backup" in _why, True)
    eq("an ordinary 5xx is held as well, having said nothing",
       P.classify(_Reply(500)), (P.HOLD, ""))
    eq("a 503 that is not a maintenance hold is one of those",
       P.classify(_Reply(503))[0], P.HOLD)
    eq("a 4xx is refused, permanently",
       P.classify(_Reply(400, {"error": "no such transaction"})),
       (P.REFUSED, "no such transaction"))
    eq("  and refused in words of ours where it gave none",
       P.classify(_Reply(404)), (P.REFUSED, "The server refused it (404)."))

    # ── what to hold, and what to write down ─────────────────────────────
    eq("a held answer keeps the whole entry and the server's words",
       P.held(P.reject(9, "wrong"), P.HOLD, "busy"),
       {"action": "reject", "id": 9, "reason": "wrong", "why": "busy"})
    eq("an answer the server took is not held",
       P.held(P.confirm(9), P.SENT, ""), None)
    eq("  nor is one it refused", P.held(P.confirm(9), P.REFUSED, "gone"), None)
    eq("a Confirm's log line is the id", P.note(P.confirm(10)), "#10")
    eq("a Reject's carries the reason",
       P.note(P.reject(10, "not mine")), "#10  not mine")
    eq("  and says so where there is none",
       P.note(P.reject(10)), "#10  (no reason given)")

    # ── the offline hold ─────────────────────────────────────────────────
    eq("a second answer about one Transaction replaces the first",
       [(_e["action"], _e["id"]) for _e in
        P.merge([P.confirm(12)], P.reject(12, "no"))], [("reject", 12)])
    eq("  and an answer about another one does not",
       [(_e["action"], _e["id"]) for _e in
        P.merge([P.confirm(12)], P.reject(13, "no"))],
       [("confirm", 12), ("reject", 13)])
    eq("  the ids compared as strings, a buffer having been through JSON",
       [_e["id"] for _e in P.merge([{"action": "confirm", "id": "12"}],
                                   P.reject(12, "no"))], [12])

    # ── the flush ────────────────────────────────────────────────────────
    def flush(items, answers):
        """One run, answering each attempt off `answers`. Returns what was
        tried, in order, beside the run itself."""
        run, tried = P.Flush(items), []
        entry = run.next()
        while entry is not None:
            tried.append(entry["id"])
            run.took(*answers.pop(0))
            entry = run.next()
        return run, tried

    five = [P.confirm(_n) for _n in (1, 2, 3, 4, 5)]
    run, tried = flush(five, [(P.HOLD, "busy")] * 5)
    eq("five held answers against a holding server are one attempt", tried, [1])
    eq("  with every one still queued, in order",
       [_e["id"] for _e in run.remaining()], [1, 2, 3, 4, 5])
    eq("  and the server's words kept for the line about it", run.held, "busy")

    run, tried = flush(five, [(P.SENT, "")] * 5)
    eq("a server taking writes again empties the queue",
       (tried, run.remaining(), run.held), ([1, 2, 3, 4, 5], [], ""))

    run, tried = flush([P.confirm(1), P.confirm(2)],
                       [(P.REFUSED, "gone"), (P.SENT, "")])
    eq("a refusal leaves the queue and does not stop the one behind it",
       (tried, run.remaining()), ([1, 2], []))
    eq("  and is handed back to be written down",
       [(_e["id"], _w) for _e, _w in run.refused], [(1, "gone")])

    run, tried = flush([P.confirm(1), P.confirm(2), P.confirm(3)],
                       [(P.SENT, ""), (P.HOLD, "busy"), (P.SENT, "")])
    eq("a hold part-way keeps what it reached and everything behind it",
       (tried, [_e["id"] for _e in run.remaining()]), ([1, 2], [2, 3]))

    # ── the order the popups are drained in ──────────────────────────────
    # The clock is handed in, so a gap is asserted rather than waited out - the
    # #194 gap is fifteen minutes by default and no gate waits on one.
    clock = [1000.0]
    pq = P.PopupQueue(1200, now=lambda: clock[0])

    eq("an empty queue has nothing to show", pq.next().kind, P.IDLE)
    eq("a poll queues what nobody has been asked about",
       [_t["id"] for _t in pq.arrived([row(1), row(2)])], [1, 2])
    eq("  and a second poll carrying the same rows queues nothing",
       (pq.arrived([row(1), row(2)]), [_t["id"] for _t in pq.queue]),
       ([], [1, 2]))
    _same = pq.queue
    eq("  appended to the same list, never a replacement",
       ([_t["id"] for _t in pq.arrived([row(3)])], pq.queue is _same),
       ([3], True))
    nxt = pq.next()
    eq("the first to arrive is the first offered, with the rest counted behind",
       (nxt.kind, nxt.tx["id"], nxt.queued), (P.SHOW, 1, 2))

    put_off = pq.next().tx
    eq("a deferred popup goes back to the front, ahead of what is behind it",
       (pq.deferred(put_off), [_t["id"] for _t in pq.queue]), (1200, [2, 3]))
    eq("  and nothing is offered while its gap is open", pq.next().kind, P.WAIT)
    clock[0] += 1.199
    _w = pq.next()
    eq("  a wake a hair early asks again rather than dropping it (#194)",
       (_w.kind, _w.wait_ms > 0, [_t["id"] for _t in pq.queue]),
       (P.WAIT, True, [2, 3]))
    clock[0] += 0.002
    _w = pq.next()
    eq("  and the gap elapsed offers that same Transaction, not the one behind",
       (_w.kind, _w.tx["id"]), (P.SHOW, 2))

    pq2 = P.PopupQueue(1200, now=lambda: clock[0])
    pq2.arrived([row(4), row(5), row(4)])
    _same = pq2.queue
    pq2.resolved(4)
    eq("a Transaction answered elsewhere leaves the queue, every copy of it",
       [_t["id"] for _t in pq2.queue], [5])
    eq("  removed in place, the poll worker appending to that same list",
       pq2.queue is _same, True)
    eq("  and stops being one this process has already offered",
       4 in pq2.seen, False)
    eq("  while the one queued beside it is untouched", 5 in pq2.seen, True)
    eq("a settings save or a Log off asks again about everything still Pending",
       (pq2.forget(), sorted(pq2.seen),
        [_t["id"] for _t in pq2.arrived([row(4), row(5)])]),
       (None, [], [4, 5]))
    pq2.repeat_ms = 60000
    eq("the gap is whatever the engineer's settings last said",
       pq2.deferred(row(6)), 60000)

    # ── what left Pending while it was held (#284) ────────────────────────
    pq3 = P.PopupQueue(1200, now=lambda: clock[0])
    pq3.arrived([row(1), row(2), row(3)])
    eq("a queued id absent from a new poll is dropped, one still there is not",
       (pq3.departed([row(1), row(3)]), [_t["id"] for _t in pq3.queue]),
       ([2], [1, 3]))
    eq("  and a poll that lists everything held drops nothing",
       pq3.departed([row(1), row(3), row(9)]), [])
    eq("  while the id on screen is dropped when it is absent",
       (pq3.departed([row(1), row(3)], shown=7), 7 in pq3.seen),
       ([7], False))
    pq3.deferred(pq3.next().tx)
    eq("a deferred popup that leaves Pending is dropped, not re-shown",
       (pq3.departed([row(3)]), [_t["id"] for _t in pq3.queue]),
       ([1], [3]))
    eq("an answer given elsewhere always reads the same",
       [P.left_pending(_r) for _r in (
           {"confirmed": 1, "origin": "desktop"},
           {"confirmed": 1}, {"confirmed": 1, "origin": "auto"}, None)],
       ["Answered elsewhere", "Answered elsewhere",
        "Answered elsewhere", "Answered elsewhere"])


def check_the_notifier_holds_an_answer_the_server_would_not_take():
    """An engineer's Confirm or Reject must not be thrown away.

    This app had no buffer at all for either. A server holding writes through a
    backup (G3, ADR-0018), or one that was simply not there, meant the answer
    went nowhere - and what a Transaction left Pending gets is the **24h
    Auto-Accept**, confirming it a day later with nobody having said yes. That
    is the one failure this app exists to prevent, and it is sharper for a
    Reject, which is auto-accepted into the opposite of what the engineer said.

    Driven rather than read: what is asserted is where the answer is across two
    places at once - the queue on disk and the call the server did or did not
    get - and the positive halves beside each hold are what stop this passing
    against a buffer that keeps everything for ever.
    """
    head("the Notifier holds an answer the server would not take")

    class _Answer(object):
        def __init__(self, status, body=None):
            self.status_code, self._body = status, (body or {})

        def json(self):
            return self._body

    held_body = {"code": "maintenance",
                 "error": "The server is busy with a backup."}

    class _App(object):
        """The three attributes `_send_answer` and the buffer helpers read."""
        server_url = "https://asset-server:8081"
        current_user = "Brian Dawson"
        _held_said = ""

        _answers_load = NT.NotifierApp.__dict__["_answers_load"]
        _answers_save = NT.NotifierApp.__dict__["_answers_save"]
        _answers_add = NT.NotifierApp.__dict__["_answers_add"]
        _send_answer = NT.NotifierApp.__dict__["_send_answer"]
        _flush_answers = NT.NotifierApp.__dict__["_flush_answers"]

    app = _App()
    asked, queued = [], []
    real_api = NT.api

    def answer(method, url, *_a, **kw):
        asked.append(url.rsplit("/api", 1)[-1])
        nxt = queued.pop(0) if queued else _Answer(500)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def clear():
        del asked[:]
        del queued[:]
        try:
            os.path.exists(NT.ANSWER_BUFFER_PATH) and os.remove(
                NT.ANSWER_BUFFER_PATH)
        except OSError:
            pass

    def buffered():
        if not os.path.exists(NT.ANSWER_BUFFER_PATH):
            return []
        return json.loads(io.open(NT.ANSWER_BUFFER_PATH,
                                  encoding="utf-8").read())

    try:
        NT.api = answer

        # ── what happens at the moment the engineer answers ───────────────
        clear()
        queued.append(_Answer(503, held_body))
        out, why = app._send_answer({"action": "confirm", "id": 7})
        eq("a maintenance hold is held rather than lost", out, "hold")
        eq("  in the server's own words", "backup" in why, True)
        app._answers_add({"action": "confirm", "id": 7, "why": why})
        eq("  and the answer is on disk",
           [(e["action"], e["id"]) for e in buffered()], [("confirm", 7)])

        clear()
        queued.append(OSError("client-checks: no server"))
        eq("a server that is not there is the same situation",
           app._send_answer({"action": "reject", "id": 8, "reason": "wrong"}),
           ("hold", ""))

        clear()
        queued.append(_Answer(200))
        eq("an answer the server took is not buffered",
           (app._send_answer({"action": "confirm", "id": 9}), buffered()),
           (("sent", ""), []))

        clear()
        queued.append(_Answer(409, {"error": "not pending", "code":
                                    "not_pending"}))
        eq("nor is one it says is already resolved",
           app._send_answer({"action": "confirm", "id": 10})[0], "sent")

        clear()
        queued.append(_Answer(400, {"error": "no such transaction"}))
        out, why = app._send_answer({"action": "confirm", "id": 11})
        eq("a 4xx is permanent, for the reason it is in the offline buffer",
           out, "refused")
        eq("  in the server's own words", why, "no such transaction")

        # ── one entry per Transaction ─────────────────────────────────────
        clear()
        app._answers_add({"action": "confirm", "id": 12, "why": ""})
        app._answers_add({"action": "reject", "id": 12, "reason": "no",
                          "why": ""})
        eq("a second answer about one Transaction replaces the first",
           [(e["action"], e["id"]) for e in buffered()], [("reject", 12)])

        # ── the flush ─────────────────────────────────────────────────────
        clear()
        app._answers_save([{"action": "confirm", "id": n, "why": ""}
                           for n in (1, 2, 3, 4, 5)])
        queued.extend([_Answer(503, held_body)] * 5)
        app._flush_answers()
        eq("five held answers against a holding server are one attempt",
           len(asked), 1)
        eq("  with every one still queued, in order",
           [e["id"] for e in buffered()], [1, 2, 3, 4, 5])

        clear()
        app._answers_save([{"action": "confirm", "id": n, "why": ""}
                           for n in (1, 2, 3)])
        queued.extend([_Answer(200), _Answer(200), _Answer(200)])
        app._flush_answers()
        eq("a server taking writes again empties the queue",
           (len(asked), buffered()), (3, []))

        clear()
        app._answers_save([{"action": "confirm", "id": 1, "why": ""},
                           {"action": "confirm", "id": 2, "why": ""}])
        queued.extend([_Answer(400, {"error": "gone"}), _Answer(200)])
        app._flush_answers()
        eq("a refusal leaves the queue and does not stop the one behind it",
           (len(asked), buffered()), (2, []))
    finally:
        NT.api = real_api
        clear()


def check_the_notifier_flushes_before_it_asks_what_is_pending():
    """Source, and about an order rather than an outcome.

    An answer this engineer has already given must reach the server before the
    server is asked what is still outstanding. The other way round, a
    Transaction they confirmed an hour ago comes back on the pending list and
    is put in front of them a second time - which no single request
    demonstrates, both orders being a working poll.
    """
    head("the Notifier flushes held answers before it asks what is pending")

    tree = ast.parse(SRC["notifier_app.py"])
    poll = [n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_poll_once"]
    eq("the poll tick is there", len(poll), 1)

    flush_at, pending_at = None, None
    for node in ast.walk(poll[0]):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_flush_answers" and flush_at is None):
            flush_at = node.lineno
        if isinstance(node, ast.JoinedStr):
            text = ast.dump(node)
            if "pending/" in text and pending_at is None:
                pending_at = node.lineno
    eq("it flushes held answers", flush_at is not None, True)
    eq("it asks what is pending", pending_at is not None, True)
    eq("  and the flush comes first",
       flush_at is not None and pending_at is not None
       and flush_at < pending_at, True)


def check_esc_closes_a_sub_window_and_never_the_popup():
    """Esc closes a sub-window - and must not reach the popup (G4).

    The confirm/reject popup is always-on-top, has **no close button** on
    purpose and stays up until the engineer answers. A popup dismissed by a
    stray keypress is an engineer who was never asked, and a Transaction the
    24h Auto-Accept resolves a day later with nobody having looked - which is
    the one failure this app exists to prevent. So it is the first thing
    asserted here, and it is asserted by pressing the key rather than by
    reading the source: what is claimed is that nothing reaches that window,
    and a binding it inherited from somewhere else is exactly what a source
    read would not see.

    Beside it the other three windows that refuse their own X while a worker
    runs - both forced-update windows and the installer's progress window -
    and they are the whole of the mid-operation case: every other long job in
    these apps runs on the Tk thread, where no keypress is delivered until it
    finishes.

    Then the property that makes `bind_all` wrong, driven on two real windows:
    Esc typed into one sub-window must not close the one beside it. That is
    the defect a global binding produces, it is invisible to any static read,
    and in an app that opens a dialog over a dialog it closes whichever of
    them the binding was added by last.
    """
    head("Esc closes a sub-window and never the popup (G4)")
    tk = tk_or_skip()
    if tk is None:
        return

    # -- the popup, which must not hear it -------------------------------
    app = NT.NotifierApp()
    root = app.root
    app._poll_once = lambda: None

    def pump():
        root.update_idletasks()
        root.update()

    try:
        app.popups.queue[:] = [{
            "id": 1, "asset_type": "Laptop", "asset_number": "A-1",
            "serial_number": "", "asset_model": "", "direction": "Out Store",
            "team_member": "Brian Dawson", "notes": "",
            "timestamp": "2026-01-01T09:00:00"}]
        app._show_next_popup()
        pump()
        popup = app._current_popup
        if popup is None:
            bad("no popup was shown, so nothing was asked of it")
            return
        popup.win.focus_force()
        popup.win.event_generate("<Escape>")
        pump()
        eq("Esc leaves the popup on screen, still asking",
           bool(popup.win.winfo_exists()), True)
        eq("  and the Transaction is not resolved by it",
           app._current_popup is popup, True)
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    # -- and the windows that cannot be closed at all ---------------------
    # The popup is in this list rather than beside it: what makes all four the
    # same case is that each already answers `WM_DELETE_WINDOW` with a refusal,
    # and the count below is derived from these spans rather than from an
    # assumption about how many an app has - the Notifier has two, and a gate
    # that assumed one per app would read the second as a missing binding.
    # The popup refuses in a stronger way than the other three - it draws no
    # title bar at all, where they answer `WM_DELETE_WINDOW` with a no-op - so
    # what is asserted of it is `overrideredirect`. What puts all four in one
    # list is the consequence rather than the mechanism: none of them can be
    # closed by the window manager, so none of them may be closed by a key.
    refused = {}
    for name, fn, how in (("storekeeper_app.py", "_forced_update",
                           "WM_DELETE_WINDOW"),
                          ("notifier_app.py", "_forced_update",
                           "WM_DELETE_WINDOW"),
                          ("notifier_app.py", "NotificationPopup",
                           "overrideredirect"),
                          ("installer.py", "_ProgressWindow",
                           "WM_DELETE_WINDOW")):
        node = None
        for n in ast.walk(ast.parse(SRC[name])):
            if (isinstance(n, (ast.FunctionDef, ast.ClassDef))
                    and n.name == fn):
                node = n
        text = ast.get_source_segment(SRC[name], node) if node else ""
        eq("%s's %s cannot be closed by the window manager (%s)"
           % (name, fn, how), how in (text or ""), True)
        eq("  so Esc is not bound on it either",
           "escape_closes" in (text or ""), False)
        if node is not None:
            refused.setdefault(name, []).append((node.lineno, node.end_lineno))

    # -- every other window does take it -----------------------------------
    for name in SRC_FILES:
        tree = ast.parse(SRC[name])
        tops = [n for n in ast.walk(tree)
                if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                and (getattr(n.value.func, "attr", None)
                     or getattr(n.value.func, "id", None)) == "Toplevel"]
        binds = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "escape_closes"]
        # Every window but the ones refused above, counted off those spans:
        # the installer opens one and it is its progress window, so none is
        # the right answer there rather than a gap.
        spans = refused.get(name, [])
        want = len([n for n in tops
                    if not any(a <= n.lineno <= b for a, b in spans)])
        eq("%s binds Esc on every window but the %d refused above"
           % (name, len(spans)), len(binds), want)
        eq("  and never on every window at once",
           'bind_all("<Escape>"' in SRC[name], False)

    # -- bound on the window, which is what a global would break -----------
    import ui_kit

    root2 = tk.Tk()
    root2.withdraw()
    try:
        a = tk.Toplevel(root2)
        b = tk.Toplevel(root2)
        ui_kit.escape_closes(a)
        answered = []
        ui_kit.escape_closes(b, lambda: answered.append("b"))
        root2.update_idletasks()
        root2.update()

        b.focus_force()
        b.event_generate("<Escape>")
        root2.update()
        eq("Esc in one sub-window goes through that window's own close",
           answered, ["b"])
        eq("  and leaves the window beside it open",
           bool(a.winfo_exists()), True)

        a.focus_force()
        a.event_generate("<Escape>")
        root2.update()
        eq("a window with no close of its own is destroyed, as its X does",
           bool(a.winfo_exists()), False)
        eq("  and the other window's close was not called a second time",
           answered, ["b"])
    finally:
        try:
            root2.destroy()
        except Exception:
            pass


def check_the_notifier_is_drawn_on_flat_colour():
    """Nothing on this window carries a colour sampled off a render (074).

    What replaced the render is the rule it existed to work around: a widget
    that cannot be transparent is **constructed in the colour of the thing it
    stands on**. So that is what is asserted, rather than the render's absence
    alone - absence is the half that passes by finding nothing, and a window
    with nothing on it has no sampled colour either.

    The positive half is the defect this is named for. Two labels side by side
    on one band each took the ground's colour at their own x, so the band
    stepped between them; here every label on a band is read back and the
    **band and its labels are compared with each other**, which fails on a
    step whatever produced it.

    And the form, which no render ever touched: fields in INPUT_BG on a flat
    strip. It is here so a change to one surface is measured against the
    other.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("the Notifier is drawn on flat colour")
    tk = tk_or_skip()
    if tk is None:
        return

    def one_colour(what, holder):
        face = str(holder.cget("bg"))
        kids = [w for w in holder.winfo_children()
                if w.winfo_class() == "Label"]
        if not kids:
            bad("  %s has no label on it - this check has stopped measuring "
                "what it names" % what)
            return
        faces = sorted(set(str(w.cget("bg")) for w in kids))
        eq("  %s and its %d labels are one colour (%s against %s)"
           % (what, len(kids), face, tuple(faces)),
           faces, [face])

    txn = {"id": 1, "asset_number": "IT-0001", "serial_number": "SN-1",
           "asset_type": "Laptop", "asset_model": "X1",
           "direction": "Out", "team_member": "Brian Dawson",
           "storekeeper": "Storekeeper User", "notes": "",
           "created_at": "2026-01-01 09:00:00"}

    NT.fetch_permissions = lambda *a, **k: []
    app = NT.NotifierApp()
    root = app.root
    root.deiconify()
    root.geometry("320x140+0+0")
    root.update_idletasks()
    root.update()

    # The popup, which is the window that opens once per Transaction.
    pop = NT.NotificationPopup(root, txn, lambda *a: None, lambda *a: None)
    root.update_idletasks()
    root.update()
    pal = NT.THEME.palette()
    placed = [w for w in pop.win.winfo_children()
              if w.winfo_class() == "Canvas" and w.winfo_manager() == "place"]
    eq("no backdrop canvas is placed under the popup", placed, [])
    # Asked of the renderer rather than spelled out here, so the label this
    # group measures cannot drift away from the one the popup draws.
    wanted = NT._ident(txn)
    ident = None
    for w in widgets(pop.win):
        try:
            if w.winfo_class() == "Label" and w.cget("text") == wanted:
                ident = w
                break
        except Exception:
            pass
    if ident is None:
        bad("the popup carries no identifier - this group has stopped "
            "measuring what it names")
    else:
        eq("the popup's body is flat CARD",
           str(ident.master.cget("bg")), pal["CARD"])
        one_colour("the popup's body", ident.master)
    pop.close()
    root.update()

    # The Dashboard's count strip: three cells side by side, which is where
    # the step this ticket is named for was reported.
    dash = NT.DashboardWindow(root, "http://127.0.0.1:1", "Brian Dawson",
                              lambda *a: None, lambda *a: None)
    root.update_idletasks()
    root.update()
    placed = [w for w in dash.win.winfo_children()
              if w.winfo_class() == "Canvas" and w.winfo_manager() == "place"]
    eq("no backdrop canvas is placed under the Dashboard", placed, [])
    cells = [w.master for w in dash.stat_lbls.values()]
    strip = cells[0].master if cells else None
    if strip is None:
        bad("the Dashboard has no count strip - this group has stopped "
            "measuring what it names")
    else:
        faces = sorted(set(str(c.cget("bg")) for c in cells))
        eq("the count strip's three cells are one colour (%s)" % (tuple(faces),),
           faces, [str(strip.cget("bg"))])
        for key, lbl in sorted(dash.stat_lbls.items()):
            one_colour("the %s cell" % key, lbl.master)

    head_bar = dash.status_lbl.master.master
    eq("the Dashboard's header band is a plain frame",
       head_bar.winfo_class(), "Frame")

    own = NT.OwnPasswordWindow(root, "http://127.0.0.1:1", "Brian Dawson")
    root.update_idletasks()
    root.update()
    entry = None
    for w in widgets(own.win):
        try:
            if w.winfo_class() == "Entry":
                entry = w
                break
        except Exception:
            pass
    if entry is None:
        bad("Change My Password has no field on it - this group has stopped "
            "measuring what it names")
    else:
        eq("Change My Password keeps its fields in INPUT_BG",
           str(entry.cget("bg")), pal["INPUT_BG"])
        eq("  and the form they sit on is flat CARD2",
           str(entry.master.cget("bg")), pal["CARD2"])
    app.running = False
    quiesce(root)


def check_the_notifier_windows_fit():
    """Every Notifier window against the form inside it.

    Three were written smaller than their children and none of the three has a
    height that can be dragged: Admin Login 50px short with its Login button
    1px tall and never mapped, First Time Setup 26px short with Complete Setup
    at 27px of 53 - the first window an engineer ever sees - and Rejection
    Reason 2px short, clipping the bottom of both footer pills.

    The Dashboard is opened both ways because its width used to be
    `1140 if see_all else 1080`, a size conditional on what is in the window;
    check_no_client_window_takes_its_size_from_a_branch is what holds that,
    and this measures both branches of the window it was conditional on.

    The popup is measured and not shrunk: it is overrideredirect with no title
    bar, its size is computed with its position, and its footer is already
    packed from the bottom.

    Change My Password is opened both ways, like the Dashboard: the forced path
    arrives with the password the engineer just typed already in the field, so
    the two branches are two different forms. Settings is opened both ways for
    the same reason: the offline one carries a three-line notice the other does
    not, and it is the window an engineer meets when nothing is answering.
    """
    head("the Notifier's windows fit their forms")
    tk = tk_or_skip()
    if tk is None:
        return
    app = NT.NotifierApp()
    root = app.root
    # The app withdraws its root - it lives in the tray - and winfo_height() is
    # not valid on an unmapped window, so it is shown here. reqheight would be
    # valid either way; the actual height is the half that needs a window.
    root.deiconify()
    root.geometry("320x140+0+0")
    root.update_idletasks()
    root.update()

    txn = {"id": 1, "asset_type": "Laptop", "asset_number": "IT-0001",
           "serial_number": "SN-1", "asset_model": "X1 Carbon",
           "team_member": "Brian Dawson", "direction": "Out Store",
           "timestamp": "2026-01-01T10:00:00", "notes": "",
           "storekeeper": "Storekeeper User"}

    def dashboard(see_all):
        def go():
            NT.fetch_permissions = (lambda *a, **k:
                                    ["view_all_history"] if see_all else [])
            NT.DashboardWindow(root, "http://127.0.0.1:1", "Brian Dawson",
                               lambda *a: None, lambda *a: None)
        return go

    run(tk, root, [
        ("the logon window", app._show_setup_wizard, True),
        ("Rejection Reason",
         lambda: NT.RejectReasonDialog(root, txn, lambda *a: None), True),
        ("Notifier Settings",
         lambda: NR.SettingsWindow(root, app.cfg, "http://127.0.0.1:1",
                                   lambda *a: None), True),
        ("Update Required",
         lambda: app._forced_update("9.9.9", "http://example/x"), False),
        ("the notification popup",
         lambda: NT.NotificationPopup(root, txn, lambda *a: None,
                                      lambda *a: None), False),
        ("the Dashboard, own history", dashboard(False), False),
        ("the Dashboard, all engineers", dashboard(True), False),
        ("Change My Password",
         lambda: NT.OwnPasswordWindow(root, "http://127.0.0.1:1",
                                      "Brian Dawson"), True),
        ("Change My Password, forced",
         lambda: NT.OwnPasswordWindow(root, "http://127.0.0.1:1",
                                      "Brian Dawson", current="handedover",
                                      forced=True), True),
        ("Remote Admin",
         lambda: NR.RemoteAdminWindow(root, "http://127.0.0.1:1"), True),
        # Unlocked without a server to unlock it against, which is what the
        # `opens` argument is for: the locked form is a password field and the
        # window this ticket is about is the one behind it. Seven panels
        # since #174, and two of them are a list with no bound inside its own
        # scroll region - a card per Engineer, and a row per installation with
        # the commands under it - so this is the leg that would show the
        # footer being pushed off by either, and `api` here raises, which is
        # the offline path both panels already have to draw.
        ("Remote Admin, unlocked",
         lambda: NR.RemoteAdminWindow(root, "http://127.0.0.1:1",
                                      opens=NR.REMOTE_PANELS,
                                      config={"host": "0.0.0.0",
                                              "port": 8081}), True),
        ("Remote Correction",
         lambda: NR.RemoteCorrectionWindow(root, "http://127.0.0.1:1",
                                           "delegated", txn), True),
    ])
    app.running = False
    quiesce(root)


def check_the_notifier_acts_on_a_temporary_own_password():
    """What the Notifier's logon window does, for each answer it can get (090).

    None of it is reachable from a static read - every branch is a Tk
    callback, and each one decides who this laptop answers for.

      - **An engineer's own password logs them on, for the name picked.** The
        window hands `verify_password` the engineer chosen, and `/auth/verify`
        checks the password against that name: it took the admin password
        alone until 090, because an own password would have let one engineer
        point a laptop at another's name, and a name-bound check closes that.
      - **A Temporary Own Password is replaced as the logon completes,** on
        the engineer's own path only: an Admin who typed the admin password is
        not the person who has to replace it, and a server too old to report
        the flag sends nothing, which reads as False.
      - **A wrong password, or no answer, saves nothing.** Both are a line on
        the window; nobody is logged on by a check that was not made.

    And the two things 090 moved around it: **Settings opens with no password
    in front of it**, straight from the app's own `_open_settings`, and **Log
    off clears the name and opens this window**, after which the poll asks
    the server nothing.

    OwnPasswordWindow, SettingsWindow and the confirmation box are stubbed:
    a real one would answer the first question and none of the rest.
    """
    head("the Notifier acts on a temporary Own Password")
    tk = tk_or_skip()
    if tk is None:
        return
    app = NT.NotifierApp()
    root = app.root
    root.deiconify()
    root.update_idletasks()
    root.update()
    real_verify, real_window = NT.verify_password, NT.OwnPasswordWindow
    real_settings, real_save = NR.SettingsWindow, NT.save_config
    real_info, real_api = NT.messagebox.showinfo, NT.api
    real_cfg = dict(app.cfg)
    opened_pw = []
    asked = []
    picked = []
    NT.OwnPasswordWindow = lambda *a, **k: opened_pw.append(k)
    NT.save_config = lambda cfg: None
    NT.messagebox.showinfo = lambda *a, **k: None

    def pump():
        root.update_idletasks()
        root.update()

    try:
        def attempt(answer):
            """Open the logon window, type a password, press Log on.

            Returns (the replacement form's kwargs or {}, how many opened,
            whether the logon saved, what the window said)."""
            del opened_pw[:]
            del asked[:]

            def verify(*a, **_k):
                asked.append(a)
                if isinstance(answer, Exception):
                    raise answer
                return answer
            NT.verify_password = verify
            app.cfg["setup_complete"] = False
            wins = opened(tk, root, "the logon window", app._show_setup_wizard)
            if not wins:
                return {}, 0, False, ""
            win = wins[-1]
            pw = [x for x in widgets(win) if x.winfo_class() == "Entry"
                  and x.cget("show")]
            if not pw:
                bad("the logon window has no masked password field")
                close(root, wins)
                return {}, 0, False, ""
            pw[0].insert(0, "the one they typed")
            del picked[:]
            picked.extend(x.get() for x in widgets(win)
                          if x.winfo_class() == "TCombobox")
            for c in controls(tk, win):
                if c.winfo_class() == "Button" and "Log on" in c.cget("text"):
                    c.invoke()
                    break
            pump()
            told = ""
            if win.winfo_exists():
                told = " ".join(x.cget("text") for x in widgets(win)
                                if x.winfo_class() == "Label")
            saved = not win.winfo_exists()
            close(root, [w for w in wins if w.winfo_exists()])
            return ({} if not opened_pw else opened_pw[0],
                    len(opened_pw), saved, told)

        temp_open = {"valid": True, "admin": False,
                     "permissions": ["view_all_history"],
                     "must_change_password": True}
        args, n, saved, _told = attempt(temp_open)
        eq("the name picked is the name the password is checked against",
           ([a[1] for a in asked][:1], len(picked)), (picked[:1], 1))
        eq("a flagged own password logs on and opens the replacement form",
           (saved, n), (True, 1))
        eq("  forced, with the password they just typed",
           (args.get("forced"), args.get("current")),
           (True, "the one they typed"))

        _args, n, saved, _told = attempt(dict(temp_open, admin=True))
        eq("the admin password is not asked to replace anybody's password",
           (saved, n), (True, 0))

        _args, n, saved, _told = attempt(
            {"valid": True, "admin": False, "permissions": []})
        eq("a server too old to report the flag changes nothing",
           (saved, n), (True, 0))

        _args, n, saved, told = attempt({"valid": False})
        eq("a wrong password logs nobody on", (saved, n), (False, 0))
        eq("  and says so", "Wrong password" in told, True)

        _args, n, saved, told = attempt(OSError("nobody answered"))
        eq("a check that could not be made logs nobody on either",
           (saved, n), (False, 0))
        eq("  and says the server could not be reached",
           "Cannot reach" in told, True)

        # Settings: no door in front of it, and no narrowing behind it.
        opened_settings = []
        NR.SettingsWindow = lambda *a, **k: opened_settings.append(k)
        app._open_settings()
        pump()
        doors = [w for w in widgets(root) if isinstance(w, tk.Toplevel)
                 and w.winfo_exists() and w.title() == "Admin Login"]
        eq("Settings opens with no password asked for (090)",
           (len(opened_settings), len(doors)), (1, 0))
        eq("  and with no Server-URL-only narrowing",
           "url_only" in (opened_settings or [{}])[0], False)

        # Log off: the name goes, the logon window comes, the poll stops.
        app.current_user = "Brian Dawson"
        app.cfg.update(current_user="Brian Dawson", setup_complete=True)
        shown = []
        real_wizard = app._show_setup_wizard
        app._show_setup_wizard = lambda: shown.append(1)
        try:
            app._log_off()
            pump()
        finally:
            app._show_setup_wizard = real_wizard
        eq("Log off clears the engineer and opens the logon window",
           (app.current_user, app.cfg.get("current_user"),
            app.cfg.get("setup_complete"), len(shown)),
           ("", "", False, 1))
        called = []
        NT.api = lambda *a, **k: called.append(a) or _offline()
        app._poll_once()
        eq("  and the poll asks the server nothing while nobody is on",
           called, [])
    finally:
        (NT.verify_password, NT.OwnPasswordWindow, NR.SettingsWindow,
         NT.save_config) = real_verify, real_window, real_settings, real_save
        NT.messagebox.showinfo, NT.api = real_info, real_api
        app.cfg.clear()
        app.cfg.update(real_cfg)
    app.running = False
    quiesce(root)


def check_the_notifier_poll_interval_is_bounded():
    """What the poll loop may be handed, from both sides of the field.

    `time.sleep` is the thing at the end of this: `_poll_loop` runs on a daemon
    thread with nothing catching it, so a value it refuses does not report a
    failure - it ends the poller while the tray icon goes on looking exactly as
    it did, and the engineer stops being asked to confirm anything. That is the
    one failure this app exists to prevent, so what is asserted here is that no
    config, however written, can reach `sleep` with a value it will not take.

    Two sides, because the field is not the only writer: `config.json` sits on
    the engineer's own machine and `poll_secs` is what the app actually runs
    on, so the form refuses and the reader clamps. `0` is the value that needs
    no mistake at all - somebody wanting the popup sooner - and it is the one
    that turns the tick into an unthrottled loop against a server that asks
    this client for no credential on purpose (ADR-0002).

    The window is the real one: what is being asserted is that Save does not
    write, which a stub would answer for.
    """
    head("the Notifier's Poll Interval is bounded")
    lo, hi = NT.POLL_INTERVAL_RANGE

    # -- the reader, which is what the poll loop runs on ---------------------
    eq("a config asking for 0 is clamped to the floor",
       NT.poll_secs({"poll_interval": 0}), lo)
    eq("  and a negative one, which is what sleep() refuses",
       NT.poll_secs({"poll_interval": -5}), lo)
    eq("  and one past the ceiling comes back at it",
       NT.poll_secs({"poll_interval": 10 * hi}), hi)
    eq("  a value that is not a number at all is the default",
       NT.poll_secs({"poll_interval": "every 15 seconds"}),
       NT.DEFAULT_CFG["poll_interval"])
    eq("  and so is no value",
       NT.poll_secs({}), NT.DEFAULT_CFG["poll_interval"])
    eq("a sound one is left exactly as it was",
       NT.poll_secs({"poll_interval": 30}), 30)
    ok("every answer above is one time.sleep accepts")

    # -- the field ------------------------------------------------------------
    tk = tk_or_skip()
    if tk is None:
        return
    app = NT.NotifierApp()
    root = app.root
    root.deiconify()
    root.update_idletasks()
    root.update()
    try:
        def typed(value):
            """Open Settings, type value into Poll Interval, press Save.

            Returns (what on_save was handed or None, is the window still
            open, what it said)."""
            saved = []
            NR.SettingsWindow(root, dict(app.cfg), app.server_url,
                              lambda cfg: saved.append(cfg))
            root.update_idletasks()
            root.update()
            win = [w for w in widgets(root) if isinstance(w, tk.Toplevel)
                   and w.winfo_exists()
                   and w.title() == "Notifier Settings"][-1]
            # The Entries on this form are Server URL, Poll Interval and the
            # two popup timers #194 added, in that order - the Assigned User
            # that sat between the first two went with 090 - so Poll
            # Interval is third from the end rather than last. It was last
            # until those two landed, and what that cost is this helper typing
            # into the return-interval box while asserting about the poll one.
            entries = [x for x in widgets(win) if x.winfo_class() == "Entry"]
            poll_e = entries[-3]
            poll_e.delete(0, "end")
            poll_e.insert(0, value)
            for c in controls(tk, win):
                if c.winfo_class() == "Button" and c.cget("text") == "Save":
                    c.invoke()
                    break
            root.update_idletasks()
            root.update()
            alive = win.winfo_exists()
            said = " ".join(x.cget("text") for x in widgets(win)
                            if x.winfo_class() == "Label"
                            and x.cget("text")) if alive else ""
            close(root, [win] if alive else [])
            return (saved[0] if saved else None), bool(alive), said

        cfg, alive, said = typed("0")
        eq("Save refuses 0 rather than writing it", cfg, None)
        eq("  and the window stays open to be corrected", alive, True)
        eq("  having said what the bound is",
           ("%d" % lo) in said and ("%d" % hi) in said, True)

        cfg, alive, _said = typed("-5")
        eq("a negative is refused the same way", (cfg, alive), (None, True))

        cfg, alive, said = typed("every 15 seconds")
        eq("so is a value that is not a number", (cfg, alive), (None, True))
        ok("  - which used to raise inside the callback, where pythonw.exe "
           "has no console to print it to")

        cfg, _alive, _said = typed("%d" % (hi + 1))
        eq("and one past the ceiling", cfg, None)

        cfg, alive, _said = typed("30")
        eq("a sound value saves", (cfg or {}).get("poll_interval"), 30)
        eq("  and the window closes", alive, False)
        eq("  leaving every other key of the config alone",
           (cfg or {}).get("client_id"), app.cfg.get("client_id"))
    finally:
        app.running = False
    quiesce(root)


def check_the_notifier_dismisses_what_was_resolved_elsewhere():
    """A Transaction resolved in the Dashboard stops being asked about.

    The Dashboard's Confirm and Reject reach the same _confirm/_reject the
    popup does, and until they dismissed as well the engineer was asked a
    second time about a Transaction they had just answered - and one still in
    the queue popped up later, after the server had already resolved it.
    Nothing static sees either half: both are Tk callbacks, and the server is
    happy either way, so no endpoint answers for it.

    The popup is real rather than stubbed. What is asserted is that the window
    goes and the queue moves on, and a stub would be answering for both. The
    queue is advanced here by calling _show_next_popup directly: the 300ms
    after() that _popup_finished arms is the app's own pacing and predates
    this, and waiting on a timer is how a gate becomes flaky.

    Which is why nothing here arms one. This said the same thing and then
    called the real _popup_finished anyway, so every dismissal below left a
    300ms after() pending while the steps after it refilled the queue - and a
    stale one firing on some later root.update() built a popup nobody had
    asked for, leaving _current_popup set at the assertion that reads it. It
    failed twice in eight runs and passed ten times in a row, on nothing but
    how slow the machine was; see #103. What the real one does that matters
    here is free the screen, so that is what is done, by hand.

    The one thing this must never prove is a popup that does not come back. An
    engineer who stops being asked to confirm anything is the failure this app
    exists to prevent, so every dismissal below is followed by the next
    Transaction still being shown.
    """
    head("the Notifier dismisses what was resolved elsewhere")
    tk = tk_or_skip()
    if tk is None:
        return
    app = NT.NotifierApp()
    root = app.root
    # _confirm and _reject end in a poll thread reaching for a server this file
    # deliberately does not have. It is caught there, but a worker appending to
    # the queue mid-assertion would make this group's verdict a coin toss.
    app._poll_once = lambda: None
    finished = []
    real_finished = app._popup_finished

    def counted_finish():
        # on_done is read off the instance when the popup is built, so this has
        # to be in place before the first one is shown. It does what the app's
        # own _popup_finished does except arm the timer, for the reason the
        # docstring gives.
        finished.append(1)
        app._current_popup = None

    app._popup_finished = counted_finish

    def pending(tid):
        return {"id": tid, "asset_type": "Laptop", "asset_number": "A-%d" % tid,
                "serial_number": "", "asset_model": "", "direction": "Out Store",
                "team_member": "Brian Dawson", "notes": "",
                "timestamp": "2026-01-01T09:00:00"}

    def pump():
        root.update_idletasks()
        root.update()

    def showing():
        """The id on screen, or None - read off the popup, not off the queue."""
        p = app._current_popup
        if p is None or not p.win.winfo_exists():
            return None
        return p.trans.get("id")

    try:
        # The Dashboard resolves the Transaction whose popup is on screen.
        app.popups.queue[:] = [pending(1), pending(2)]
        app._show_next_popup()
        pump()
        eq("the first pending Transaction is on screen", showing(), 1)
        popup = app._current_popup
        app._confirm(1)
        pump()
        eq("confirming it elsewhere closes its popup",
           popup.win.winfo_exists(), 0)
        eq("  and the app knows the screen is free", app._current_popup, None)
        eq("  leaving the one behind it queued",
           [t["id"] for t in app.popups.queue], [2])
        app._show_next_popup()
        pump()
        eq("  and that one is still shown", showing(), 2)

        # A Transaction resolved while a different one is on screen. Rejecting
        # rather than confirming, because the Dashboard has both doors and they
        # are separate callbacks.
        app.popups.queue[:] = [pending(3), pending(3), pending(4)]
        on_screen = app._current_popup
        app._reject(3, "not mine")
        pump()
        eq("rejecting a queued Transaction takes every copy of it out",
           [t["id"] for t in app.popups.queue], [4])
        eq("  and leaves the popup of another alone",
           (showing(), app._current_popup is on_screen), (2, True))

        # An id neither on screen nor in the queue - the ordinary case, since
        # the Dashboard lists confirmed rows too.
        before = list(app.popups.queue)
        app._confirm(99)
        pump()
        eq("an unrelated id changes nothing",
           (app.popups.queue == before, showing()), (True, 2))

        # The popup's own button, after _dismiss has already closed it: the
        # engineer's Confirm reaches the app first and comes back to close a
        # window that has gone. Without the guard in close() this destroys
        # twice and re-arms the queue twice, which skips a Transaction.
        del finished[:]
        popup = app._current_popup
        popup._confirm()
        pump()
        eq("the popup's own Confirm still resolves exactly once",
           (len(finished), popup.win.winfo_exists(), app._current_popup),
           (1, 0, None))
        app._show_next_popup()
        pump()
        eq("  and the queue is not skipped past the next one", showing(), 4)
    finally:
        app._popup_finished = real_finished
        if app._current_popup is not None:
            app._current_popup.close()
    app.running = False
    quiesce(root)


def check_the_notifier_reject_can_be_backed_out_of():
    """Changing your mind about a rejection gives the popup back.

    _reject withdraws the popup, opens the reason dialog, and brings it back if
    the engineer does not go through with it. That coming-back was wired to
    WM_DELETE_WINDOW alone, which a window manager raises for the X and a
    programmatic destroy() never does - and the dialog's own Cancel button
    called win.destroy straight. So the control actually labelled for this left
    the popup withdrawn and unresolved, _popup_finished never ran,
    _current_popup stayed set, and _show_next_popup refused to show anything
    behind it for the life of the process. Every pending Transaction after that
    queued up unseen and was confirmed by the server's 24h auto-accept with
    nobody looking, which is the failure this app exists to prevent.

    Both exits are driven rather than the one that was broken, because what is
    asserted is that dismissing the dialog gives the popup back however it was
    dismissed - the X passed either way, and a pair one half of which cannot
    fail is a restatement rather than a measurement.

    The popup and the dialog are both real. What is being asked about is which
    window is on screen and whether the queue still moves, and a stub would be
    answering for both.
    """
    head("the Notifier's reject can be backed out of")
    tk = tk_or_skip()
    if tk is None:
        return
    app = NT.NotifierApp()
    root = app.root
    # As in the group above: _confirm and _reject end in a worker reaching for
    # a server this file deliberately does not have.
    app._poll_once = lambda: None

    # The popup's own countdown, silenced for the same reason the background
    # ticks at the top of this file are: it re-arms itself every two seconds,
    # and one still armed when a popup here is closed fires against a window
    # that has gone - which Tk reports as `invalid command name` on stderr,
    # printed among the results and reading exactly like a failure.
    real_tick = NT.NotificationPopup._tick
    NT.NotificationPopup._tick = lambda self: None

    finished, rejected = [], []
    real_finished = app._popup_finished

    def counted_finish():
        # Deliberately not the app's own _popup_finished. That arms a 300ms
        # after() to show the next one, which is this app's pacing rather than
        # anything asserted here, and one still armed from an earlier leg
        # firing part-way through a later one makes the verdict a coin toss.
        # What it does is freeing the screen, and the queue is advanced by
        # calling _show_next_popup directly - the group above's answer too.
        finished.append(1)
        app._current_popup = None

    # Both are read off the instance when a popup is built, so both have to be
    # in place before the first one is shown.
    app._popup_finished = counted_finish
    app._reject = lambda tid, reason="": rejected.append((tid, reason))

    def pending(tid):
        return {"id": tid, "asset_type": "Laptop", "asset_number": "A-%d" % tid,
                "serial_number": "", "asset_model": "", "direction": "Out Store",
                "team_member": "Brian Dawson", "notes": "",
                "timestamp": "2026-01-01T09:00:00"}

    def pump():
        root.update_idletasks()
        root.update()

    def reason_dialog():
        """The window _reject opened, found by its title rather than by being
        the newest Toplevel: the app has others open."""
        found = [w for w in root.winfo_children()
                 if isinstance(w, tk.Toplevel) and w.winfo_exists()
                 and w.title() == "Rejection Reason"]
        return found[0] if len(found) == 1 else None

    def pill(win, label):
        for w in widgets(win):
            p = getattr(w, "_pill", None)
            if p is not None and p.full == label:
                return p
        return None

    def leg(name, dismiss):
        """Open the reason dialog on a fresh popup and back out of it."""
        app.popups.queue[:] = [pending(1), pending(2)]
        app._show_next_popup()
        pump()
        popup = app._current_popup
        popup._reject()
        pump()
        dlg = reason_dialog()
        eq("%s: the reason dialog is open and the popup is put away" % name,
           (dlg is not None, bool(popup.win.winfo_ismapped())), (True, False))
        if dlg is None:
            return
        dismiss(dlg, popup)
        pump()
        eq("  the dialog is gone", reason_dialog(), None)
        eq("  and the popup is back on screen, still asking",
           (bool(popup.win.winfo_exists()),
            bool(popup.win.winfo_ismapped())), (True, True))
        eq("  with nothing rejected and the queue not moved on",
           (rejected, finished, [t["id"] for t in app.popups.queue]),
           ([], [], [2]))
        # Emptied before the popup is closed: close() re-arms the queue on a
        # 300ms after(), and a leg that left rows there would have the next
        # one open a popup of its own part-way through the leg after it.
        app.popups.queue[:] = []
        popup.close()
        pump()
        del finished[:]

    try:
        # The control that is labelled for this, and the one that was broken.
        leg("Cancel",
            lambda dlg, _popup: pill(dlg, "Cancel")._fire())
        # And the X, which always worked - through the protocol handler, since
        # no window manager here raises one.
        leg("the window's X",
            lambda dlg, _popup: dlg.tk.call(
                "eval", dlg.protocol("WM_DELETE_WINDOW")))

        # So this cannot pass by finding a dialog that never rejects anything:
        # going through with it still rejects exactly once and still lets the
        # queue move on.
        app.popups.queue[:] = [pending(3), pending(4)]
        app._show_next_popup()
        pump()
        popup = app._current_popup
        popup._reject()
        pump()
        dlg = reason_dialog()
        for w in widgets(dlg):
            if isinstance(w, tk.Entry):
                w.insert(0, "not mine")
                break
        pill(dlg, "✘  Confirm Rejection")._fire()
        pump()
        eq("going through with it rejects exactly once",
           rejected, [(3, "not mine")])
        eq("  and closes the popup, re-arming the queue",
           (bool(popup.win.winfo_exists()), len(finished),
            app._current_popup), (False, 1, None))
        app._show_next_popup()
        pump()
        eq("  so the Transaction behind it is still shown",
           app._current_popup is not None
           and app._current_popup.trans.get("id"), 4)
    finally:
        app._popup_finished = real_finished
        NT.NotificationPopup._tick = real_tick
        if app._current_popup is not None:
            app._current_popup.close()
    app.running = False
    quiesce(root)


def check_the_notifier_queue_offers_only_this_engineers_rows():
    """view_all_history widens the history table, not the Pending queue.

    The queue carries Confirm and Reject, which reach the same callbacks the
    popup does, and the popup only ever asks this engineer about their own
    Transactions. Built from the widened row set it offered another
    Engineer's - and the server accepts a confirmation from anybody, on purpose
    and permanently (ADR-0002), so nothing behind the client refuses it. That
    is what makes the scope a display decision this file has to hold.

    A group of its own rather than more assertions in the size group above:
    this one needs a server that answers, and `api` is swapped here for one
    that serves rows, which every other window in that group's plan would then
    see. What it reuses is that group's fixture - the same fetch_permissions
    stub, opened both ways round.

    The rows are read off the screen rather than off `_queue_rows`, because a
    helper returning the right list is not the finding and what is offered to
    be clicked is. The widened table is asserted in the same breath: a fix that
    scoped the queue by narrowing the fetch would pass half of this while
    taking the permission away.

    Since 079 the list is a `ui_kit.ListPane` and the two buttons are in the
    `DetailPane` beside it, so **the detail is driven as well as the list**:
    the pane carries the answer now, and a list correctly scoped with a pane
    that never follows it is an engineer answering about whatever was selected
    first. It is driven off the **older** row, so a pane that repaints only on
    the way in cannot pass.
    """
    head("the Notifier's Pending queue is this engineer's own")
    tk = tk_or_skip()
    if tk is None:
        return

    def row(tid, member, status="pending"):
        return {"id": tid, "asset_type": "Laptop", "asset_number": "A-%d" % tid,
                "serial_number": "", "asset_model": "", "direction": "Out Store",
                "team_member": member, "notes": "", "rejection_reason": "",
                "confirmed": 1 if status == "confirmed" else 0,
                "rejected": 0, "cancelled": 0,
                "timestamp": "2026-01-01T09:00:00"}

    rows = [row(1, "Brian Dawson"), row(2, "Carol Evans"),
            row(3, "Brian Dawson"), row(4, "Alice Carter"),
            row(5, "David Foster", "confirmed")]
    mine = [r for r in rows if r["team_member"] == "Brian Dawson"]

    class Served:
        ok = True

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    def served(_method, _url, params=None, **_k):
        # The server's own member filter, which is what an engineer without
        # the permission is answered with - matched without regard to case,
        # the way `team_member=? COLLATE NOCASE` matches it there.
        if params and params.get("member"):
            want = params["member"].casefold()
            return Served([r for r in rows
                           if r["team_member"].casefold() == want])
        return Served(list(rows))

    def texts(w):
        out = []
        for c in widgets(w):
            try:
                out.append(str(c.cget("text")))
            except Exception:
                pass
        return out

    app = NT.NotifierApp()
    root = app.root
    real_api, real_perms = NT.api, NT.fetch_permissions
    NT.api = served
    try:
        for see_all in (True, False):
            what = "with view_all_history" if see_all else "without it"
            NT.fetch_permissions = (lambda *a, **k:
                                    ["view_all_history"] if see_all else [])
            dash = NT.DashboardWindow(root, "http://127.0.0.1:1", "Brian Dawson",
                                      lambda *a: None, lambda *a: None)
            root.update_idletasks()

            eq("the queue holds this engineer's pending rows and no others, %s"
               % what,
               sorted(dash.listing.keys()), [1, 3])
            eq("  no other Engineer's asset is on a row, %s" % what,
               sorted(t for t in texts(dash.listing.body)
                      if t.startswith("A-")),
               ["A-1", "A-3"])

            # The one counter reads the queue and not the fetch: a figure
            # reading 4 over a queue of 2 is the same defect one level up.
            eq("  the list's header counts what the list holds, %s" % what,
               dash.queue_count.cget("text"), "2")

            # The pane the two answers live in. Driven as a **real click on a
            # real label**, `check_a_feed_row_opens_that_record`'s reason: a
            # ListPane row is a frame with four labels packed on top of it, so
            # a binding on the frame alone leaves a click on the asset number
            # landing on a widget that has none. Off the row the pane did
            # **not** open on, so a pane painted once on the way in and never
            # again cannot pass.
            target = [w for w in widgets(dash.listing.body)
                      if isinstance(w, tk.Label) and w.cget("text") == "A-3"]
            if not target:
                bad("the queue drew no row for A-3, %s - nothing to click"
                    % what)
            else:
                eq("  the row says it is clickable, %s" % what,
                   str(target[-1].cget("cursor")), "hand2")
                target[-1].event_generate("<Button-1>", x=2, y=2)
                root.update_idletasks()
                eq("  the detail pane follows the selection, %s" % what,
                   (dash.listing.selected,
                    "A-3" in texts(dash.detail.body)), (3, True))
                eq("  and carries the evidence the decision wants, %s" % what,
                   [t for t in ("Asset type", "Model", "Engineer",
                                "Storekeeper", "Logged")
                    if t not in texts(dash.detail.body)], [])
                # Beside the evidence rather than at the foot of the window,
                # which is the whole of what 079 moved. A Pill is a polygon on
                # a canvas, so it is read off the canvas it hangs itself on.
                eq("  with Confirm and Reject on it, %s" % what,
                   sorted(w._pill.full for w in widgets(dash.detail.body)
                          if getattr(w, "_pill", None) is not None),
                   ["Confirm", "Reject"])

            # The permission still does what it is for.
            listed = [i for i in dash.tree.get_children()
                      if "day" not in dash.tree.item(i, "tags")]
            eq("  the history table is %s" % ("widened" if see_all
                                              else "this engineer's own"),
               (len(listed), "Engineer" in dash.tree.cget("columns")),
               (len(rows), True) if see_all else (len(mine), False))
            close(root, [dash.win])

        # A configured name cased differently from the rows. The queue used to
        # empty itself silently here, which is an engineer who stops being
        # asked to confirm anything - the one failure this app exists to
        # prevent - and it looked exactly like a store with nothing pending.
        NT.fetch_permissions = lambda *a, **k: []
        dash = NT.DashboardWindow(root, "http://127.0.0.1:1", "brian dawson",
                                  lambda *a: None, lambda *a: None)
        root.update_idletasks()
        eq("a mis-cased configured name still fills the queue",
           sorted(dash.listing.keys()), [1, 3])
        eq("  with this engineer's own assets",
           sorted(t for t in texts(dash.listing.body)
                  if t.startswith("A-")), ["A-1", "A-3"])
        eq("  and the count agrees", dash.queue_count.cget("text"), "2")
        close(root, [dash.win])

        # Nothing pending, which is the state this window is in most of the
        # time. The sentence is asserted because it is the one 079 names: it
        # stops describing the tray as the place this happens and says what
        # will land here.
        dash = NT.DashboardWindow(root, "http://127.0.0.1:1", "Nobody At All",
                                  lambda *a: None, lambda *a: None)
        root.update_idletasks()
        eq("with nothing pending the split gives way to the empty state",
           (dash.split.winfo_manager(), dash.empty.winfo_manager(),
            dash.queue_count.cget("text")), ("", "pack", "0"))
        eq("  which says what will land here rather than describing the tray",
           texts(dash.empty),
           ["Nothing to confirm",
            "When the store logs a movement against you it lands here, and "
            "the tray icon pops it up."])
        close(root, [dash.win])
    finally:
        NT.api, NT.fetch_permissions = real_api, real_perms
    app.running = False
    quiesce(root)


def check_the_notifier_leaves_only_through_quit():
    """Every exit from the Notifier is _quit, because only _quit ships the log.

    A source check: what is claimed is an absence, and the one place it was
    wrong is a Tk callback behind a dialog no harness reaches - the forced
    update's Download & Install Now, which needs a server advertising a version
    it holds no zip for and five postponements before it can be clicked at all.

    _quit is two halves. The second stops things - the poll loop, the tray
    icon, the mainloop - and is what somebody reaching for an exit writes out
    by hand. The first is app.stopped and the ship of whatever client.log still
    holds, and it is the half that goes missing when they do: the forced
    update's download branch stopped the loop, stopped the tray icon and ended
    at root.destroy, so a Notifier that took that exit is one the Admin's
    System Log shows starting and never stopping, with the Confirms and
    Rejects of that session left on the laptop.

    **The Storekeeper is deliberately not held to this**, and the leg below is
    why: that app logs and ships after `root.mainloop()` returns, so a bare
    `root.destroy()` there is covered however it was reached. The Notifier's
    `run()` ends at `mainloop()` and the process goes, so it has no such place
    and `_quit` is the only one there is. Asserting the Storekeeper's pair here
    is what stops this scoping from being right for a reason that has since
    stopped holding.
    """
    head("the Notifier leaves only through _quit")
    tree = ast.parse(SRC["notifier_app.py"])
    where = _enclosing_functions(tree)

    def is_self(node, attr):
        return (isinstance(node, ast.Attribute) and node.attr == attr
                and isinstance(node.value, ast.Name) and node.value.id == "self")

    strays = []
    for node in ast.walk(tree):
        act = None
        # self.running = False
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)                 and node.value.value is False:
            if any(is_self(t, "running") for t in node.targets):
                act = "self.running = False"
        # self.tray_icon.stop()
        elif (isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and node.func.attr == "stop"
              and is_self(node.func.value, "tray_icon")):
            act = "self.tray_icon.stop()"
        # self.root.quit / self.root.destroy, called or handed to after()
        elif (isinstance(node, ast.Attribute)
              and node.attr in ("quit", "destroy")
              and is_self(node.value, "root")):
            act = "self.root.%s" % node.attr
        if act and where.get(node) != "_quit":
            strays.append("%s at line %d, in %s"
                          % (act, node.lineno, where.get(node) or "module"))
    eq("nothing but _quit stops the Notifier", strays, [])
    eq("and _quit itself is there once",
       len([n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_quit"]), 1)

    # What makes the scoping above correct rather than lucky.
    sk = ast.parse(SRC["storekeeper_app.py"])
    after = []
    for node in sk.body:
        if not (isinstance(node, ast.If)
                and "__name__" in ast.unparse(node.test)):
            continue
        seen_loop = False
        for stmt in node.body:
            text = ast.unparse(stmt)
            if "mainloop()" in text:
                seen_loop = True
                continue
            if seen_loop:
                after.append(text)
    eq("the Storekeeper logs app.stopped after mainloop returns",
       any("app.stopped" in t for t in after), True)
    eq("  and ships it there too",
       any(t.startswith("ship_log(") for t in after), True)


def check_a_decided_row_names_where_it_was_answered():
    """`Confirmed (auto)` beside the state, and nothing where there is no
    Origin to name (#283).

    No window: `_row_values` reads nothing of `self` but `see_all`, and the
    Storekeeper's `_recent_state` is a staticmethod. A row from a server that
    predates 106 has no `origin` key at all and must read as it always did.
    """
    head("a decided row names where it was answered")

    def hist(**kw):
        row = {"id": 1, "confirmed": 1, "rejected": 0}
        row.update(kw)
        return NT.DashboardWindow._row_values(
            type("W", (), {"see_all": False})(), row)[5]

    eq("Confirmed by Auto-Approve", hist(origin="auto"), "✓ Confirmed (auto)")
    eq("desktop says nothing", hist(origin="desktop"), "✓ Confirmed")
    eq("NULL says nothing", hist(origin=None), "✓ Confirmed")
    eq("no origin key reads as before", hist(), "✓ Confirmed")
    eq("pending takes no suffix",
       hist(origin="auto", confirmed=0), "● Pending")
    eq("the Storekeeper's list says it too",
       SK.StorekeeperApp._recent_state({"confirmed": 1, "origin": "auto"})[0],
       "Confirmed (auto)")
    eq("  and without an origin key, as before",
       SK.StorekeeperApp._recent_state({"confirmed": 1})[0], "Confirmed")
