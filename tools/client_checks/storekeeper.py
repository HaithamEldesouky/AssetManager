r"""The Storekeeper's window: its sizes, its surfaces and what it offers.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import json
import os

from client_checks.stage import (C, SE, SK, STAGE, _offline, bad, close,
                                 controls, eq, head, measure, ok, quiesce, run,
                                 skip, tk_or_skip, widgets)


def check_the_storekeeper_windows_fit():
    """Every Storekeeper window against the form inside it, and which opens.

    Six of the nine this file measured when it was written were smaller than
    their children, measured before ui_kit.fit was called here: Admin Login
    47px short with its Login button 1px tall and never mapped, Server Settings
    35px short with Save at 11px of 46, Delete David Foster7px short with the
    same 1px button, Cancel Transaction 21px short as a Pending row and 27px as
    a Confirmed one, and Add Carol Evans7px narrow. Delete Engineer is not one
    of the eight now: 013 took it out of this app, along with Add Engineer's
    password field and its permission ticks. The measurements stay as written
    because they are the record of what each window had lost - Add Engineer's
    is against the form it had then, and the check below is against the form it
    has now.

    Bulk submit is 129px shorter than its children and passes: its footer is
    already packed at side="bottom" before the list, so the shortfall lands on
    an expanding Treeview that is meant to take whatever room is left. That is
    the difference this file is for - a window smaller than its children is
    only a defect where the thing being squeezed is a control.

    Server Settings is opened both ways, like the Notifier's: the offline one
    carries a three-line notice the other does not, and it is the window the
    storekeeper meets when nothing is answering.

    The leg after the measurements is the other question this file asks - not
    how big a window is but *which* one opens. `verify_admin_password` is a
    POST, so the answer it cannot give is a third one beside right and wrong,
    and the branch that reads it is a Tk callback nothing static reaches. An
    unanswered check opens Server Settings with the Server URL alone; a refusal
    opens nothing at all, because that is an answer. It is driven through the
    app's own _open_settings rather than a hand-built dialog: which window
    opens is the app's decision and that wiring is half of what is asserted.
    It lives in this group rather than one of its own, the way the Notifier's
    offline leg went into the group it already had.
    """
    head("the Storekeeper's windows fit their forms")
    tk = tk_or_skip()
    if tk is None:
        return
    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = SK.StorekeeperApp(root)
    root.update_idletasks()
    root.update()
    measure(tk, "the Storekeeper window", root)

    row = {"id": 1, "asset_number": "IT-0001", "serial_number": "SN-1",
           "asset_type": "Laptop", "team_member": "Brian Dawson",
           "direction": "Out Store", "rejected": 0, "timestamp": "x"}

    def cancel(confirmed):
        def go():
            app._all_rows = [dict(row, confirmed=confirmed)]
            app._selected_row = lambda: app._all_rows[0]
            app._cancel_selected()
        return go

    run(tk, root, [
        ("Export to Excel", app._open_export, True),
        ("Add Engineer", app._add_engineer_dialog, True),
        ("Add New Asset", app._propose._propose_dialog, True),
        # Opened past its file picker, which is the only part of it this file
        # cannot drive: the window is handed the rows a delivery note holds.
        ("Import Asset List",
         lambda: app._propose._import_proposals_window(
             "delivery.csv", ["Asset No", "Serial Number", "Type", "Model"],
             [["F-1", "FS-1", "Laptop", "T14"]]), True),
        ("Admin Login", app._open_settings, True),
        ("Server Settings", app._show_settings_window, True),
        ("Server Settings, Server URL only",
         lambda: app._show_settings_window(url_only=True), True),
        ("Update Required",
         lambda: app._forced_update("9.9.9", "http://example/x"), False),
        ("Cancel Transaction, a Pending row", cancel(0), True),
        ("Cancel Transaction, a Confirmed row", cancel(1), True),
        # Not shrunk: its list is what gives way, on purpose.
        ("Bulk submit", app._bulk.open, False),
    ])

    # -- and which window opens, for each answer the door can get -------------
    real_verify = SK.verify_admin_password
    real_show   = app._show_settings_window
    settings    = []
    app._show_settings_window = lambda **k: settings.append(k)
    try:
        def login(answer):
            """Open Server Settings the way the toolbar does, and press Login."""
            del settings[:]
            SK.verify_admin_password = answer
            app._open_settings()
            root.update_idletasks()
            root.update()
            dlgs = [w for w in widgets(root) if isinstance(w, tk.Toplevel)
                    and w.winfo_exists() and w.title() == "Admin Login"]
            for d in dlgs:
                for c in controls(tk, d):
                    if c.winfo_class() == "Button":
                        c.invoke()
                        break
            root.update_idletasks()
            root.update()
            alive = [d for d in dlgs if d.winfo_exists()]
            close(root, alive)
            # The dict of the one call that was made, or an empty one: a group
            # that raises stops reporting, and the assertions after the first
            # failure are the ones that say what happened instead.
            return len(dlgs), ({} if not settings else settings[0]), len(alive)

        asked, args, held = login(_offline)
        eq("a check that could not be made still opens the login dialog",
           asked, 1)
        eq("  and then Server Settings, with the Server URL alone",
           (len(settings), args.get("url_only")), (1, True))
        eq("  and the dialog it could not satisfy is gone", held, 0)

        _asked, _args, held = login(lambda *a, **k: False)
        eq("a refused password opens no offline window - it is an answer",
           len(settings), 0)

        _asked, args, _held = login(lambda *a, **k: True)
        eq("the admin password opens the whole window, not the URL alone",
           (len(settings), args.get("url_only")), (1, None))
    finally:
        SK.verify_admin_password = real_verify
        app._show_settings_window = real_show

    # -- and what a file of proposals does with no server ---------------------
    # The same answer as one proposal, and it has to be: twenty questions
    # queued into a state this app cannot see is twenty the storekeeper
    # believes were asked. The window still opens - the file is in front of
    # them and the columns are worth mapping either way - and says on itself
    # that nothing was proposed.
    buffered_before = os.path.exists(SK.BUFFER_PATH) and io.open(
        SK.BUFFER_PATH, encoding="utf-8").read()
    file_dlg = app._propose._import_proposals_window(
        "delivery.csv", ["Asset No", "Serial Number", "Type", "Model"],
        [["F-1", "FS-1", "Laptop", "T14"]])
    root.update_idletasks()
    root.update()
    said = [str(l.cget("text")) for l in widgets(file_dlg)
            if l.winfo_class() == "Label"
            and "cannot be reached" in str(l.cget("text"))]
    eq("a file of proposals says so too when nothing answers", len(said), 1)
    eq("  in the same words, and nothing queued",
       bool(said) and "not queued" in said[0], True)
    eq("  the window stays open, the columns still worth mapping",
       file_dlg.winfo_exists() and file_dlg.title(), "Import Asset List")
    eq("  and the offline buffer is untouched by a file as well as by one row",
       (os.path.exists(SK.BUFFER_PATH) and io.open(
           SK.BUFFER_PATH, encoding="utf-8").read()), buffered_before)
    close(root, [file_dlg])

    # -- and what a proposal does with no server: refuse, never buffer --------
    # A Transaction is buffered because the movement already happened and the
    # record is owed. A proposal is a question, and a question queued into a
    # state this app cannot see is one the storekeeper believes was asked. The
    # api here raises, which is this file's whole server, so this is the real
    # offline path rather than a simulated one.
    buffered_before = os.path.exists(SK.BUFFER_PATH) and io.open(
        SK.BUFFER_PATH, encoding="utf-8").read()
    app._propose._propose_dialog("PROP-1", "")
    root.update_idletasks()
    root.update()
    dlgs = [w for w in widgets(root) if isinstance(w, tk.Toplevel)
            and w.winfo_exists() and w.title() == "Add New Asset"]
    eq("proposing opens its own window", len(dlgs), 1)
    if dlgs:
        dlg = dlgs[0]
        boxes = [c for c in widgets(dlg) if c.winfo_class() == "TCombobox"]
        if boxes:
            boxes[0].set("Laptop")

        def settled_height():
            # A size asked for is not a size granted: read until it repeats.
            last = None
            for _ in range(20):
                root.update_idletasks()
                root.update()
                h = dlg.winfo_height()
                if h == last:
                    return h
                last = h
            return last

        empty_h = settled_height()
        for c in widgets(dlg):
            if c.winfo_class() == "Button":
                c.invoke()
                break
        refused_h = settled_height()
        said = [str(l.cget("text")) for l in widgets(dlg)
                if l.winfo_class() == "Label"
                and "cannot be reached" in str(l.cget("text"))]
        eq("with no server it says so on the form", len(said), 1)
        # 103: fitted once with the label empty and not resizable, the window
        # clipped every refusal longer than a line to its first.
        eq("  and the window grows to the refusal rather than clipping it",
           (refused_h > empty_h, refused_h >= dlg.winfo_reqheight()),
           (True, True))
        eq("  and says nothing was proposed rather than queued",
           bool(said) and "not queued" in said[0], True)
        eq("  the window stays open, the question unasked",
           dlg.winfo_exists() and dlg.title(), "Add New Asset")
        buffered_after = os.path.exists(SK.BUFFER_PATH) and io.open(
            SK.BUFFER_PATH, encoding="utf-8").read()
        eq("  and the offline buffer is untouched - a proposal is not a "
           "Transaction", buffered_after, buffered_before)
        close(root, dlgs)
    quiesce(root)


#: The default for `_file_bytes`, so that `None` can mean a file
#: that was not there rather than "read this one".
_READ = object()


def _file_bytes(path, data=_READ):
    """Read a file's bytes, or put them back. `None` is a file that is not there.

    What a group changes on disk is state the group after it is built from, the
    same way the theme object above is, and these sources are staged once for
    the whole run rather than per group.
    """
    if data is _READ:
        if not os.path.exists(path):
            return None
        return io.open(path, "rb").read()
    if data is None:                       # it was not there before either
        if os.path.exists(path):
            os.remove(path)
        return
    io.open(path, "wb").write(data)


def _scaling(value=None):
    """Read the display's `tk scaling`, or set it, through a throwaway root.

    It is display state rather than interpreter state, so this is how a group
    that raises it puts it back: there is no Tk to ask without a root, and the
    root that raised it has been destroyed by the time the group is done.
    """
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    try:
        if value is None:
            return root.tk.call("tk", "scaling")
        root.tk.call("tk", "scaling", value)
    finally:
        root.destroy()


def ui_kit_theme_state(theme, state=None):
    """Read an app's theme setting, or put one back.

    Assigned rather than driven through `set()`: what is being restored is the
    state a later group expects to start from, and `set()` would repaint the
    windows this group has already destroyed to get there. The palette is
    re-bound with it, since the app's colour names are what every widget built
    afterwards is born out of and `_swap` leaves them pointing at whatever was
    last active - a mode restored without them is a theme saying one thing and
    a window drawn in the other.
    """
    if state is None:
        return (theme.mode, theme.active, theme.why)
    theme.mode, theme.active, theme.why = state
    theme._bind(theme.pals[theme.active])


def check_the_storekeeper_header_controls_carry_their_whole_label():
    """The header pill that says which theme is in force, at two scalings (165).

    A `Pill` is built with a written `w`, and every one of those numbers was
    measured at the display scaling it was written on, while the label inside
    it is `_font.measure`d at whatever this machine is set to. At any other
    scaling the two part company and `Pill._fit` answers the only way it can,
    by eliding - so the theme button, `w=158`, drew its caption at 175px on a
    175% display and read `Follow Wi...`, which loses the mode and leaves a sun
    over `Follow Windows` and a sun over `Light` looking like the same control.

    `Pill.fit_text` is the answer and this is what holds it: a packed pill has
    nothing else deciding its width, so it takes the one its own label asks
    for. Driven at 1.00x and 1.75x because the defect is invisible at the first
    - a gate that only ever measures the scaling the number was written at
    measures the number against itself - and through all three modes, since
    they are three different lengths and only the longest overflows.

    `truncated` is read rather than the pixel width alone: what is being
    asserted is that the whole caption is on the control, and that flag is
    `_fit`'s own answer about the string it actually drew.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("the Storekeeper's header controls carry their whole label")
    tk = tk_or_skip()
    if tk is None:
        return

    import ui_kit
    real_init = tk.Tk.__init__
    # Two things here outlive this group and both are shared with every group
    # after it. `tk scaling` is a property of the **display** rather than of
    # the interpreter that set it, so a fresh `tk.Tk()` in this same process
    # reads back whatever the last one wrote - a raised scaling left behind is
    # every window measured afterwards at a size none of them was written for.
    # And the theme is one object per app module, so the mode this loop ends
    # on is the mode the next group starts from, where a switch to the colour
    # it is already in redraws nothing and reads as a switch that does not
    # work. Both are read here and put back below.
    base = _scaling()
    was_theme = ui_kit_theme_state(SK.THEME)
    # And the third: `_set_theme` saves the mode to this installation's own
    # `config.json`, which is a staged file the next group's app is built from
    # - so a mode left written there is the app after this one starting up in
    # it, whatever is put back on the object above.
    was_cfg = _file_bytes(SK.CONFIG_PATH)
    try:
        for scale in (1.0, 1.75):
            # On the interpreter as it is created: the app builds its fonts and
            # its styles a line later, and a scaling applied to a window whose
            # fonts already exist moves nothing.
            def init(self, *a, **k):
                real_init(self, *a, **k)
                self.tk.call("tk", "scaling", scale)

            tk.Tk.__init__ = init
            try:
                root = tk.Tk()
            finally:
                tk.Tk.__init__ = real_init
            root.geometry("1360x830")
            app = SK.StorekeeperApp(root)
            root.update_idletasks()
            root.update()

            btn = app.theme_btn
            seen = []
            for mode in ui_kit.MODES:
                # Through the app's own setter, which is what the button's
                # command reaches: the caption is repainted after the retint
                # rather than beside it, and that order is part of what is
                # being measured.
                app._set_theme(mode)
                root.update_idletasks()
                root.update()
                btn.redraw()
                label = ui_kit.MODE_LABELS[mode]
                seen.append(label)
                want, got = btn.intrinsic(), btn.cv.winfo_width()
                if btn.truncated:
                    bad("  %.2fx: the theme button elides %r - the mode behind "
                        "the icon is the whole reason that caption is there"
                        % (scale, label))
                elif got < want:
                    bad("  %.2fx: the theme button is %dpx for a label that "
                        "measures %dpx" % (scale, got, want))
                else:
                    ok("  %.2fx: %r is drawn whole, %dpx of %dpx"
                       % (scale, label, want, got))
            # The positive half, so neither leg can pass by finding a button
            # carrying no caption at all.
            eq("  %.2fx: and all three modes were painted" % scale,
               len(set(seen)), len(ui_kit.MODES))
            quiesce(root)
    finally:
        tk.Tk.__init__ = real_init
        _scaling(base)
        ui_kit_theme_state(SK.THEME, was_theme)
        _file_bytes(SK.CONFIG_PATH, was_cfg)


