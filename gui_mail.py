"""Mail Settings and Notification Rules - the relay, and who hears from it.

Lifted out of server_gui.py by #235 (060). Paired because the second reads
the first's own recipient list, and because Mail Settings opens Notification
Rules directly. Both are the console's face on ``server_mail.py``.

The seam back to ``server_gui.py`` - ``S`` read at call time, the
palette seeded by ``_bind_palette`` - is described once, in that module's own
docstring, under "The nine window modules".
"""

import ui_kit
from ui_kit import font

import server_gui
from server_gui import _track_unsaved


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


def mail_settings(root):
    """Where the Asset Server sends mail from, and the password it replays.

    Reached from Server Administration, where Capability Passwords, Engineer
    Passwords and Manage Users are reached from and for the same reason: that
    is the window an Admin opens to think about who holds which password, and
    this is the first password this server *holds* rather than checks. Every
    other one here is a salted hash it can only compare something against
    (ADR-0008); an SMTP password is replayed at every send, so it is stored
    recoverably, which is what ADR-0013 is about. Not on the action row, which
    is full at five labels.

    Every change takes the **admin password**, asked at the door: the Mail
    Settings entry asks `_admin_again` on every open (096) and nothing here
    asks again.
    Deliberately not a fifth capability: whoever can point this at a mail
    server can mail the department as the Asset Server, which is not one
    delegated console action (ADR-0006).

    **Send test mail saves first.** A test that passes against what is in the
    form and then fails against what is in the file is worse than no test at
    all, and the fields it would differ on - the relay, the sender, the
    password - are exactly the ones a test exists to check.
    """
    from server_gui import S

    import tkinter as tk
    if ui_kit.raise_open("mail_settings") is not None:
        return
    win = tk.Toplevel(root)
    ui_kit.single(win, "mail_settings")
    win.title("Mail Settings")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.transient(root)
    win.grab_set()

    hdr = tk.Frame(win, bg=ACCENT, height=44)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="✉  Mail Settings", bg=ACCENT, fg="white",
             font=font("title")).pack(side="left", padx=14, pady=12)

    # Packed before the body and from the bottom, so the buttons are the first
    # children served rather than the last - pack gives a shortfall to whatever
    # went in last, and that is how four dialogs here came to have no usable
    # button.
    foot = tk.Frame(win, bg=BG)
    foot.pack(side="bottom", fill="x")

    # The form scrolls (095): at 868px it is taller than the 688px a 768px
    # screen leaves once `fit` has clamped it, and pack gives the shortfall to
    # whatever it served last. The footer above is outside the region and was
    # packed before it, so it stays on the screen however short that is.
    scroll = ui_kit.ScrollRegion(win, BG)
    body = scroll.body
    scroll.pack(padx=0, pady=0)

    tk.Label(body, text="Everything the Asset Server sends goes out through "
                       "this relay, as this address. Nothing is sent because "
                       "of what is on this window except the test mail - which "
                       "events are mailed and to whom is set elsewhere. A "
                       "send that fails never holds anything up: it is "
                       "recorded in the System Log and the Transaction behind "
                       "it is recorded either way.",
             bg=BG, fg=FAINT, font=font("micro"), wraplength=520,
             justify="left").pack(anchor="w", padx=18, pady=(10, 6))

    # msg, not err: every button here reports through it and most of what it
    # says is a success, the same reason Manage Users names its one that.
    msg = tk.Label(body, text="", bg=BG, fg=DANGER, font=font("body"),
                   wraplength=520, justify="left")
    msg.pack(anchor="w", padx=18, pady=(6, 0))

    cfg = S._smtp_cfg()
    frm = tk.Frame(body, bg=CARD, padx=16, pady=10)
    frm.pack(fill="x", padx=18, pady=(8, 0))

    def field(label, value, show=None):
        tk.Label(frm, text=label, bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(6, 2))
        e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                     font=font("value"), insertbackground=TEXT,
                     **({"show": show} if show else {}))
        e.insert(0, str(value))
        e.pack(fill="x", ipady=6)
        # The masked one here is the SMTP password, and this window is never
        # told what is stored (ADR-0013) - `GET /admin/mail` answers whether
        # one is there and never what it is - so it opens empty and stays that
        # way. What the toggle shows is what somebody typed into it just now,
        # which is the whole of what it can ever show (#202).
        if show:
            ui_kit.reveal(e)
        return e

    host_e = field("Mail server", cfg["host"])
    port_e = field("Port", cfg["port"])
    from_e = field("From address", cfg["from"])
    user_e = field("Username  ·  leave empty for a relay that asks for none",
                   cfg["username"])
    pw_e = field("Password", "", show="●")
    # What is on disk, derived each time this window is opened rather than
    # kept beside the widget: the field is always empty, because a password
    # this server can read back is not a password it should be showing.
    pw_note = tk.Label(frm, text="", bg=CARD, fg=FAINT, anchor="w",
                       font=font("micro"), wraplength=460, justify="left")
    pw_note.pack(fill="x", pady=(4, 0))
    if not S.HAS_DPAPI:
        # Refused with the reason named, never a plaintext fallback (ADR-0013).
        pw_e.config(state="disabled")
        pw_note.config(text="This machine cannot store a mail password: "
                            "Windows DPAPI is not available here, which needs "
                            "pywin32. It is never written in plaintext "
                            "instead. A relay that asks for no password works "
                            "as it does anywhere else.", fg=WARNING)
    elif S._smtp_secret_stored():
        pw_note.config(text="A password is stored, encrypted for this machine. "
                            "Type a new one to replace it, or use Clear.",
                       fg=SUCCESS)
    else:
        pw_note.config(text="No password stored. One typed here is encrypted "
                            "for this machine and kept in smtp_secret.dat, "
                            "never in server_config.json.", fg=FAINT)

    tls_var = tk.BooleanVar(value=cfg["starttls"])
    tk.Checkbutton(frm, text="STARTTLS  ·  upgrade the connection before "
                             "logging in",
                   variable=tls_var, bg=CARD, fg=SUBTEXT, selectcolor=INPUT_BG,
                   activebackground=CARD, activeforeground=TEXT,
                   font=font("body")).pack(anchor="w", pady=(10, 0))

    tf = tk.Frame(body, bg=CARD, padx=16, pady=10)
    tf.pack(fill="x", padx=18, pady=(8, 0))
    tk.Label(tf, text="Send a test mail to", bg=CARD, fg=SUBTEXT,
             font=font("body")).pack(anchor="w", pady=(0, 2))
    test_e = tk.Entry(tf, bg=INPUT_BG, fg=TEXT, relief="flat",
                      font=font("value"), insertbackground=TEXT)
    test_e.pack(fill="x", ipady=6)
    tk.Label(tf, text="Saves what is above first, then sends, and reports "
                      "whatever the mail server says back.",
             bg=CARD, fg=FAINT, font=font("micro"), anchor="w",
             wraplength=460, justify="left").pack(fill="x", pady=(4, 0))

    def save(clear_password=False):
        """Write the settings. Returns True when they were written."""
        typed = "" if not S.HAS_DPAPI else pw_e.get()
        touching = clear_password or bool(typed)
        code, err = S._save_mail_settings(
            host_e.get(), port_e.get(), from_e.get(), user_e.get(),
            tls_var.get(),
            password=("" if clear_password else typed) if touching else S._KEEP)
        if code:
            msg.config(text="✗  " + err, fg=DANGER)
            return False
        if touching:
            pw_e.delete(0, "end")
        pw_note.config(
            text=("A password is stored, encrypted for this machine. Type a "
                  "new one to replace it, or use Clear.")
                 if S._smtp_secret_stored() else
                 ("No password stored. One typed here is encrypted for this "
                  "machine and kept in smtp_secret.dat, never in "
                  "server_config.json."),
            fg=SUCCESS if S._smtp_secret_stored() else FAINT)
        return True

    def do_save():
        if not save():
            return False
        msg.config(text="✓  Saved. Applied at once - no restart needed.",
                   fg=SUCCESS)
        return True

    def do_clear():
        if save(clear_password=True):
            msg.config(text="✓  Saved, and the stored password removed.",
                       fg=SUCCESS)

    def do_test():
        if not save():
            return
        to = test_e.get().strip()
        if not to:
            msg.config(text="✗  An address to send the test to is required.",
                       fg=DANGER)
            return
        # Sent and waited for, unlike every other send in this file: an Admin
        # standing at this console asked for it and the answer is the whole
        # point of the button. _send_mail's worker is for the sends nobody is
        # watching. The send and the two entries beside it are
        # `_send_test_mail`'s, so this window and POST /admin/mail/test cannot
        # report the same relay differently (#172).
        err = S._send_test_mail(to, "Admin (Server GUI)")
        if err:
            msg.config(text="✗  " + err, fg=DANGER)
        else:
            msg.config(text="✓  Test mail accepted by %s for %s."
                            % (host_e.get().strip(), to), fg=SUCCESS)

    def unsaved():
        """The form against what is on disk, plus a password typed and not
        saved.

        Read back rather than flagged, the way the note under the password
        field is derived from disk each time rather than kept: this window is
        one of the two the settings behind it are read from on every use, so
        what "unsaved" means here is exactly the difference between the fields
        and the file.
        """
        now = S._smtp_cfg()
        return (host_e.get().strip() != now["host"]
                or port_e.get().strip() != str(now["port"])
                or from_e.get().strip() != now["from"]
                or user_e.get().strip() != now["username"]
                or bool(tls_var.get()) != bool(now["starttls"])
                or bool(S.HAS_DPAPI and pw_e.get()))

    close = _track_unsaved(win, "Mail Settings", unsaved, do_save)
    ui_kit.escape_closes(win, close)

    tk.Button(foot, text="Clear stored password", bg=CARD2, fg=SUBTEXT,
              font=font("micro"), relief="flat", cursor="hand2", pady=6,
              command=do_clear,
              activebackground=LINE).pack(fill="x", padx=18, pady=(8, 6))
    # The relay and the credential are this window's; which events go out over
    # it is a list that changes for entirely different reasons, so it is the
    # window next door rather than a second half of this one (031).
    tk.Button(foot, text="Notification Rules  ·  which events reach a mailbox, "
                          "and whose",
              bg=CARD2, fg=SUBTEXT, font=font("micro"), relief="flat",
              cursor="hand2", pady=6,
              command=lambda: notification_rules(root),
              activebackground=LINE).pack(fill="x", padx=18, pady=(0, 6))
    bbox, _brow = ui_kit.row_of(
        foot,
        [("✉  Send test mail", "✉  Test", (BG, CARD2, LINE, SUBTEXT), do_test),
         ("Save", None, (BG, ACCENT, ACCENT2, "white"), do_save),
         ("Close", None, (BG, CARD2, LINE, SUBTEXT), close)],
        kind="footer")
    bbox.pack(fill="x", padx=18, pady=(0, 12))

    scroll.size()
    ui_kit.fit(win, scroll.width(560))


