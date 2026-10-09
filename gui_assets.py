"""Manage Assets - the assets in the Lookup Sheet, added, corrected, removed.

Lifted out of server_gui.py by #235 (060). On its own rather than beside the
two proposal surfaces: this is the register's own editor, the one window here
that writes a row nobody proposed.

The seam back to ``server_gui.py`` - ``S`` read at call time, the
palette seeded by ``_bind_palette`` - is described once, in that module's own
docstring, under "The nine window modules".
"""

import os

import ui_kit
from ui_kit import font

import server_gui


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


def manage_assets(root):
    """The assets in the Lookup Sheet - add one, correct one, remove one.

    Reached from Database Location, which is where the Database chip already
    goes: the chip is what an Admin clicks when the question is what this
    server holds, and the Lookup Sheet is the half of that answer the database
    does not hold. The Transactions in assets.db are Manage Transaction
    History,
    and an asset the sheet does not know cannot be transacted at all (rule 6),
    so this is where that refusal is fixed.

    The admin password is asked at the door - the Lookup Sheet entry asks
    `_admin_again` on every open (096), Backup / Restore's shape - and not
    again here. The Lookup Sheet is the sole authority on which assets and
    which Asset Types exist, which is what makes it trusted (rule 2), so it is
    not one of the four delegable capabilities - and POST /lookup/upload, the
    other door to it, demands the admin password too.

    Every write goes through `_save_asset` and `_delete_asset`, so this console
    and that endpoint cannot disagree about what an asset is, and the list is
    read back off the table afterwards rather than patched in place. Since 024
    a write touches **one row**: correcting one asset used to rewrite the whole
    workbook, which is the shape of defect the import and the external sync
    behind it cannot be built on. Nothing needs invalidating for the rest of
    the server to see it - `_load_lookup_table` reads the table on every call
    and caches nothing - and reading it back is how this window shows the write
    really landed.
    """
    from server_gui import S

    import tkinter as tk
    import tkinter.messagebox as mb
    from tkinter import ttk

    if ui_kit.raise_open("manage_assets") is not None:
        return
    win = tk.Toplevel(root)
    ui_kit.single(win, "manage_assets")
    win.title("Lookup Sheet")
    win.configure(bg=BG)
    win.transient(root)
    win.grab_set()
    ui_kit.escape_closes(win)

    hdr = tk.Frame(win, bg=ACCENT, height=44)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="🧾  Lookup Sheet", bg=ACCENT, fg="white",
             font=font("title")).pack(side="left", padx=14, pady=12)

    # Packed before the body and from the bottom, so the buttons are the first
    # children served rather than the last: pack gives a shortfall to whatever
    # went in last, and that is how four dialogs here came to have no usable
    # button.
    foot = tk.Frame(win, bg=BG)
    foot.pack(side="bottom", fill="x")

    tk.Label(win, text="Every asset the department owns. An asset that is not "
                       "here cannot be transacted at all, and the Asset Types "
                       "listed here are the ones every client offers - so a "
                       "type mistyped here reaches the Storekeeper's dropdown "
                       "as a type of its own. Each change here saves one "
                       "row of it in the database; asset_lookup.xlsx is what "
                       "GET /lookup/file exports out of that and what an "
                       "upload replaces it from.",
             bg=BG, fg=FAINT, font=font("micro"), wraplength=660,
             justify="left").pack(anchor="w", padx=18, pady=(10, 6))

    # msg, not err: every button here reports through it and most of what it
    # says is a success - the same reason Manage Users names its one msg.
    msg = tk.Label(win, text="", bg=BG, fg=DANGER, font=font("body"),
                   wraplength=660, justify="left")
    msg.pack(anchor="w", padx=18, pady=(6, 0))

    # Asset Number and Serial Number first, as they are in every other table
    # and form here (rule 4).
    cols    = ("asset_number", "serial_number", "asset_type", "asset_model")
    headers = {"asset_number": "Asset Number", "serial_number": "Serial Number",
               "asset_type": "Asset Type", "asset_model": "Asset Model"}
    widths  = {"asset_number": 150, "serial_number": 175, "asset_type": 125,
               "asset_model": 195}
    body = tk.Frame(win, bg=BG)
    body.pack(fill="both", expand=True, padx=18, pady=(8, 0))
    tree = ttk.Treeview(body, columns=cols, show="headings",
                        selectmode="browse", height=12)
    for c in cols:
        tree.heading(c, text=headers[c])
        tree.column(c, width=widths[c], anchor="w")
    sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    count = tk.Label(win, text="", bg=BG, fg=SUBTEXT, font=font("body"))
    count.pack(anchor="w", padx=18, pady=(4, 0))

    def load_rows():
        """Read the sheet back off the table, never patch the list in place.

        The row's own id is the item id, so every button here names the row it
        was given rather than the position it sat at - a position is what
        another Admin's insert moves out from under this window.
        """
        tree.delete(*tree.get_children())
        for a in S._load_assets():
            tree.insert("", "end", iid=str(a["id"]),
                        values=(a["asset_number"], a["serial_number"],
                                a["asset_type"], a["asset_model"]))
        n = len(tree.get_children())
        types = {tree.set(k, "asset_type") for k in tree.get_children()}
        types.discard("")
        count.config(text="%d asset%s  ·  %d Asset Type%s"
                          % (n, "" if n == 1 else "s",
                             len(types), "" if len(types) == 1 else "s"))

    def rows_now():
        """The list as (id, asset_number, serial_number, type, model) strings.

        Read through `tree.set` rather than `item()["values"]`, which hands an
        all-digit value back as an int: an Asset Number like 0012 would read as
        12, and what this feeds - the Asset Type list the form offers, and the
        count under the table - is built by comparing these as strings.
        """
        return [(k,) + tuple(tree.set(k, c) for c in cols)
                for k in tree.get_children()]

    def known_types():
        return sorted({r[3] for r in rows_now() if r[3]})

    def known_models(for_type=""):
        """The Asset Models already in the Lookup Sheet, for one type or all.

        `_asset_models` is the whole of it since G2 put the same answer on the
        wire as `GET /asset_models`: this window offering one list and a client
        another would be two spellings of one query, which is what rule 10
        exists to prevent. It reads the table rather than the rows this tree is
        showing, which is the same set - every write here repaints from the
        table, there being no edit buffer - and is current the moment a row
        lands whoever wrote it.
        """
        return S._asset_models(for_type)

    def write(do, said, err=None):
        """The one write, then read the Lookup Sheet back.

        `err` is where a refusal goes while a modal dialog is over this window,
        since a message painted behind one is a message nobody can read. The
        success line stays on this window, which is what is left showing.

        A `ValueError` from `_save_asset` is shown **as it is**: it is the one
        writer saying what is wrong with the asset - no identifier, no type, an
        identifier another asset already has - and it already names it. Dressing
        it as "the Lookup Sheet was not written" would put the failure in front
        of the reason. Anything else is a failure of the write itself - a locked
        database, a disk - where that sentence is the accurate one.
        """
        say = err if err is not None else msg
        # fg with every message: msg is green while it holds the last success,
        # and a refusal painted into it would be a red sentence in green.
        try:
            do()
        except ValueError as ex:
            say.config(text="✗  %s" % ex, fg=DANGER)
            return False
        except Exception as ex:
            say.config(text="✗  The Lookup Sheet was not written: %s" % ex,
                       fg=DANGER)
            return False
        load_rows()
        msg.config(text="✓  " + said, fg=SUCCESS)
        return True

    def form(iid=None):
        """Add one asset, or correct the selected one."""
        current = ([tree.set(iid, c) for c in cols] if iid is not None
                   else ["", "", "", ""])
        dlg = tk.Toplevel(win)
        dlg.title("Edit Asset" if iid is not None else "Add Asset")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(win)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)

        dhdr = tk.Frame(dlg, bg=CARD2, height=44)
        dhdr.pack(fill="x")
        dhdr.pack_propagate(False)
        tk.Label(dhdr, text=("✎  Edit Asset" if iid is not None
                             else "＋  Add Asset"),
                 bg=CARD2, fg=TEXT,
                 font=font("title")).pack(side="left", padx=14,
                                                     pady=12)

        # Packed before the form and from the bottom, for the reason the window
        # behind it packs its buttons first.
        dfoot = tk.Frame(dlg, bg=BG)
        dfoot.pack(side="bottom", fill="x")

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
                         font=font("micro"), wraplength=380,
                         justify="left").pack(anchor="w", pady=(2, 0))
            return e

        an_e = field("Asset Number", current[0])
        sn_e = field("Serial Number", current[1],
                     "at least one of the two is required - the same shape a "
                     "Transaction is held to (rule 5)")
        tk.Label(frm, text="Asset Type", bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(6, 2))
        known  = known_types()
        type_v = tk.StringVar(value=current[2])
        # Editable rather than readonly, unlike the pickers in Modify
        # Transaction: a type the sheet does not have yet has to be typeable
        # somewhere, and this window is now the second place the sheet grows
        # one. What guards it is the question below, not the widget.
        ttk.Combobox(frm, textvariable=type_v, values=known,
                     style="S.TCombobox", font=font("value")).pack(fill="x")
        tk.Label(frm, text="one of the %d type%s already in the sheet, or a "
                           "new one - a new type appears in every client's "
                           "dropdown" % (len(known),
                                         "" if len(known) == 1 else "s"),
                 bg=CARD, fg=FAINT, font=font("micro"),
                 wraplength=380, justify="left").pack(anchor="w", pady=(2, 0))
        tk.Label(frm, text="Asset Model", bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(6, 2))
        am_v  = tk.StringVar(value=current[3])
        # The same widget as the Asset Type above, and editable for the same
        # reason - a model nobody has bought before has to be typeable
        # somewhere. Unlike a type it is **not** confirmed with a question: a
        # type reaches every client's dropdown and changes what rule 2 serves,
        # a model is filled into a Transaction that sent none and reaches
        # nothing else, so asking would be ceremony. What it is here for is
        # that the same machine was typed in freehand every time and the sheet
        # ended up holding `ThinkPad T14`, `Thinkpad T14` and `T14`.
        am_cb = ttk.Combobox(frm, textvariable=am_v,
                             values=known_models(current[2]),
                             style="S.TCombobox", font=font("value"))
        am_cb.pack(fill="x")
        am_hint = tk.Label(frm, text="", bg=CARD, fg=FAINT,
                           font=font("micro"), wraplength=380,
                           justify="left")
        am_hint.pack(anchor="w", pady=(2, 0))

        def models_for_type(*_):
            """Re-read the list whenever the Asset Type above changes.

            Traced on the variable rather than bound to <<ComboboxSelected>>,
            because that type field is editable: a type typed in reaches this
            the same way a type picked from the list does.
            """
            at_now = type_v.get().strip()
            vals   = known_models(at_now)
            am_cb["values"] = vals
            if not at_now:
                am_hint.config(text="optional - filled into a Transaction that "
                                    "sends none. Pick an Asset Type above to "
                                    "narrow this to that type's models.")
            elif vals:
                am_hint.config(text="optional - one of the %d model%s this "
                                    "sheet already has for %s, or a new one"
                                    % (len(vals), "" if len(vals) == 1 else "s",
                                       at_now))
            else:
                am_hint.config(text="optional - this sheet has no model for %s "
                                    "yet, so type one" % at_now)

        type_v.trace_add("write", models_for_type)
        models_for_type()

        err = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=font("body"),
                       wraplength=400, justify="left")
        err.pack(padx=18, anchor="w")

        def do_save():
            an = an_e.get().strip()
            sn = sn_e.get().strip()
            at = type_v.get().strip()
            am = am_v.get().strip()
            if not an and not sn:
                err.config(text="✗  An asset needs an Asset Number or a Serial "
                                "Number - at least one of the two.")
                return
            if not at:
                err.config(text="✗  An Asset Type is required. It is what "
                                "GET /asset_types serves to every client, and "
                                "a row without one is dropped from the sheet.")
                return
            # A duplicate identifier is refused by `_save_asset` and named
            # by it, and `write` puts that sentence on this form. It was
            # computed here, over the rows this window happened to be
            # showing, until 025 - which is why the upload endpoint walked
            # straight past a rule the Admin at this console could not.
            # The same fold the importer beside this button does, and for
            # the same reason: a type matching one in the sheet apart from
            # case is that type, so it is saved as that rather than added
            # beside it. What is left to ask about is a type the sheet really
            # does not have.
            at = {t.lower(): t for t in known}.get(at.lower(), at)
            if at not in known:
                if not mb.askyesno(
                        "New Asset Type",
                        "\"%s\" is not an Asset Type this sheet has yet.\n\n"
                        "Saving adds it to the list every client offers, "
                        "beside %s.\n\nIs that what you meant?"
                        % (at, ", ".join(known) if known else "nothing else"),
                        icon="warning", parent=dlg):
                    return
            said = ("%s saved." % (an or sn) if iid is not None
                    else "%s added to the Lookup Sheet." % (an or sn))
            if write(lambda: S._save_asset(an, sn, at, am,
                                         asset_id=(int(iid) if iid is not None
                                                   else None)),
                     said, err):
                dlg.destroy()

        tk.Button(dfoot, text="Save to the Lookup Sheet", bg=ACCENT,
                  fg="white", font=font("heading"), relief="flat",
                  cursor="hand2", pady=9, command=do_save,
                  activebackground=ACCENT2).pack(fill="x", padx=18,
                                                 pady=(10, 12))
        ui_kit.fit(dlg, 440)
        an_e.focus_set()

    def selected():
        sel = tree.selection()
        if len(sel) == 1:
            return sel[0]
        mb.showinfo("Lookup Sheet",
                    "Select exactly one asset first.\n\nEvery field describes "
                    "one particular asset, so this is one at a time.",
                    parent=win)
        return None

    def add_asset():
        form(None)

    def edit_asset(_e=None):
        iid = selected()
        if iid is not None:
            form(iid)

    def remove_asset():
        iid = selected()
        if iid is None:
            return
        an = tree.set(iid, "asset_number")
        sn = tree.set(iid, "serial_number")
        if not mb.askyesno("Remove Asset",
                           "Remove %s from the Lookup Sheet?\n\nIt can no "
                           "longer be transacted - a Transaction for an asset "
                           "the Lookup Sheet does not hold is refused. "
                           "Transactions already recorded against it are "
                           "untouched." % (an or sn),
                           icon="warning", parent=win):
            return
        write(lambda: S._delete_asset(int(iid)),
              "%s removed from the Lookup Sheet." % (an or sn))

    def import_assets():
        """Add the assets an .xlsx or a .csv holds - map, validate, commit.

        The other two doors to this sheet take a file in **this application's**
        shape: `POST /lookup/upload` replaces the whole sheet from the workbook
        `GET /lookup/file` exports, and the form beside this button takes one
        asset. A delivery note from a vendor is neither - its columns are called
        whatever that vendor calls them, and what it means is "these assets
        exist as well" rather than "this is the Lookup Sheet now". So this adds
        rather than replaces, and it asks what the columns are rather than
        assuming.

        Three stages, and **nothing is written until all three have passed**:

        1. **Map.** Every guess is shown for confirmation rather than applied,
           because a wrong one applied silently writes the serial numbers into
           the Asset Number column of three hundred assets and the first anybody
           hears of it is a scan that finds nothing. A column the guess could
           not place is left unfilled rather than pointed at the nearest header.
        2. **Validate.** Every row is answered at once - what it would become,
           and the refusal where there is one - so the operator fixes the
           spreadsheet against the whole list rather than one refusal per run.
        3. **Commit.** The good rows go through `_save_asset` in one
           transaction. The refused rows are not written and were not hidden.

        A new Asset Type is confirmed once for the whole file, not once per row:
        a type reaches every client's dropdown (rule 2), which is the same
        question the asset form asks, asked about a file instead of a row.
        """
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=win, title="Import Assets",
            filetypes=[("Excel workbook or CSV", "*.xlsx *.csv"),
                       ("Excel workbook", "*.xlsx"),
                       ("CSV file", "*.csv")])
        if not path:
            return
        name = os.path.basename(path)
        try:
            headers, rows = S._import_file_rows(path)
        except Exception as ex:
            msg.config(text="✗  %s could not be read: %s" % (name, ex),
                       fg=DANGER)
            return
        if not rows:
            msg.config(text="✗  %s has no rows under its header row." % name,
                       fg=DANGER)
            return

        NOT_HERE = "—  not in this file  —"
        choices  = [NOT_HERE] + ["%d · %s" % (i + 1, h or "(unnamed column)")
                                 for i, h in enumerate(headers)]
        guess    = S._map_import_columns(headers)

        dlg = tk.Toplevel(win)
        dlg.title("Import Assets")
        dlg.configure(bg=BG)
        dlg.transient(win)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)

        dhdr = tk.Frame(dlg, bg=CARD2, height=44)
        dhdr.pack(fill="x")
        dhdr.pack_propagate(False)
        tk.Label(dhdr, text="📥  Import Assets  ·  %s" % name, bg=CARD2,
                 fg=TEXT, font=font("title")).pack(side="left",
                                                              padx=14, pady=12)
        dfoot = tk.Frame(dlg, bg=BG)
        dfoot.pack(side="bottom", fill="x")
        derr = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=font("body"),
                        wraplength=620, justify="left")
        derr.pack(side="bottom", anchor="w", padx=18, pady=(0, 6))
        stage = tk.Frame(dlg, bg=BG)
        stage.pack(fill="both", expand=True)

        def clear():
            for w in list(stage.winfo_children()) + list(
                    dfoot.winfo_children()):
                w.destroy()
            derr.config(text="")

        def map_stage():
            """What each column is, with every guess shown rather than used."""
            clear()
            tk.Label(stage, text="%d row%s under %d column%s. Say which column "
                                 "is which - a guess is shown where one could "
                                 "be made, and a field this file does not carry "
                                 "is left as it is. An Asset Type and at least "
                                 "one identifier are what an asset needs "
                                 "(rule 5), so those cannot be left unmapped."
                                 % (len(rows), "" if len(rows) == 1 else "s",
                                    len(headers),
                                    "" if len(headers) == 1 else "s"),
                     bg=BG, fg=FAINT, font=font("micro"), wraplength=620,
                     justify="left").pack(anchor="w", padx=18, pady=(10, 8))
            card = tk.Frame(stage, bg=CARD, padx=16, pady=12)
            card.pack(fill="x", padx=18)
            pick = {}
            for f in S._IMPORT_FIELDS:
                i = guess.get(f)
                tk.Label(card, text=S._IMPORT_LABELS[f]
                                    + ("" if i is None else "   · guessed"),
                         bg=CARD, fg=SUBTEXT,
                         font=font("body")).pack(anchor="w", pady=(6, 2))
                v  = tk.StringVar(value=NOT_HERE if i is None
                                  else choices[i + 1])
                cb = ttk.Combobox(card, textvariable=v, values=choices,
                                  state="readonly", style="S.TCombobox",
                                  font=font("value"))
                cb.pack(fill="x")
                pick[f] = v

            def go():
                mapping = {}
                for f in S._IMPORT_FIELDS:
                    chosen = pick[f].get()
                    mapping[f] = (None if chosen == NOT_HERE
                                  else choices.index(chosen) - 1)
                # The same three refusals the Storekeeper's importer is
                # given by `POST /assets/import/preview`, which calls this
                # function too: one file arriving at two doors has to be called
                # one thing (029).
                refusal = S._check_import_mapping(mapping)
                if refusal:
                    derr.config(text="✗  " + refusal)
                    return
                validate_stage(mapping)

            tk.Button(dfoot, text="Check the rows  →", bg=ACCENT, fg="white",
                      font=font("heading"), relief="flat",
                      cursor="hand2", pady=9, command=go,
                      activebackground=ACCENT2).pack(fill="x", padx=18,
                                                     pady=(10, 6))
            tk.Button(dfoot, text="Cancel", bg=CARD2, fg=SUBTEXT,
                      font=font("body"), relief="flat", cursor="hand2",
                      pady=6, command=dlg.destroy).pack(fill="x", padx=18,
                                                        pady=(0, 12))
            ui_kit.fit(dlg, 660)

        def validate_stage(mapping):
            """The whole answer, before anything is written."""
            clear()
            assets = S._load_assets()
            verdicts = S._validate_import_rows(rows, mapping, assets)
            good = [v for v in verdicts if not v["error"]]
            bad_ = [v for v in verdicts if v["error"]]
            tk.Label(stage, text="%d of %d row%s would be added. %d refused, "
                                 "and a refused row is not written - correct "
                                 "the file and import it again, or import "
                                 "what is good now and the rest after."
                                 % (len(good), len(verdicts),
                                    "" if len(verdicts) == 1 else "s",
                                    len(bad_)),
                     bg=BG, fg=FAINT, font=font("micro"), wraplength=620,
                     justify="left").pack(anchor="w", padx=18, pady=(10, 8))
            # A warning, not a refusal (#269): the mapping was accepted, but
            # the values it points at look like the Asset Number and Serial
            # Number columns are swapped. Shown, not blocking, because a
            # register with nothing to compare against cannot tell either way.
            swap_warning = S._check_swapped_columns(rows, mapping, assets)
            if swap_warning:
                tk.Label(stage, text="⚠  " + swap_warning, bg=BG,
                         fg=WARNING, font=font("micro"), wraplength=620,
                         justify="left").pack(anchor="w", padx=18,
                                              pady=(0, 8))
            vcols = ("line", "asset", "type", "verdict")
            vhead = {"line": "Row", "asset": "Asset", "type": "Asset Type",
                     "verdict": "What would happen"}
            vwide = {"line": 55, "asset": 190, "type": 110, "verdict": 430}
            vbody = tk.Frame(stage, bg=BG)
            vbody.pack(fill="both", expand=True, padx=18)
            vt = ttk.Treeview(vbody, columns=vcols, show="headings",
                              selectmode="browse", height=12)
            for c in vcols:
                vt.heading(c, text=vhead[c])
                vt.column(c, width=vwide[c], anchor="w")
            vsb = ttk.Scrollbar(vbody, orient="vertical", command=vt.yview)
            vt.configure(yscrollcommand=vsb.set)
            vt.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")
            vt.tag_configure("bad", foreground=DANGER)
            for v in verdicts:
                ident = " · ".join(x for x in (v["asset_number"],
                                               v["serial_number"]) if x)
                vt.insert("", "end", values=(
                    v["line"], ident or "no identifier", v["asset_type"],
                    v["error"] or ("added as %s" % (v["asset_model"]
                                                    or "no model"))),
                    tags=("bad",) if v["error"] else ())

            def commit():
                if not good:
                    derr.config(text="✗  No row in this file can be added as "
                                     "it stands.")
                    return
                known_now = {t.lower() for t in known_types()}
                fresh = sorted({v["asset_type"] for v in good
                                if v["asset_type"].lower() not in known_now})
                if fresh and not mb.askyesno(
                        "New Asset Type",
                        "This file brings %d Asset Type%s this sheet does not "
                        "have yet:\n\n%s\n\nEach one is added to the list "
                        "every client offers. Is that what you meant?"
                        % (len(fresh), "" if len(fresh) == 1 else "s",
                           ", ".join(fresh)),
                        icon="warning", parent=dlg):
                    return
                n = len(good)
                if write(lambda: S._import_assets(verdicts),
                         "%d asset%s added from %s%s."
                         % (n, "" if n == 1 else "s", name,
                            "" if not bad_ else
                            ", %d row%s refused and not written"
                            % (len(bad_), "" if len(bad_) == 1 else "s")),
                         derr):
                    dlg.destroy()

            tk.Button(dfoot, text="Add the %d valid asset%s"
                              % (len(good), "" if len(good) == 1 else "s"),
                      bg=ACCENT if good else CARD2,
                      fg="white" if good else SUBTEXT,
                      font=font("heading"), relief="flat",
                      cursor="hand2", pady=9, command=commit,
                      activebackground=ACCENT2).pack(fill="x", padx=18,
                                                     pady=(10, 6))
            tk.Button(dfoot, text="←  Back to the columns", bg=CARD2,
                      fg=SUBTEXT, font=font("body"), relief="flat",
                      cursor="hand2", pady=6,
                      command=map_stage).pack(fill="x", padx=18, pady=(0, 12))
            ui_kit.fit(dlg, 840)

        map_stage()

    tree.bind("<Double-1>", edit_asset)
    load_rows()

    fbox, frow = ui_kit.row_of(
        foot,
        [("＋  Add Asset", "＋  Add", (BG, ACCENT, ACCENT2, "white"),
          add_asset),
         ("✎  Edit Selected", "✎  Edit", (BG, CARD2, LINE, "white"),
          edit_asset),
         ("🗑  Remove Selected", "🗑  Remove",
          (BG, DANGER_BG, DANGER_HOT, "white"), remove_asset),
         ("📥  Import Assets", "📥  Import", (BG, CARD2, LINE, "white"),
          import_assets),
         ("↻  Refresh", "↻", (BG, CARD2, LINE, SUBTEXT), load_rows),
         ("Close", None, (BG, CARD2, LINE, SUBTEXT), win.destroy)],
        kind="footer")
    fbox.pack(fill="x", padx=18, pady=(8, 12))
    # minsize before fit, not after: fit lowers a height floor that is above
    # the form, and one written afterwards would put the shortfall back.
    win.minsize(frow.min_width() + 36, 420)
    ui_kit.fit(win, 720)