def check_the_storekeeper_tables_state_identity_first():
    """What each of this app's two surfaces says about a movement, and in what
    order (166, 078).

    Rule 4 is the first half: Asset No. and Serial No. come first, in both of
    them. History is a table and states it as its first two data columns;
    RECENT is the list-and-detail shape since 078 and states it as the Asset
    Number over the Serial Number on the row, so the rule is held on the
    **drawn row** there rather than on a column set - a rule asserted on one of
    the two surfaces is a rule with a hole the width of the other.

    The second half is what RECENT's column set used to carry. `RECENT_COLS`
    was `COLS` without Asset Type, the Rejection Reason and Direction, on the
    argument that a receipt says less than the record and History is one tab
    away. The pane beside the list carries all three now, so what is asserted
    is that they are **there** - the trip to History that set bought is the
    thing 078 removed, and a pane that dropped them would have removed the
    answer with it.

    The third half is the one only a driven fill can show, and it is two
    failures rather than one. A positional tuple written for nine columns into
    a tree built with seven writes the serial numbers under Model, so a row
    goes through History's tree and every cell is read back **under its own
    heading**. And a detail pane is only a pane if it repaints: the older row
    is selected first and the newer second, so a pane that painted once and
    never again cannot pass by happening to hold the right row.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("the Storekeeper's tables state identity first")

    App = SK.StorekeeperApp
    first = [c for c, _ in App.COLS][:2]
    if first != ["Asset No.", "Serial No."]:
        bad("History states %s first - rule 4 is that both identifiers are "
            "the first data columns, in every table" % (first,))
    else:
        ok("History states Asset No. and Serial No. first, of %d columns"
           % (len(App.COLS),))

    tk = tk_or_skip()
    if tk is None:
        return

    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = App(root)
    root.update_idletasks()
    root.update()
    try:
        # Values distinct enough that a cell landing under the wrong heading
        # cannot read as the right one.
        row = {"id": 1, "asset_number": "AM-1", "serial_number": "SN-2",
               "asset_model": "T14", "asset_type": "Laptop",
               "team_member": "Brian Dawson", "direction": "Out Store",
               "rejection_reason": "not mine", "notes": "",
               "timestamp": "2026-09-15T09:30:00",
               "confirmed": 0, "rejected": 1, "cancelled": 0}
        older = dict(row, id=2, asset_number="AM-9", serial_number="SN-9",
                     rejection_reason="", confirmed=1, rejected=0,
                     timestamp="2026-09-14T08:00:00")
        want = {"Asset No.": "AM-1", "Serial No.": "SN-2", "Model": "T14",
                "Type": "Laptop", "Member": "Brian Dawson",
                "Direction": "Out Store", "Rejection Reason": "not mine"}
        app._fill_table(app.tree, [row], grouped=False)
        kids = [i for i in app.tree.get_children()
                if "group" not in app.tree.item(i, "tags")]
        if len(kids) != 1:
            bad("History took %d rows from one Transaction" % (len(kids),))
        else:
            wrong = [(c, app.tree.set(kids[0], c)) for c in app.tree.ui_cols
                     if c in want and app.tree.set(kids[0], c) != want[c]]
            if wrong:
                bad("History wrote %s - a cell under the wrong heading is "
                    "what a positional fill does to a table with its own "
                    "columns" % (wrong,))
            else:
                ok("History: every cell is under its own heading, %d columns"
                   % (len(app.tree.ui_cols),))

        app._all_rows = [row, older]
        app._fill_recent([row, older])
        root.update_idletasks()
        if app.recent.keys() != [1, 2]:
            bad("RECENT drew %s from two Transactions - the row's key is the "
                "Transaction's id, and the pane is asked for a row by it"
                % (app.recent.keys(),))
        else:
            ok("RECENT drew both movements, keyed by Transaction id")

        # Rule 4 on the drawn row: the two labels carrying the identifiers,
        # and which of them is above the other. Read off the screen rather
        # than out of the pane's own list, since what the rule is about is
        # what somebody holding the laptop reads first.
        placed = {}
        for w in widgets(app.recent.body):
            try:
                text = str(w.cget("text"))
            except Exception:
                continue
            if text in ("AM-1", "SN-2"):
                placed[text] = w.winfo_rooty()
        if len(placed) != 2:
            bad("RECENT's row drew %s of the two identifiers - rule 4 is that "
                "both are on it, and first" % (sorted(placed),))
        elif placed["AM-1"] >= placed["SN-2"]:
            bad("RECENT's row draws the Serial Number above the Asset Number "
                "- rule 4 is that order, on the row as well as in a table")
        else:
            ok("RECENT's row states the Asset Number over the Serial Number")

        def pane_text():
            out = []
            for w in widgets(app.recent_detail.body):
                try:
                    out.append(str(w.cget("text")))
                except Exception:
                    pass
            return out

        # The older row first, so a pane that paints once cannot pass.
        app._paint_recent_detail(2)
        root.update_idletasks()
        stale = [t for t in pane_text() if "not mine" in t]
        app._paint_recent_detail(1)
        root.update_idletasks()
        said = pane_text()
        if stale:
            bad("RECENT's pane said %s about the confirmed movement - that "
                "reason belongs to the other row" % (stale,))
        else:
            ok("RECENT's pane took the row it was handed, not the newest one")
        missing = [f for f in ("AM-1", "SN-2", "Laptop", "T14", "Brian Dawson",
                               "not mine")
                   if not any(f in t for t in said)]
        if missing:
            bad("RECENT's pane does not state %s - those are the facts the "
                "column set dropped and History was the trip to read them"
                % (missing,))
        else:
            ok("RECENT's pane states the Asset Type, the model and the "
               "rejection reason RECENT_COLS dropped, and repaints per row")
    finally:
        quiesce(root)


def check_the_storekeeper_sections_and_panes_follow_a_theme_switch():
    """The Split shape's three widgets paint out of the live palette after a
    switch, not the one they were built in (078).

    `SectionBar`, `ListPane` and `DetailPane` are handed their colours once and
    keep them as Python attributes as well as on their widgets. `ui_kit.retint`
    walks widgets, so the strip and the rows already on screen come back
    correct on a switch and **the next `select()` does not**: it paints the
    selected cell, its 2px mark and the selected row's fill out of what the
    pane is still holding. That is a dark cell in a light window, it is
    invisible until somebody changes section after changing theme, and the
    section bar did exactly that until this group drove it. Which is why every
    assertion below reads something painted **after** the switch: a read of
    what the retint walk has just repainted passes with the hook removed.

    `_follows_theme` in `storekeeper_app.py` is what answers it, through the
    same `_retint_hook` door `_tag_status` uses for a Treeview's tag colours.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("the Storekeeper's sections and panes follow a theme switch")

    tk = tk_or_skip()
    if tk is None:
        return

    was_theme = ui_kit_theme_state(SK.THEME)
    root = tk.Tk()
    root.geometry("1180x700+0+0")
    try:
        SK.THEME.set("dark")
        app = SK.StorekeeperApp(root)
        root.update_idletasks()
        root.update()
        rows = [{"id": 1, "asset_number": "AM-1", "serial_number": "SN-2",
                 "asset_model": "T14", "asset_type": "Laptop",
                 "team_member": "Brian Dawson", "direction": "Out Store",
                 "rejection_reason": "", "notes": "",
                 "timestamp": "2026-09-15T09:30:00",
                 "confirmed": 1, "rejected": 0, "cancelled": 0},
                {"id": 2, "asset_number": "AM-9", "serial_number": "SN-9",
                 "asset_model": "T14", "asset_type": "Laptop",
                 "team_member": "Brian Dawson", "direction": "In Store",
                 "rejection_reason": "", "notes": "",
                 "timestamp": "2026-09-14T08:00:00",
                 "confirmed": 1, "rejected": 0, "cancelled": 0}]
        app._all_rows = list(rows)
        app._fill_recent(rows)
        app.recent.select(1)
        app._show_tab("Submit")
        root.update_idletasks()

        SK.THEME.set("light")
        root.update_idletasks()
        root.update()
        pal = SK.THEME.palette()

        app.recent.select(2)
        app._show_tab("History")
        root.update_idletasks()

        picked = [w for w in app.recent.body.winfo_children()
                  if getattr(w, "_ui_list_row", None) is not None]
        if len(picked) != 2:
            bad("RECENT drew %d rows from two Transactions - the row a "
                "selection paints cannot be read off a list that is not there"
                % (len(picked),))
        else:
            eq("a row selected after the switch takes the light WELL",
               str(picked[1].cget("bg")), pal["INPUT_BG"])
        cell, lbl, mark = app.sections.cells["History"]
        eq("a section picked after the switch takes the light CARD",
           str(cell.cget("bg")), pal["CARD"])
        eq("  and its 2px mark the light TEXT",
           str(mark.cget("bg")), pal["TEXT"])
        eq("  with its label on the same fill",
           str(lbl.cget("bg")), pal["CARD"])

        app._show_tab("Submit")
        app._paint_recent_detail(2)
        root.update_idletasks()
        eq("a detail pane repainted after the switch stands on light CARD",
           str(app.recent_detail.body.cget("bg")), pal["CARD"])
    finally:
        quiesce(root)
        ui_kit_theme_state(SK.THEME, was_theme)