def notification_rules(root):
    """Which System Log events reach a mailbox, and whose (031).

    Beside Mail Settings rather than on it: that window is the relay and the
    credential, this one is the subscription list, and one window carrying both
    would be one door for two decisions an Admin makes months apart. Reached from its footer, which is the adjacency Capability
    Passwords has to Server Administration.

    A rule is an event name, the mailboxes it goes to and the least level that
    counts. The names offered are the ones this log has actually seen
    (_log_event_names), never a catalogue kept beside _log_event's call
    sites - that would be the event list written down twice - and a name that
    has never happened is accepted, because a rule is a standing instruction
    rather than an assertion that something exists.

    What that costs is that the first time somebody wants mail about
    `update.failed`, that event has by definition never happened and is not in
    the list - so the window has to **say** that typing one is allowed, and
    name where the list of names lives (L2). It is
    `docs/system-log-events.md`, read by a person rather than by this server,
    which is what keeps it from being the second copy of a set of literals that
    031 refused to keep.

    Every change takes the **admin password**, for Mail Settings' reason:
    whoever can add a rule can point the department's mail at themselves. It
    is asked at the door - this entry's `_admin_again`, or Mail Settings' own
    from whose footer this opens (096) - and not again here.
    """
    from server_gui import S

    import tkinter as tk
    from tkinter import ttk
    if ui_kit.raise_open("notification_rules") is not None:
        return
    win = tk.Toplevel(root)
    ui_kit.single(win, "notification_rules")
    win.title("Notification Rules")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.transient(root)
    win.grab_set()

    hdr = tk.Frame(win, bg=ACCENT, height=44)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="🔔  Notification Rules", bg=ACCENT, fg="white",
             font=font("title")).pack(side="left", padx=14, pady=12)

    # Packed before the body and from the bottom, for the reason every dialog
    # here packs its buttons first.
    foot = tk.Frame(win, bg=BG)
    foot.pack(side="bottom", fill="x")

    tk.Label(win, text="One row per event that should reach a mailbox. The "
                       "level is the least that counts, so a rule at warn "
                       "passes warn and error and leaves the ordinary ones "
                       "alone. Mail is sent only where Mail Settings has a "
                       "relay, and a send that fails never holds up whatever "
                       "caused it.",
             bg=BG, fg=FAINT, font=font("micro"), wraplength=620,
             justify="left").pack(anchor="w", padx=18, pady=(10, 4))
    # The one thing the list of names cannot say for itself. The names offered
    # are the ones this log has actually seen, so anything worth being told
    # about is missing from the list on the day somebody comes here to
    # subscribe to it - and nothing on this window said that typing it was
    # allowed.
    tk.Label(win, text="The event box lists what this log has already seen. A "
                       "name that has never happened here may still be typed, "
                       "and the rule works the first time it does - which is "
                       "usually the point. Every name this build can write, "
                       "and the level each is written at, is in "
                       "docs\\system-log-events.md.",
             bg=BG, fg=SUBTEXT, font=font("micro"), wraplength=620,
             justify="left").pack(anchor="w", padx=18, pady=(0, 4))
    tk.Label(win, text="Bounded on purpose: at most one mail per event every "
                       "%d seconds, and %d in total per hour across every rule "
                       "here. Client entries arrive over an unauthenticated "
                       "channel, so a rule on one is a mail amplifier pointed "
                       "at the department. Nothing is dropped in silence - "
                       "what a bound held back is counted on the next mail "
                       "that event does send, and the System Log has all of "
                       "it either way."
                       % (S._NOTIFY_MIN_SECS, S._NOTIFY_HOURLY_MAX),
             bg=BG, fg=WARNING, font=font("micro"), wraplength=620,
             justify="left").pack(anchor="w", padx=18, pady=(0, 6))

    msg = tk.Label(win, text="", bg=BG, fg=DANGER, font=font("body"),
                   wraplength=620, justify="left")
    msg.pack(anchor="w", padx=18, pady=(6, 0))

    # The body scrolls, for Manage Users' and Capability Passwords' reason:
    # a card per rule has no bound at all, and this window is fixed on both
    # axes, so past `fit`'s clamp there is nothing to drag open. At 24 rules it
    # asked for 1794px of height against a screen with 1080 and lost 794px of
    # rules - and what it loses is not the tail of a list somebody can scroll
    # to, it is the rules themselves. The footer above is outside this region
    # and was packed before it, which is what keeps Save and Close on the
    # screen however many rules there are.
    scroll = ui_kit.ScrollRegion(win, BG)
    body = scroll.body
    scroll.pack()
    known = S._log_event_names()
    rows = []

    def add_row(rule=None):
        rule = rule or {"event": "", "to": "", "level": "info"}
        card = tk.Frame(body, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)
        card.pack(fill="x", pady=(0, 6))
        pad = tk.Frame(card, bg=CARD, padx=12, pady=8)
        pad.pack(fill="x")
        line = tk.Frame(pad, bg=CARD)
        line.pack(fill="x")
        ev_v = tk.StringVar(value=rule["event"])
        # Editable rather than a fixed list: a rule may name an event that has
        # not happened on this server yet, and the first time it does is
        # exactly when somebody wants to have been told.
        ttk.Combobox(line, textvariable=ev_v, values=known,
                     style="S.TCombobox", font=font("body"),
                     width=26).pack(side="left")
        lv_v = tk.StringVar(value=rule["level"])
        ttk.Combobox(line, textvariable=lv_v, values=list(S.LOG_LEVELS),
                     state="readonly", style="S.TCombobox",
                     font=font("body"), width=7).pack(side="left",
                                                         padx=(8, 0))
        to_e = tk.Entry(line, bg=INPUT_BG, fg=TEXT, relief="flat",
                        font=font("body"), insertbackground=TEXT)
        to_e.insert(0, rule["to"])
        to_e.pack(side="left", fill="x", expand=True, ipady=4, padx=(8, 0))
        entry = [ev_v, lv_v, to_e, card]
        rows.append(entry)

        def drop():
            rows.remove(entry)
            card.destroy()
            refit()

        tk.Button(line, text="🗑", bg=CARD2, fg=DANGER, font=font("body"),
                  relief="flat", cursor="hand2", command=drop,
                  activebackground=LINE).pack(side="left", padx=(8, 0),
                                              ipadx=6, ipady=3)
        return entry

    tk.Label(body, text="EVENT                                LEVEL      "
                        "RECIPIENTS  ·  comma separated",
             bg=BG, fg=FAINT, font=font("mono")).pack(anchor="w",
                                                         pady=(0, 4))
    for r in S._notify_rules():
        add_row({"event": r["event"], "to": ", ".join(r["to"]),
                 "level": r["level"]})
    if not rows:
        add_row()

    def refit():
        """The region measured beside `fit`, on the same repaint.

        This window's children change while it is open - a rule is added and
        dropped without anything being written - so the region has to be
        re-asked each time rather than sized once at build time, or the
        twenty-fifth rule lengthens the window instead of the scroll.
        """
        scroll.size()
        ui_kit.fit(win, scroll.width(680))

    def do_add():
        add_row()
        refit()

    tk.Button(body, text="＋  Add a rule", bg=CARD2, fg=SUBTEXT,
              font=font("body"), relief="flat", cursor="hand2",
              command=do_add,
              activebackground=LINE).pack(anchor="w", pady=(2, 6), ipadx=10,
                                          ipady=4)

    def do_save():
        # A blank row is the one this window opens with and the one an Add
        # leaves behind. Which rows are dropped, which are refused and in whose
        # words is `_save_notify_rules`', so this window and
        # POST /admin/notify_rules cannot judge one file two ways (#172).
        code, err, kept = S._save_notify_rules(
            [{"event": ev_v.get(), "to": to_e.get(), "level": lv_v.get()}
             for ev_v, lv_v, to_e, _card in rows], "Admin (Server GUI)")
        if code:
            msg.config(text="✗  " + err, fg=DANGER)
            return False
        msg.config(text="✓  %d rule(s) saved. Applied at once - they are read "
                        "from the file on every entry." % len(kept),
                   fg=SUCCESS)
        return True

    def unsaved():
        """The rows on the window against the rules in the file.

        This is the one window here with a real edit buffer - a row is typed,
        added and dropped without anything being written until Save - so it is
        also the one where closing over it costs the most. The comparison is
        made on the shape `_notify_rules` reads back rather than on the text,
        so re-spacing a recipient list is not an unsaved change and saving
        really does clear the flag.
        """
        def split(text):
            return tuple(a.strip() for a in
                         text.replace(";", ",").split(",") if a.strip())

        here = [(ev_v.get().strip(), split(to_e.get()), lv_v.get())
                for ev_v, lv_v, to_e, _card in rows
                if ev_v.get().strip() or to_e.get().strip()]
        disk = [(r["event"], tuple(r["to"]), r["level"])
                for r in S._notify_rules()]
        return here != disk

    close = _track_unsaved(win, "Notification Rules", unsaved, do_save)
    ui_kit.escape_closes(win, close)

    bbox, _brow = ui_kit.row_of(
        foot,
        [("Save", None, (BG, ACCENT, ACCENT2, "white"), do_save),
         ("Close", None, (BG, CARD2, LINE, SUBTEXT), close)],
        kind="footer")
    bbox.pack(fill="x", padx=18, pady=(8, 12))

    refit()
