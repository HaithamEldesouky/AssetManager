"""Connected Clients - which installations exist, and what may be said back.

Lifted out of server_gui.py by #235 (060). The Clients section's pane
(#260/085) and the command queue behind it; the registry it draws from is
``server_clients.py``'s.

The seam back to ``server_gui.py`` - ``S`` read at call time, the
palette seeded by ``_bind_palette`` - is described once, in that module's own
docstring, under "The nine window modules".
"""

import ui_kit
from ui_kit import font
from server_cert import _cert_fingerprint, _push_next_cert

import server_gui
from server_gui import _ago_ts, _client_colour, _tag_ages, _when_ts


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


def client_list(parent):
    """Connected Clients - which installations exist, and when each was last
    heard from. **The Clients section's pane**, not a window (#260/085).

    Reads the table rather than an endpoint, for the reason `_client_rows`
    gives. Nothing here is a live connection: a Client is listed because it
    checked in, and the only question this pane answers is how long ago.

    What went with the Toplevel is everything that was about being one: the
    `raise_open`/`single` pair, because a pane the console builds once is
    single by construction and there is no second copy to raise; Escape and
    the Close pill, because there is nothing to close - the bar swaps what is
    on the stage and Clients is one of its six cells; and the written 900x640
    with the 480px floor under it, because a pane is served whatever the
    console has. What it gained is the stage's own surface: a window painted
    itself BG and a pane is CARD, which is what the other five sections are
    and what the list's own `S.Treeview` block was already drawn in.

    Everything else is the window's, unchanged: the nine columns at their
    widths, the header and its caption, the commands list below them, and Log
    Off Selected and Reset Identity on a footer that is offered nowhere else
    in the application. Send Command, one level inside here, is still a
    dialog and still a Toplevel - and still BG, being still a window.

    Returns the pane. `_ui_reload` on it is what `show_section` calls each
    time Clients is put on the stage: the pane is built once and a Client
    checks in every 15s, so rows read at build time would be the answer from
    whenever the console started - the staleness `clients_caption` was read
    at hover to avoid, one shape along.
    """
    from server_gui import S

    import tkinter as tk
    from tkinter import ttk
    import tkinter.messagebox as mb
    # CARD, not BG. This was a window and painted itself the app background;
    # it is one of six section panes now and the other five are the stage's
    # own surface, which is what `section_pane` builds on. On the dark
    # palette the two are a shade apart and on the light one they are #e8ebeb
    # against #ffffff, so a pane left on BG is the one section that reads as
    # a different surface from its five siblings. The `S.Treeview` block is
    # already CARD-backed, so this also puts the list's own surround on the
    # colour the list is drawn in.
    pane = tk.Frame(parent, bg=CARD)
    # Every dialog one level inside here is still a Toplevel and still asks to
    # sit over the console, which is a window - `wm transient` and a
    # messagebox's `-parent` both want one, and a Frame is not.
    top = pane.winfo_toplevel()

    # The footer is packed here, from the bottom and before the body, so it
    # is the first child pack serves rather than the last - the same shape
    # the eight fit() dialogs use. Its Row is filled in at the end of this
    # function, where the callbacks it needs exist; what has to happen up
    # here is the reservation. What that ordering was worth while this was a
    # window - packed last, the footer was the child a too-small window
    # squeezed - it is still worth on a stage that can be dragged narrower.
    btnf = tk.Frame(pane, bg=CARD)
    btnf.pack(side="bottom", fill="x", padx=14, pady=(0, 12))

    tk.Label(pane, text="👥  Connected Clients  —  every installation that has "
                       "checked in", bg=CARD, fg=TEXT,
             font=font("heading")).pack(anchor="w", padx=14,
                                                 pady=(12, 2))
    tk.Label(pane, text="Listed by the identifier each Client generates once and "
                       "keeps, so a renamed machine or a new DHCP lease updates "
                       "its row instead of adding another - and a reinstall "
                       "appears as the new installation it is. The source "
                       "address is what you need to go and find the machine.",
             bg=CARD, fg=FAINT, font=font("micro"), wraplength=860,
             justify="left").pack(anchor="w", padx=14, pady=(0, 8))

    # The Certificate column sits beside Version because the two answer the
    # same kind of question about an installation, and it is **100px wide for
    # a 95-character value** on purpose: it was added to a window holding a
    # written 900x640 that was already 84px below what its form asked for, so
    # it was a new column inside a fixed size and the other eight gave up
    # 105px between them rather than Ago falling off the right-hand edge. The
    # written size went with the Toplevel in 085 and these widths did not: a
    # pane is served whatever the console has, which is more than 900 and
    # never less than what these add up to. Reported Address sits directly
    # after Source Address (#281): behind NAT the source is the gateway for
    # every row, and the claim beside it is the one that finds the machine.
    # What it
    # shows is a verdict and the last two pairs - the verdict because the
    # question being asked here is who would break if the certificate were
    # replaced today, and the pairs because two Clients stranded on two
    # *different* old certificates have to be told apart. The full 95
    # characters are on the line under the list, which is where one
    # fingerprint is actually compared against another.
    cols = ("hostname", "app", "version", "cert", "member", "os_user",
            "address", "reported", "last_seen", "ago")
    headers = {"hostname": "Hostname", "app": "App", "version": "Version",
               "cert": "Certificate", "member": "Engineer",
               "os_user": "Windows Account", "address": "Source Address",
               "reported": "Reported Address",
               "last_seen": "Last Check-in", "ago": "Ago"}
    widths = {"hostname": 125, "app": 85, "version": 60, "cert": 100,
              "member": 120, "os_user": 120, "address": 100,
              "reported": 110, "last_seen": 100, "ago": 60}
    tree = ttk.Treeview(pane, columns=cols, show="headings", height=9)
    for c in cols:
        tree.heading(c, text=headers[c])
        tree.column(c, width=widths[c], anchor="w")
    tree.pack(fill="both", expand=True, padx=14, pady=4)
    # A stale Client is what this window exists to show, so it is coloured
    # rather than left to be read off a timestamp.
    _tag_ages(tree, (("fresh", "SUCCESS"), ("today", "WARNING"),
                     ("stale", "DANGER")))

    count = tk.Label(pane, text="", bg=CARD, fg=SUBTEXT, font=font("body"))
    count.pack(anchor="w", padx=14, pady=(2, 2))
    # #242: install-iis.ps1 writes URL Rewrite's rule so `_client_addr()`
    # gets the caller's own address instead of the loopback hop every
    # request makes under HttpPlatformHandler. Where it is missing, every
    # row here is 127.0.0.1 with nothing beside it saying why - this is
    # that why, shown only where there is something to explain. Unpacked
    # here; load_rows below packs and forgets it with side="bottom", which
    # keeps it directly above btnf regardless of what else this window has
    # packed by the time a repaint decides it is needed.
    iis_hint = tk.Label(
        pane, text="IIS is not forwarding addresses: install URL Rewrite "
                  "and re-run tools\\install-iis.ps1",
        bg=CARD, fg=WARNING, font=font("micro"), wraplength=860,
        justify="left")
    # The whole fingerprint, for the selected Client. A comparison is made
    # against another 95-character value read off the Server Settings window
    # or off a client's own prompt, so the full thing has to be somewhere -
    # and this is the one place in this window with room for it.
    certline = tk.Label(pane, text="", bg=CARD, fg=MONO, font=font("mono"))
    certline.pack(anchor="w", padx=14, pady=(0, 10))
    # The whole value per Client, kept beside the tree rather than in a column
    # nothing could read it out of: the cell holds two pairs, and re-reading
    # the table on every click of a list would be a query per keypress of an
    # arrow key.
    held_cert = {}

    def cert_cell(held, served):
        """What the Certificate column shows for one Client.

        A verdict only where there is something to judge against: a server
        with no `ssl_cert.pem` beside it is serving plain HTTP, and saying NO
        to every Client there would read as a fleet about to be stranded by a
        certificate that does not exist.
        """
        if not held:
            return "—"
        tail = ".." + held[-5:]
        if not served:
            return tail
        return ("OK  " if held == served else "NO  ") + tail

    def load_rows():
        # Refresh is what the Admin presses to see whether a command has been
        # collected yet, so it must not throw the selection away and blank the
        # panel they pressed it to read. The row ids are the Client
        # identifiers, so a Client that is still listed keeps its selection.
        keep = tree.selection()
        tree.delete(*tree.get_children())
        rows = S._client_rows()
        # Read once per repaint rather than once per row, and read here rather
        # than when the window opened: a certificate can be replaced from the
        # Server Settings window while this one is open, and Refresh is what
        # the Admin presses to see what that did to the fleet.
        served = _cert_fingerprint()
        held_cert.clear()
        for r in rows:
            held_cert[r["client_id"]] = r["cert_fingerprint"] or ""
            colour = _client_colour(r["last_seen"])
            tag = ("fresh" if colour == SUCCESS else
                   "today" if colour == WARNING else "stale")
            # The row's own id is the Client's identifier, so a command
            # can be queued from a selection without showing an opaque
            # identifier in a column nobody reads.
            tree.insert("", "end", iid=r["client_id"], tags=(tag,), values=(
                r["hostname"] or "—", r["app"] or "—", r["version"] or "—",
                cert_cell(r["cert_fingerprint"], served),
                r["member"] or "—", r["os_user"] or "—", r["address"] or "—",
                r["reported_address"] or "—",
                _when_ts(r["last_seen"]), _ago_ts(r["last_seen"]) or "—"))
        still = [c for c in keep if tree.exists(c)]
        if still:
            tree.selection_set(*still)
        fresh = sum(1 for r in rows
                    if (S._since_ts(r["last_seen"]) or 1e9) < 15 * 60)
        # How many would survive a certificate replacement, which is the whole
        # reason the column beside it exists. Said only where there is a
        # certificate being served, for cert_cell's reason.
        holding = sum(1 for r in rows
                      if served and r["cert_fingerprint"] == served)
        count.config(text="no Client has checked in yet" if not rows else
                     "%d installation%s  ·  %d heard from in the last 15 "
                     "minutes%s" % (len(rows), "" if len(rows) == 1 else "s",
                                    fresh,
                                    ("  ·  %d of %d hold the certificate this "
                                     "server is serving"
                                     % (holding, len(rows))) if served else ""))
        iis_hint.pack_forget()
        if (S._iis_host() is not None and rows and
                all((r["address"] or "") in S._LOOPBACK_PEERS for r in rows)):
            iis_hint.pack(side="bottom", fill="x", padx=14, pady=(0, 4))
    tk.Label(pane, text="COMMANDS FOR THE SELECTED CLIENT", bg=CARD, fg=SUBTEXT,
             font=font("emph")).pack(anchor="w", padx=14,
                                                 pady=(4, 4))
    ccols = ("command", "issued", "by", "expires", "state")
    cheaders = {"command": "Command", "issued": "Issued", "by": "By",
                "expires": "Expires", "state": "State"}
    cwidths = {"command": 300, "issued": 130, "by": 150, "expires": 130,
               "state": 110}
    ctree = ttk.Treeview(pane, columns=ccols, show="headings", height=5)
    for c in ccols:
        ctree.heading(c, text=cheaders[c])
        ctree.column(c, width=cwidths[c], anchor="w")
    ctree.pack(fill="x", padx=14, pady=(0, 2))
    # A command that was never collected is the signal that the machine has not
    # been running, so the three states are coloured apart rather than left to
    # be read off two dates.
    _tag_ages(ctree, (("queued", "WARNING"), ("collected", "SUCCESS"),
                      ("expired", "DANGER")))
    chint = tk.Label(pane, text="Select a Client above.", bg=CARD, fg=FAINT,
                     font=font("micro"))
    chint.pack(anchor="w", padx=14, pady=(0, 8))

    def selected_client():
        sel = tree.selection()
        return sel[0] if len(sel) == 1 else None

    def load_commands(_e=None):
        ctree.delete(*ctree.get_children())
        cid = selected_client()
        if not cid:
            chint.config(text="Select a Client above.")
            return
        rows = S._command_rows(cid)
        for r in rows:
            st = S._command_status(r)
            ctree.insert("", "end", tags=(st,), values=(
                S.COMMAND_LABELS.get(r["command"], r["command"]),
                _when_ts(r["issued_at"]), r["issued_by"] or "Admin",
                _when_ts(r["expires_at"]), st))
        waiting = sum(1 for r in rows if S._command_status(r) == "queued")
        chint.config(
            text=("nothing has been queued for this Client"
                  if not rows else
                  "%d command%s  ·  %d still waiting to be collected"
                  % (len(rows), "" if len(rows) == 1 else "s", waiting)))

    def show_cert(_e=None):
        cid = selected_client()
        if not cid:
            certline.config(text="")
            return
        full = held_cert.get(cid, "")
        certline.config(
            text=("this Client has not reported a certificate" if not full
                  else "certificate held:  %s" % full))

    def selection_changed(_e=None):
        show_cert()
        load_commands()

    tree.bind("<<TreeviewSelect>>", selection_changed)
    load_rows()
    selection_changed()

    def queue(command):
        """Ask for the admin password, then queue one command.

        Asked through `_admin_again` when Queue is pressed (096): the Clients
        section is a pane with no entry to put a door on, and this acts on
        somebody else's machine rather than on a record. Reached as
        `server_gui._admin_again` so the check suite's staging patch reaches it.
        """
        cid = selected_client()
        if not cid:
            mb.showinfo("Send Command",
                        "Select exactly one Client first.\n\n"
                        "Only a Client that has checked in can be sent a "
                        "command, which is why this list is the only place to "
                        "do it.", parent=top)
            return
        host = tree.set(cid, "hostname")
        d = tk.Toplevel(top)
        d.title("Send Command")
        # No written size: what is in this window depends on which command was
        # picked - `reset_identity` and `update_now` each add a wrapped
        # paragraph the other two do not have - so a number written here is
        # wrong for at least one branch, and `pack` gives the shortfall to the
        # buttons because they go in last. `ui_kit.fit` below takes it from
        # what the children actually ask for, which is the rule every other
        # dialog in this file keeps and the one Push Certificate beside it
        # already keeps.
        d.configure(bg=BG)
        d.transient(top)
        d.grab_set()
        ui_kit.escape_closes(d)
        tk.Label(d, text=S.COMMAND_LABELS[command], bg=BG, fg=TEXT,
                 font=font("title")).pack(anchor="w", padx=18,
                                                     pady=(16, 2))
        tk.Label(d, text="for %s" % (host,), bg=BG, fg=MONO,
                 font=font("ident")).pack(anchor="w", padx=18)
        # rewrap on both: this dialog's width drags, so 440 is the floor rather
        # than the answer and anything wider comes from the dialog. 36 is the
        # padx below, on both sides.
        ui_kit.rewrap(tk.Label(
            d, text="The Client collects this on its next check-in, and "
                    "it is handed over exactly once. It expires after %d "
                    "days if the machine never comes back, and stays in "
                    "the list either way so you can see what happened."
                    % S.COMMAND_TTL_DAYS,
            bg=BG, fg=FAINT, font=font("micro"), wraplength=440,
            justify="left"), 36).pack(anchor="w", padx=18, pady=(10, 0))
        if command == "reset_identity":
            ui_kit.rewrap(tk.Label(
                d, text="The setup wizard asks for the admin password, so "
                        "whoever is at the machine cannot quietly point "
                        "it at a different Engineer.",
                bg=BG, fg=WARNING, font=font("micro"), wraplength=440,
                justify="left"), 36).pack(anchor="w", padx=18, pady=(6, 0))
        if command == "update_now":
            # What is worth saying here is the one thing that differs from the
            # engineer clicking Check for Updates themselves: nobody is asked.
            # The verification, the rollback and the reported outcome are the
            # same ones that path has had since #148, which is why they are not
            # re-described - what an Admin needs to know before pressing this
            # is that a window is going to close on somebody without warning.
            ui_kit.rewrap(tk.Label(
                d, text="The app closes and reopens itself at %s. Nobody at "
                        "the machine is asked and there is no postponing it, "
                        "which is the whole difference from the engineer "
                        "pressing Check for Updates. A Client already on this "
                        "version does nothing." % S.APP_VERSION,
                bg=BG, fg=WARNING, font=font("micro"), wraplength=440,
                justify="left"), 36).pack(anchor="w", padx=18, pady=(6, 0))

        def send():
            # The password moved out of `_queue_command` at #174, so this
            # window asks it here: the helper is reached from the network too
            # now, and one that checked a password could only know about one
            # of its two callers.
            if not server_gui._admin_again(d, "Send Command"):
                return
            payload, status = S._queue_command(cid, command,
                                             issued_by="Admin (Server GUI)")
            if status >= 400:
                mb.showerror("Send Command", payload.get("error", "Refused"),
                             parent=d)
                return
            d.destroy()
            load_commands()
            mb.showinfo("Send Command",
                        "Queued for %s.\n\nIt will be handed over on the "
                        "Client's next check-in." % (host,), parent=top)

        bf = tk.Frame(d, bg=BG)
        bf.pack(fill="x", padx=18, pady=(16, 14))
        qbox, qrow = ui_kit.row_of(
            bf,
            [("Queue Command", "Queue", (BG, ACCENT, ACCENT2, "white"), send),
             ("Cancel", None, (BG, CARD2, LINE, SUBTEXT), d.destroy)],
            kind="footer")
        qbox.pack(fill="x")
        d.resizable(True, False)
        ui_kit.fit(d, max(480, qrow.min_width() + 36))

    def push_cert():
        """Queue `trust_cert` for every Client. C3, ADR-0020.

        Not a per-Client control, unlike the two beside it: what this is for is
        the fleet learning to accept a certificate before the binding moves to
        it, and doing that one machine at a time is how one gets missed. It
        needs no selection for the same reason.

        What it does **not** do is replace anything. Every Client ends up
        holding both certificates, which is what makes the cutover (C4) a
        restart on this machine rather than a visit to each laptop - so the
        confirmation says so rather than carrying the warning the SSL
        Certificate window carries, which would be the wrong warning on the one
        action in this area that strands nobody.
        """
        fp = _cert_fingerprint(S.SSL_CERT_NEXT_PATH)
        if not fp:
            mb.showinfo(
                "Push Staged Certificate",
                "Nothing is staged on this server.\n\n"
                "Generate one first, in Server Settings under Next "
                "certificate. It is written beside the live pair and nothing "
                "is bound to it.", parent=top)
            return
        n = len(S._client_rows())
        if not n:
            mb.showinfo("Push Staged Certificate",
                        "No Client has checked in yet, so there is nobody to "
                        "push to.", parent=top)
            return
        d = tk.Toplevel(top)
        d.title("Push Staged Certificate")
        d.configure(bg=BG)
        d.transient(top)
        d.grab_set()
        ui_kit.escape_closes(d)
        tk.Label(d, text="Push the staged certificate to %d installation%s"
                         % (n, "" if n == 1 else "s"),
                 bg=BG, fg=TEXT, font=font("title")).pack(
                     anchor="w", padx=18, pady=(16, 2))
        tk.Label(d, text=fp, bg=BG, fg=MONO,
                 font=font("mono")).pack(anchor="w", padx=18)
        ui_kit.rewrap(tk.Label(
            d, text="Each Client fetches this certificate on its next "
                    "check-in and adds it to the one it already trusts. "
                    "Nothing is replaced and nothing is bound: every Client "
                    "ends up accepting both, which is what lets the cutover "
                    "happen later with nobody at any machine.",
            bg=BG, fg=FAINT, font=font("micro"), wraplength=440,
            justify="left"), 36).pack(anchor="w", padx=18, pady=(10, 0))
        ui_kit.rewrap(tk.Label(
            d, text="One command per Client, collected exactly once. The "
                    "list below this window is what says who has answered: a "
                    "row stays queued until that machine checks in. The "
                    "Certificate column does not move - a Client reports the "
                    "certificate this server is serving, which is still the "
                    "old one and is the point.",
            bg=BG, fg=SUBTEXT, font=font("micro"), wraplength=440,
            justify="left"), 36).pack(anchor="w", padx=18, pady=(6, 0))

        def send():
            # #174, for the reason Send Command gives one dialog up, and
            # asked the way it asks (096).
            if not server_gui._admin_again(d, "Push Staged Certificate"):
                return
            payload, status = _push_next_cert(issued_by="Admin (Server GUI)")
            if status >= 400:
                mb.showerror("Push Staged Certificate",
                             payload.get("error", "Refused"), parent=d)
                return
            d.destroy()
            load_commands()
            mb.showinfo(
                "Push Staged Certificate",
                "Queued for %d of %d installations.\n\n"
                "%d already had one waiting and %d could not be queued.\n\n"
                "Each is handed over on that Client's next check-in."
                % (payload["queued"], payload["clients"],
                   payload["already_waiting"], payload["failed"]),
                parent=top)

        bf = tk.Frame(d, bg=BG)
        bf.pack(fill="x", padx=18, pady=(16, 14))
        pbox, prow = ui_kit.row_of(
            bf,
            [("Push to All Clients", "Push",
              (BG, ACCENT, ACCENT2, "white"), send),
             ("Cancel", None, (BG, CARD2, LINE, SUBTEXT), d.destroy)],
            kind="footer")
        pbox.pack(fill="x")
        ui_kit.fit(d, max(480, prow.min_width() + 36))

    def clear_old():
        """Clear every installation not heard from for longer than X (#268).

        **The threshold is typed here, and saved.** Until #268 this was
        chosen from a fixed list and stored nowhere - an act somebody
        performed by hand when a batch of machines had been reimaged. It is
        now also what `_client_sweep_loop` runs on its own every hour, so
        what is confirmed here is not just this one clear: saving it is what
        lets an Admin who never opens this dialog again still get the
        housekeeping they asked for once.

        The field reads "d:h:m" - `_parse_age_threshold` - because a fixed
        list of four choices cannot say what an hourly job needs and a plain
        day count cannot say what #268 asked for either.

        The count is read through `_stale_clients`, the same reader the writer
        uses, so the number in the confirmation is the number that goes.
        """
        d = tk.Toplevel(top)
        d.title("Clear Old Clients")
        d.configure(bg=BG)
        d.transient(top)
        d.grab_set()
        ui_kit.escape_closes(d)
        tk.Label(d, text="Remove installations nobody has heard from",
                 bg=BG, fg=TEXT, font=font("title")).pack(
                     anchor="w", padx=18, pady=(16, 2))
        ui_kit.rewrap(tk.Label(
            d, text="A Client is on this list because it checked in, so how "
                    "long ago is the only question the list answers. Set how "
                    "long, as days:hours:minutes, and every installation past "
                    "it is removed from the registry - by this, and, saved, "
                    "by itself every hour.",
            bg=BG, fg=SUBTEXT, font=font("micro"), wraplength=440,
            justify="left"), 36).pack(anchor="w", padx=18, pady=(4, 0))

        saved_days = S._load_server_cfg().get(
            "clear_age_threshold_days", S.CLEAR_AGE_DEFAULT_DAYS)
        age_var = tk.StringVar(value=S._format_age_threshold(saved_days))
        count_lbl = tk.Label(d, text="", bg=BG, fg=WARNING,
                             font=font("heading"))

        def _parsed_or_none():
            try:
                return S._parse_age_threshold(age_var.get())
            except ValueError:
                return None

        def restate(*_a):
            parsed = _parsed_or_none()
            if parsed is None:
                count_lbl.config(
                    text="Enter a threshold as days:hours:minutes, such as "
                         "1:12:0")
                return
            n = len(S._stale_clients(parsed))
            count_lbl.config(
                text="%d of %d installation%s would be removed"
                     % (n, len(S._client_rows()), "" if n == 1 else "s"))

        aline = tk.Frame(d, bg=BG)
        aline.pack(anchor="w", padx=18, pady=(12, 2))
        tk.Label(aline, text="Threshold (d:h:m)", bg=BG, fg=SUBTEXT,
                 font=font("body")).pack(side="left", padx=(0, 8))
        age_entry = tk.Entry(aline, textvariable=age_var, bg=CARD, fg=TEXT,
                             insertbackground=TEXT, relief="flat", width=12,
                             font=font("value"))
        age_entry.pack(side="left", ipady=4)
        age_var.trace_add("write", restate)
        count_lbl.pack(anchor="w", padx=18, pady=(4, 0))
        restate()

        ui_kit.rewrap(tk.Label(
            d, text="A Client that is still running comes back on its next "
                    "check-in, under the identifier it has always had, with "
                    "the commands issued to it still listed. This is "
                    "housekeeping on a list and nothing is done to any "
                    "machine.",
            bg=BG, fg=FAINT, font=font("micro"), wraplength=440,
            justify="left"), 36).pack(anchor="w", padx=18, pady=(10, 0))
        ui_kit.rewrap(tk.Label(
            d, text="The commands issued to a removed Client are kept: an "
                    "uncollected one is the evidence that machine was not "
                    "running. This is not a way to withdraw one - an "
                    "installation that comes back is still owed whatever is "
                    "still waiting for it.",
            bg=BG, fg=FAINT, font=font("micro"), wraplength=440,
            justify="left"), 36).pack(anchor="w", padx=18, pady=(6, 0))

        def go():
            # Send Command's door (096): this pane has no entry to carry one.
            if not server_gui._admin_again(d, "Clear Old Clients"):
                return
            days = _parsed_or_none()
            if days is None:
                mb.showerror("Clear Old Clients",
                             "Enter a threshold as days:hours:minutes, such "
                             "as 1:12:0", parent=d)
                return
            rows = S._stale_clients(days)
            if not mb.askyesno(
                    "Confirm Clear",
                    "Remove %d installation%s last heard from more than %s?\n"
                    "This cannot be undone, and the threshold is saved for "
                    "the hourly auto-clear too."
                    % (len(rows), "" if len(rows) == 1 else "s",
                       age_var.get()),
                    icon="warning", parent=d):
                return
            S._save_server_cfg(clear_age_threshold_days=days)
            payload, status = S._clear_stale_clients(
                days, actor="Admin (Server GUI)")
            if status >= 400:
                mb.showerror("Clear Old Clients",
                             payload.get("error", "Refused"), parent=d)
                return
            d.destroy()
            load_rows()
            load_commands()
            mb.showinfo("Clear Old Clients",
                        "\u2713  %d installation%s removed, %d left."
                        % (payload["removed"],
                           "" if payload["removed"] == 1 else "s",
                           payload["remaining"]), parent=top)

        bf = tk.Frame(d, bg=BG)
        bf.pack(fill="x", padx=18, pady=(16, 14))
        rbox, rrow = ui_kit.row_of(
            bf,
            [("Clear Old Clients", "Clear", (BG, DANGER_BG, DANGER, "white"),
              go),
             ("Cancel", None, (BG, CARD2, LINE, SUBTEXT), d.destroy)],
            kind="footer")
        rbox.pack(fill="x")
        ui_kit.fit(d, max(480, rrow.min_width() + 36))
        age_entry.bind("<Return>", lambda _e: go())

    # CARD for the same reason the pane is: a pill's first colour is the
    # surface it sits on, and this footer sits on the stage now. The three
    # dialogs above keep BG - they are still windows.
    cbox, _ = ui_kit.row_of(
        btnf,
        [("⏻  Log Off Selected", "⏻  Log Off",
          (CARD, CARD2, LINE, "white"), lambda: queue("logoff")),
         ("↺  Reset Identity", "↺  Reset",
          (CARD, CARD2, LINE, "white"), lambda: queue("reset_identity")),
         ("⬆  Update Selected", "⬆  Update",
          (CARD, CARD2, LINE, "white"), lambda: queue("update_now")),
         ("⇪  Push Certificate", "⇪  Push",
          (CARD, CARD2, LINE, "white"), push_cert),
         ("⌦  Clear Old", "⌦  Clear",
          (CARD, CARD2, LINE, "white"), clear_old),
         ("↻  Refresh", "↻", (CARD, CARD2, LINE, SUBTEXT),
          lambda: (load_rows(), load_commands()))],
        kind="footer")
    cbox.pack(fill="x")
    # Refresh by hand stays: it is what the Admin presses to see whether a
    # queued command has been collected yet, a question asked while standing
    # in front of the pane. This is the other one - arriving at it.
    pane._ui_reload = lambda: (load_rows(), load_commands())
    return pane