def check_the_storekeeper_is_drawn_on_flat_colour():
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
    head("the Storekeeper is drawn on flat colour")
    tk = tk_or_skip()
    if tk is None:
        return

    def labelled(root, text):
        for w in widgets(root):
            try:
                if w.winfo_class() == "Label" and w.cget("text") == text:
                    return w
            except Exception:
                pass
        return None

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

    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = SK.StorekeeperApp(root)
    root.update_idletasks()
    root.update()
    pal = SK.THEME.palette()

    placed = [w for w in root.winfo_children()
              if w.winfo_class() == "Canvas" and w.winfo_manager() == "place"]
    eq("no backdrop canvas is placed under the window", placed, [])

    name = labelled(root, "Asset Manager")
    if name is None:
        bad("the header has no app name on it - this group has stopped "
            "measuring what it names")
        root.destroy()
        return
    bar = name.master
    eq("the header band is a plain frame", bar.winfo_class(), "Frame")
    eq("  drawn in the palette's own BG", str(bar.cget("bg")), pal["BG"])
    one_colour("the header band", bar)

    entry = app.v_asset_no
    eq("the transaction form's fields keep INPUT_BG",
       str(entry.cget("bg")), pal["INPUT_BG"])
    eq("  and the strip they sit on is flat CARD",
       str(entry.master.master.master.cget("bg")), pal["CARD"])

    was = str(name.cget("bg"))
    SK.THEME.set("light")
    root.update_idletasks()
    root.update()
    light = SK.THEME.palette()
    eq("a theme switch moves the band and its labels together",
       (str(bar.cget("bg")), str(name.cget("bg"))),
       (light["BG"], light["BG"]))
    eq("  which is a colour it was not", str(name.cget("bg")) != was, True)
    SK.THEME.set("dark")
    root.destroy()


