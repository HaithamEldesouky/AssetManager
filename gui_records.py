"""Manage Records - every Transaction, newest first.

Lifted out of server_gui.py by #235 (060). The Transactions section's pane
(#263/088), with the two helpers only it reads - which System Log entries are
about one Transaction, and which client answered it.

The seam back to ``server_gui.py`` - ``S`` read at call time, the
palette seeded by ``_bind_palette`` - is described once, in that module's own
docstring, under "The nine window modules".
"""

import re
from datetime import datetime

import ui_kit
from ui_kit import font

import server_gui
from server_gui import _CONSOLE_UNLOCKED, _console_unlock


def _decided(row, word):
    """`Confirmed (auto)`: the state, and `(auto)` when the answer was
    auto-approved. `origin` is NULL on a row decided before 106."""
    o = row["origin"]
    return "%s (%s)" % (word, o) if o in ("auto",) else word


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


def _transaction_log_rows(tid):
    """The System Log entries about one Transaction, in order.

    /confirm and /reject write the id into `detail` as "#<id>" rather than
    into a column of their own (there is no `transaction_id` on `system_log`),
    so this matches on the event's "transaction." prefix plus that token,
    bounded by a non-digit - or the ends of the string - on both sides, so
    "#4" never matches "#42". The same shape is written by .created,
    .confirmed, .rejected, .cancelled and .modified. .deleted does not write
    it - its ids are a plain comma-separated list, with no "#" - but a
    deleted Transaction has no row left for a caller of this function to have
    been opened from; .auto_accepted names a count rather than any one id and
    is correctly never found this way either.
    """
    from server_gui import S

    conn = S.get_db()
    rows = conn.execute(
        "SELECT * FROM system_log WHERE event LIKE 'transaction.%' "
        "AND detail LIKE ? ORDER BY id",
        ("%#" + str(tid) + "%",)
    ).fetchall()
    conn.close()
    token = re.compile(r"(?<!\d)#%d(?!\d)" % tid)
    return [r for r in rows if token.search(r["detail"] or "")]


def _transaction_client(log_rows):
    """Hostname and Windows account of whichever client confirmed/rejected it.

    Only a *shipped* System Log entry carries a client_id: POST /confirm and
    POST /reject are unauthenticated and write no column of their own for it
    (ADR-0002), while a Notifier's own `log_event("transaction.confirmed", ...)`
    is shipped through POST /clients/log, which does carry one. So this reads
    the client_id off the most recent matching entry that has one and joins
    `clients` on it for the machine's name - the address shown beside it is
    the one that entry itself recorded, not `clients.address`, which is that
    installation's *last* check-in and may have moved on since. None where no
    matching entry ever carried a client_id, which is the ordinary case for a
    server still running clients too old to ship their own log.
    """
    from server_gui import S

    for r in reversed(log_rows):
        if r["event"] in ("transaction.confirmed", "transaction.rejected") \
                and r["client_id"]:
            conn = S.get_db()
            c = conn.execute(
                "SELECT hostname, os_user FROM clients WHERE client_id=?",
                (r["client_id"],)).fetchone()
            conn.close()
            return {"hostname": (c["hostname"] if c else "") or "",
                    "os_user":  (c["os_user"] if c else "") or "",
                    "address":  r["address"] or ""}
    return None


