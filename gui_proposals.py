"""Asset Proposals and Asset Sync - the two ways an asset arrives unasked.

Lifted out of server_gui.py by #235 (060). Paired rather than split: both
work the Assets section against the same register, one folding in what
another system says exists and the other answering what a Storekeeper has
proposed, and both end in ``_save_asset``.

The seam back to ``server_gui.py`` - ``S`` read at call time, the
palette seeded by ``_bind_palette`` - is described once, in that module's own
docstring, under "The nine window modules".
"""

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


def asset_proposals(parent):
    """What the Storekeeper is holding and the Admin has not approved yet.

    **The Assets section's pane** (#261/086), not a window. Unlike Connected
    Clients one ticket back, the section it sits on carries rows as well -
    Lookup Sheet and Asset Sync are still entries, and this is the list under
    them, which is the shape `section_pane` grew a third argument for.

    A pane rather than a row naming a window because of what it holds: this
    is the one thing in this system somebody else is waiting on an answer to,
    and it was three clicks deep behind the Lookup Sheet window behind the
    Database Location dialog behind a status chip. A proposal nobody sees is
    rule 6 stopping the delivery, with more steps in between. On the stage it
    is read by arriving at Assets, and the count is read with it.

    What went with the Toplevel is everything that was about being one: the
    `raise_open`/`single` pair, a pane the console builds once being single by
    construction; `grab_set`, Escape and the Close pill, because there is
    nothing to close - the bar swaps what is on the stage; and the written
    size, `fit` and the `minsize` under it, because a pane is served whatever
    the console has. The ACCENT title band went too: a saturated strip across
    the middle of a section that already names itself is a window's header on
    something that is not one. And the 18px inset every row of it carried
    went with them: `section_pane` packs this inside a container that is
    already inset, so keeping one of its own would draw this list 18px in
    from the entry rows above it.

    Every decision still takes the **admin password**, asked at the door: the
    Asset Proposals entry asks `_admin_again` on every open (096), Backup /
    Restore's shape, and nothing here asks again. Approving writes the
    register, which is rule 11's ground, and a capability password that could
    approve a proposal would be a way for a delegate to add an asset
    (ADR-0006, ADR-0012) - which is why that door is the admin password alone.

    A **table rather than a card per proposal**, unlike Manage Users: the facts
    on a proposal are the four an asset has plus who asked and when, which is a
    row, and it sits under the Lookup Sheet entry that opens the same four in
    the same order (rule 4). What a card would buy is room for the rejection
    reason, and that is the one thing here that is written rather than read.

    Approve writes through `_save_asset` - by way of `_decide_proposal`, the
    one writer of a decision - so a proposal and a hand-typed asset cannot mean
    different things. A rejection keeps the row: the Storekeeper is owed the
    answer, and there is deliberately nothing here that deletes one.

    **A batch is one row that opens.** A delivery arrives as a file (029) and
    every proposal out of it carries the one `proposed_at` that batch was
    stamped with, so the rows that arrived together are shown together and a
    decision on the parent is a decision on all of them - one confirmation,
    one reason. Each child is still selectable on its own,
    because a delivery of twenty machines may be nineteen the Admin recognises
    and one they do not. Grouping on the stamp rather than on a batch column is
    deliberate: the moment a batch arrived is a fact those rows already carry,
    and `client_commands` next door is the standing argument for deriving a
    thing rather than storing a second copy of it.

    Returns the pane. `_ui_reload` on it is `load_rows`, which `show_section`
    calls each time Assets is put on the stage - and the **decision path calls
    it too**, which is where the count re-read lives now. It used to be the
    window's own `<Destroy>`, read back through `show_section("Assets")`; a
    pane never closes, and answering a proposal is the only thing that moves
    the number. Never `wait_window`, which 077 had to take out of the opener:
    a nested event loop started inside a console callback does not return
    until the window goes, which is a console that has stopped repainting
    and, in `tools/server-checks.py`, a gate that hangs rather than fails.
    """
    from server_gui import S

    import tkinter as tk
    import tkinter.messagebox as mb
    from tkinter import ttk

    pane = tk.Frame(parent, bg=CARD)
    # The stage's own surface, not the app's: the five other sections are
    # CARD, and 085 had to move Connected Clients onto it for the same
    # reason. Every dialog this pane opens is still a Toplevel and still
    # wants a window to sit over - `wm transient` and a messagebox's
    # `-parent` both take one, and a Frame is not.
    top = pane.winfo_toplevel()

    tk.Label(pane, text="🧭  Asset Proposals", bg=CARD, fg=TEXT,
             font=font("heading")).pack(anchor="w", pady=(12, 2))

    # Packed before the body and from the bottom, for the reason every form
    # here is: pack gives a shortfall to whatever went in last.
    foot = tk.Frame(pane, bg=CARD)
    foot.pack(side="bottom", fill="x")

    tk.Label(pane, text="An asset the Storekeeper is holding that the Lookup "
                        "Sheet does not have yet. Nothing here is an asset "
                        "until it is approved - a proposal cannot be "
                        "transacted, which is what makes it safe for a client "
                        "to record one without a password. Approving adds it "
                        "to the Lookup Sheet exactly as typing it in here "
                        "would; rejecting keeps the row, with the reason, so "
                        "the Storekeeper is told and the same asset is not "
                        "proposed again every week.",
             bg=CARD, fg=FAINT, font=font("micro"), wraplength=660,
             justify="left").pack(anchor="w", pady=(0, 6))

    msg = tk.Label(pane, text="", bg=CARD, fg=DANGER, font=font("body"),
                   wraplength=660, justify="left")
    msg.pack(anchor="w", pady=(6, 0))

    # Reserved here, from the bottom and above the footer, for the reason
    # `foot` is: the list below takes `expand=True` and pack gives what is
    # left to whichever child went in last. On a window `fit` sized the form
    # around this line; a pane is served whatever the console has, which
    # measured 363px against the 505px this form asks for - and the count was
    # the child that paid, drawn 1px high and never mapped. It is written
    # into by `load_rows` further down.
    count = tk.Label(pane, text="", bg=CARD, fg=SUBTEXT, font=font("body"))
    count.pack(side="bottom", anchor="w", pady=(4, 0))

    # Asset Number and Serial Number first (rule 4), then who is asking - the
    # two questions an Admin has about a proposal are what it is and who is
    # holding it.
    cols    = ("asset_number", "serial_number", "asset_type", "asset_model",
               "proposed_by", "proposed_at")
    headers = {"asset_number": "Asset Number", "serial_number": "Serial Number",
               "asset_type": "Asset Type", "asset_model": "Asset Model",
               "proposed_by": "Proposed by", "proposed_at": "When"}
    widths  = {"asset_number": 135, "serial_number": 150, "asset_type": 105,
               "asset_model": 150, "proposed_by": 180, "proposed_at": 135}
    body = tk.Frame(pane, bg=CARD)
    body.pack(fill="both", expand=True, pady=(8, 0))
    # `tree headings` rather than `headings`: a batch is a row that opens, and
    # the handle that opens it is drawn in the tree column.
    tree = ttk.Treeview(body, columns=cols, show="tree headings",
                        selectmode="browse", height=10)
    tree.column("#0", width=28, stretch=False)
    for c in cols:
        tree.heading(c, text=headers[c])
        tree.column(c, width=widths[c], anchor="w")
    sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.tag_configure("batch", foreground=ACCENT)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    def load_rows():
        """Read the pending proposals back, never patch the list in place.

        Rows sharing a proposer and a `proposed_at` arrived as one file, so
        they are shown under one row that opens; a proposal on its own is still
        a row of its own, which is what a Storekeeper typing one gets.

        **This is the count**, and since 086 it is the only one.
        `proposals_label` was a second spelling of it beside the console
        entry, read off the same `_load_proposals` for the reason the cascade
        rule gives, and the entry went with the window. Read here, off that
        reader, narrowed to `"pending"`, and never off a `SELECT COUNT(*)` of
        its own.
        """
        tree.delete(*tree.get_children())
        pending = S._load_proposals("pending")
        batches = {}
        for p in pending:
            batches.setdefault((p["proposed_by"], p["proposed_at"]),
                               []).append(p)

        def when(p):
            return (p["proposed_at"] or "")[:16].replace("T", " ")

        def put(parent, p):
            tree.insert(parent, "end", iid=str(p["id"]),
                        values=(p["asset_number"], p["serial_number"],
                                p["asset_type"], p["asset_model"],
                                p["proposed_by"], when(p)))

        done = set()
        for p in pending:
            key = (p["proposed_by"], p["proposed_at"])
            if key in done:
                continue
            done.add(key)
            group = batches[key]
            if len(group) == 1:
                put("", group[0])
                continue
            node = tree.insert(
                "", "end", iid="batch:%d" % group[0]["id"], open=True,
                values=("%d assets in one file" % len(group), "", "", "",
                        p["proposed_by"], when(p)), tags=("batch",))
            for member in group:
                put(node, member)
        decided = [q for q in S._load_proposals() if q["status"] != "pending"]
        # Nothing waiting is said in words rather than as a bare 0, which is
        # what the entry's subtitle said and is the half of it worth keeping.
        count.config(text="%s  ·  %d decided"
                          % ("nothing waiting on an answer" if not pending
                             else "%d waiting on an answer" % len(pending),
                             len(decided)))

    def ask_reason(ident):
        """Why it was refused, which is the whole of what is sent back."""
        from tkinter import simpledialog
        return (simpledialog.askstring(
            "Reject Proposal",
            "Why is %s not an asset?\n\nThe Storekeeper sees this, and it is "
            "kept on the row - so \"already registered under another serial\" "
            "is worth more than \"no\".\n\nReason:" % ident,
            parent=top) or "").strip()

    def chosen():
        """The proposals the selection stands for: one, or a whole batch."""
        sel = tree.selection()
        if len(sel) != 1:
            return []
        kids = tree.get_children(sel[0])
        return [int(k) for k in kids] if kids else [int(sel[0])]

    def decide(approve):
        """The decision, then read it back.

        A batch is decided as one thing - one confirmation, one
        reason - because that is what it is: a delivery. Each row is still
        answered by `_decide_proposal` on its own, so a refusal reaches only
        the row it is about and the rest of the delivery still lands.

        `load_rows()` below is the **count re-read**, and this is its home
        since 086: answering a proposal is the only thing that moves the
        number, and the `<Destroy>` it used to be read off went with the
        window. It runs before the verdict line is written and on the failure
        path as well, a delivery of which three of twenty landed having moved
        the count by three.
        """
        ids = chosen()
        if not ids:
            mb.showinfo("Asset Proposals",
                        "Select one proposal, or the file a delivery arrived "
                        "in.\n\nEach proposal is a separate asset somebody is "
                        "holding - picking the file answers all of them at "
                        "once, and picking one row answers that one.",
                        parent=top)
            return
        sel = tree.selection()
        many  = len(ids) > 1
        ident = ("the %d assets in this file" % len(ids) if many
                 else (tree.set(sel[0], "asset_number")
                       or tree.set(sel[0], "serial_number")))
        reason = ""
        if approve:
            if not mb.askyesno(
                    "Approve Proposal",
                    "Add %s to the Lookup Sheet%s?\n\nThey can be transacted "
                    "from that moment, and any Asset Type among them is one "
                    "every client offers."
                    % (ident, "" if many
                       else " as %s" % tree.set(sel[0], "asset_type")),
                    icon="warning", parent=top):
                return
        else:
            reason = ask_reason(ident)
            if not reason:
                return
        failed = []
        for pid in ids:
            try:
                S._decide_proposal(pid, approve, reason=reason)
            except ValueError as ex:
                # `_decide_proposal`'s own words: it is the one writer, and a
                # refusal here is either "somebody already answered this" or
                # `_save_asset` saying the register gained that identifier
                # while the proposal waited. Both name what to do next, and
                # both are about one row - the rest of a delivery still lands.
                failed.append("#%d: %s" % (pid, ex))
            except Exception as ex:
                failed.append("#%d: the decision was not written: %s"
                              % (pid, ex))
        load_rows()
        if failed:
            msg.config(text="✗  %d of %d not decided.  %s"
                            % (len(failed), len(ids), "  ".join(failed[:3])),
                       fg=DANGER)
            return
        msg.config(text="✓  %s %s." % (ident, "approved and added to the "
                                            "Lookup Sheet" if approve
                                            else "rejected - the Storekeeper "
                                                 "is told the reason"),
                   fg=SUCCESS)

    load_rows()

    fbox, _ = ui_kit.row_of(
        foot,
        [("✓  Approve Selected", "✓  Approve",
          (CARD, ACCENT, ACCENT2, "white"), lambda: decide(True)),
         ("✗  Reject Selected", "✗  Reject",
          (CARD, DANGER_BG, DANGER_HOT, "white"), lambda: decide(False)),
         ("↻  Refresh", "↻", (CARD, CARD2, LINE, SUBTEXT),
          load_rows)],
        kind="footer")
    fbox.pack(fill="x", pady=(8, 12))
    # No `focus_set` on the password: this pane is built with the console, and
    # a field that takes focus while the console is still opening is one
    # nobody asked for.
    pane._ui_reload = load_rows
    return pane