def check_the_storekeeper_offers_the_models_the_register_holds():
    """Asset Model is picked from what the register holds, not typed blind (S2).

    026 gave the Server GUI's Lookup Sheet window a model combobox and left
    the other door - the one actually used by the person standing where the
    hardware arrives - as a free-text box. That is how one laptop came to be
    held as `ThinkPad T14`, `Thinkpad T14` and `T14`.

    Two halves. `common.py`'s, because the cache is what this offers when the
    server cannot be reached and its rules are not the types cache's: an empty
    list is an **answer** here and is cached as one, where an empty types
    answer is a server that has not answered properly. And the window's, since
    what changed is the widget - and a combobox that is not editable would be
    the opposite failure, a model nobody has bought before being untypeable at
    the one door where the register grows one.
    """
    head("the Storekeeper offers the models the register holds (S2)")
    tk = tk_or_skip()
    if tk is None:
        return

    class _Answer(object):
        def __init__(self, payload):
            self.ok, self._p = True, payload

        def json(self):
            return self._p

    asked = []

    def answering(models_by_type, types=None):
        def _api(_verb, url, params=None, **_k):
            asked.append((url, (params or {}).get("type", "")))
            if url.endswith("/asset_types"):
                return _Answer({"asset_types": types or ["Laptop", "Screen"]})
            want = (params or {}).get("type", "")
            return _Answer({"asset_models": models_by_type.get(want, [])})
        return _api

    if os.path.exists(C.ASSET_CACHE_PATH):
        os.remove(C.ASSET_CACHE_PATH)

    # -- with no server at all: nothing offered, and nothing written ---------
    eq("a fetch that cannot reach the server offers nothing",
       C.fetch_asset_models("http://127.0.0.1:1", "Laptop"), [])
    eq("  and writes no cache to answer out of later",
       os.path.exists(C.ASSET_CACHE_PATH), False)

    real_api = C.api
    try:
        C.api = answering({"Laptop": ["EliteBook 840", "ThinkPad T14"],
                           "Screen": [],
                           "": ["EliteBook 840", "ThinkPad T14", "U2419H"]})
        eq("the register's models for one type, as the server sorted them",
           C.fetch_asset_models("http://s", "Laptop"),
           ["EliteBook 840", "ThinkPad T14"])
        eq("  narrowed, so the unnarrowed answer is a different question",
           C.fetch_asset_models("http://s", ""),
           ["EliteBook 840", "ThinkPad T14", "U2419H"])
        # An empty answer is a type nobody has recorded a model against, which
        # is an ordinary state and the same answer the console gives. The
        # types fetch beside it treats empty as a failure; this one must not,
        # or a Screen would go on being offered a Laptop's models for ever.
        eq("a type with no model recorded is an empty answer, not a failure",
           C.fetch_asset_models("http://s", "Screen"), [])
        eq("  and it is cached as one", C.cached_asset_models("Screen"), [])

        # 027's fold, one level out: a sheet holding `Laptop` answers `LAPTOP`
        # too, so two spellings of one type must not become two cache entries
        # free to disagree.
        eq("a type is cached without regard to case",
           C.cached_asset_models("LAPTOP"),
           ["EliteBook 840", "ThinkPad T14"])

        # The types fetch writes this same file. It wrote a fresh dict until
        # S2, which would drop every model on the 15s tick that refreshes the
        # types - the cache then answering nothing exactly when the server is
        # unreachable, which is the one time it is read.
        C.fetch_asset_types("http://s")
        eq("a types fetch does not take the models down with it",
           C.cached_asset_models("Laptop"),
           ["EliteBook 840", "ThinkPad T14"])
        eq("  and the types it wrote are still there",
           bool(C.cached_asset_types()), True)

        C.api = _offline
        eq("a fetch that fails afterwards answers out of the cache",
           C.fetch_asset_models("http://s", "Laptop"),
           ["EliteBook 840", "ThinkPad T14"])
    finally:
        C.api = real_api

    # -- and the window ------------------------------------------------------
    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = SK.StorekeeperApp(root)
    root.update_idletasks()
    root.update()

    app._propose._propose_dialog("MODEL-1", "")
    root.update_idletasks()
    root.update()
    dlgs = [w for w in widgets(root) if isinstance(w, tk.Toplevel)
            and w.winfo_exists() and w.title() == "Add New Asset"]
    if not dlgs:
        bad("Add New Asset did not open")
        close(root, [])
        return
    dlg = dlgs[0]
    boxes = [c for c in widgets(dlg) if c.winfo_class() == "TCombobox"]
    eq("Asset Type and Asset Model are both comboboxes now", len(boxes), 2)
    if len(boxes) < 2:
        close(root, dlgs)
        return
    at_box, am_box = boxes[0], boxes[1]

    # Editable, for the reason Type is: a model nobody has bought before has
    # to be typeable somewhere and this is where the register grows one. What
    # stops a typo becoming a permanent model is that an Admin approves the
    # proposal (ADR-0012), not that the form refused to let it be typed.
    eq("the model box is editable, not readonly",
       "readonly" in str(am_box.cget("state")), False)

    # The api is offline here, which is this file's whole server, so what is
    # offered is the cache - which is the offline path itself rather than a
    # simulation of one.
    at_box.set("Laptop")
    root.update_idletasks()
    root.update()
    eq("picking a type offers that type's models out of the cache",
       list(am_box.cget("values")), ["EliteBook 840", "ThinkPad T14"])
    at_box.set("Screen")
    root.update_idletasks()
    root.update()
    eq("a type with no model offers nothing, not every model in the "
       "department", list(am_box.cget("values")), [])

    # And a model this register has never held is still sendable: the box is
    # the offer and not the rule.
    am_box.set("Something Nobody Has Bought")
    eq("a model in no list is still what the form holds",
       am_box.get(), "Something Nobody Has Bought")
    close(root, dlgs)
    quiesce(root)


