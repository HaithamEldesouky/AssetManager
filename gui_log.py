"""The System Log - what was done, by which component, when.

Lifted out of server_gui.py by #235 (060). The System section's pane
(#262/087); the rows, the retention and the clear behind its button are
``server_log.py``'s, and this is the console's reader of them.

The seam back to ``server_gui.py`` - ``S`` read at call time, the
palette seeded by ``_bind_palette`` - is described once, in that module's own
docstring, under "The nine window modules".
"""

from datetime import datetime

import ui_kit
from ui_kit import font

import server_gui
from server_gui import _tag_ages, _when_ts


def _bind_palette():
    """This module's colour names, out of the palette that is live.

    Written through ``globals()`` rather than restated as literals for the
    reason ``ui_kit.DARK`` exists at all: ``retint`` repaints a widget by
    reading its colour back off it and looking that up in the table, so a
    widget painted from a value this file wrote down itself has no entry, is
    skipped, and stays dark inside a light window.
    """
    g = globals()
    for name, colour in server_gui.THEME.palette().items():
        g[name] = colour


# Seeded at import, before the swap that may never come: the console can run
# its whole life in the mode it started in, and a window drawn in that life
# still needs the names.
_bind_palette()
server_gui.THEME.watch(_bind_palette)


def system_log(parent):
    """The System Log - what was done, by which component, when.

    **The System section's pane** (#262/087), not a window. Like Asset
    Proposals one ticket back and unlike Connected Clients two, the section it
    sits on carries rows as well: Server Settings, Display Settings, Database
    Location, Mail Settings, Notification Rules and Backup / Restore are still
    entries, and this is the list under them - `section_pane`'s third
    argument, named in `LISTED` beside the build loop.

    What went with the Toplevel is everything that was about being one: the
    `raise_open`/`single` pair, a pane the console builds once being single by
    construction; Escape and the Close pill, because there is nothing to close
    - the bar swaps what is on the stage; `transient`; and the written
    `minsize` with the `ui_kit.fit` above it, a pane being served whatever the
    console has. The 14px inset every child of it carried went too, for the
    reason 086 dropped its own 18px: `section_pane` packs this inside a
    container that is already inset, and keeping one would draw the filters
    and the table in from the entry rows above them. It paints CARD rather
    than BG, the stage's own surface, which is what the five other sections
    are.

    Reads the table rather than an endpoint, for the reason `_client_rows`
    gives and one more: this is a record of who typed a wrong password and from
    where, and publishing it would hand that to anybody who can reach the port.
    There is deliberately no GET behind it.

    Filtered by component and by date, because those are the two questions
    actually asked of it - "what did that laptop do" and "what happened on the
    day of the dispute" - and both are a WHERE over a column, which is half the
    reason the log is a table rather than a file beside the server.

    The `From` column is the load-bearing one. It holds the source address the
    server saw, and it is empty for exactly the rows the server wrote in
    process, so a row claiming component "Server" with an address beside it is
    visibly a claim made over the network rather than something this server
    did. POST /clients/log is unauthenticated (ADR-0002, ADR-0005) and that is
    accepted; being able to see it is the part that is not optional.

    Asks for no password, for the reason Display Settings does not: it shows
    what this console already holds, and it changes nothing. What it must never
    show is a password, in any form - `_log_event` is where that is enforced,
    because nothing is stored for this window to leak.

    **Export** and **Clear** both act on what the filter is showing rather
    than on the whole table (ticket A9): retention is automatic and bounded
    (90 days / `LOG_MAX_ROWS` rows) and neither bound is reachable by hand, so
    an Admin who wants this machine's log off it, or a compromised window of
    it gone, has a door - and it is the same door as the one they are already
    looking through, not a second, wider one. Export needs no password, being
    a read of what this window already shows; Clear does, the same way
    Manage Transaction History's Delete does, because unlike a Transaction row
    a System Log row is never kept-but-marked - there is no ADR-0003 for this
    table, so deleting it is the only door there is, and it takes what
    deleting anything else here takes. `log.cleared` is written **after** the
    delete, unconditionally, as the first row of the log that follows it -
    that entry is the only evidence the clear happened at all.
    """
    from server_gui import S

    import tkinter as tk
    from tkinter import ttk

    pane = tk.Frame(parent, bg=CARD)
    # Every dialog this pane opens is still a Toplevel and still wants a
    # window to sit over - `wm transient` and a messagebox's `-parent` both
    # take one, and a Frame is not.
    top = pane.winfo_toplevel()

    # Packed before the body and from the bottom, so the controls are the
    # first children served rather than the last: pack gives a shortfall to
    # whatever went in last, and that is how four dialogs here came to have no
    # usable button.
    foot = tk.Frame(pane, bg=CARD)
    foot.pack(side="bottom", fill="x")

    # **The paragraph is gone, and it is the one thing 087 gave up.** The six
    # entries this section keeps take 350px of a 493px stage, so the pane is
    # served 143px - and its fixed furniture came to 146px before a single
    # table row, which is a list that is not merely cramped but never mapped.
    # What was cut is the 34px of prose, because of the four things on this
    # pane it was the only one that was documentation rather than the record:
    # the filters are the two questions asked of the log, the table is the
    # answer, the count is how much of it there is, and a paragraph explaining
    # them is the thing a reader can do without when the alternative is not
    # being shown the rows at all. **Nothing load-bearing went with it.** The
    # sentence it carried about the source address is said by the `From`
    # column itself, by the count line below - which names how many rows
    # arrived over the network - and in full words by the row-detail popup,
    # which is where an entry is actually read (ADR-0002, ADR-0005). The
    # retention bound it also stated is the table's and not this pane's, and
    # is asserted where it is applied.
    #
    # The name and the count on **one** line, the count from the right. On a
    # window each had a line of its own; on a 143px pane a line is 32px with
    # its padding, and the table is what pays for it. They read as one
    # sentence anyway - what this is, and how much of it there is.
    hrow = tk.Frame(pane, bg=CARD)
    hrow.pack(fill="x", pady=(8, 2))
    tk.Label(hrow, text="🗒  System Log  —  what was done, across all three "
                        "components, and where each row came from",
             bg=CARD, fg=TEXT,
             font=font("heading")).pack(side="left")

    # ── the two filters ──────────────────────────────────────────────────────
    # The two questions actually asked of this log - "what did that laptop do"
    # and "what happened on the day of the dispute" - and each is a WHERE over
    # a column, which is half the reason it is a table rather than a file
    # beside the server. They are untouched by 087: the pane changed what this
    # is drawn on, not what it is for.
    fr = tk.Frame(pane, bg=CARD)
    fr.pack(fill="x", pady=(0, 6))
    comp_v = tk.StringVar(value="All")
    tk.Label(fr, text="Component", bg=CARD, fg=SUBTEXT,
             font=font("body")).pack(side="left")
    ttk.Combobox(fr, textvariable=comp_v, values=["All"] + list(S.LOG_COMPONENTS),
                 state="readonly", width=14, style="S.TCombobox",
                 font=font("body")).pack(side="left", padx=(6, 18))
    tk.Label(fr, text="From", bg=CARD, fg=SUBTEXT,
             font=font("body")).pack(side="left")
    from_e = tk.Entry(fr, bg=INPUT_BG, fg=TEXT, relief="flat", width=12,
                      insertbackground=TEXT, font=font("body"))
    from_e.pack(side="left", padx=(6, 12), ipady=3)
    tk.Label(fr, text="To", bg=CARD, fg=SUBTEXT,
             font=font("body")).pack(side="left")
    to_e = tk.Entry(fr, bg=INPUT_BG, fg=TEXT, relief="flat", width=12,
                    insertbackground=TEXT, font=font("body"))
    to_e.pack(side="left", padx=(6, 12), ipady=3)
    tk.Label(fr, text="YYYY-MM-DD, either or both", bg=CARD, fg=FAINT,
             font=font("micro")).pack(side="left")

    # `meaning` is derived at read time and sits **after** Actor, so a row reads
    # left to right as who, then what they did, then the line of context (#196).
    # `event` stays on the window in front of it rather than being replaced by
    # it: that short name is what an Admin writing a Notification Rule has to
    # type, and it is what every older row, both clients and every rule already
    # match on.
    cols = ("ts", "component", "level", "event", "actor", "meaning", "detail",
            "address", "client_ts")
    headers = {"ts": "When (this server)", "component": "Component",
               "level": "Level", "event": "Event", "actor": "Actor",
               "meaning": "What happened", "detail": "Detail",
               "address": "From", "client_ts": "Client's own clock"}
    widths = {"ts": 125, "component": 90, "level": 52, "event": 150,
              "actor": 130, "meaning": 250, "detail": 270, "address": 100,
              "client_ts": 118}
    # `height=8` rather than the window's 16: a pane is served whatever the
    # console has and the table takes the remainder through `expand=True`, so
    # the number is what this pane *asks* for - and one asking 349px of a
    # 143px stage is a request it cannot back.
    tree = ttk.Treeview(pane, columns=cols, show="headings", height=8)
    # Which System Log row each item is (#195). The id is not a column - it is
    # a key rather than a fact about the act, and a column of it would take
    # width off `Detail` on the window this is read on - and the values a
    # Treeview holds are the strings it drew, so the row-detail popup is
    # opened by this map rather than by reading a cell back.
    row_ids = {}
    for c in cols:
        tree.heading(c, text=headers[c])
        tree.column(c, width=widths[c], anchor="w")
    # A refusal and an ordinary action must not read the same at a glance -
    # this list exists to be skimmed.
    _tag_ages(tree, (("info", "SUBTEXT"), ("warn", "WARNING"),
                     ("error", "DANGER")))

    # On the heading line rather than under the table, and packed from the
    # right so the name beside it is what grows. This is 086's correction
    # taken one step further: there the count was reserved from the bottom so
    # `pack` could not squeeze it out, and here there is not a line spare to
    # reserve - the six rows above leave 143px and the furniture on this pane
    # is most of it. Sharing the heading's line is what a line costs against
    # a table that has none. Written into by `load_rows`.
    count = tk.Label(hrow, text="", bg=CARD, fg=SUBTEXT, font=font("micro"),
                     anchor="e", justify="right")
    count.pack(side="right", padx=(18, 0))
    tree.pack(fill="both", expand=True, pady=(2, 2))

    def _date(entry):
        """The entry's date, '' when empty, or None when it is not a date."""
        raw = entry.get().strip()
        if not raw:
            return ""
        try:
            datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
        return raw

    def load_rows(_e=None):
        since, until = _date(from_e), _date(to_e)
        if since is None or until is None:
            # Said rather than silently ignored: an unparsed date that quietly
            # widened the filter would be a window showing more than it was
            # asked for while looking like it had answered.
            tree.delete(*tree.get_children())
            count.config(text="A date must be written YYYY-MM-DD.")
            return
        comp = "" if comp_v.get() == "All" else comp_v.get()
        rows = S._log_rows(component=comp, since=since, until=until)
        tree.delete(*tree.get_children())
        row_ids.clear()
        for r in rows:
            lvl = r["level"] or "info"
            item = tree.insert(
                        "", "end",
                        tags=(lvl if lvl in S.LOG_LEVELS else "info",),
                        values=(_when_ts(r["ts"], "%d %b %H:%M:%S"),
                                r["component"] or "—", lvl,
                                r["event"] or "—", r["actor"] or "—",
                                S._log_cell(r, "meaning") or "—",
                                r["detail"] or "", r["address"] or "—",
                                _when_ts(r["client_ts"], "%d %b %H:%M:%S")
                                if r["client_ts"] else "—"))
            row_ids[item] = r["id"]
        shipped = sum(1 for r in rows if r["address"])
        count.config(text="nothing logged yet" if not rows else
                     "%d entr%s shown  ·  %d arrived from a Client over the "
                     "network  ·  newest first, at most 500"
                     % (len(rows), "y" if len(rows) == 1 else "ies", shipped))

    comp_v.trace_add("write", lambda *_a: load_rows())
    from_e.bind("<Return>", load_rows)
    to_e.bind("<Return>", load_rows)
    load_rows()

    def show_log_detail(eid):
        """Read-only: everything recorded in one System Log entry (#195).

        The table elides - `Detail` is 270px and holds up to
        `_LOG_DETAIL_MAX` characters, the actor is a sentence naming a
        capability and its holder, and the two clocks and the address are
        three columns read against each other - so the row somebody
        double-clicks is the row they cannot finish reading. This is the
        Transaction Detail popup one table over and is deliberately the same
        shape: read-only, no password, `ui_kit.fit` rather than a written
        size, Close packed from the bottom first, Escape closing it.

        **Where the entry carries a diff it is shown as one** (#200): a
        correction's `detail` is the only entry here that records a *change*
        rather than a fact, and reading `field: "old" -> "new"` off a 270px
        column is exactly what this window could not do. An entry with no diff
        - which is every other event, and a correction written by a build
        before #200 - shows its `detail` as it is.

        Asks for no password, for the reason the window around it does not: it
        shows what this console already holds and changes nothing, and there is
        no password in it to show, `_log_event` never receiving one.
        """
        import tkinter.messagebox as mb
        row = S._log_entry(eid)
        if row is None:
            mb.showerror("System Log Entry",
                         "Entry #%d is no longer there - refresh." % eid,
                         parent=top)
            return
        client = S._log_client(row["client_id"])
        diff = S._log_diff(row)

        if ui_kit.raise_open("log_detail:%d" % eid) is not None:
            return
        dlg = tk.Toplevel(top)
        ui_kit.single(dlg, "log_detail:%d" % eid)
        dlg.title("System Log Entry #%d" % eid)
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(top)

        hdr = tk.Frame(dlg, bg=CARD2, height=44)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🗒  System Log  #%d" % eid, bg=CARD2, fg=TEXT,
                 font=font("title")).pack(side="left", padx=14, pady=12)

        # Packed first and from the bottom, the reason every other dialog here
        # does: the control that closes this one must not be what a long diff
        # pushes off the bottom.
        dfoot = tk.Frame(dlg, bg=BG)
        dfoot.pack(side="bottom", fill="x")
        tk.Button(dfoot, text="Close", bg=CARD2, fg=TEXT,
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=dlg.destroy,
                  activebackground=LINE).pack(fill="x", padx=18, pady=(4, 12))

        body = tk.Frame(dlg, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(12, 4))

        def section(title):
            tk.Label(body, text=title, bg=BG, fg=SUBTEXT,
                     font=font("strong")).pack(anchor="w", pady=(10, 2))

        def line(label, value):
            tk.Label(body, text="%s:  %s" % (label, value or "—"), bg=BG,
                     fg=TEXT, font=font("code"), wraplength=560,
                     justify="left").pack(anchor="w")

        def fmt_ts(s):
            try:
                return datetime.fromisoformat(s).strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                return s

        section("What happened")
        line("Event", row["event"])
        line("In words", S._log_cell(row, "meaning"))
        line("Level", row["level"] or "info")
        line("Component", row["component"])
        # The actor exactly as the column holds it - `Admin (Server GUI)`,
        # `Delegate: <label> held by "<name>" (remote)`, `<name> (Storekeeper)`
        # - rather than reworded here: the wording is what #74 put in that
        # column and a second spelling of it on this window is a second answer
        # to who did something.
        line("Actor", row["actor"])

        section("When, and from where")
        line("This server's clock", fmt_ts(row["ts"]))
        line("The Client's own clock", fmt_ts(row["client_ts"]))
        # Empty for exactly the rows this server wrote in process, which is
        # the load-bearing column on the window behind this one.
        line("Source address", row["address"] or
             "— (written by this server, not received over the network)")

        if diff is not None:
            changes, dropped = diff
            section("What the correction changed")
            for field, old, new in changes:
                line(field.replace("_", " ").title(),
                     '"%s"   ->   "%s"' % (old, new))
            if dropped:
                tk.Label(body, text="%d further field(s) changed and did not "
                                    "fit the entry." % dropped, bg=BG,
                         fg=FAINT, font=font("micro"),
                         wraplength=560, justify="left").pack(anchor="w",
                                                              pady=(2, 0))
        else:
            section("Detail")
            tk.Label(body, text=row["detail"] or "—", bg=BG, fg=TEXT,
                     font=font("code"), wraplength=560,
                     justify="left").pack(anchor="w")

        if row["client_id"]:
            section("Shipped by")
            line("Installation", row["client_id"])
            if client:
                line("Hostname", client["hostname"])
                line("Windows Account", client["os_user"])
            else:
                tk.Label(body, text="That installation is no longer in the "
                                    "Client registry - it was reset or "
                                    "removed after this entry was written.",
                         bg=BG, fg=FAINT, font=font("micro"),
                         wraplength=560, justify="left").pack(anchor="w")

        ui_kit.fit(dlg, 620)

    def _open_log_detail(event):
        item = tree.identify_row(event.y)
        if item in row_ids:
            show_log_detail(row_ids[item])

    tree.bind("<Double-1>", _open_log_detail)

    def _current_filter():
        """(since, until, comp) for whatever the filter fields hold now, or
        None where a typed date does not parse - the same check load_rows
        makes, so Export and Clear cannot act on a filter the window itself
        would have refused to apply."""
        since, until = _date(from_e), _date(to_e)
        if since is None or until is None:
            return None
        return since, until, ("" if comp_v.get() == "All" else comp_v.get())

    def do_export():
        import tkinter.messagebox as mb
        import tkinter.filedialog as fd
        parsed = _current_filter()
        if parsed is None:
            mb.showerror("Export System Log",
                         "A date must be written YYYY-MM-DD.", parent=top)
            return
        since, until, comp = parsed
        rows = S._log_rows(component=comp, since=since, until=until)
        if not rows:
            mb.showinfo("Export System Log", "Nothing matches this filter.",
                        parent=top)
            return
        default_name = ("SystemLog_" +
                        datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx")
        save_path = fd.asksaveasfilename(
            parent=top, title="Save System Log export",
            defaultextension=".xlsx", initialfile=default_name,
            filetypes=[("Excel workbook", "*.xlsx")])
        if not save_path:
            return
        try:
            n = S._export_log_xlsx(save_path, rows, cols,
                                 [headers[c] for c in cols])
        except Exception as ex:
            mb.showerror("Export System Log", "✗  Export failed: %s" % ex,
                         parent=top)
            return
        S._log_event("log.exported",
                   "%d row(s), %s to %s%s"
                   % (n, since or "the start", until or "now",
                      " · " + comp if comp else ""),
                   actor="Admin (Server GUI)")
        mb.showinfo("Export System Log",
                    "✓  %d row(s) exported to:\n%s" % (n, save_path),
                    parent=top)

    def do_clear():
        import tkinter.messagebox as mb
        parsed = _current_filter()
        if parsed is None:
            mb.showerror("Clear System Log",
                         "A date must be written YYYY-MM-DD.", parent=top)
            return
        since, until, comp = parsed
        n = len(S._log_rows(component=comp, since=since, until=until,
                          limit=S.LOG_MAX_ROWS))
        if not n:
            mb.showinfo("Clear System Log", "Nothing matches this filter.",
                        parent=top)
            return
        scope = ("every row" if not (comp or since or until) else
                 "the %d row(s) this filter matches" % n)

        dlg = tk.Toplevel(top)
        dlg.title("Clear System Log")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(top)

        # Packed before the form and from the bottom, for the reason every
        # other dialog here packs its buttons first.
        dfoot = tk.Frame(dlg, bg=BG)
        dfoot.pack(side="bottom", fill="x")

        hdr = tk.Frame(dlg, bg=DANGER_BG, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🗑  Clear System Log", bg=DANGER_BG, fg="white",
                 font=font("title")).pack(side="left", padx=14,
                                                     pady=12)

        frm = tk.Frame(dlg, bg=CARD, padx=20, pady=14)
        frm.pack(fill="x", padx=18, pady=14)
        tk.Label(frm, text=("⚠  This will permanently delete %s (%d in "
                            "total) - what this window's filter is showing, "
                            "not the whole log." % (scope, n)),
                 bg=CARD, fg=WARNING, font=font("body"), wraplength=380,
                 justify="left").pack(anchor="w", pady=(0, 10))

        def do_confirm():
            # The System Log is a pane with no entry to put a door on, so
            # Clear asks the door itself (096), Send Command's shape.
            if not server_gui._admin_again(dlg, "Clear System Log"):
                return
            if not mb.askyesno("Confirm Clear",
                               "Delete %s permanently?\nThis cannot be undone."
                               % scope, icon="warning", parent=dlg):
                return
            deleted = S._log_clear(component=comp, since=since, until=until)
            # The only evidence the clear happened, so it is written
            # unconditionally, and after the delete so it lands as the first
            # row of the log that follows it rather than one it deletes.
            S._log_event("log.cleared",
                       "%d row(s) removed%s"
                       % (deleted, " · " + comp if comp else ""),
                       actor="Admin (Server GUI)", level="warn")
            dlg.destroy()
            load_rows()
            mb.showinfo("Clear System Log", "✓  %d row(s) removed." % deleted,
                        parent=top)

        tk.Button(dfoot, text="🗑  Clear", bg=DANGER_BG, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=do_confirm,
                  activebackground=DANGER_HOT).pack(fill="x", padx=18,
                                                    pady=(4, 12))
        ui_kit.fit(dlg, 420)

    # Three controls where there were four: Close went with the Toplevel, the
    # bar swapping what is on the stage being what closes a pane. The pills
    # are drawn against CARD now rather than BG, the surface they actually
    # sit on - a pill takes the colour it is given and a BG one on a CARD
    # pane is the mismatch 085 had to correct after the fact.
    btnf = tk.Frame(foot, bg=CARD)
    btnf.pack(fill="x", pady=(0, 4))
    lbox, _lrow = ui_kit.row_of(
        btnf,
        [("↻  Apply / Refresh", "↻", (CARD, CARD2, LINE, SUBTEXT), load_rows),
         ("⬇  Export", "⬇", (CARD, CARD2, LINE, SUBTEXT), do_export),
         ("🗑  Clear…", "🗑", (CARD, DANGER_BG, DANGER_HOT, "white"), do_clear)],
        kind="footer")
    lbox.pack(fill="x")

    # `show_section` asks for this each time System is put on the stage, the
    # same forwarding `section_pane` does for the Assets list: a log read at
    # build time would be the answer from whenever the console started, and
    # this table gains a row every time anything in this product happens.
    pane._ui_reload = load_rows
    return pane