def asset_sync(root):
    """The external asset system this register reads from (032).

    Reached from the Lookup Sheet's footer, beside Import Assets and Asset
    Proposals: all three add assets to the register through `_save_asset`, and
    this is the window an Admin opens to ask where the register's contents come
    from. Not on the action row, which is full at five labels - the width that
    row has and what it spends is measured in CLAUDE.md and by
    tools/server-checks.py on the real window, and is deliberately not
    restated here.

    Every change takes the **admin password**, asked at the door - the Asset
    Sync entry asks `_admin_again` on every open (096) and nothing here asks
    again - the same answer the Lookup Sheet itself gives, and for the same
    reason: whatever writes the register is what rule 6 refuses
    Transactions against, so it is not one of the four delegable capabilities
    (ADR-0006).

    **Run now saves first**, for the reason Send test mail saves first: a run
    that succeeds against what is in the form and then fails against what is in
    the file is worse than no run at all, and the fields it would differ on -
    the URL, the credential, the mapping - are exactly the ones a hand-started
    run exists to check. It is waited for rather than handed to the loop,
    because an Admin is standing here and the answer is the whole point of the
    button; the scheduled runs are the ones nobody is watching.

    **The last run is read off the System Log**, not out of a saved key: it is
    derived from rows that already say it (`_sync_last_run`), which is what
    `client_commands` does with `queued` and `collected` and for the same
    reason.
    """
    from server_gui import S

    import tkinter as tk
    from tkinter import ttk
    if ui_kit.raise_open("asset_sync") is not None:
        return
    win = tk.Toplevel(root)
    ui_kit.single(win, "asset_sync")
    win.title("Asset Sync")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.transient(root)
    win.grab_set()
    ui_kit.escape_closes(win)

    hdr = tk.Frame(win, bg=ACCENT, height=44)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="🔄  Asset Sync", bg=ACCENT, fg="white",
             font=font("title")).pack(side="left", padx=14, pady=12)

    # Packed before the body and from the bottom, so the buttons are the first
    # children served rather than the last.
    foot = tk.Frame(win, bg=BG)
    foot.pack(side="bottom", fill="x")

    # The form scrolls (095): at 965px it is taller than the 688px a 768px
    # screen leaves once `fit` has clamped it, and pack gives the shortfall to
    # whatever it served last. The footer above is outside the region and was
    # packed before it, so it stays on the screen however short that is.
    scroll = ui_kit.ScrollRegion(win, BG)
    body = scroll.body
    scroll.pack(padx=0, pady=0)

    tk.Label(body, text="Reads another system's asset list and folds it into "
                       "this register. It only ever reads. An asset this "
                       "register does not have is added; a field this register "
                       "has left empty is filled in; a field the two disagree "
                       "about is reported and left exactly as it is; and an "
                       "asset the external system does not have is reported "
                       "and never removed. What each run did is in the System "
                       "Log, which is also how a run reaches a mailbox - "
                       "through Notification Rules, on the sync.* events.",
             bg=BG, fg=FAINT, font=font("micro"), wraplength=560,
             justify="left").pack(anchor="w", padx=18, pady=(10, 6))

    msg = tk.Label(body, text="", bg=BG, fg=DANGER, font=font("body"),
                   wraplength=560, justify="left")
    msg.pack(anchor="w", padx=18, pady=(6, 0))

    cfg = S._sync_cfg()
    frm = tk.Frame(body, bg=CARD, padx=16, pady=10)
    frm.pack(fill="x", padx=18, pady=(8, 0))
    frm.columnconfigure(1, weight=1)

    # Label beside the field rather than above it, unlike every other dialog
    # here. Eleven fields stacked in this one's idiom measure 1231px, which is
    # 151px more than a 1080p screen has - and `ui_kit.fit` clamping that gives
    # the shortfall to whatever was packed last, which is the failure 017 is
    # about. The alternative is Manage Users' scrolling body, and that is for a
    # form with no bound at all; this one has eleven fields and will have
    # eleven tomorrow.
    def field(parent, row, label, value, show=None):
        tk.Label(parent, text=label, bg=CARD, fg=SUBTEXT,
                 font=font("body")).grid(row=row, column=0, sticky="w",
                                            padx=(0, 10), pady=3)
        e = tk.Entry(parent, bg=INPUT_BG, fg=TEXT, relief="flat",
                     font=font("value"), insertbackground=TEXT,
                     **({"show": show} if show else {}))
        e.insert(0, str(value))
        e.grid(row=row, column=1, sticky="ew", ipady=4, pady=3)
        # Only a masked field gets one (#202) - this helper draws the base URL
        # and the list path too. The credential it does draw is the external
        # system's, which this window is never told (ADR-0014), so the field
        # opens empty and the toggle has nothing to show until somebody types.
        if show:
            ui_kit.reveal(e)
        return e

    base_e = field(frm, 0, "Base URL", cfg["base"])
    path_e = field(frm, 1, "Path that lists assets", cfg["path"])
    key_e = field(frm, 2, "Key the list sits under", cfg["list_key"])
    tk.Label(frm, text="Empty where the answer is the list itself. A "
                       "credential is sent over https:// only.",
             bg=CARD, fg=FAINT, font=font("micro"), anchor="w",
             wraplength=520,
             justify="left").grid(row=3, column=0, columnspan=2, sticky="ew")

    tk.Label(frm, text="Authentication", bg=CARD, fg=SUBTEXT,
             font=font("body")).grid(row=4, column=0, sticky="w",
                                        padx=(0, 10), pady=3)
    auth_v = tk.StringVar(value=cfg["auth"])
    ttk.Combobox(frm, textvariable=auth_v, values=list(S._SYNC_AUTH_MODES),
                 state="readonly", style="S.TCombobox",
                 font=font("body")).grid(row=4, column=1, sticky="ew",
                                            pady=3)
    user_e = field(frm, 5, "Username  ·  basic only", cfg["username"])
    cred_e = field(frm, 6, "Token, key or password", "", show="●")
    # What is on disk, derived each time this window opens rather than kept
    # beside the widget: the field is always empty, because a credential this
    # server can read back is not one it should be showing.
    cred_note = tk.Label(frm, text="", bg=CARD, fg=FAINT, anchor="w",
                         font=font("micro"), wraplength=520, justify="left")
    cred_note.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(2, 0))

    def say_credential():
        if not S.HAS_DPAPI:
            # Refused with the reason named, never a plaintext fallback
            # (ADR-0013, ADR-0014).
            cred_e.config(state="disabled")
            cred_note.config(text=S._SYNC_NO_DPAPI, fg=WARNING)
        elif S._sync_secret_stored():
            cred_note.config(text="A credential is stored, encrypted for this "
                                  "machine. Type a new one to replace it, or "
                                  "use Clear.", fg=SUCCESS)
        else:
            cred_note.config(text="No credential stored. One typed here is "
                                  "encrypted for this machine and kept in "
                                  "sync_secret.dat, never in "
                                  "server_config.json.", fg=FAINT)

    say_credential()
    every_e = field(frm, 8, "Run every  ·  minutes, 0 for none", cfg["every"])

    mf = tk.Frame(body, bg=CARD, padx=16, pady=10)
    mf.pack(fill="x", padx=18, pady=(8, 0))
    mf.columnconfigure(1, weight=1)
    tk.Label(mf, text="Field mapping  ·  the JSON key each field is read from",
             bg=CARD, fg=SUBTEXT,
             font=font("body")).grid(row=0, column=0, columnspan=2,
                                        sticky="w")
    tk.Label(mf, text="Left empty, each is guessed from the keys the answer "
                      "carries - the same guess Import Assets makes about a "
                      "spreadsheet's headers, so the two cannot disagree about "
                      "what an Asset Number is called. A key typed here is "
                      "used whatever the guess says.",
             bg=CARD, fg=FAINT, font=font("micro"), wraplength=520,
             justify="left").grid(row=1, column=0, columnspan=2, sticky="w",
                                  pady=(2, 4))
    map_e = {}
    for i, f in enumerate(S._IMPORT_FIELDS):
        map_e[f] = field(mf, 2 + i, S._IMPORT_LABELS[f], cfg["mapping"].get(f, ""))

    lf = tk.Frame(body, bg=CARD, padx=16, pady=10)
    lf.pack(fill="x", padx=18, pady=(8, 0))
    tk.Label(lf, text="Last run", bg=CARD, fg=SUBTEXT,
             font=font("body")).pack(anchor="w")
    last_l = tk.Label(lf, text="", bg=CARD, fg=FAINT, anchor="w",
                      font=font("micro"), wraplength=520, justify="left")
    last_l.pack(fill="x", pady=(2, 0))

    def say_last():
        last = S._sync_last_run()
        if not last:
            last_l.config(text="No run has finished on this server yet.",
                          fg=FAINT)
            return
        ts, ok, detail = last
        last_l.config(text="%s  ·  %s%s" % (ts, "finished" if ok else "FAILED",
                                            ("  ·  " + detail) if detail
                                            else ""),
                      fg=SUCCESS if ok else DANGER)

    say_last()

    def save(clear_credential=False):
        """Write the settings. Returns True when they were written."""
        try:
            every = int((every_e.get() or "0").strip())
        except ValueError:
            msg.config(text="✗  Run every must be a number of minutes, or 0.",
                       fg=DANGER)
            return False
        if every < 0:
            msg.config(text="✗  Run every must be a number of minutes, or 0.",
                       fg=DANGER)
            return False
        typed = "" if not S.HAS_DPAPI else cred_e.get()
        if clear_credential or typed:
            err = S._sync_secret_set("" if clear_credential else typed)
            if err:
                msg.config(text="✗  " + err, fg=DANGER)
                return False
            cred_e.delete(0, "end")
        S._save_server_cfg(
            sync_base_url=base_e.get().strip(),
            sync_list_path=path_e.get().strip(),
            sync_list_key=key_e.get().strip(),
            sync_auth=auth_v.get(),
            sync_username=user_e.get().strip(),
            sync_interval_mins=every,
            sync_mapping=dict((f, map_e[f].get().strip())
                              for f in S._IMPORT_FIELDS))
        S._log_event("sync.configured",
                   "%s · %s auth · every %d minute(s)"
                   % (S._sync_url() or "nothing configured", auth_v.get(), every),
                   actor="Admin (Server GUI)", level="warn")
        say_credential()
        return True

    def do_save():
        if save():
            msg.config(text="✓  Saved. Applied at once - the settings are read "
                            "from the file on every run.", fg=SUCCESS)

    def do_clear():
        if save(clear_credential=True):
            msg.config(text="✓  Saved, and the stored credential removed.",
                       fg=SUCCESS)

    def do_run():
        if not save():
            return
        report, err = S._sync_run(actor="Admin (Server GUI)")
        say_last()
        if err:
            # The external system's own words, for the reason a failed test
            # mail shows the mail server's: "failed" is the one answer nobody
            # can act on.
            msg.config(text="✗  " + err, fg=DANGER)
            return
        msg.config(text="✓  " + S._sync_summary(report), fg=SUCCESS)

    tk.Button(foot, text="Clear stored credential", bg=CARD2, fg=SUBTEXT,
              font=font("micro"), relief="flat", cursor="hand2", pady=6,
              command=do_clear,
              activebackground=LINE).pack(fill="x", padx=18, pady=(8, 6))
    bbox, _brow = ui_kit.row_of(
        foot,
        [("🔄  Run now", "🔄  Run", (BG, CARD2, LINE, SUBTEXT), do_run),
         ("Save", None, (BG, ACCENT, ACCENT2, "white"), do_save),
         ("Close", None, (BG, CARD2, LINE, SUBTEXT), win.destroy)],
        kind="footer")
    bbox.pack(fill="x", padx=18, pady=(0, 12))

    scroll.size()
    ui_kit.fit(win, scroll.width(600))