def check_the_storekeeper_offers_adding_an_engineer_while_it_may():
    """The Add Engineer offer follows the switch on the heartbeat (S3).

    Two halves, and the second is what the ticket is actually about. The
    offer: hidden rather than greyed while the switch is off, for the reason
    the Cancel pill is - the switch is not about anything the storekeeper can
    do something about - and the whole card rather than the button alone, what
    would be left otherwise being a heading and a sentence about a control that
    is not there. A server that says nothing leaves the offer standing, the
    answer `storekeeper_can_cancel` gives beside it.

    And the dialog: it asks for **no password**, so what goes on the wire is a
    body with no `password` key at all - which is what the server reads as this
    path, `password: ""` being an attempt at the admin one and refused as wrong
    (ADR-0017). Asserted on the body rather than on the answer, since the
    server this file has is one that raises, and what could go wrong silently
    is sending `password: ""` and having every creation refused as a bad
    credential on a machine nobody is watching.
    """
    head("the Storekeeper offers adding an engineer while it may (S3)")
    tk = tk_or_skip()
    if tk is None:
        return

    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = SK.StorekeeperApp(root)
    root.update_idletasks()
    root.update()

    def card_shown():
        return bool(app._eng_card.winfo_manager())

    eq("a fresh client offers it", card_shown(), True)
    app._note_health({"storekeeper_can_cancel": True})
    eq("a server too old to carry the key leaves the offer standing",
       card_shown(), True)
    app._note_health(None)
    eq("an unreachable server keeps the last answer rather than guessing",
       card_shown(), True)

    app._note_health({"storekeeper_can_add_engineer": False})
    root.update_idletasks()
    eq("the switch off hides the card, rather than greying a button",
       card_shown(), False)
    app._note_health({"storekeeper_can_add_engineer": True})
    root.update_idletasks()
    eq("and it comes back when the switch does", card_shown(), True)
    # Back in its own place: pack puts a re-shown child last, which would leave
    # Engineers under Assets after a switch that went off and on again.
    kids = [w for w in app._eng_card.master.winfo_children()
            if w.winfo_manager()]
    eq("  above the Assets card it sat above",
       kids.index(app._eng_card) < kids.index(app._assets_card), True)

    # -- and what the dialog puts on the wire ---------------------------------
    sent = []

    def _api(_verb, url, json=None, **_k):
        sent.append((url, json or {}))
        raise OSError("no server in this harness")

    real_api = SK.api
    try:
        SK.api = _api
        app._add_engineer_dialog()
        root.update_idletasks()
        root.update()
        dlgs = [w for w in widgets(root) if isinstance(w, tk.Toplevel)
                and w.winfo_exists() and w.title() == "Add Engineer"]
        if not dlgs:
            bad("Add Engineer did not open")
            close(root, [])
            return
        dlg = dlgs[0]
        shown = [c for c in widgets(dlg)
                 if isinstance(c, tk.Entry) and c.winfo_manager()]
        eq("the form asks for one thing, a name", len(shown), 1)
        eq("  and nothing on it is a password field",
           [c for c in shown if str(c.cget("show"))], [])

        shown[0].insert(0, "Nadia Fouad")
        for b in widgets(dlg):
            if isinstance(b, tk.Button) and "Add Engineer" in str(b.cget("text")):
                b.invoke()
                break
        root.update_idletasks()

        posts = [(u, j) for (u, j) in sent if u.endswith("/members")]
        eq("it posts the creation", len(posts), 1)
        if posts:
            body = posts[0][1]
            eq("  with no password key at all - not an empty one",
               "password" in body, False)
            eq("  naming who", body.get("name"), "Nadia Fouad")
            eq("  and carrying auto-approve, the one flag settable here",
               "auto_approve" in body, True)
            eq("  and nothing that would be an edit",
               [k for k in ("profile", "permissions", "member_password")
                if k in body], [])
        close(root, dlgs)
    finally:
        SK.api = real_api
    quiesce(root)


