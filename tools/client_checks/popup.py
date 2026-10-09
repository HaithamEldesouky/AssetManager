r"""The Notifier's popup: the two #194 timers, Dismiss, and the one window in
this product that is always on top (#193, #201).

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.

These four drive real `after` timers turned down to the smallest interval a
wall clock can show, and they are what tools/gate.py's SHARD_CAP["client"]
is measured against. They share no state and would pass in separate
processes; they are one module because they are one concern. The cap is on
how many shards run at once, not on which file these sit in - --shard slices
by position across every group, so moving them changed nothing it measures.
"""
import ast
import io
import json
import os

from client_checks.stage import (NR, NT, R, SRC, _enclosing_functions, bad,
                                 close, eq, head, opened, pump_until, quiesce,
                                 show_next, tk_or_skip, widgets)


def check_the_popup_hides_itself_and_comes_back():
    """The popup goes away after X and is offered again after Y (#194).

    The rule this window enforces is *the engineer is asked until they
    answer*, and until now it enforced it by never going away at all - which
    is right in front of somebody at their desk and wrong in front of somebody
    demonstrating a laptop, on a call, or looking at anything else on that
    screen. What auto-hide must not become is the dismissal this app has
    always refused: a popup that goes and does not come back is an engineer
    who was never asked, and the 24h Auto-Accept resolves the Transaction a
    day later with nobody having looked.

    So the pair is what is driven, and every leg of it is about the
    Transaction rather than about the window. It hides; it is still in the
    queue, at the front, because it has not been answered; it comes back
    still asking about the same id; a Confirm on the popup that came back
    resolves it exactly **once**, which is the thing a hide-and-return could
    most easily break by leaving two windows or two callbacks behind; and
    `0` - the default, and what every installation does until somebody sets
    otherwise - never hides it at all.

    The four rules that were already true here are asserted on the same
    window rather than trusted to the groups that own them, because what is
    being changed is when this window goes away: no Escape binding, no close
    button, its own X refused, and the queue still advancing on a real answer.

    Real timers rather than reaching past them - `hide_after` is what the app
    hands the popup and the return is a real `after` - with the numbers turned
    down to the smallest thing a wall clock can show. What that costs is a
    second of the gate's run; what reaching past them would cost is a group
    that passes against a popup whose timer was never armed.
    """
    head("the popup hides itself and comes back (#194)")
    import time
    tk = tk_or_skip()
    if tk is None:
        return

    def row(tid):
        return {"id": tid, "asset_type": "Laptop", "asset_number": "A-%d" % tid,
                "serial_number": "", "asset_model": "", "direction": "Out Store",
                "team_member": "Brian Dawson", "notes": "",
                "timestamp": "2026-01-01T09:00:00"}

    app = NT.NotifierApp()
    root = app.root
    app._poll_once = lambda: None

    def pump(seconds=0.0):
        end = time.time() + seconds
        while True:
            root.update_idletasks()
            root.update()
            if time.time() >= end:
                return

    answered = []
    app._confirm = lambda tid: answered.append(tid)

    try:
        # -- X of 0 never hides it, which is today's behaviour --------------
        app.popup_hide_secs = 0
        app.popups.queue[:] = [row(1)]
        # Through show_next rather than `_show_next_popup()` and a `pump()`:
        # a gap left by an earlier hide defers the showing, and under eight
        # shards `pump()` returned before it. See show_next.
        popup = show_next(app, root)
        if popup is None:
            bad("no popup was shown, so nothing was measured")
            return
        eq("with auto-hide off, no timer is armed at all",
           popup._hide_job, None)

        # The four that were already true, on this same window.
        eq("  it still takes no Escape binding", popup.win.bind("<Escape>"), "")
        # How this window refuses its own X is that it has no X: it is drawn
        # `overrideredirect`, so there is no frame and no title bar, which is
        # also why the size gates skip it. A `WM_DELETE_WINDOW` handler is
        # registered on it and is beside the point - nothing can ever deliver
        # that message to a frameless window - so what is asserted is the
        # absence of the frame rather than the shape of the handler.
        eq("  and has no frame to be closed from at all",
           bool(popup.win.overrideredirect()), True)
        def label_of(w):
            try:
                return str(w.cget("text"))
            except Exception:
                return ""
        shut = [label_of(w) for w in widgets(popup.win)
                if label_of(w) in ("✕", "×", "X", "Close")]
        eq("  and carries no close button", shut, [])
        popup.close()
        pump()
        eq("  and answering it still advances the queue",
           app._current_popup, None)

        # -- X of 1 hides it, and the Transaction is still in the queue -----
        app.popup_hide_secs = 1
        # Y, turned down to what a wall clock can show - but not so far down
        # that it has already elapsed by the time the hide is measured, which
        # is a leg asserting the return it meant to assert the hide.
        app.popups.repeat_ms = 1200
        app.popups.queue[:] = [row(2), row(3)]
        # Before the show, not after it: the timer is armed as the popup is
        # built, so a clock started once it is on screen has already lost
        # however long the build took and reads the wait as shorter than X.
        began = time.time()
        popup = show_next(app, root)
        if popup is None:
            bad("no popup was shown for the auto-hide leg")
            return
        eq("with auto-hide on, the timer is armed",
           popup._hide_job is not None, True)
        hid = pump_until(root, lambda: not popup.win.winfo_exists())
        eq("the popup hides itself after X",
           hid and not popup.win.winfo_exists(), True)
        eq("  and not before X, the timer being a real one",
           time.time() - began >= 0.9, True)
        eq("  and nothing was answered by it",
           answered, [])
        eq("  the Transaction is still in the queue, at the front",
           [t["id"] for t in app.popups.queue], [2, 3])
        eq("  with nothing on screen in the meantime",
           app._current_popup, None)

        # -- and it comes back after Y, still asking --------------------------
        pump_until(root, lambda: app._current_popup is not None)
        back = app._current_popup
        eq("it comes back after Y", back is not None, True)
        if back is None:
            return
        eq("  still asking about the same Transaction",
           back.trans["id"], 2)
        eq("  and the one behind it is still waiting",
           [t["id"] for t in app.popups.queue], [3])

        # -- a Confirm after a hide-and-return resolves exactly once ---------
        back._confirm()
        pump()
        eq("a Confirm on the returned popup resolves it exactly once",
           answered, [2])
        eq("  and the hidden window it replaced answers nothing",
           popup._closed, True)
        pump_until(root, lambda: app._current_popup is not None)
        eq("  and the queue advances to the one behind it",
           app._current_popup.trans["id"] if app._current_popup else None, 3)
    finally:
        quiesce(root)
        try:
            root.destroy()
        except Exception:
            pass