def manage_records(parent):
    """The history table - every Transaction, newest first.

    **The Transactions section's pane** (#263/088), not a window, and the
    last of the four #252 carved out. Like Asset Proposals and the System Log
    the section it sits on keeps rows of its own - Add Transaction and Import
    Transaction Archive - and this is the list under them, named in `LISTED`
    beside the build loop.

    **The door does not move.** A table that can delete every record in the
    database is not one to show first and ask about afterwards, so the pane
    is built with the console but the table is packed only once
    `_console_unlock` has answered; until then the pane is a single row
    naming it, which is what the section entry was. The flag is scoped to the
    process (ADR-0015), so an Admin who unlocked the console through any other
    door finds the table already there and one who has not is asked once, by
    the same name, and not again.

    `select_id` went with the call shape (A11). A feed row on Overview used to
    open this window on its record; it now puts Transactions on the stage and
    asks `_select_transaction`, hung on the pane, for that row - which asks
    at the door first, so the feed is not a way round it. An id that is no
    longer here still leaves the table open with nothing selected.

    What went with the Toplevel: `raise_open`/`single`, a pane built once
    being single by construction - the feed row and the section are one
    Manage Transaction History because there is one (#191); Escape, the
    geometry, the title, `transient`, and the 14px inset `section_pane`
    already gives. What stays: newest-first, and the four dialogs one level
    inside - Delete Records, Modify Transaction, and Cancel against a Pending
    and a Confirmed row - each still a Toplevel and each still wanting a row
    selected before it opens.
    """
    from server_gui import S

    # tkinter as tk, because there is no module-level one: server.py must stay
    # importable headless. This lost it when it was lifted out of run_gui,
    # where the name came from that scope, and every click on this button
    # has raised NameError since.
    import tkinter as tk
    import tkinter.messagebox as mb
    from tkinter import ttk

    pane = tk.Frame(parent, bg=CARD)
    # Every dialog this pane opens is still a Toplevel and still wants a
    # window to sit over - `wm transient` and a messagebox's `-parent` both
    # take one, and a Frame is not.
    top = pane.winfo_toplevel()
    # The table and everything that acts on it, packed only behind the door.
    body = tk.Frame(pane, bg=CARD)

    # Packed before the table and from the bottom, so the controls are the
    # first children served rather than the last: pack gives a shortfall to
    # whatever went in last, and on a pane served whatever the console has
    # that would be the row holding Delete.
    foot = tk.Frame(body, bg=CARD)
    foot.pack(side="bottom", fill="x")

    tk.Label(body, text="🗂  Manage Transaction History  —  tick rows, then "
                        "Modify or Cancel one, or Delete",
             bg=CARD, fg=TEXT, font=font("heading")).pack(anchor="w",
                                                          pady=(0, 6))

    cols = ("id", "asset_number", "serial_number", "type", "member", "direction", "status", "date")
    headers = {c: c.replace("_", " ").title() for c in cols}
    # `tree headings` rather than `headings`, because the box lives in the
    # tree column: see _paint_boxes below for why it is not a ninth data one.
    # `height=8` rather than the window's 15: the pane is served whatever
    # the console has and the table takes the remainder through
    # `expand=True`, so this is only what it asks for - 087's reason.
    tree = ttk.Treeview(body, columns=cols, show="tree headings",
                        selectmode="extended", height=8)
    widths = {"id": 45, "asset_number": 95, "serial_number": 95, "type": 80,
              "member": 130, "direction": 75, "status": 120, "date": 120}
    sort_state = {"col": None, "rev": False}
    def _sort(col):
        rev = (not sort_state["rev"]) if sort_state["col"] == col else False
        sort_state["col"], sort_state["rev"] = col, rev
        def key(v):
            if col == "id":
                try: return (0, int(v))
                except Exception: return (1, str(v).lower())
            if col == "date":
                try: return (0, datetime.strptime(v, "%d/%m/%Y %H:%M"))
                except Exception: return (1, str(v))
            return (0, str(v).lower())
        items = sorted(((tree.set(k, col), k) for k in tree.get_children("")),
                       key=lambda t: key(t[0]), reverse=rev)
        for pos, (_, k) in enumerate(items):
            tree.move(k, "", pos)
        for c in cols:
            arrow = ("  ▲" if not rev else "  ▼") if c == col else ""
            tree.heading(c, text=headers[c] + arrow)
    for c in cols:
        tree.heading(c, text=headers[c], command=lambda c=c: _sort(c))
        tree.column(c, width=widths[c], anchor="w")

    _BOX, _TICKED = "☐", "☑"

    def _paint_boxes(_evt=None):
        """Draw every row's box from the selection, and the header's from all.

        The box is a **display of** the selection rather than a second one:
        this window has always multi-selected with ctrl-click, which is
        invisible to anybody who has not been told, and Delete asks for the
        admin password and an archive over whatever is selected. So what the
        box buys is that the selection is legible before that prompt rather
        than after it - which it can only be if the two cannot disagree, and
        they cannot if there is one of them and this redraws it.

        Bound to <<TreeviewSelect>>, so a ctrl-click, a Select All and a click
        on a box itself all end here. Setting an item's text changes no
        selection, so this does not re-enter.
        """
        rows = tree.get_children("")
        sel = set(tree.selection())
        for item in rows:
            want = _TICKED if item in sel else _BOX
            if tree.item(item, "text") != want:
                tree.item(item, text=want)
        tree.heading("#0", text=(_TICKED if rows and len(sel) == len(rows)
                                 else _BOX))

    def _toggle_row(event):
        """A click on the box toggles that row and leaves the rest alone.

        Only in the tree column - anywhere else is an ordinary click and keeps
        the selection behaviour this window already had, ctrl-click included.
        `break` because the default binding would otherwise replace the whole
        selection with the row that was clicked, which is the opposite of what
        ticking a second box means.
        """
        if tree.identify_region(event.x, event.y) != "tree":
            return None
        item = tree.identify_row(event.y)
        if not item:
            return None
        if item in tree.selection():
            tree.selection_remove(item)
        else:
            tree.selection_add(item)
        return "break"

    tree.heading("#0", text=_BOX, command=lambda: select_all())
    tree.column("#0", width=34, minwidth=34, stretch=False, anchor="center")
    tree.bind("<Button-1>", _toggle_row)
    tree.bind("<<TreeviewSelect>>", _paint_boxes)
    tree.pack(fill="both", expand=True, pady=4)

    def load_rows():
        tree.delete(*tree.get_children())
        conn = S.get_db()
        rows = conn.execute("SELECT * FROM transactions ORDER BY id DESC").fetchall()
        conn.close()
        for r in rows:
            status = ("Cancelled" if r["cancelled"] else
                      _decided(r, "Confirmed") if r["confirmed"] else
                      _decided(r, "Rejected") if r["rejected"] else "Pending")
            ds = r["timestamp"]
            try: ds = datetime.fromisoformat(ds).strftime("%d/%m/%Y %H:%M")
            except Exception: pass
            tree.insert("", "end", text=_BOX,
                        values=(r["id"], r["asset_number"], r["serial_number"],
                                r["asset_type"], r["team_member"],
                                r["direction"], status, ds))
        _paint_boxes()
    load_rows()

    def _select_transaction(target_id):
        """Tick and scroll to one row, for the feed click that asked for it.

        The feed's way in (A11), hung on the pane for `run_gui` to call once
        it has put Transactions on the stage. It asks at the door first: a
        feed row is a second route to this table and is not a route round
        `_console_unlock`. Refused, the section is on the stage with the
        table still behind its row, and nothing is selected.

        After the reload `show_section` makes rather than inside `load_rows`:
        this is the click that asked for one row and not every later repaint,
        and a selection re-applied on each refresh would fight whatever the
        admin has since ticked. `selection_set` is what paints the box,
        `<<TreeviewSelect>>` being where _paint_boxes hangs, so the row is
        ticked by the same path a ctrl-click ticks it and Delete cannot be
        holding something else.

        A row that is no longer here - deleted between the feed's paint and
        the click on it - leaves the table with nothing selected rather than
        raising: the feed is a snapshot of a table that goes on moving, and an
        id that has stopped existing is an ordinary answer to that.
        """
        if not open_table():
            return
        tree.selection_set(())
        for _item in tree.get_children(""):
            if str(tree.set(_item, "id")) == str(target_id):
                tree.selection_set(_item)
                tree.focus(_item)
                tree.see(_item)
                break

    def select_all():
        """Every box, or none of them - the header box is this same control.

        It flips rather than only selecting, because the header carries a box
        now and a box that cannot be unticked is not one. The footer button
        keeps its own label: what it does to an already-full selection is
        clear the way clicking a ticked box is.
        """
        rows = tree.get_children("")
        if rows and len(tree.selection()) == len(rows):
            tree.selection_remove(*rows)
        else:
            tree.selection_set(rows)

    def cancel_selected():
        """Cancel the selected Transaction - retract a mis-scan, keeping the row.

        One row at a time, not a multi-select like Delete: only the newest
        Transaction for an asset can be cancelled, so a bulk cancel would refuse
        most of what it was handed and there would be no useful way to say which.

        It asks for the reason always, because a retraction with no reason is
        indistinguishable from a mistake, and never for a password: this pane
        is behind the console door, so every cancel from here reaches
        `_cancel_transaction` as `authorised_as="Admin (Server GUI)"` - the
        admin path, a Confirmed Transaction included (096).
        """
        sel = tree.selection()
        if len(sel) != 1:
            mb.showinfo("Cancel Transaction",
                        "Select exactly one row to cancel.\n\n"
                        "Only the newest transaction for an asset can be "
                        "cancelled, so cancelling is one at a time.",
                        parent=top)
            return
        vals = tree.item(sel[0])["values"]
        tid  = int(vals[0])

        dlg = tk.Toplevel(top)
        dlg.title("Cancel Transaction")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(top)

        hdr = tk.Frame(dlg, bg=CARD2, height=44)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="⦸  Cancel Transaction", bg=CARD2, fg=TEXT,
                 font=font("title")).pack(side="left", padx=14, pady=12)

        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")

        frm = tk.Frame(dlg, bg=CARD, padx=20, pady=14)
        frm.pack(fill="x", padx=18, pady=14)
        tk.Label(frm, text="#%d   %s   %s   %s" % (tid, vals[1] or vals[2],
                                                   vals[4], vals[5]),
                 bg=CARD, fg=MONO, font=font("code_lg")).pack(anchor="w")
        tk.Label(frm, text="Cancelling says the movement never happened. The "
                           "record is kept and marked, not deleted, and stops "
                           "counting towards Pending and Out Now.",
                 bg=CARD, fg=SUBTEXT, font=font("body"),
                 wraplength=360, justify="left").pack(anchor="w", pady=(8, 10))
        tk.Label(frm, text="Reason", bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(0, 2))
        rsn_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
        rsn_e.pack(fill="x", ipady=7)
        err_lbl = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=font("body"),
                           wraplength=400, justify="left")
        err_lbl.pack(pady=(2, 0))

        def do_cancel():
            payload, status = S._cancel_transaction(
                tid, rsn_e.get(), "Admin (Server GUI)",
                authorised_as="Admin (Server GUI)")
            if status != 200:
                err_lbl.config(text="✗  " + payload.get("error", "Refused."))
                return
            dlg.destroy()
            load_rows()
            mb.showinfo("Cancelled", "✓  Transaction #%d cancelled." % tid,
                        parent=top)

        tk.Button(foot, text="⦸  Cancel This Transaction", bg=CARD2, fg=TEXT,
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=do_cancel,
                  activebackground=LINE).pack(fill="x", padx=18, pady=(4, 12))
        ui_kit.fit(dlg, 440)
        rsn_e.focus_set()

    def _confirm_and_delete(ids, all_selected):
        """Password + optional archive, then delete the given ids. Used for any
        count — a subset or every row (Select All) — so the export option is
        always offered, replacing the old separate Clear-All dialog."""
        import tkinter.filedialog as fd
        dlg = tk.Toplevel(top)
        dlg.title("Delete Records")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(top)

        hdr = tk.Frame(dlg, bg=DANGER_BG, height=44)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        scope = "ALL records" if all_selected else f"{len(ids)} selected record(s)"
        tk.Label(hdr, text="🗑  Delete Records", bg=DANGER_BG, fg="white",
                 font=font("title")).pack(side="left", padx=14, pady=12)

        # Packed before the form and from the bottom, so the
        # button that does the deleting is the first child given
        # the space it asked for rather than the last.
        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")

        frm = tk.Frame(dlg, bg=CARD, padx=20, pady=14)
        frm.pack(fill="x", padx=18, pady=14)
        tk.Label(frm, text=f"⚠  This will permanently delete {scope}.",
                 bg=CARD, fg=WARNING, font=font("body"),
                 wraplength=340).pack(anchor="w", pady=(0, 10))
        archive_var = tk.IntVar(value=1)
        tk.Checkbutton(frm, text="Export these records to an archive file first",
                       variable=archive_var, bg=CARD, fg=TEXT,
                       selectcolor=INPUT_BG, activebackground=CARD,
                       activeforeground=TEXT, font=font("body")).pack(anchor="w", pady=(10, 0))
        err_lbl = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=font("body"))
        err_lbl.pack(pady=(2, 0))

        def do_delete():
            save_path = None
            if archive_var.get():
                default_name = "AssetManager_Archive_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"
                save_path = fd.asksaveasfilename(
                    parent=dlg, title="Save records archive",
                    defaultextension=".xlsx", initialfile=default_name,
                    filetypes=[("Excel archive", "*.xlsx")])
                if not save_path:
                    err_lbl.config(text="✗  Archive cancelled — nothing deleted."); return
                try:
                    S._export_records_xlsx(save_path, ids=ids)
                except Exception as ex:
                    err_lbl.config(text=f"✗  Archive failed: {ex}"); return
            if not mb.askyesno("Confirm Delete",
                               f"Delete {scope} permanently?\nThis cannot be undone.",
                               icon="warning", parent=dlg):
                return
            try:
                conn = S.get_db()
                qmarks = ",".join("?" * len(ids))
                cur = conn.execute(
                    f"DELETE FROM transactions WHERE id IN ({qmarks})", ids)
                deleted = cur.rowcount
                conn.commit(); conn.close()
                # The same entry POST /transactions/delete writes, because this
                # is the same act through the other door. Deleting is the one
                # thing here whose evidence cannot be reconstructed afterwards -
                # the rows are gone - so an unlogged deletion leaves nothing
                # saying it happened, who did it or how many went. Sharper still
                # because this window opens on a *capability* password
                # (ADR-0006): a delegate handed Manage / Delete Records could
                # destroy records and leave the System Log silent, while the
                # Admin doing it over the endpoint was recorded. The archive
                # checkbox is not a substitute - it is optional, and it writes
                # to a path the operator picks.
                S._log_event("transaction.deleted",
                           "%d record(s): %s"
                           % (deleted, ", ".join(str(i) for i in ids)),
                           actor="Admin (Server GUI)", level="warn")
                dlg.destroy()
                load_rows()
                msg = f"✓  Deleted {len(ids)} record(s)."
                if save_path:
                    msg += f"\n\nArchived to:\n{save_path}"
                mb.showinfo("Done", msg)
            except Exception as ex:
                err_lbl.config(text=f"✗  Error: {ex}")

        tk.Button(foot, text="🗑  Delete", bg=DANGER_BG, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2", pady=9,
                  command=do_delete,
                  activebackground=DANGER_HOT).pack(fill="x", padx=18,
                                                    pady=(4, 12))
        ui_kit.fit(dlg, 420)

    def modify_selected():
        """Correct one Pending Transaction.

        It lives here rather than on the main toolbar for the reason the
        Cancel button does: correcting a Transaction needs the table you pick
        it from. It is also where the remedy for a Confirmed one sits, one
        button away.

        One row at a time. Every field is a statement about one specific
        movement, so there is nothing a bulk edit could sensibly set.
        """
        sel = tree.selection()
        if len(sel) != 1:
            mb.showinfo("Modify Transaction",
                        "Select exactly one row to modify.\n\n"
                        "Every field describes one particular movement, so "
                        "modifying is one at a time.", parent=top)
            return
        vals = tree.item(sel[0])["values"]
        tid  = int(vals[0])
        if vals[6] != "Pending":
            # _modify_transaction refuses these as well, and it is the
            # enforcement point - but opening an edit form only to refuse the
            # save is worse than saying so now, and for a Confirmed row the
            # remedy is the button beside this one.
            mb.showerror("Modify Transaction", {
                "Confirmed": "#%d is already confirmed and cannot be edited. "
                             "The engineer's confirmation is the evidence, and "
                             "editing the record underneath it would destroy "
                             "it.\n\nCancel it and record the movement again "
                             "- that keeps both facts." % tid,
                "Rejected":  "#%d was rejected by the engineer. That answer is "
                             "the record and is not edited." % tid,
                "Cancelled": "#%d records a movement that never happened, so "
                             "there is nothing in it to correct. Record the "
                             "real movement instead." % tid,
            }[vals[6]], parent=top)
            return

        conn = S.get_db()
        row = conn.execute("SELECT * FROM transactions WHERE id=?",
                           (tid,)).fetchone()
        members = [r["name"] for r in conn.execute(
            "SELECT name FROM team_members ORDER BY name").fetchall()]
        conn.close()
        if row is None:
            mb.showerror("Modify Transaction",
                         "#%d is no longer there - refresh." % tid, parent=top)
            return

        dlg = tk.Toplevel(top)
        dlg.title("Modify Transaction")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(top)

        hdr = tk.Frame(dlg, bg=CARD2, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="✎  Modify Transaction  #%d" % tid, bg=CARD2,
                 fg=TEXT, font=font("title")).pack(side="left",
                                                              padx=14, pady=12)

        # Packed before the form and from the bottom, so the button that saves
        # the correction is the first child given the space it asked for rather
        # than the last. Same as Add Transaction, same reason.
        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")

        frm = tk.Frame(dlg, bg=CARD, padx=20, pady=12)
        frm.pack(fill="x", padx=18, pady=(12, 6))

        def field(label, initial, hint=""):
            tk.Label(frm, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 2))
            e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
            e.insert(0, initial or "")
            e.pack(fill="x", ipady=6)
            if hint:
                tk.Label(frm, text=hint, bg=CARD, fg=FAINT,
                         font=font("micro")).pack(anchor="w", pady=(2, 0))
            return e

        def picker(label, values, initial):
            tk.Label(frm, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 2))
            values = list(values)
            # An engineer since deleted, or a type the current sheet no longer
            # names, is still what this row says. Dropping it from the list
            # would silently reassign the Transaction on save.
            if initial and initial not in values:
                values.insert(0, initial)
            var = tk.StringVar(value=initial)
            ttk.Combobox(frm, textvariable=var, values=values,
                         state="readonly", style="S.TCombobox",
                         font=font("value")).pack(fill="x")
            return var

        asset_e  = field("Asset Number", row["asset_number"])
        serial_e = field("Serial Number", row["serial_number"],
                         "at least one of the two is required (rule 5)")
        types    = S._lookup_asset_types()
        type_v   = picker("Asset Type  (corrected from the lookup sheet)",
                          types, row["asset_type"])
        member_v = picker("Engineer", members, row["team_member"])
        dir_v    = picker("Direction", ("Out Store", "In Store"),
                          row["direction"])
        try:
            shown = datetime.fromisoformat(
                row["timestamp"]).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            shown = row["timestamp"]
        when_e  = field("When it happened", shown,
                        "YYYY-MM-DD HH:MM  ·  the future is refused")
        notes_e = field("Notes", row["notes"])

        tk.Label(dlg, text=("It stays Pending, and the engineer is asked about "
                            "the corrected version. Changing either identifier "
                            "is checked against the lookup sheet, exactly as "
                            "recording it would be."),
                 bg=BG, fg=SUBTEXT, font=font("micro"),
                 wraplength=520, justify="left").pack(padx=18, pady=(8, 2),
                                                      anchor="w")
        err_lbl = tk.Label(dlg, text="", bg=BG, fg=DANGER,
                           font=font("body"), wraplength=520,
                           justify="left")
        err_lbl.pack(padx=18, anchor="w")

        def do_modify():
            raw, stamp = when_e.get().strip(), None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                try:
                    stamp = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
            if stamp is None:
                err_lbl.config(text="✗  Use YYYY-MM-DD HH:MM, e.g. %s."
                                    % datetime.now().strftime("%Y-%m-%d %H:%M"))
                return
            payload, status = S._modify_transaction(tid, {
                "asset_number":  asset_e.get().strip(),
                "serial_number": serial_e.get().strip(),
                "asset_type":    type_v.get(),
                "team_member":   member_v.get(),
                "direction":     dir_v.get(),
                "notes":         notes_e.get().strip(),
                "timestamp":     stamp.isoformat(),
            })
            if status != 200:
                err_lbl.config(text="✗  " + payload.get("error", "Refused."))
                return
            dlg.destroy()
            load_rows()
            f = payload["fields"]
            mb.showinfo("Modified",
                        "✓  Transaction #%d corrected and still Pending.\n\n"
                        "%s  ·  %s  ·  %s  ·  %s"
                        % (tid, f["asset_number"] or f["serial_number"],
                           f["team_member"], f["direction"],
                           stamp.strftime("%Y-%m-%d %H:%M")), parent=top)

        tk.Button(foot, text="✎  Save Correction", bg=CARD2, fg=TEXT,
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=do_modify,
                  activebackground=LINE).pack(fill="x", padx=18, pady=(10, 12))

        ui_kit.fit(dlg, 580)
        asset_e.focus_set()

    def show_detail(tid):
        """Read-only: everything recorded about one Transaction.

        Bound to a double-click rather than a single one: a single click on
        the data area already selects the row the usual way (ctrl-click and
        shift-click included), which is what Delete acts on, and stealing
        that click here would take away the only way to multi-select without
        touching the box column.
        """
        conn = S.get_db()
        row = conn.execute("SELECT * FROM transactions WHERE id=?",
                           (tid,)).fetchone()
        conn.close()
        if row is None:
            mb.showerror("Transaction Detail",
                         "#%d is no longer there - refresh." % tid, parent=top)
            return

        log_rows = _transaction_log_rows(tid)
        client = _transaction_client(log_rows)

        if ui_kit.raise_open("transaction_detail:%d" % tid) is not None:
            return
        dlg = tk.Toplevel(top)
        ui_kit.single(dlg, "transaction_detail:%d" % tid)
        dlg.title("Transaction #%d" % tid)
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(top)

        hdr = tk.Frame(dlg, bg=CARD2, height=44)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="🔍  Transaction  #%d" % tid, bg=CARD2, fg=TEXT,
                 font=font("title")).pack(side="left", padx=14,
                                                     pady=12)

        # Packed first and from the bottom, the reason every other dialog
        # here does: the control that closes this one must not be what a
        # long System Log pushes off the bottom.
        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")
        tk.Button(foot, text="Close", bg=CARD2, fg=TEXT,
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=dlg.destroy,
                  activebackground=LINE).pack(fill="x", padx=18, pady=(4, 12))

        body = tk.Frame(dlg, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(12, 4))

        def section(title):
            tk.Label(body, text=title, bg=BG, fg=SUBTEXT,
                     font=font("strong")).pack(anchor="w",
                                                        pady=(10, 2))

        def line(label, value):
            tk.Label(body, text="%s:  %s" % (label, value or "—"), bg=BG,
                     fg=TEXT, font=font("code"), wraplength=560,
                     justify="left").pack(anchor="w")

        def fmt_ts(s):
            try: return datetime.fromisoformat(s).strftime("%d/%m/%Y %H:%M:%S")
            except Exception: return s

        status = ("Cancelled" if row["cancelled"] else
                  _decided(row, "Confirmed") if row["confirmed"] else
                  _decided(row, "Rejected") if row["rejected"] else "Pending")

        section("Record")
        line("Asset Number", row["asset_number"])
        line("Serial Number", row["serial_number"])
        line("Type", row["asset_type"])
        line("Model", row["asset_model"])
        line("Engineer", row["team_member"])
        line("Direction", row["direction"])
        line("Storekeeper", row["storekeeper"])
        line("Notes", row["notes"])
        line("Status", status)
        line("Recorded", fmt_ts(row["timestamp"]))
        line("Resolved", fmt_ts(row["confirmed_at"]))

        if row["rejected"]:
            section("Rejected")
            line("Reason", row["rejection_reason"])
            # The Engineer it was recorded against - the only person who can
            # reject a Transaction is the one it was queued to (ADR-0003).
            line("By", row["team_member"])
        if row["cancelled"]:
            section("Cancelled")
            line("Reason", row["cancel_reason"])
            line("By", row["cancelled_by"])
            line("At", fmt_ts(row["cancelled_at"]))

        if client:
            section("Confirmed / Rejected From")
            line("Hostname", client["hostname"])
            line("Windows Account", client["os_user"])
            line("Address", client["address"])

        section("System Log")
        if log_rows:
            cols = ("ts", "event", "actor", "address")
            lv = ttk.Treeview(body, columns=cols, show="headings",
                              selectmode="none",
                              height=min(6, len(log_rows)))
            widths = {"ts": 150, "event": 150, "actor": 140, "address": 110}
            for c in cols:
                lv.heading(c, text=c.replace("_", " ").title())
                lv.column(c, width=widths[c], anchor="w")
            for r in log_rows:
                lv.insert("", "end", values=(fmt_ts(r["ts"]), r["event"],
                                             r["actor"], r["address"]))
            lv.pack(fill="x", pady=(2, 4))
        else:
            tk.Label(body, text="Nothing in the System Log names this "
                                "transaction.", bg=BG, fg=FAINT,
                     font=font("body")).pack(anchor="w")

        ui_kit.fit(dlg, 560)

    def _open_detail(event):
        if tree.identify_region(event.x, event.y) == "tree":
            return  # the box column - a double-click there is two toggles
        item = tree.identify_row(event.y)
        if not item:
            return
        vals = tree.item(item)["values"]
        if vals:
            show_detail(int(vals[0]))

    tree.bind("<Double-1>", _open_detail)

    def delete_selected():
        sel = tree.selection()
        if not sel:
            mb.showinfo("Manage Transaction History",
                        "Tick one or more rows first (or use Select All).")
            return
        all_rows = tree.get_children()
        ids = [int(tree.item(s)["values"][0]) for s in sel]
        _confirm_and_delete(ids, all_selected=(len(sel) == len(all_rows) and len(all_rows) > 0))

    btnf = tk.Frame(foot, bg=CARD)
    btnf.pack(fill="x", pady=(4, 4))
    # Drawn against CARD rather than BG, the surface they sit on now - a
    # pill takes the colour it is given, and 085 had to correct a BG one on
    # a CARD pane after the fact.
    # Five buttons in equal columns, dropping to short labels before any of
    # them truncates. Delete is the one where a half-read label costs the most,
    # which is why the tier comes before the ellipsis rather than after it.
    fbox, _frow = ui_kit.row_of(
        btnf,
        [("🗑  Delete Selected", "🗑  Delete",
          (CARD, DANGER_BG, DANGER_HOT, "white"), delete_selected),
         ("⦸  Cancel Selected", "⦸  Cancel", (CARD, CARD2, LINE, "white"),
          cancel_selected),
         ("✎  Modify Selected", "✎  Modify", (CARD, CARD2, LINE, "white"),
          modify_selected),
         ("☑  Select All", "☑  All", (CARD, CARD2, LINE, "white"),
          select_all),
         ("↻  Refresh", "↻", (CARD, CARD2, LINE, "white"), load_rows)],
        kind="footer")
    fbox.pack(fill="x")

    # The switch lives here rather than on the main toolbar because it belongs
    # beside Cancel - it is the same subject, and what it changes is which
    # Cancels the network may make.
    sk_var = tk.IntVar(value=1 if S._storekeeper_can_cancel() else 0)

    def toggle_sk():
        """Flip the storekeeper's ability to cancel.

        Asks for no password: this pane is behind the console door, which
        has already taken the admin password (096).
        """
        wanted = bool(sk_var.get())
        S._save_server_cfg(storekeeper_can_cancel=wanted)
        mb.showinfo("Storekeeper Cancel",
                    "✓  The storekeeper %s cancel transactions.\n\n"
                    "Published on the heartbeat, so a client picks it up on its "
                    "next poll. The server enforces it either way."
                    % ("can now" if wanted else "can no longer"), parent=top)

    tk.Checkbutton(btnf, text="Storekeeper may cancel", variable=sk_var,
                   command=toggle_sk, bg=CARD, fg=SUBTEXT, selectcolor=INPUT_BG,
                   activebackground=CARD, activeforeground=TEXT,
                   font=font("body")).pack(side="right")

    # The row the table sits behind while the console is locked - the section
    # entry this was until 088, drawn the way `section_pane` draws one and
    # stamped as one, so the chip sweep in `tools/server_checks` knows it for
    # a row rather than a status chip.
    gate = tk.Frame(pane, bg=INPUT_BG)
    gate._ui_section_row = "Transactions"
    gpad = tk.Frame(gate, bg=INPUT_BG, padx=16, pady=11)
    gpad.pack(fill="x")
    tk.Label(gpad, text="Manage Transaction History", bg=INPUT_BG, fg=TEXT,
             font=font("label")).pack(side="left")
    tk.Label(gpad, text="Open", bg=INPUT_BG, fg=SUBTEXT,
             font=font("micro")).pack(side="right")
    tk.Label(gpad, text="sort, select, archive first, then delete - asks "
                        "for a password", bg=INPUT_BG, fg=SUBTEXT,
             font=font("micro")).pack(side="left", padx=(16, 0))

    def show_table():
        gate.pack_forget()
        if not body.winfo_manager():
            body.pack(fill="both", expand=True)

    def open_table(_e=None):
        """The door, then the table. Returns whether the table is open."""
        if not _console_unlock(top, "Manage Transaction History"):
            return False
        show_table()
        load_rows()
        return True

    def clickable(w):
        w.configure(cursor="hand2")
        w.bind("<Button-1>", open_table)
        for child in w.winfo_children():
            clickable(child)
    clickable(gate)

    def reload_():
        # Asked by `show_section` each time Transactions goes on the stage.
        # Reads the flag rather than asking the door: putting a section on
        # the stage is not a request to open what is gated on it.
        if _CONSOLE_UNLOCKED[0]:
            show_table()
            load_rows()
        else:
            body.pack_forget()
            gate.pack(fill="x")

    reload_()
    pane._ui_reload = reload_
    pane._select_transaction = _select_transaction
    return pane
