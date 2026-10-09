r"""What the console's windows carry: the version, the secrets, the guard.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import hashlib
import io
import os
import shutil

from server_checks.stage import (M, SRC_ALL, add_txn, bad, eq, fresh_db,
                                 gui_root, head, ok, tk_or_skip, widgets)



def masked_entries(win, tk):
    """Every `tk.Entry` under win that is masking what is typed into it."""
    return [w for w in widgets(win)
            if isinstance(w, tk.Entry) and str(w.cget("show"))]


def toggle_of(entry, tk):
    """The control `ui_kit.reveal` placed inside this entry, or None.

    A child of the entry rather than a sibling, which is the whole of why one
    helper served thirty-one call sites laid out with `pack` and with `grid`
    alike.
    """
    for c in entry.winfo_children():
        if isinstance(c, tk.Label):
            return c
    return None


def flips(entry, tk, label):
    """Assert one masked field unmasks on a click and re-masks on the next."""
    mask = str(entry.cget("show"))
    # `event_generate` queues the event (`-when tail`), and
    # `update_idletasks` runs idle work without draining that queue -
    # so the click has to be pumped with a full `update` or the field
    # is read back before the binding has run at all.
    lab = toggle_of(entry, tk)
    if lab is None:
        bad("%s has a masked field with no show toggle on it" % label)
        return False
    lab.event_generate("<Button-1>", x=2, y=2)
    entry.update()
    if str(entry.cget("show")) != "":
        bad("%s: a click on the toggle left the field masked" % label)
        return False
    lab.event_generate("<Button-1>", x=2, y=2)
    entry.update()
    if str(entry.cget("show")) != mask:
        bad("%s: the field did not go back to its own mask" % label)
        return False
    return True


def check_version_advertises_what_this_server_actually_holds():
    r"""`client_packages` is one entry per zip in dist\, and nothing else.

    This is the half of #190 that lives on the server. A pushed `update_now`
    that applies nothing answers with one of two sentences, and the likelier
    of them - *this server holds no package for it* - is decided here rather
    than on the client: `/version` advertises `latest` as this build's own
    `APP_VERSION` whatever else is on the machine, so a server whose dist\
    never received the client zips tells every installation it is behind and
    then offers it nothing to apply. `_queue_command` refuses the push at
    issue time for that state, but a week may pass before the command is
    collected, so what the client meets is whatever this endpoint says then.

    Driven rather than read, and against real bytes: the digest is what the
    updater checks a finished download against **before** the running app is
    stopped, so an entry advertising a digest of something other than the file
    `/download/client/<key>` serves is an update that refuses itself on every
    machine at once.

    Both shapes `_client_package` looks in are covered - `<dist>\<version>\`,
    which is what a carried release directory is, and `<dist>` itself, which is
    a zip carried on its own - and so is the one that must **not** resolve: a
    zip at some other version, left behind by an older release. `/version`
    told the client to ask for `latest` and that is the only thing this may
    hand out.
    """
    head("what /version advertises is what dist" + chr(92) + " holds")
    c = M.app.test_client()
    dist = os.path.join(M.BASE_DIR, "dist")
    ver = M.APP_VERSION
    blob = b"PK these bytes are what the digest is over"
    digest = hashlib.sha256(blob).hexdigest()

    def advertised():
        return (c.get("/version").get_json() or {}).get("client_packages") or {}

    try:
        shutil.rmtree(dist, ignore_errors=True)
        M._CLIENT_PKG_DIGESTS.clear()

        body = c.get("/version").get_json() or {}
        eq("a server holding nothing still publishes its own version",
           body.get("latest"), ver)
        eq("and advertises no client package at all",
           body.get("client_packages"), {})
        r = c.get("/download/client/notifier")
        eq("with the download refused by name",
           (r.status_code, (r.get_json() or {}).get("code")),
           (404, "no_package"))

        os.makedirs(os.path.join(dist, ver))
        nzip = os.path.join(dist, ver, "NotifierApp-%s.zip" % ver)
        with io.open(nzip, "wb") as fh:
            fh.write(blob)
        entry = advertised().get("notifier") or {}
        eq("the notifier zip is advertised by its own filename",
           entry.get("filename"), os.path.basename(nzip))
        eq("at the route that serves it", entry.get("path"),
           "/download/client/notifier")
        eq("carrying the digest of its own bytes", entry.get("sha256"), digest)
        eq("and their length", entry.get("size"), len(blob))
        eq("and the app with no zip beside it is not advertised",
           sorted(advertised()), ["notifier"])
        r = c.get("/download/client/notifier")
        eq("the download serves exactly those bytes",
           (r.status_code, r.data), (200, blob))

        with io.open(os.path.join(dist, ver, "StorekeeperApp-0.0.1.zip"),
                     "wb") as fh:
            fh.write(blob)
        eq("a zip at another version is not what the client was told to ask for",
           sorted(advertised()), ["notifier"])

        with io.open(os.path.join(dist, "StorekeeperApp-%s.zip" % ver),
                     "wb") as fh:
            fh.write(blob)
        eq("a zip carried on its own beside dist" + chr(92) + " resolves as well",
           sorted(advertised()), ["notifier", "storekeeper"])

        r = c.get("/download/client/lib")
        eq("and a key CLIENT_PACKAGES does not hold reaches no file",
           (r.status_code, (r.get_json() or {}).get("code")),
           (404, "no_package"))
    finally:
        shutil.rmtree(dist, ignore_errors=True)
        M._CLIENT_PKG_DIGESTS.clear()


def check_every_password_field_on_this_console_can_be_shown():
    """Every masked field carries the toggle and every one opens masked (#202).

    Driven on the real windows rather than read off the source, because what
    is being asserted is a widget inside another widget: `ui_kit.reveal` places
    its control **inside** the `tk.Entry`, which is what let one helper answer
    for thirty-one call sites without one of them changing its geometry
    manager - and a source read would see the call and not whether the control
    is there, wired, and putting the mask back.

    The mask is read off the entry rather than assumed, so a field masking
    with something other than the twenty-seven `\u25cf` sites is flipped back
    to its own mask rather than restyled to a house one.

    Three things per field, and the third is the one a toggle gets wrong: it
    opens **masked**, it unmasks on a real click on the control rather than on
    a call to a handler behind it, and clicking again puts the field's own
    mask back. A field that unmasks and stays unmasked is worse than no
    toggle, this being a window an Admin opens standing over somebody's desk.

    The count is asserted rather than left implicit: a group that walks every
    window and finds no masked field at all passes by finding nothing, which
    is this file's own standing complaint about a check that cannot fail.
    """
    head("every password field on this console can be shown (#202)")
    tk = tk_or_skip()
    if tk is None:
        return

    fresh_db()
    root = gui_root(tk)

    openers = [
        ("Capability Passwords", lambda: M.capability_passwords(root)),
        ("Manage Users", lambda: M.manage_users(root)),
        ("Mail Settings", lambda: M.mail_settings(root)),
        ("Asset Sync", lambda: M.asset_sync(root)),
        ("Lookup Sheet", lambda: M.manage_assets(root)),
        # Manage Transaction History was here until 088 and is the
        # Transactions section's pane now, so there is no window of its own to
        # open - and the pane carries no masked field either: Storekeeper
        # Cancel asks through `simple_password_prompt`, and the one field
        # inside is on Cancel against a Confirmed row, a dialog further in.
        # Connected Clients was here until 085 and is the Clients section's
        # pane now, so there is no window of its own for this walk to open
        # and no masked field on it either - the one password inside it is on
        # Push Certificate, a dialog two presses further in that this walk
        # has never reached.
    ]

    seen = 0
    for label, opener in openers:
        before = {str(w) for w in widgets(root) if isinstance(w, tk.Toplevel)}
        opener()
        root.update_idletasks()
        root.update()
        fresh = [w for w in widgets(root)
                 if isinstance(w, tk.Toplevel) and str(w) not in before]
        for win in fresh:
            for ent in masked_entries(win, tk):
                seen += 1
                if not flips(ent, tk, label):
                    break
        for win in fresh:
            try:
                win.destroy()
            except Exception:
                pass
        root.update_idletasks()
        root.update()

    if seen:
        ok("every one of the %d masked fields these windows open with carries "
           "the toggle and puts its own mask back" % seen)
    else:
        bad("no masked field was found at all, so nothing was measured")

    try:
        root.destroy()
    except Exception:
        pass


def check_the_two_replayable_secrets_open_empty():
    """The toggle can reveal nothing on the two fields nothing is told about.

    `smtp_secret.dat` and `sync_secret.dat` are the two secrets this server
    **holds** rather than checks (ADR-0013, ADR-0014), and the property they
    exist to have is that nothing reads them back - `GET /admin/mail` answers
    *whether* one is stored and never what it is. So the two windows that set
    them are never told either, and their fields open **empty**: the toggle
    there can only ever show what somebody typed into it a moment ago, which
    is the sharpest case of what #202 is and the one worth asserting rather
    than assuming.

    Driven with a secret **stored**, since an empty field on a server that has
    none is the answer either way and would pass a window that read the file.
    """
    head("the two replayable secrets open empty (#202)")
    tk = tk_or_skip()
    if tk is None:
        return

    fresh_db()
    real_smtp, real_sync = M._smtp_secret_stored, M._sync_secret_stored
    M._smtp_secret_stored = lambda: True
    M._sync_secret_stored = lambda: True
    root = gui_root(tk)
    try:
        for label, opener in (("Mail Settings", M.mail_settings),
                              ("Asset Sync", M.asset_sync)):
            before = {str(w) for w in widgets(root)
                      if isinstance(w, tk.Toplevel)}
            opener(root)
            root.update_idletasks()
            root.update()
            fresh = [w for w in widgets(root)
                     if isinstance(w, tk.Toplevel) and str(w) not in before]
            fields = []
            for win in fresh:
                fields.extend(masked_entries(win, tk))
            if not fields:
                bad("%s opened no masked field, so nothing was measured"
                    % label)
            for ent in fields:
                eq("%s's secret field opens empty, whatever is stored" % label,
                   ent.get(), "")
                lab = toggle_of(ent, tk)
                if lab is None:
                    bad("%s's secret field carries no toggle" % label)
                    continue
                lab.event_generate("<Button-1>", x=2, y=2)
                root.update_idletasks()
                root.update()
                eq("  and revealing it shows nothing, this window never "
                   "having been told what is stored", ent.get(), "")
            for win in fresh:
                try:
                    win.destroy()
                except Exception:
                    pass
            root.update_idletasks()
            root.update()
    finally:
        M._smtp_secret_stored, M._sync_secret_stored = real_smtp, real_sync
        try:
            root.destroy()
        except Exception:
            pass


def check_a_window_opened_twice_is_one_window():
    """Every window this console opens is one window (#191).

    Nothing stopped a second copy of any of them. The action row, the console
    entries, the status chips and the feed rows are all still there while a
    window is open - a grab is released by whatever sub-dialog was destroyed
    last rather than restored to the window under it, so after Manage Users,
    Add an Engineer, Close the console is clickable again with Manage Users
    still open. What that costs is a second Manage Users listing the Engineers
    as they were when the first was opened, a second Notification Rules whose
    edit buffer the first one's Save will overwrite, and a second window in
    #119's count that the console then asks about twice.

    The guard is `ui_kit.raise_open` and `ui_kit.single`, keyed on what the
    window is **about** rather than on who asked for it, so the feed row's
    click on Manage Transaction History and the action row's pill are one
    window. Driven rather than read, because what is asserted is that the
    second request produced no widget and that the same window came forward:
    a source read sees the call and not the answer.

    Three things per window, and the third is the one a guard gets wrong: it
    has to open again once it has been closed. A key left behind by a window
    that is gone is an action that works once per process.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("a window opened twice is one window")
    tk = tk_or_skip()
    if tk is None:
        return

    db = fresh_db()
    add_txn(db, asset_number="IT-0001", serial_number="SN-1")
    root = gui_root(tk)

    def tops():
        return [w for w in widgets(root) if isinstance(w, tk.Toplevel)]

    # The module-level openers, which is every window on this console a user
    # reaches from the action row, a console entry or a status chip. The ones
    # nested inside run_gui are held by the source group below instead: they
    # are reached by pressing a control, and what this group is about is the
    # second press rather than the first.
    openers = [
        # Connected Clients is not here since 085, Asset Proposals since 086,
        # the System Log since 087 and Manage Transaction History since 088,
        # for one reason: none of the four opens a window to open twice. Each is a section's pane, built once
        # with the console, and `show_section` packs and forgets the one copy
        # - which is this guard's property held by construction rather than by
        # a key in `ui_kit`.
        ("Lookup Sheet", lambda: M.manage_assets(root)),
        ("Capability Passwords", lambda: M.capability_passwords(root)),
        ("Manage Users", lambda: M.manage_users(root)),
        ("Mail Settings", lambda: M.mail_settings(root)),
        ("Notification Rules", lambda: M.notification_rules(root)),
        ("Backup / Restore", lambda: M.backup_restore(root)),
    ]

    def opened(before, opener):
        opener()
        root.update_idletasks()
        root.update()
        return [w for w in tops() if str(w) not in before]

    for label, opener in openers:
        before = {str(w) for w in tops()}
        first = opened(before, opener)
        if len(first) != 1:
            bad("%s opened %d windows the first time" % (label, len(first)))
            for w in first:
                w.destroy()
            continue
        win = first[0]
        again = opened(before, opener)
        if len(again) != 1:
            bad("%s opened a second window - there are now %d of it"
                % (label, len(again)))
        elif again[0] is not win:
            bad("%s answered the second request with a different window"
                % label)
        elif not win.winfo_ismapped():
            bad("%s was not raised on the second request" % label)
        else:
            ok("%s asked for twice is one window, raised rather than rebuilt"
               % label)
        win.destroy()
        root.update_idletasks()
        root.update()
        before = {str(w) for w in tops()}
        third = opened(before, opener)
        if len(third) != 1:
            bad("%s did not open again after it was closed - the key outlived "
                "the window" % label)
        else:
            ok("%s opens again once it has been closed" % label)
        for w in third:
            w.destroy()
        root.update_idletasks()
        root.update()

    try:
        root.destroy()
    except Exception:
        pass


def check_every_window_this_console_opens_takes_the_guard():
    """The pair is at every opener, including the ones a harness cannot press.

    Source, because six of these are nested inside `run_gui` - Server
    Administration, Change Admin Password, Database Location, Add Transaction,
    Display Settings and Server Settings - and Transaction Detail is a
    double-click inside Manage Transaction History. The group above drives the
    module-level ones; this is what stops a window being added without the
    guard, which is invisible at the time and is a second copy of whatever
    that window is about.

    What is asserted is the **pair**: the decision has to be made before
    `tk.Toplevel` is called, so a `single` with no `raise_open` in front of it
    registers a window nothing ever asks about, and a `raise_open` with no
    `single` behind it answers None for ever.

    Transaction Detail is keyed per id, since it is a window about a selected
    row: two ids are two windows and the same id twice is one.
    """
    head("every window the console opens takes the single-instance guard")
    tree = ast.parse(SRC_ALL)
    # `client_list` came off this list with 085, `asset_proposals` with 086,
    # `system_log` with 087 and `manage_records` with 088. A pane takes no
    # guard because there is nothing to open twice, and leaving any of them
    # here would fail on "no longer opens a window of its own" - which would
    # be true, and would be the point rather than the defect.
    #
    # `manage_records` is the one of the four #191 was about: the feed row
    # and the section entry were to be **one** Manage Transaction History,
    # and the guard is what made them one. A pane is one by construction,
    # which is what makes dropping the guard safe rather than convenient -
    # asserted below as the feed row asking the pane rather than opening
    # anything.
    want = ["asset_sync", "manage_assets",
            "capability_passwords", "manage_users",
            "backup_restore", "mail_settings",
            "notification_rules", "server_settings",
            "change_admin_password",
            "change_db_location", "add_transaction",
            "change_display_settings", "show_detail"]
    fns = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name in want + [
                "manage_records", "open_in_history"]:
            fns[n.name] = n
    missing = [w for w in want if w not in fns]
    if missing:
        bad("no such opener in server.py: %s" % ", ".join(missing))
        return
    for name in want:
        seg = ast.get_source_segment(SRC_ALL, fns[name]) or ""
        opens = [b for b in fns[name].body
                 if isinstance(b, ast.Assign) and isinstance(b.value, ast.Call)
                 and isinstance(b.value.func, ast.Attribute)
                 and b.value.func.attr == "Toplevel"]
        if not opens:
            bad("%s no longer opens a window of its own" % name)
        elif "ui_kit.raise_open(" not in seg or "ui_kit.single(" not in seg:
            bad("%s opens a window without the guard pair - a second copy of "
                "it can be opened over the first" % name)
        else:
            ok("%s asks ui_kit.raise_open before it builds, and registers "
               "what it built" % name)
    detail = ast.get_source_segment(SRC_ALL, fns["show_detail"]) or ""
    eq("Transaction Detail is keyed on the transaction it is about",
       'transaction_detail:%d" % tid' in detail, True)
    hist = ast.get_source_segment(SRC_ALL, fns["manage_records"]) or ""
    feed = ast.get_source_segment(SRC_ALL, fns["open_in_history"]) or ""
    eq("and a feed row's click selects its row on the one history pane "
       "rather than opening a second table",
       ("pane._select_transaction" in hist, "_select_transaction(" in feed,
        "tk.Toplevel(" in feed),
       (True, True, False))


def check_manage_records_names_where_a_decision_was_answered():
    """`Confirmed (auto)` in the state column, as the Notifier says it (#283).

    `origin` is NULL on a row decided before 106, and a row is a
    `sqlite3.Row`, so what is read here is the column and not a dict key.
    """
    head("Manage Records names where a decision was answered")
    import gui_records as GR
    fresh_db()
    db = M.get_db()
    for origin in ("auto", "desktop", None):
        db.execute("INSERT INTO transactions (asset_number, serial_number, "
                   "asset_type, team_member, direction, timestamp, confirmed, "
                   "origin) VALUES ('A', 'S', 'Laptop', 'Brian Dawson', "
                   "'Out', '2026-10-05T10:00:00', 1, ?)", (origin,))
    db.commit()
    got = [GR._decided(r, "Confirmed") for r in
           db.execute("SELECT * FROM transactions ORDER BY id")]
    db.close()
    eq("auto, desktop and NULL", got,
       ["Confirmed (auto)", "Confirmed", "Confirmed"])