def check_dismiss_defers_the_popup_and_never_answers_it():
    """Dismiss puts the Transaction away and #194's own timer brings it back.

    The window has always refused to be dismissed, and the reason is the
    failure this app exists to prevent: a popup that goes and does not come
    back is an engineer who was never asked, with the 24h Auto-Accept
    resolving the Transaction a day later. What #201 adds is not a way out but
    the auto-hide asked for by hand - so every leg here is about the
    Transaction rather than about the window, and the ones that matter most
    are the two absences: nothing is answered, and it comes back.

    So: the control is there and is the quietest thing on the row, drawn with
    its face the same colour as the footer it sits on, which is what makes it
    unmistakable for Confirm (the one inverted block) and Reject (its equal in
    width, precisely so those two cannot be misread for each other). A real
    click on it - not a call to the handler, since what is being asserted is
    that the control the engineer presses is wired to it - takes the window
    away, confirms nothing, rejects nothing, sends nothing and writes nothing
    into `pending_answers.json`; leaves the Transaction at the **front** of the
    queue; and is followed by that same Transaction being offered again on the
    popup's own return interval. One `transaction.dismissed` at `info` is
    written and an auto-hide beside it writes none, which is the whole of what
    the flag across `on_hide` decides. A Confirm on the popup that comes back
    resolves it exactly once and the queue advances, so the deferral has left
    no second window and no second callback behind.

    And it is driven with the auto-hide **off**, which is the default and what
    every installation does until somebody sets otherwise: the return interval
    is its own setting with a floor of one minute and no off value, so a
    Dismiss returns whatever X is, and the leg that would show the opposite -
    a Dismiss that returns never - is the one this ticket is named for.

    The four rules that were already true are asserted on this same window for
    #194's reason, since what is being changed is how this window goes away:
    no Escape binding, no close button, no frame to be closed from, and the
    queue still advancing on a real answer.
    """
    head("Dismiss defers the popup and never answers it (#201)")
    import time
    tk = tk_or_skip()
    if tk is None:
        return

    def row(tid):
        return {"id": tid, "asset_type": "Laptop", "asset_number": "A-%d" % tid,
                "serial_number": "", "asset_model": "", "direction": "Out Store",
                "team_member": "Brian Dawson", "notes": "",
                "timestamp": "2026-01-01T09:00:00"}

    app = NT.NotifierApp()
    root = app.root
    app._poll_once = lambda: None

    def pump(seconds=0.0):
        end = time.time() + seconds
        while True:
            root.update_idletasks()
            root.update()
            if time.time() >= end:
                return

    confirmed, rejected, entries = [], [], []
    app._confirm = lambda tid: confirmed.append(tid)
    app._reject = lambda tid, reason: rejected.append((tid, reason))
    real_log = NT.log_event

    def buffered():
        if not os.path.exists(NT.ANSWER_BUFFER_PATH):
            return []
        return json.loads(io.open(NT.ANSWER_BUFFER_PATH,
                                  encoding="utf-8").read())

    try:
        os.path.exists(NT.ANSWER_BUFFER_PATH) and os.remove(
            NT.ANSWER_BUFFER_PATH)
    except OSError:
        pass

    try:
        NT.log_event = (lambda ev, detail="", level="info", **kw:
                        entries.append((ev, detail, level)))

        # -- auto-hide off, which is the default -----------------------------
        app.popup_hide_secs = 0
        app.popups.repeat_ms = 1200
        app.popups.queue[:] = [row(2), row(3)]
        popup = show_next(app, root)
        if popup is None:
            bad("no popup was shown, so nothing was measured")
            return
        eq("with auto-hide off, no timer is armed at all",
           popup._hide_job, None)

        # The four that were already true, on this same window.
        eq("  it still takes no Escape binding", popup.win.bind("<Escape>"), "")
        eq("  and has no frame to be closed from at all",
           bool(popup.win.overrideredirect()), True)

        def label_of(w):
            try:
                return str(w.cget("text"))
            except Exception:
                return ""

        shut = [label_of(w) for w in widgets(popup.win)
                if label_of(w) in ("\u2715", "\u00d7", "X", "Close")]
        eq("  and carries no close button", shut, [])

        # -- the control, and how loudly it is drawn -------------------------
        pills = [w._pill for w in widgets(popup.win)
                 if getattr(w, "_pill", None) is not None]
        by_word = dict((p.full, p) for p in pills)
        eq("the footer offers Dismiss beside Confirm and Reject",
           sorted(by_word), ["Confirm", "Dismiss", "Reject"])
        dis = by_word.get("Dismiss")
        if dis is None:
            return
        eq("  its face is the footer's own colour, so it draws no block",
           dis.fill == dis.bg, True)
        eq("  where Confirm is the one inverted block",
           by_word["Confirm"].fill != by_word["Confirm"].bg, True)
        eq("  and it does not join the equal-width pair those two are",
           dis._w != by_word["Confirm"]._w
           and by_word["Confirm"]._w == by_word["Reject"]._w, True)

        # -- a real click on it ----------------------------------------------
        # Two waits, and they are not the same wait. Tk drops a synthetic
        # `<Button-1>` on a widget that has never been mapped - the window is
        # built inside `_show_next_popup` but nothing is laid out until the
        # loop turns, and an unmapped canvas measures 1x1 and takes no events.
        # `show_next` returns without turning the loop where the popup is
        # already up, which is the usual case here, so the mapping is waited
        # for rather than assumed: without it the click lands nowhere, and the
        # four legs below read a popup nobody pressed anything on - green
        # before #205 only because the `pump()` this replaced turned the loop
        # once on its way past.
        pump_until(root, lambda: dis.cv.winfo_ismapped())
        eq("  and is on screen to be pressed",
           bool(dis.cv.winfo_ismapped()), True)
        # And `event_generate` queues the click rather than delivering it, so
        # the second wait is for the window to go rather than for one turn of
        # the loop: under eight shards a single `pump()` returned with the
        # click still in the queue.
        dis.cv.event_generate("<Button-1>", x=5, y=5)
        pump_until(root, lambda: not popup.win.winfo_exists())
        eq("a click on Dismiss takes the window away",
           bool(popup.win.winfo_exists()), False)
        eq("  confirming nothing", confirmed, [])
        eq("  and rejecting nothing", rejected, [])
        eq("  with nothing held in pending_answers.json", buffered(), [])
        eq("  the Transaction back at the front of the queue",
           [t["id"] for t in app.popups.queue], [2, 3])
        eq("  and nothing on screen in the meantime", app._current_popup, None)
        eq("  written down once, and as a deferral rather than an answer",
           [e for e in entries if e[0].startswith("transaction.")],
           [("transaction.dismissed", "#2", "info")])

        # -- and it comes back, with the auto-hide still off -----------------
        pump_until(root, lambda: app._current_popup is not None)
        back = app._current_popup
        eq("the popup comes back on the return interval", back is not None, True)
        if back is None:
            return
        eq("  still asking about the same Transaction", back.trans["id"], 2)
        eq("  and the one behind it is still waiting",
           [t["id"] for t in app.popups.queue], [3])

        # -- a Confirm after a deferral resolves exactly once -----------------
        back._confirm()
        pump()
        eq("a Confirm on the returned popup resolves it exactly once",
           confirmed, [2])
        pump_until(root, lambda: app._current_popup is not None)
        eq("  and the queue advances to the one behind it",
           app._current_popup.trans["id"] if app._current_popup else None, 3)

        # -- the auto-hide writes no entry, which is what the flag decides ----
        del entries[:]
        app._current_popup.close()
        pump()
        app.popup_hide_secs = 1
        app.popups.repeat_ms = 60000
        app.popups.queue[:] = [row(4)]
        hiding = show_next(app, root)
        if hiding is None:
            bad("no popup was shown for the auto-hide leg")
            return
        eq("an auto-hide arms a timer of its own",
           hiding._hide_job is not None, True)
        pump_until(root, lambda: not hiding.win.winfo_exists())
        eq("  and hides the window as it always did",
           bool(hiding.win.winfo_exists()), False)
        eq("  leaving the Transaction where it was",
           [t["id"] for t in app.popups.queue], [4])
        eq("  writing no transaction.dismissed, nobody having dismissed it",
           [e for e in entries if e[0] == "transaction.dismissed"], [])
    finally:
        NT.log_event = real_log
        quiesce(root)
        try:
            root.destroy()
        except Exception:
            pass