def check_the_storekeeper_takes_its_name_from_the_server():
    """Who this installation records Transactions as arrives on /health.

    Not a window check, but this app's and a Tk callback either way: the name
    is adopted on the background tick, which no endpoint answers for and no
    static read sees. What matters is the three ways of saying nothing - an
    unreachable server, a server too old to carry the key, and an empty value -
    all leaving the name this installation already had. A server that predates
    the key would otherwise blank the name on its first heartbeat, and every
    entry after that would be attributed to nobody.

    The write-back to config.json is the other half. app.started is logged
    inside __init__, before any heartbeat has been answered, so a name held
    only in memory would attribute the first entry of every run to the default
    rather than to whoever holds the store.
    """
    head("the Storekeeper takes its name from the server")
    tk = tk_or_skip()
    if tk is None:
        return

    was_default = dict(SK.DEFAULT_CFG)
    was_name = SK._sk_name
    try:
        if os.path.exists(SK.CONFIG_PATH):
            os.remove(SK.CONFIG_PATH)
        root = tk.Tk()
        root.geometry("1360x830+0+0")
        app = SK.StorekeeperApp(root)
        root.update_idletasks()

        eq("a fresh install records under the column default",
           SK._sk_name, "Storekeeper User")
        eq("and attributes its entries with the role",
           SK.sk_actor(), "Storekeeper User (Storekeeper)")
        eq("the window says who that is",
           "Storekeeper User" in app.sk_lbl.cget("text"), True)

        app._note_health(None)
        eq("an unreachable server changes nothing", SK._sk_name,
           "Storekeeper User")
        app._note_health({"storekeeper_can_cancel": True})
        eq("a server too old to carry the key changes nothing",
           SK._sk_name, "Storekeeper User")
        app._note_health({"storekeeper_name": "   "})
        eq("an empty name is nothing said, not a name cleared",
           SK._sk_name, "Storekeeper User")

        app._note_health({"storekeeper_name": "Ahmed Fathy"})
        eq("a name on the heartbeat is adopted", SK._sk_name, "Ahmed Fathy")
        eq("the label follows it",
           "Ahmed Fathy" in app.sk_lbl.cget("text"), True)
        eq("and so does what entries are attributed to",
           SK.sk_actor(), "Ahmed Fathy (Storekeeper)")

        with io.open(SK.CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        eq("it survives a restart", saved.get("storekeeper_name"),
           "Ahmed Fathy")
        eq("and nothing else in the file moved",
           saved.get("server_url"), app.cfg.get("server_url"))

        url = app.cfg.get("server_url")
        close(root, [])
        quiesce(root)

        # The other way the name can be lost, and it is not the heartbeat's.
        # load_config (common.load_config since #211) reads the file over a
        # copy of the defaults; written the
        # other way round - the file into DEFAULT_CFG, then copied - the first
        # read replaces the module's record of what a default is with whatever
        # the file said, and __init__'s `or DEFAULT_CFG["storekeeper_name"]`
        # can from then on never answer with one. So the input that fallback
        # exists for is the input it got wrong: a whole run attributed to
        # " (Storekeeper)", with every Transaction carrying an empty
        # storekeeper column.
        io.open(SK.CONFIG_PATH, "w", encoding="utf-8").write(
            json.dumps({"server_url": url, "storekeeper_name": "   "}))
        SK._sk_name = "Storekeeper User"
        root = tk.Tk()
        root.geometry("1360x830+0+0")
        app = SK.StorekeeperApp(root)
        root.update_idletasks()

        eq("a config naming nobody records under the column default",
           SK._sk_name, "Storekeeper User")
        eq("  and its entries are attributed to somebody",
           SK.sk_actor(), "Storekeeper User (Storekeeper)")
        eq("  because reading a config leaves the defaults where they are",
           SK.DEFAULT_CFG.get("storekeeper_name"), "Storekeeper User")

        close(root, [])
        quiesce(root)

        # And the half that stops this passing by ignoring the file: a name
        # that is a name is still read out of it.
        io.open(SK.CONFIG_PATH, "w", encoding="utf-8").write(
            json.dumps({"server_url": url, "storekeeper_name": "Sara Nabil"}))
        root = tk.Tk()
        root.geometry("1360x830+0+0")
        app = SK.StorekeeperApp(root)
        root.update_idletasks()
        eq("a name in the config is what the run records under",
           SK._sk_name, "Sara Nabil")
        eq("  and the defaults are still the defaults beside it",
           SK.DEFAULT_CFG.get("storekeeper_name"), "Storekeeper User")

        close(root, [])
        quiesce(root)
    finally:
        SK._sk_name = was_name
        SK.DEFAULT_CFG.clear()
        SK.DEFAULT_CFG.update(was_default)
        if os.path.exists(SK.CONFIG_PATH):
            os.remove(SK.CONFIG_PATH)


def check_the_export_summarises_the_rows_it_was_given():
    """The workbook's Summary counts the Transactions in the workbook.

    It counted TEAM_MEMBERS instead, which is the fallback list a client shows
    when it cannot reach the server, not the engineers this store has. So one
    workbook carried a Detail sheet listing an Engineer added since the build
    and a Summary eight rows from the Total that did not mention them, three
    engineers who had done nothing at zero, and a per-engineer column that did
    not add up to the Total beside it. The bar chart plotted the same range.

    Which engineers a set of Transactions is about is a fact those rows
    already hold, so it is read off them - and that is what is asserted here,
    rather than the new list being the right one: a list is what went wrong.

    Not a window check. The workbook is written past a file dialog no harness
    can answer, so _write_excel is called with the rows directly, which is
    also the only way to read the result back. It is `SE._write_excel` since
    #219 - the writer and the dialog are storekeeper_export.py now, while
    `_open_export`, the caller this also reads, stayed with the app.
    """
    head("the export summarises the rows it was given")
    try:
        import openpyxl
    except ImportError:
        skip("openpyxl is not installed - the export cannot be written")
        return

    # One Engineer the baked-in list has and one it does not. Both have to
    # come out of the Summary the same way, since what is being asserted is
    # that the list plays no part.
    known   = SK.TEAM_MEMBERS[1]
    unknown = "Sara Nabil"
    eq("the test engineer is deliberately not in the fallback list",
       unknown in SK.TEAM_MEMBERS, False)

    rows = []
    for i, who in enumerate([unknown] * 3 + [known]):
        rows.append({"id": i + 1, "asset_number": "IT-%04d" % (i + 1),
                     "serial_number": "", "asset_type": "Laptop",
                     "asset_model": "T14", "team_member": who,
                     "direction": "Out Store",
                     "timestamp": "2026-09-13T10:0%d:00" % i,
                     "confirmed": 1, "rejected": 0, "confirmed_at": "",
                     "rejection_reason": "", "notes": "",
                     "storekeeper": "Storekeeper User"})

    # `_write_excel` ends by telling the storekeeper where it saved the
    # workbook, and a real `showinfo` is a modal nobody is standing in front
    # of: the gate stops on it with no output and no failure, which is
    # indistinguishable from a deadlock, and every group behind this one
    # never runs. Every other group here stubs the module for its own
    # reasons; this one has to stub it to finish at all.
    class _Said(object):
        def __init__(self):
            self.said = []

        def showinfo(self, title, msg=None, **kw):
            self.said.append(("info", title, msg))

        def showerror(self, title, msg=None, **kw):
            self.said.append(("error", title, msg))

        def showwarning(self, title, msg=None, **kw):
            self.said.append(("warn", title, msg))

    path = os.path.join(STAGE, "export-check.xlsx")
    said, real_mb = _Said(), SE.messagebox
    try:
        SE.messagebox = said
        SE._write_excel(rows, path)
    finally:
        SE.messagebox = real_mb
    eq("the workbook was written and said so", bool(said.said), True)
    wb = openpyxl.load_workbook(path)
    ws2 = wb["Summary"]

    summary = {}
    for r in range(5, 40):
        name = ws2.cell(row=r, column=6).value
        if not name:
            break
        summary[name] = ws2.cell(row=r, column=7).value

    eq("an Engineer added since the build is counted",
       summary.get(unknown), 3)
    eq("  and one the fallback list happens to hold is counted the same way",
       summary.get(known), 1)
    eq("  and nobody who did nothing is invented beside them",
       sorted(summary), sorted([known, unknown]))
    # The Status table's Total sits eight rows to the left of that column.
    eq("the per-Engineer counts add up to the Total on the same sheet",
       sum(summary.values()), ws2.cell(row=8, column=2).value)

    # And the half that stops this passing on an empty summary: the rows are
    # in the workbook either way, so a Summary listing nobody is not a pass.
    eq("the Summary lists somebody at all", bool(summary), True)

    # The list is gone from where it was read, and the live one is handed
    # over instead. A source check: _open_export is a Tk callback and what is
    # claimed of _write_excel is an absence. Two files since #219, read as one
    # mapping: the writer and the dialog are storekeeper_export.py's and
    # `StorekeeperApp` is still storekeeper_app.py's, and what is asserted
    # below is the same three things about the same three definitions.
    top = {}
    for _f in ("storekeeper_app.py", "storekeeper_export.py"):
        tree = ast.parse(io.open(os.path.join(STAGE, _f),
                                 encoding="utf-8").read())
        top.update({n.name: n for n in tree.body
                    if isinstance(n, (ast.FunctionDef, ast.ClassDef))})

    def body(node):
        """A definition's source, comments dropped.

        Unparsed rather than sliced out of the file, so a comment saying why
        the fallback list is not read here does not read as a read of it -
        the same reason cascade-audit.py asks which module *calls* a thing."""
        return ast.unparse(node)

    def method(cls, name):
        return next(n for n in top[cls].body
                    if isinstance(n, ast.FunctionDef) and n.name == name)

    app = next(n for n in top["StorekeeperApp"].body
               if isinstance(n, ast.FunctionDef) and n.name == "_open_export")
    eq("the summary writer names no engineer list",
       "TEAM_MEMBERS" in body(top["_write_excel"]), False)
    eq("  and the export dialog is handed one rather than naming one",
       "members" in [a.arg for a in method("ExportDialog", "__init__").args.args],
       True)
    eq("  which is the list this installation was told about",
       "_members" in body(app), True)


def check_the_storekeeper_names_nobody_in_its_source():
    """No Transaction this app submits carries a hardcoded name.

    A source check: the three bodies - the form, the offline buffer and the
    bulk flush - are reached through a server this file deliberately does not
    have, and a literal left in one of them would only show up as a Transaction
    recorded under the wrong person months later.
    """
    head("the Storekeeper names nobody in its source")
    src = io.open(os.path.join(STAGE, "storekeeper_app.py"),
                  encoding="utf-8").read()
    tree = ast.parse(src)
    literal = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, ast.Constant) and k.value == "storekeeper"
                    and isinstance(v, ast.Constant)):
                literal.append((node.lineno, v.value))
    eq("no Transaction body names a storekeeper outright", literal, [])
    eq("the default is stated once, in DEFAULT_CFG",
       src.count('"storekeeper_name": "Storekeeper User"'), 1)


def check_the_storekeeper_says_it_on_the_window():
    """A notification is drawn on the window and flashes the taskbar (#193).

    The three notifications this app makes - a rejection, a proposal answered,
    and a Transaction the offline buffer could not get recorded - each forced
    the window forward with `deiconify` + `lift` + `-topmost` and then opened a
    modal `messagebox` on it. Dropping the forcing on its own would have been
    **worse than leaving it**, which is why this is a replacement rather than a
    deletion: a `messagebox` is modal and appears over its parent, so a parent
    behind another application is an app wedged behind a dialog nobody can see.

    So what is driven is the pair. The notice lands on the strip and says what
    the box said; nothing is raised and nothing grabs, so a Transaction being
    typed at the moment one arrives is untouched; and the \u2715 on it is what
    takes it away, because a notice nobody can dismiss is the popup this
    ticket refuses by another door. The bound is asserted too - the strip
    cannot grow until it pushes the form off the window.
    """
    head("the Storekeeper says it on the window (#193)")
    tk = tk_or_skip()
    if tk is None:
        return

    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = SK.StorekeeperApp(root)
    root.update_idletasks()
    root.update()

    def pump():
        root.update_idletasks()
        root.update()

    def rows():
        return list(app.notices.winfo_children())

    try:
        eq("the strip starts empty and costs no height",
           (len(rows()), app.notices.winfo_height() <= 1), (0, True))

        app._notify_rejection({"asset_number": "A-1", "asset_type": "Laptop",
                               "direction": "Out Store",
                               "team_member": "Brian Dawson",
                               "rejection_reason": "not mine"})
        pump()
        said = [w for w in widgets(app.notices)
                if isinstance(w, tk.Label) and str(w.cget("text"))]
        text = " | ".join(str(w.cget("text")) for w in said)
        eq("a rejection puts one notice on the window", len(rows()), 1)
        eq("  naming the engineer, the asset and the reason",
           ("Brian Dawson" in text, "A-1" in text, "not mine" in text),
           (True, True, True))
        eq("  and it takes no grab, so the form is still typed into",
           root.grab_current(), None)
        eq("  and asks for no topmost",
           bool(root.attributes("-topmost")), False)

        # The X on it is what takes it away.
        shut = [w for w in widgets(app.notices)
                if isinstance(w, tk.Label) and str(w.cget("text")) == "\u2715"]
        eq("  it carries one dismiss control", len(shut), 1)
        shut[0].event_generate("<Button-1>", x=2, y=2)
        pump()
        eq("  and clicking it takes the notice away", len(rows()), 0)

        # A proposal answered and a buffered Transaction refused go the same
        # way, and the strip is bounded however many arrive.
        app._notify_decision({"asset_number": "A-2", "status": "approved",
                              "asset_type": "Laptop", "decided_by": "Admin"})
        app._notify_decision({"asset_number": "A-3", "status": "rejected",
                              "reason": "already held"})
        pump()
        eq("an answered proposal says so the same way", len(rows()), 2)

        for i in range(6):
            app._notify_rejection({"asset_number": "B-%d" % i,
                                   "asset_type": "Laptop",
                                   "direction": "In Store",
                                   "team_member": "Brian Dawson",
                                   "rejection_reason": "no"})
        pump()
        eq("and the strip is bounded rather than unbounded",
           len(rows()) <= SK.StorekeeperApp.NOTICE_MAX, True)
        eq("  with the newest of them kept",
           any("B-5" in str(w.cget("text")) for w in widgets(app.notices)
               if isinstance(w, tk.Label)), True)
    finally:
        quiesce(root)
        try:
            root.destroy()
        except Exception:
            pass