def check_what_the_popup_timers_may_be_set_to():
    """Both #194 numbers are held on both sides, like the Poll Interval.

    `poll_secs` is the precedent and the reason: these are timers on a window
    the engineer is answered through, and `config.json` is a file on their own
    machine that the Settings form is not the only writer of. So the field
    refuses what is out of range and the reader clamps whatever the file
    holds - and the reader is the half that matters, since a form that was
    never opened cannot have refused anything.

    `0` is the one value outside the auto-hide range that is accepted, on
    purpose: it means never hide, it is what this popup did before #194, and
    it is the default - so it is asserted as an accepted answer at both ends
    rather than left to look like a hole in the bound.
    """
    head("what the popup timers may be set to (#194)")

    lo, hi = NT.POPUP_DISMISS_RANGE
    rlo, rhi = NT.POPUP_REPEAT_RANGE

    # -- the reader clamps whatever is in the file -------------------------
    for held, want in ((0, 0), ("0", 0), (-5, 0), (lo - 1, lo), (lo, lo),
                       (hi, hi), (hi + 1000, hi), ("nonsense", 0), (None, 0)):
        eq("auto-hide of %r is read as %r" % (held, want),
           NT.dismiss_secs({"popup_dismiss_secs": held}), want)
    for held, want in ((0, rlo), (rlo - 1, rlo), (rlo, rlo), (rhi, rhi),
                       (rhi + 1000, rhi), ("nonsense",
                                           NT.DEFAULT_CFG["popup_repeat_mins"])):
        eq("return interval of %r is read as %r" % (held, want),
           NT.repeat_mins({"popup_repeat_mins": held}), want)

    # -- and the field refuses them ----------------------------------------
    for typed in ("0", str(lo), str(hi)):
        val, err = NT.validate_dismiss_secs(typed)
        eq("the auto-hide field takes %r" % typed, (val, err), (int(typed), None))
    for typed in (str(lo - 1), str(hi + 1), "-1", "", "ten"):
        val, err = NT.validate_dismiss_secs(typed)
        eq("  and refuses %r with a sentence" % typed,
           (val, bool(err)), (None, True))
    for typed in (str(rlo), str(rhi)):
        val, err = NT.validate_repeat_mins(typed)
        eq("the return field takes %r" % typed, (val, err), (int(typed), None))
    for typed in ("0", str(rhi + 1), "-1", "", "ten"):
        val, err = NT.validate_repeat_mins(typed)
        eq("  and refuses %r with a sentence" % typed,
           (val, bool(err)), (None, True))

    # -- the ceiling is chosen against the Auto-Accept window ---------------
    # A Transaction has to be put back in front of the engineer several times
    # inside the 24h the server will confirm it after on its own. At the worst
    # value anybody can save, that is 24 * 60 / rhi offers.
    eq("the worst return interval still offers it many times in 24h",
       (24 * 60) // rhi >= 12, True)


def check_only_the_notifier_popup_is_topmost():
    """One window in this product is always on top, and it is the popup (#193).

    Nine windows across the two client apps asked for `-topmost`, which is a
    window pinned over every other **application** on the machine rather than
    over the app it belongs to. What that is for is the confirm/reject popup:
    an engineer who is never asked is the one failure that app exists to
    prevent, so that window takes the screen. Everything else asking for it
    spends the same signal on an Admin Login, a password form or a dialog the
    person opened a moment ago and is already looking at - and a window that
    cannot be put down is one they cannot get behind to read what it is asking
    them about.

    The absence is a **source** check, because that is what is being claimed
    and because most of these are Tk callbacks behind a password. The two
    exceptions are named rather than counted: `NotificationPopup`, and
    `RejectReasonDialog`, which the popup **withdraws itself** for - so a
    reason dialog lost behind another application reads as the Transaction
    having vanished, which is the popup's own failure reached one window
    along. `ui_kit.raise_open` is the third and is not the same act at all: it
    is #191's answer to a menu clicked twice, a raise the person asked for by
    clicking, and the sweep must not take it with the rest.

    Beside it the positive, driven rather than read: the popup really is
    topmost on a real window, and a window beside it really is not. An absence
    asserted on its own passes just as happily against an app that has stopped
    opening the popup at all.
    """
    head("only the Notifier popup is topmost (#193)")

    def classes(tree):
        """Every node mapped to the class it is written inside, innermost."""
        where = {}
        for cl in ast.walk(tree):
            if not isinstance(cl, ast.ClassDef):
                continue
            for node in ast.walk(cl):
                where[node] = cl.name
        return where

    def forcings(name):
        """Every raise-over-everything in one source, as (what, class, line)."""
        text = SRC.get(name) or io.open(os.path.join(R, name),
                                        encoding="utf-8", newline="").read()
        tree = ast.parse(text)
        where = classes(tree)
        fns = _enclosing_functions(tree)
        found = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                continue
            act = None
            if node.func.attr == "attributes" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value == "-topmost":
                    act = "-topmost"
            elif node.func.attr in ("lift", "focus_force"):
                act = node.func.attr + "()"
            if act:
                found.append((act, where.get(node) or fns.get(node) or "module",
                              node.lineno))
        return found

    # The popup keeps every one it has; the reason dialog keeps the topmost it
    # is given for the reason above and asks for no lift.
    allowed = {
        "notifier_app.py": {("-topmost", "NotificationPopup"),
                            ("lift()", "NotificationPopup"),
                            ("-topmost", "RejectReasonDialog")},
        "storekeeper_app.py": {("lift()", "_show_window"),
                               ("focus_force()", "_show_window")},
        "installer.py": set(),
        "ui_kit.py": {("lift()", "raise_open"), ("focus_force()", "raise_open")},
    }
    for name, ok_set in sorted(allowed.items()):
        strays = ["%s in %s at line %d" % (act, who, line)
                  for act, who, line in forcings(name)
                  if (act, who) not in ok_set]
        eq("nothing in %s forces itself in front of another app" % name,
           strays, [])

    # And the permitted ones are still there, so none of the above can pass by
    # finding an app that no longer opens the popup.
    nt = {(a, w) for a, w, _l in forcings("notifier_app.py")}
    eq("  the popup still asks for topmost",
       ("-topmost", "NotificationPopup") in nt, True)
    eq("  the reason dialog still does, the popup withdrawing for it",
       ("-topmost", "RejectReasonDialog") in nt, True)
    kit = {(a, w) for a, w, _l in forcings("ui_kit.py")}
    eq("  and #191's asked-for raise is untouched",
       ("focus_force()", "raise_open") in kit, True)

    # -- driven: the real popup, and a real window beside it ---------------
    tk = tk_or_skip()
    if tk is None:
        return
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
            bad("no popup was shown, so nothing was measured")
            return
        eq("the popup is on top of everything",
           bool(popup.win.attributes("-topmost")), True)

        wins = opened(tk, root, "Notifier Settings",
                      lambda: NR.SettingsWindow(root, dict(app.cfg),
                                                "http://127.0.0.1:1",
                                                lambda *a: None))
        for w in wins:
            eq("  and Notifier Settings beside it is not",
               bool(w.attributes("-topmost")), False)
        close(root, wins)
    finally:
        quiesce(root)
        try:
            root.destroy()
        except Exception:
            pass