def check_the_storekeeper_hides_to_its_tray():
    """Closing the window hides it; only the tray's Exit quits (#272).

    The tray itself is pystray's and needs a desktop, so `run_tray_icon` is
    replaced by one that records what it was handed. What is checked is this
    app's side: the menu has exactly three actions, close withdraws rather
    than destroys, and Exit stops the icon and ends the window.
    """
    head("the Storekeeper hides to its tray")
    tk = tk_or_skip()
    if tk is None:
        return

    handed = {}

    class _Icon:
        stopped = False

        def stop(self):
            self.stopped = True

    def _fake_tray(root, name, tooltip, image, items, on_ready=None):
        handed["items"] = items
        if on_ready is not None:
            on_ready(_Icon())

    was = SK.ui_kit.HAS_TRAY, SK.ui_kit.run_tray_icon
    SK.ui_kit.HAS_TRAY, SK.ui_kit.run_tray_icon = True, _fake_tray
    root = None
    try:
        root = tk.Tk()
        root.geometry("1360x830+0+0")
        app = SK.StorekeeperApp(root)
        app._build_tray()
        root.update_idletasks()

        items = handed.get("items") or []
        actions = [label for item in items if item is not None
                   for label, cb in [item] if cb is not None]
        eq("the tray has exactly its three actions", actions,
           ["Show console", "Check for updates", "Exit"])
        eq("  Check for updates is the Tools tab's callback, not a second",
           [cb for item in items if item is not None
            for label, cb in [item] if label == "Check for updates"],
           [app._manual_update_check])

        root.deiconify()
        root.update()
        root.tk.eval(root.protocol("WM_DELETE_WINDOW"))
        root.update()
        eq("closing the window withdraws it", root.state(), "withdrawn")
        app._show_console()
        root.update()
        eq("Show console brings it back", root.state(), "normal")

        icon = app.tray_icon
        app._quit()
        eq("Exit stops the tray icon", icon.stopped, True)
        try:
            root.winfo_exists()
            bad("Exit left the window standing")
        except tk.TclError:
            ok("Exit ends the window")
        root = None
    finally:
        SK.ui_kit.HAS_TRAY, SK.ui_kit.run_tray_icon = was
        if root is not None:
            quiesce(root)
            try:
                root.destroy()
            except Exception:
                pass


def check_the_tray_helper_builds_a_menu_pystray_accepts():
    """`ui_kit.run_tray_icon` hands pystray actions it will take (#272).

    pystray counts an action's parameters and refuses more than two, so a
    helper that wrapped each callback with a third, defaulted one built no
    tray at all, in every app, and said so only on a thread nobody watched.
    The icon is built for real here and stopped in `on_ready`, before `run()`
    would need a desktop.
    """
    head("the tray helper builds a menu pystray accepts")
    import ui_kit
    if not ui_kit.HAS_TRAY:
        skip("pystray or pillow is not installed")
        return

    class _Built(Exception):
        pass

    def _stop(icon):
        raise _Built()

    try:
        ui_kit.run_tray_icon(None, "check", "check", ui_kit.app_icon(64),
                             [("caption", None), None, ("action", print)],
                             on_ready=_stop)
        bad("run_tray_icon returned without calling on_ready")
    except _Built:
        ok("pystray took every item the helper built")
    except Exception as e:
        bad("pystray refused the menu: %r" % (e,))
