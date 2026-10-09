"""Capability Passwords and Manage Users - who holds which credential.

Lifted out of server_gui.py by #235 (060). Paired because they are two
surfaces over one permission table: rule 8 keeps the names themselves in
``server.py``, and these are the two windows that read them.

The seam back to ``server_gui.py`` - ``S`` read at call time, the
palette seeded by ``_bind_palette`` - is described once, in that module's own
docstring, under "The nine window modules".
"""

import ui_kit
from ui_kit import font

import server_gui
from server_gui import _capability_holders, _capability_state, _track_unsaved


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


def capability_passwords(root):
    """Set or clear the optional password on each of the four capabilities.

    Reached from Server Administration rather than from the action row because
    that is the window an admin opens to think about who holds which password.

    **What a password set here opens is an endpoint, not a control on this
    screen.** These stopped gating this console when Server Administration
    became one door with the admin password on it, and they were never a
    console delegation to begin with - they are the credential an Admin
    administers this server *remotely* with, which is the argument ADR-0006
    said would have to be made again against the network and ADR-0015 makes.
    R1 built that channel, so the window now says which of the four reach it:
    three do, and **SSL Certificate does not and must not**, since installing
    a certificate means uploading `ssl_key.pem` - the one file that must never
    travel, and anybody holding it impersonates this server to every client
    that pinned it (rule 1).

    **Each row also takes the holder's name**, which is a label on the
    credential and not an authentication of anybody: what it buys is that the
    `remote.action` entry every use writes says who the Admin handed the
    password to, rather than only which password it was. It is set with the
    password and cleared with it, because a name beside no credential names
    nothing.

    The admin password is asked at the door - the Capability Passwords entry
    asks `_admin_again` on every open (096), Backup / Restore's shape - and
    not again here, and the door takes the admin password alone rather than
    going through `_authorise`: delegation is the Admin's own call and a
    capability password must not be able to grant or revoke itself.
    """
    from server_gui import S

    import tkinter as tk
    from tkinter import ttk
    if ui_kit.raise_open("capability_passwords") is not None:
        return
    win = tk.Toplevel(root)
    ui_kit.single(win, "capability_passwords")
    win.title("Capability Passwords")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.transient(root)
    win.grab_set()

    hdr = tk.Frame(win, bg=ACCENT, height=44)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="🔐  Capability Passwords", bg=ACCENT, fg="white",
             font=font("title")).pack(side="left", padx=14, pady=12)

    # Packed before the body, and from the bottom: the body is expand=True, so
    # it would otherwise take the room and leave the only control that closes
    # this window with whatever is left.
    foot = tk.Frame(win, bg=BG)
    foot.pack(side="bottom", fill="x")

    tk.Label(win, text="Give somebody one of these actions without giving them "
                       "the admin password. A capability password opens only "
                       "its own action; the admin password keeps opening all of "
                       "them, so setting one can never lock you out. Changing "
                       "the admin password is not in this list and cannot be "
                       "delegated.",
             bg=BG, fg=FAINT, font=font("micro"), wraplength=520,
             justify="left").pack(anchor="w", padx=18, pady=(10, 2))
    # Said on the window rather than left to be discovered, and the absence is
    # the half worth saying: an Admin setting a password on SSL Certificate is
    # entitled to know it opens nothing over the network and never will, rather
    # than finding out when the delegate cannot use it.
    tk.Label(win, text="⚠  These open nothing at this console "
                       "- Server Administration asks for the admin password "
                       "once at the door and everything behind it opens. They "
                       "are the credential for administering this server "
                       "REMOTELY, over HTTPS only. SSL Certificate is "
                       "deliberately not one of them: installing a certificate "
                       "means uploading the private key, which never leaves "
                       "this machine.",
             bg=BG, fg=WARNING, font=font("micro"), wraplength=520,
             justify="left").pack(anchor="w", padx=18, pady=(0, 6))

    err = tk.Label(win, text="", bg=BG, fg=DANGER, font=font("body"),
                   wraplength=520, justify="left")
    err.pack(anchor="w", padx=18, pady=(6, 0))

    rows = {}

    def repaint():
        state = _capability_state()
        named = _capability_holders()
        for cap, (pill, _entry, who) in rows.items():
            on = state[cap]
            pill.config(text="own password set" if on else "admin only",
                        fg=SUCCESS if on else FAINT)
            # The stored name, read back each time rather than left as whatever
            # was typed: a Set that was refused must not leave the field
            # claiming a name this server does not hold.
            if who.get() != named.get(cap, ""):
                who.delete(0, "end")
                who.insert(0, named.get(cap, ""))

    def act(cap, clear):
        payload, status = S._set_capability_password(
            cap, "" if clear else rows[cap][1].get(), None,
            holder=None if clear else rows[cap][2].get(),
            authorised_as="Admin (Server GUI)")
        if status >= 400:
            err.config(text="✗  " + payload.get("error", "Refused"))
            return
        rows[cap][1].delete(0, "end")
        err.config(text="")
        repaint()
        was = payload.get("status")
        if was == "cleared" and not payload.get("was_set"):
            say = "%s had no password of its own. Nothing changed." \
                % (S.CAPABILITY_LABELS[cap],)
        elif was == "cleared":
            say = "✓  %s no longer has its own password. The admin password " \
                  "still opens it." % (S.CAPABILITY_LABELS[cap],)
        elif payload.get("holder"):
            say = "✓  %s now has its own password, held by %s." \
                % (S.CAPABILITY_LABELS[cap], payload["holder"])
        else:
            say = "✓  %s now has its own password, with no " \
                  "holder named." % (S.CAPABILITY_LABELS[cap],)
        err.config(text=say, fg=FAINT if was == "cleared" else SUCCESS)

    # The body scrolls, which is Manage Users' answer to the same shape one
    # window over: a card per capability, each carrying a heading, two captions,
    # a holder field and a password field with two buttons, and the list grows
    # by a ticket rather than by anything this window can bound. Four of them
    # asked for exactly what a 1080p screen has, so #170's fifth - and the line
    # on each row saying what it opens - put it past the clamp, where `fit`
    # gives the shortfall to whatever was packed last. The footer above is
    # outside this canvas and was packed before it, which is what keeps Close on
    # the screen however many capabilities there are.
    canvas = tk.Canvas(win, bg=BG, highlightthickness=0)
    # ttk rather than tk, like every other scrollbar in this file: the
    # Vertical.TScrollbar style is where this window's palette reaches one.
    bar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    body = tk.Frame(canvas, bg=BG)
    body_window = canvas.create_window((0, 0), window=body, anchor="nw")

    def body_resized(_e=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def canvas_resized(e):
        # The form is kept as wide as the viewport, so the cards fill the
        # window as they did when they were packed straight into it - a frame
        # windowed into a canvas otherwise sits at whatever width it asked for.
        canvas.itemconfig(body_window, width=e.width)

    body.bind("<Configure>", body_resized)
    canvas.bind("<Configure>", canvas_resized)

    # Bound on this window rather than with `bind_all`, for Manage Users'
    # reason: this GUI keeps a dozen windows and a global binding would outlive
    # this one and fire into a destroyed canvas.
    win.bind("<MouseWheel>",
             lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    for cap in S.CAPABILITIES:
        box = tk.Frame(body, bg=CARD, highlightthickness=1,
                       highlightbackground=LINE)
        box.pack(fill="x", pady=(0, 8))
        pad = tk.Frame(box, bg=CARD, padx=14, pady=9)
        pad.pack(fill="x")
        top = tk.Frame(pad, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text=S.CAPABILITY_LABELS[cap], bg=CARD, fg=TEXT,
                 font=font("heading")).pack(side="left")
        pill = tk.Label(top, text="", bg=CARD, fg=FAINT,
                        font=font("caption"))
        pill.pack(side="right")
        tk.Label(pad,
                 text=("reachable over HTTPS" if cap in S.CAPABILITY_REMOTE
                       else "console only - never over the network"),
                 bg=CARD, fg=SUBTEXT if cap in S.CAPABILITY_REMOTE else FAINT,
                 font=font("micro")).pack(anchor="w", pady=(2, 0))
        # What this password opens, in the one place that says it (#170). Two
        # of these rows are captioned with an action that describes itself and
        # three are not, and Change Host / Port sits directly above Server
        # Settings - an Admin deciding which of the two to hand out is reading
        # this line rather than guessing from the heading.
        tk.Label(pad, text="opens: " + S.CAPABILITY_REACH[cap], bg=CARD,
                 fg=FAINT, font=font("micro"), wraplength=470,
                 justify="left").pack(anchor="w", pady=(1, 0))
        hold = tk.Frame(pad, bg=CARD)
        hold.pack(fill="x", pady=(6, 0))
        tk.Label(hold, text="Held by", bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(side="left", padx=(0, 6))
        who = tk.Entry(hold, bg=INPUT_BG, fg=TEXT, relief="flat",
                       font=font("body"), insertbackground=TEXT)
        who.pack(side="left", fill="x", expand=True, ipady=4)
        line = tk.Frame(pad, bg=CARD)
        line.pack(fill="x", pady=(6, 0))
        ent = tk.Entry(line, show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                       font=font("body"), insertbackground=TEXT)
        ent.pack(side="left", fill="x", expand=True, ipady=5)
        ui_kit.reveal(ent)
        tk.Button(line, text="Set", bg=ACCENT, fg="white",
                  font=font("strong"), relief="flat", cursor="hand2",
                  command=lambda c=cap: act(c, False),
                  activebackground=ACCENT2).pack(side="left", padx=(6, 0),
                                                 ipadx=10, ipady=4)
        tk.Button(line, text="Clear", bg=CARD2, fg=SUBTEXT,
                  font=font("body"), relief="flat", cursor="hand2",
                  command=lambda c=cap: act(c, True),
                  activebackground=LINE).pack(side="left", padx=(6, 0),
                                              ipadx=8, ipady=4)
        rows[cap] = (pill, ent, who)

    tk.Label(win, text="At least %d characters, and not the admin password - "
                       "that would look like a delegation while handing over "
                       "everything, and clearing it later would take nothing "
                       "away. The holder's name is written into every System "
                       "Log entry that password opens something with; it is "
                       "set with the password and cleared with it."
                       % S.CAPABILITY_MIN,
             bg=BG, fg=FAINT, font=font("micro"), wraplength=520,
             justify="left").pack(side="bottom", anchor="w", padx=18,
                                  pady=(2, 0))

    # Packed last and after that caption on purpose: `pack` serves a cavity in
    # the order it was filled, so a canvas taking the room before the caption
    # went in is the caption getting whatever is left, which is nothing. Every
    # pinned child of this window is packed before this line.
    bar.pack(side="right", fill="y", padx=(0, 6), pady=(8, 0))
    canvas.pack(side="left", fill="both", expand=True, padx=(18, 0),
                pady=(8, 0))

    def size_body():
        """How much height the canvas gets: the form's, or what the screen has.

        Manage Users' helper, for its reason and asked the same way - laid
        flat, the window reports what everything *but* the list needs, and what
        is left of the screen is what the list may have. So a server with four
        capabilities gets a window exactly as tall as its form with nothing to
        scroll, and a fifth lengthens the scroll rather than the window.
        """
        canvas.configure(height=1)
        win.update_idletasks()
        chrome = win.winfo_reqheight() - 1
        room = win.winfo_screenheight() - 80 - chrome
        canvas.configure(height=max(160, min(body.winfo_reqheight(), room)))

    def typed():
        """A capability password typed into a row that no Set was pressed on.

        The only unsaved state here: a Set writes through
        `_set_capability_password` at once and empties the field it wrote.
        """
        return [c for c in S.CAPABILITIES if rows[c][1].get()]

    def save_typed():
        for cap in typed():
            act(cap, False)
        return not typed()

    close = _track_unsaved(win, "Capability Passwords",
                           lambda: bool(typed()), save_typed)
    ui_kit.escape_closes(win, close)

    tk.Button(foot, text="Close", bg=CARD2, fg=SUBTEXT,
              font=font("body"), relief="flat", cursor="hand2", pady=7,
              command=close,
              activebackground=LINE).pack(side="right", padx=18, pady=12)

    size_body()
    # The width is handed to fit rather than left for it to measure, for Manage
    # Users' reason: a frame windowed into a canvas does not pass its request
    # up, so this window's own reqwidth is the canvas's configured width
    # whatever is inside it. 560 stays the floor it always was.
    ui_kit.fit(win, max(560, body.winfo_reqwidth() + 24 + bar.winfo_reqwidth()))
    repaint()


def manage_users(root):
    """The Engineers, the Admin and the Storekeeper - one window, three answers.

    The three are not the same kind of thing and this window does not pretend
    they are. An **Engineer** is a row in `team_members`, so it is managed here
    as one: added, removed, Auto-Approve, and which of the three states their
    Own Password is in. The **Admin** is not a user at all - it is one password
    hash in `admin_config.json` plus the capability passwords (ADR-0006), and
    nobody is named - so it is shown as what it is, next to the controls that
    change it. The **Storekeeper** is not a user either: `Storekeeper User` is the
    default value of a column on every Transaction, and the app is identified
    by its installation, which is what Connected Clients lists.

    Inventing a row for each of the last two would be a schema claiming three
    people exist where one credential and one install do, and every predicate
    that reads `team_members` today - the Engineer dropdowns, GET /members,
    Auto-Approve, the Notifier's own-profile read - would have to learn to skip
    two of its rows. Showing them as what they are costs nothing and lies about
    nothing.

    Own Passwords are **shown and set** here, on the Engineer's own card
    (A5). They were shown here and set in a window of its own until this
    ticket, which meant this card said which of the three states an Engineer
    was in and sent the Admin somewhere else to change it - two windows both
    wording "temporary until the Engineer replaces it", and one of them free
    to drift. The state is still derived from the table on every read rather
    than kept in a flag beside the widget.
    **Access Profile and Permissions are set here**, on the Engineer's own
    card: Default or Custom, and the per-Permission ticks a Custom profile
    grants. They were only ever editable from the *Storekeeper's* Add Engineer
    dialog - a client an Admin has to walk to another machine to reach, and
    which can only set them on the way in, so an Engineer already on the list
    could not be changed at all. What a Permission gates is what an Engineer's
    own client shows them, which makes it the Admin's decision and this the
    Admin's console. 013 took that form out of the Storekeeper, which now
    creates an Engineer - a name and Auto-Approve - and nothing more, so this
    is the only place a profile is set.

    The admin password is asked at the door - the Manage Users entry asks
    `_admin_again` on every open (096) - and not again here, so every write
    below reaches the register as `authorised_as="Admin (Server GUI)"`. This
    is deliberately not a fifth capability: whoever can add an Engineer, or clear
    one, can then be that Engineer at that Engineer's client, which is a second
    Admin rather than one delegated action - the reasoning ADR-0009 gives for
    setting an Own Password at all.

    Every write goes through `_save_member`, `_delete_member` or
    `_set_member_password`, the helpers POST /members and POST /members/delete
    go through, so this console and the wire cannot disagree about what a
    change means - and an Own Password set here is Temporary for the same
    reason it is over the wire, because it is the same helper that arms the
    flag. **There is deliberately no endpoint**,
    the same call Add Transaction, Modify, the Client commands and the Lookup
    Sheet made: the Admin at this console is the only actor.
    """
    from server_gui import S

    import tkinter as tk
    import tkinter.messagebox as mb
    from tkinter import ttk
    if ui_kit.raise_open("manage_users") is not None:
        return
    win = tk.Toplevel(root)
    ui_kit.single(win, "manage_users")
    win.title("Manage Users")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.transient(root)
    win.grab_set()

    hdr = tk.Frame(win, bg=ACCENT, height=44)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="👥  Manage Users", bg=ACCENT, fg="white",
             font=font("title")).pack(side="left", padx=14, pady=12)

    # Packed before the body and from the bottom, so Close is the first child
    # served rather than the last: pack gives a shortfall to whatever went in
    # last, and that is how four dialogs here came to have no usable button.
    foot = tk.Frame(win, bg=BG)
    foot.pack(side="bottom", fill="x")

    # Outside the scrolling canvas below, so it stays reachable at a glance
    # whatever the Engineer count is - adding one was the first thing done
    # in this window and used to be the last thing reachable in it, at the
    # bottom of a body with no bound. It opens a popup rather than growing
    # that body, so the scroll region stays a function of the Engineer count
    # and never of a form.
    addlink = tk.Frame(win, bg=BG)
    addlink.pack(fill="x", padx=18, pady=(10, 0))
    tk.Button(addlink, text="＋  Add an Engineer", bg=BG, fg=ACCENT, bd=0,
              font=font("strong"), relief="flat", cursor="hand2",
              activebackground=BG, activeforeground=ACCENT2,
              command=lambda: open_add_engineer()).pack(anchor="w")

    tk.Label(win, text="This system knows three kinds of people and they are "
                       "not the same kind of thing. An Engineer is a row, and "
                       "is added and removed here. The Admin is a password "
                       "rather than a person - nobody is named. The "
                       "Storekeeper is an installation, known by the machine "
                       "it checked in from.",
             bg=BG, fg=FAINT, font=font("micro"), wraplength=540,
             justify="left").pack(anchor="w", padx=18, pady=(10, 6))

    # msg, not err: every button here reports through it and most of what it
    # says is a success - the same reason Manage Users names its one msg.
    msg = tk.Label(win, text="", bg=BG, fg=DANGER, font=font("body"),
                   wraplength=540, justify="left")
    msg.pack(anchor="w", padx=18, pady=(6, 0))

    # The body scrolls, and this is the one window here that needs it to: its
    # form has no bound at all - a card per Engineer, each with a name, an Own
    # Password state, Auto-Approve, Remove and an Access Profile with a tick per
    # Permission - so four Engineers already asked for 1423px of height, 343px
    # more than a 1080p screen physically has. `fit`'s clamp then bit and pack
    # gave the shortfall to whatever went in last. The footer above is outside
    # this canvas and was packed before it, which is what keeps Close on the
    # screen however many Engineers there are: a control that scrolls away is
    # the same lost button one level down. The shape is `installer.py`'s, which
    # is where this repo already scrolls a body, rather than a second one.
    canvas = tk.Canvas(win, bg=BG, highlightthickness=0)
    # ttk rather than tk, like every other scrollbar in this file: the
    # Vertical.TScrollbar style is where this window's palette reaches one,
    # and a tk.Scrollbar would sit in the dark theme wearing the system grey.
    bar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y", padx=(0, 6), pady=(8, 0))
    canvas.pack(side="left", fill="both", expand=True, padx=(18, 0),
                pady=(8, 0))
    body = tk.Frame(canvas, bg=BG)
    body_window = canvas.create_window((0, 0), window=body, anchor="nw")

    def body_resized(_e=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def canvas_resized(e):
        # The form is kept as wide as the viewport, so the cards fill the
        # window as they did when they were packed straight into it - a frame
        # windowed into a canvas otherwise sits at whatever width it asked for.
        canvas.itemconfig(body_window, width=e.width)

    body.bind("<Configure>", body_resized)
    canvas.bind("<Configure>", canvas_resized)

    def wheel(e):
        canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    # Bound on this window, not with `bind_all` the way the installer can
    # afford to - that is one window in a process of its own, while this GUI
    # keeps a dozen and a global binding would outlive this one and fire into a
    # destroyed canvas. A widget's bindtags run through its own toplevel, so
    # this catches the wheel anywhere inside this window and nowhere else.
    win.bind("<MouseWheel>", wheel)

    def size_body():
        """How much height the canvas gets: the form's, or what the screen has.

        Asked for rather than written down, the same way the window's own size
        is. Laid flat, the window reports what everything *but* the list needs,
        and what is left of the screen is what the list may have. So a small
        team gets a window exactly as tall as its form with nothing to scroll,
        and a large one gets a window that stops at the screen instead of
        growing past it - which is the whole of the fix: the height this window
        asks for is now bounded by the viewport rather than by the number of
        Engineers. The 160px floor is for the screen too short even for that;
        there the footer packed first is still what keeps Close usable.
        """
        canvas.configure(height=1)
        win.update_idletasks()
        chrome = win.winfo_reqheight() - 1
        room = win.winfo_screenheight() - 80 - chrome
        canvas.configure(height=max(160, min(body.winfo_reqheight(), room)))

    def section(text):
        tk.Label(body, text=text, bg=BG, fg=SUBTEXT,
                 font=font("caption")).pack(anchor="w", pady=(4, 4))

    section("ENGINEERS  ·  rows in team_members")
    people = tk.Frame(body, bg=BG)
    people.pack(fill="x")

    # (StringVar, original name, id) per Engineer card, rebuilt on every
    # repaint() - the widgets themselves are, so a second copy kept beside
    # them would be the one that goes stale. Read by unsaved()/save_unsaved()
    # to hold a typed-but-not-renamed name to the same rule the Storekeeper
    # name field below is held to.
    rename_entries = []
    # {name: Entry} for the Own Password field on each card, cleared and
    # refilled by repaint() for the same reason rename_entries is. A password
    # typed against an Engineer and never Set is the second thing this window
    # can lose, and is what unsaved() reads it for.
    pw_entries = {}

    def do_rename(member_id, var, original):
        new_name = var.get().strip()
        if new_name == original:
            return True
        payload, status = S._rename_member(member_id, new_name, None,
                                          authorised_as="Admin (Server GUI)")
        if status >= 400:
            # Back to what the table holds, the same as every other refusal
            # on this card - a rejected edit did not happen.
            var.set(original)
            msg.config(text="✗  " + payload.get("error", "Refused"), fg=DANGER)
            return False
        moved = payload.get("transactions", 0)
        msg.config(text="✓  %s is now %s. %d Transaction%s and the Client "
                        "row moved with the name; the System Log keeps the "
                        "act under both spellings rather than being rewritten."
                        % (original, payload["name"], moved,
                           "" if moved == 1 else "s"), fg=SUCCESS)
        repaint()
        return True

    def toggle_auto(name, var):
        payload, status = S._save_member(name, None, bool(var.get()),
                                         authorised_as="Admin (Server GUI)")
        if status >= 400:
            # The tick goes back to what the table holds rather than staying on
            # what was clicked - the same thing the Storekeeper Cancel switch
            # does, and for the same reason: a refused change did not happen,
            # and a switch showing otherwise is the copy that lies.
            row = S._member_row(name)
            var.set(1 if row is not None and row["auto_approve"] else 0)
            msg.config(text="✗  " + payload.get("error", "Refused"), fg=DANGER)
            return
        if payload.get("auto_approve"):
            msg.config(text="✓  %s is Auto-Approve: their Transactions are "
                            "confirmed as they are recorded and no Notifier is "
                            "asked." % name, fg=SUCCESS)
        else:
            msg.config(text="✓  %s is no longer Auto-Approve: their "
                            "Transactions wait for their Notifier." % name,
                       fg=FAINT)

    def _perm_sentence(perms):
        """What a profile grants, in the words the checkboxes use.

        Read back off what the helper returned rather than off what was
        ticked: a Permission the server dropped - a name this console knows and
        that build does not - would otherwise be reported as granted.
        """
        if not perms:
            return "nothing beyond confirming and rejecting their own " \
                   "Transactions"
        return "; ".join(S.PERMISSION_LABELS.get(p, p).lower() for p in perms)

    def set_profile(name, auto_var, prof_var):
        """Default or Custom for one Engineer.

        `permissions` is deliberately not sent: the stored list survives a
        switch to Default and comes back when Custom does, which is what
        `_member_permissions` reads the column only on a Custom profile for -
        an Admin who switches an Engineer down and back does not have to
        remember what was ticked. `auto_approve` is sent because the helper has
        no _KEEP for it, and the tick on this card is what was last written.
        """
        want = "custom" if prof_var.get() == "custom" else "default"
        payload, status = S._save_member(name, None,
                                       bool(auto_var.get()), profile=want,
                                       authorised_as="Admin (Server GUI)")
        if status >= 400:
            row = S._member_row(name)
            prof_var.set((row["profile"] or "default")
                         if row is not None else "default")
            msg.config(text="✗  " + payload.get("error", "Refused"), fg=DANGER)
            return
        # Repainted rather than left as it is: the ticks appear or disappear
        # with the choice, so the card is a different height and the window has
        # to ask for its size again.
        repaint()
        if payload.get("profile") == "custom":
            msg.config(text="✓  %s is on a Custom profile, granting %s."
                            % (name, _perm_sentence(payload.get("permissions"))),
                       fg=SUCCESS)
        else:
            msg.config(text="✓  %s is on the Default profile: %s. What was "
                            "ticked is kept and comes back with Custom."
                            % (name, _perm_sentence(())), fg=FAINT)

    def set_perms(name, auto_var, perm_vars):
        """The ticks on one Custom profile, written as one statement.

        Every box is sent each time rather than the one that moved, because
        that is the shape `_save_member` takes - a list of what is granted -
        and a per-box write would have to read the others back off the row
        anyway.
        """
        asked = [p for p in S.PERMISSIONS if perm_vars[p].get()]
        payload, status = S._save_member(name, None,
                                       bool(auto_var.get()),
                                       profile="custom", permissions=asked,
                                       authorised_as="Admin (Server GUI)")
        if status >= 400:
            # Back to what the table holds, for the reason toggle_auto gives.
            row = S._member_row(name)
            live = S._member_permissions(row) if row is not None else []
            for p, v in perm_vars.items():
                v.set(1 if p in live else 0)
            msg.config(text="✗  " + payload.get("error", "Refused"), fg=DANGER)
            return
        # No repaint: nothing appeared or disappeared, and rebuilding the card
        # under the box that was just clicked would take the focus with it.
        msg.config(text="✓  %s's Custom profile grants %s. It changes what "
                        "their own Notifier shows them; every write is still "
                        "checked on the server."
                        % (name, _perm_sentence(payload.get("permissions"))),
                   fg=SUCCESS)

    def set_own_password(name, clear):
        """Set or clear one Engineer's Own Password, on their own card.

        Through `_set_member_password`, the enforcement point POST /members'
        `member_password` field goes through as well, so a password set at
        this console and one set over the wire cannot come to mean different
        things - an Admin sets a **Temporary** one either way, and the flag is
        armed by that one helper rather than by whichever door called it
        (ADR-0009).

        Behind the admin password at this window's door like everything else
        on it, and deliberately not a fifth Capability, for the reason the docstring
        above gives: whoever can set an Engineer's Own Password can then open
        that Engineer's Settings as them, which is a second Admin rather than
        one delegated action.
        """
        payload, status = S._set_member_password(
            name, "" if clear else pw_entries[name].get(), None,
            authorised_as="Admin (Server GUI)")
        if status >= 400:
            msg.config(text="✗  " + payload.get("error", "Refused"), fg=DANGER)
            return False
        # Emptied before the repaint below, which destroys the field this is
        # reading: the card is rebuilt from the table on every repaint, so
        # what clears the box is doing it while the box is still there.
        pw_entries[name].delete(0, "end")
        # Repainted rather than the pill poked, so the three-state display in
        # front of the Admin is read off the table that was just written and
        # can never be the copy that goes stale.
        repaint()
        if payload.get("status") == "cleared":
            msg.config(text="✓  %s now has no Own Password. Nothing changes "
                            "about their Transactions, and the admin password "
                            "still opens their Settings." % name, fg=FAINT)
        else:
            msg.config(text="✓  %s has a temporary Own Password, and will be "
                            "made to replace it the first time they use it."
                            % name, fg=SUCCESS)
        return True

    def remove(name):
        if not mb.askyesno("Delete Engineer",
                           "Remove %s from the Engineer list?\n\n"
                           "Their Transactions are kept exactly as they are - "
                           "the name is stored on every one of them. What goes "
                           "is the list they can be picked from, and their Own "
                           "Password with the row." % name, parent=win):
            return
        payload, status = S._delete_member(
            name, None, authorised_as="Admin (Server GUI)")
        if status >= 400:
            msg.config(text="✗  " + payload.get("error", "Refused"), fg=DANGER)
            return
        repaint()
        msg.config(text="✓  %s is off the Engineer list. Their Transactions "
                        "are untouched." % name, fg=FAINT)

    def engineer_card(r):
        name = r["name"]
        box = tk.Frame(people, bg=CARD, highlightthickness=1,
                       highlightbackground=LINE)
        box.pack(fill="x", pady=(0, 8))
        pad = tk.Frame(box, bg=CARD, padx=14, pady=9)
        pad.pack(fill="x")
        top = tk.Frame(pad, bg=CARD)
        top.pack(fill="x")
        # Editable on M1's id (#117): a name is a label rather than a key,
        # so correcting one is `_rename_member`, not a delete and an add.
        # Tracked in rename_entries rather than written on every keystroke -
        # the same reason the Storekeeper's own name field below is a Save,
        # not a live write.
        name_var = tk.StringVar(value=name)
        name_entry = tk.Entry(top, textvariable=name_var, bg=CARD, fg=TEXT,
                              relief="flat", bd=0, insertbackground=TEXT,
                              font=font("heading"))
        name_entry.pack(side="left", fill="x", expand=True)
        rename_entries.append((name_var, name, r["id"]))
        tk.Button(top, text="Rename", bg=CARD2, fg=SUBTEXT,
                  font=font("micro"), relief="flat", cursor="hand2",
                  command=lambda mid=r["id"], v=name_var, o=name:
                      do_rename(mid, v, o),
                  activebackground=LINE).pack(side="left", padx=(6, 6))
        name_entry.bind("<Return>", lambda e, mid=r["id"], v=name_var,
                        o=name: do_rename(mid, v, o))
        # Three states, read off the row each time this is built rather than
        # kept in a flag beside the widget: the copy in a widget is the one
        # that goes stale. Shown here and, since A5, set here too - by the
        # Set and Clear below, which is the whole of what the window this
        # replaced did.
        if not r["password_hash"]:
            state, colour = "no own password", FAINT
        elif r["must_change_password"]:
            state, colour = "temporary · must be replaced", WARNING
        else:
            state, colour = "own password set by the Engineer", SUCCESS
        tk.Label(top, text=state, bg=CARD, fg=colour,
                 font=font("caption")).pack(side="right")
        tk.Label(pad, text="Renaming rewrites this Engineer's Transactions "
                           "and Client row to the new spelling. The System "
                           "Log is never rewritten - it keeps the act under "
                           "both names.",
                 bg=CARD, fg=FAINT, font=font("micro"), wraplength=470,
                 justify="left").pack(anchor="w", pady=(2, 0))
        line = tk.Frame(pad, bg=CARD)
        line.pack(fill="x", pady=(6, 0))
        var = tk.IntVar(value=1 if r["auto_approve"] else 0)
        tk.Checkbutton(line, text="Auto-Approve  ·  no Notifier, Transactions "
                                  "confirmed as they are recorded",
                       variable=var,
                       command=lambda n=name, v=var: toggle_auto(n, v),
                       bg=CARD, fg=SUBTEXT, selectcolor=INPUT_BG,
                       activebackground=CARD, activeforeground=TEXT,
                       font=font("body")).pack(side="left")
        tk.Button(line, text="🗑  Remove", bg=CARD2, fg=DANGER,
                  font=font("body"), relief="flat", cursor="hand2",
                  command=lambda n=name: remove(n),
                  activebackground=LINE).pack(side="right", ipadx=8, ipady=4)

        # The Own Password, set where its state is already shown. The state
        # pill above is the display half of this pair and they are deliberately
        # on one card: a window that showed which of three states a password
        # was in while another window set it is two places wording the same
        # sentence about what Temporary means.
        pwline = tk.Frame(pad, bg=CARD)
        pwline.pack(fill="x", pady=(7, 0))
        tk.Label(pwline, text="Own Password", bg=CARD, fg=SUBTEXT,
                 font=font("caption")).pack(side="left", padx=(0, 8))
        pw_e = tk.Entry(pwline, show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                        font=font("body"), insertbackground=TEXT)
        pw_e.pack(side="left", fill="x", expand=True, ipady=5)
        ui_kit.reveal(pw_e)
        tk.Button(pwline, text="Set", bg=ACCENT, fg="white",
                  font=font("strong"), relief="flat", cursor="hand2",
                  command=lambda n=name: set_own_password(n, False),
                  activebackground=ACCENT2).pack(side="left", padx=(6, 0),
                                                 ipadx=10, ipady=4)
        tk.Button(pwline, text="Clear", bg=CARD2, fg=SUBTEXT,
                  font=font("body"), relief="flat", cursor="hand2",
                  command=lambda n=name: set_own_password(n, True),
                  activebackground=LINE).pack(side="left", padx=(6, 0),
                                              ipadx=8, ipady=4)
        pw_entries[name] = pw_e
        tk.Label(pad, text="Lets this Engineer open their own Notifier "
                           "Settings; it opens nothing here and nothing of "
                           "anybody else's. One you set is temporary - they "
                           "are made to replace it the first time they use "
                           "it - so this is also how a forgotten one is "
                           "reset. At least %d characters, the same bound the "
                           "admin password is held to. Clearing one takes "
                           "nothing else away: the admin password still opens "
                           "their Settings, and their Transactions are "
                           "untouched either way." % S.PASSWORD_MIN,
                 bg=CARD, fg=FAINT, font=font("micro"), wraplength=470,
                 justify="left").pack(anchor="w", pady=(4, 0))

        # Access Profile. Read off the row each time the card is built, like
        # the Own Password state above and for the same reason.
        prof = (r["profile"] or "default")
        pline = tk.Frame(pad, bg=CARD)
        pline.pack(fill="x", pady=(7, 0))
        tk.Label(pline, text="Access Profile", bg=CARD, fg=SUBTEXT,
                 font=font("caption")).pack(side="left", padx=(0, 8))
        prof_var = tk.StringVar(value="custom" if prof == "custom"
                                else "default")
        for value, label in (("default", "Default"), ("custom", "Custom")):
            tk.Radiobutton(pline, text=label, value=value, variable=prof_var,
                           command=lambda n=name, a=var, p=prof_var:
                               set_profile(n, a, p),
                           bg=CARD, fg=SUBTEXT, selectcolor=INPUT_BG,
                           activebackground=CARD, activeforeground=TEXT,
                           font=font("body")).pack(side="left", padx=(0, 6))

        if prof != "custom":
            tk.Label(pad, text="Grants nothing beyond confirming and rejecting "
                               "their own Transactions. Custom shows the "
                               "Permissions to tick.",
                     bg=CARD, fg=FAINT, font=font("micro"), wraplength=470,
                     justify="left").pack(anchor="w", pady=(4, 0))
            return

        granted = S._member_permissions(r)
        perm_vars = {}
        pbox = tk.Frame(pad, bg=CARD)
        pbox.pack(fill="x", pady=(4, 0))
        # Looped over PERMISSIONS, not over the label table: rule 8 keeps the
        # list in one place, and a name with no label here is still offered as
        # itself rather than silently missing from the form.
        for p in S.PERMISSIONS:
            pv = tk.IntVar(value=1 if p in granted else 0)
            perm_vars[p] = pv
            tk.Checkbutton(pbox, text=S.PERMISSION_LABELS.get(p, p), variable=pv,
                           command=lambda n=name, a=var, pvs=perm_vars:
                               set_perms(n, a, pvs),
                           bg=CARD, fg=SUBTEXT, selectcolor=INPUT_BG,
                           activebackground=CARD, activeforeground=TEXT,
                           font=font("body")).pack(anchor="w")

    def open_add_engineer():
        """Add one Engineer, in a popup rather than the scrolling body.

        It was a card at the bottom of ENGINEERS until this ticket: adding
        one is the first thing done in this window, and was the last thing
        reachable in it once the list grew past a screen. A popup keeps the
        scroll region a function of the Engineer count and never of a form.

        Asks for no password: the door in front of the parent window already
        took the admin password (096), and a field here would just be a
        second place to type it.
        """
        dlg = tk.Toplevel(win)
        dlg.title("Add an Engineer")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(win)
        dlg.grab_set()

        hdr2 = tk.Frame(dlg, bg=ACCENT, height=44)
        hdr2.pack(fill="x")
        hdr2.pack_propagate(False)
        tk.Label(hdr2, text="＋  Add an Engineer", bg=ACCENT, fg="white",
                 font=font("title")).pack(side="left", padx=14,
                                                     pady=12)

        # Packed before the body, from the bottom, for the reason every
        # other dialog in this file is.
        foot2 = tk.Frame(dlg, bg=BG)
        foot2.pack(side="bottom", fill="x")

        body2 = tk.Frame(dlg, bg=BG, padx=18, pady=12)
        body2.pack(fill="both", expand=True)
        tk.Label(body2, text="Name", bg=BG, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w")
        dlg_name_e = tk.Entry(body2, bg=INPUT_BG, fg=TEXT, relief="flat",
                              font=font("value"), insertbackground=TEXT)
        dlg_name_e.pack(fill="x", ipady=6, pady=(2, 8))
        dlg_auto = tk.IntVar(value=0)
        tk.Checkbutton(body2, text="Auto-Approve  ·  no Notifier, "
                                  "Transactions confirmed as they are "
                                  "recorded",
                       variable=dlg_auto, bg=BG, fg=SUBTEXT,
                       selectcolor=INPUT_BG, activebackground=BG,
                       activeforeground=TEXT,
                       font=font("body")).pack(anchor="w")
        dlg_msg = tk.Label(dlg, text="", bg=BG, fg=DANGER,
                          font=font("body"), wraplength=380,
                          justify="left")
        dlg_msg.pack(in_=body2, anchor="w", pady=(8, 0))

        def do_add():
            name = dlg_name_e.get().strip()
            # An existing name is refused rather than written: _save_member
            # would take it as an update and quietly set that Engineer's
            # Auto-Approve to whatever this tick happens to say.
            if name and S._member_row(name) is not None:
                dlg_msg.config(text="✗  %s is already on the Engineer "
                                    "list. Auto-Approve is the tick on "
                                    "their card." % name, fg=DANGER)
                return
            payload, status = S._save_member(
                name, None, bool(dlg_auto.get()),
                authorised_as="Admin (Server GUI)")
            if status >= 400:
                dlg_msg.config(text="✗  " + payload.get("error", "Refused"),
                              fg=DANGER)
                return
            dlg_name_e.delete(0, "end")
            repaint()
            msg.config(text="✓  %s is on the Engineer list and can be "
                            "picked in the Storekeeper. They start on the "
                            "Default profile, which is changed on their "
                            "card, and with no Own Password - which is "
                            "optional, and is set on that card too."
                            % payload["name"], fg=SUCCESS)
            dlg_close()

        def dlg_unsaved():
            return bool(dlg_name_e.get().strip())

        def dlg_save_unsaved():
            if dlg_name_e.get().strip():
                do_add()
            return not dlg_unsaved()

        dlg_close = _track_unsaved(dlg, "Add an Engineer", dlg_unsaved,
                                   dlg_save_unsaved)
        ui_kit.escape_closes(dlg, dlg_close)

        tk.Button(foot2, text="Add", bg=ACCENT, fg="white",
                  font=font("strong"), relief="flat", cursor="hand2",
                  command=do_add,
                  activebackground=ACCENT2).pack(side="right", padx=18,
                                                 pady=12, ipadx=14, ipady=5)
        tk.Button(foot2, text="Cancel", bg=CARD2, fg=SUBTEXT,
                  font=font("body"), relief="flat", cursor="hand2",
                  command=dlg_close,
                  activebackground=LINE).pack(side="right", pady=12,
                                             ipadx=10, ipady=5)

        ui_kit.fit(dlg, 420)
        dlg_name_e.focus_set()


    section("ADMIN  ·  a password, not a person")
    admf = tk.Frame(body, bg=CARD, highlightthickness=1,
                    highlightbackground=LINE)
    admf.pack(fill="x", pady=(0, 8))
    admpad = tk.Frame(admf, bg=CARD, padx=14, pady=9)
    admpad.pack(fill="x")
    tk.Label(admpad, text="Admin", bg=CARD, fg=TEXT,
             font=font("heading")).pack(anchor="w")
    adm_lbl = tk.Label(admpad, text="", bg=CARD, fg=SUBTEXT,
                       font=font("micro"), wraplength=480, justify="left")
    adm_lbl.pack(anchor="w", pady=(4, 6))

    def admin_line():
        # Derived from the map each time it is read, for the reason Capability
        # Passwords derives it: a count kept beside the widget is the copy
        # that is wrong the moment a delegation is made there - reached from
        # the console this window opened from, not from a button here.
        delegated = sum(1 for on in _capability_state().values() if on)
        return ("One password on this server. Nobody is named and there is no "
                "row to add or remove - it opens every action on this console "
                "and every admin endpoint. Changed from Change Admin "
                "Password, and delegated from Capability Passwords - both "
                "sibling entries in the console this window opened from. "
                "%d of the four delegable actions %s a password of their own."
                % (delegated, "has" if delegated == 1 else "have"))

    section("STOREKEEPER  ·  an installation with a name, not a login")
    skf = tk.Frame(body, bg=CARD, highlightthickness=1,
                   highlightbackground=LINE)
    skf.pack(fill="x", pady=(0, 8))
    skpad = tk.Frame(skf, bg=CARD, padx=14, pady=9)
    skpad.pack(fill="x")
    tk.Label(skpad, text="Storekeeper", bg=CARD, fg=TEXT,
             font=font("heading")).pack(anchor="w")
    tk.Label(skpad, text="Not a user. The app is known by the installation "
                         "that checked in rather than by a login, and the "
                         "Storekeeper is never the recipient of a Transaction "
                         "- so there is no row here to add or remove, and "
                         "nothing to set a password on. What there is, is a "
                         "name: it goes in the storekeeper column of every "
                         "Transaction that installation records, and the "
                         "System Log attributes the act to \"<name> "
                         "(Storekeeper)\". Which installations exist, and "
                         "when each was last heard from, is Connected "
                         "Clients, another entry in the console this window "
                         "opened from.",
             bg=CARD, fg=SUBTEXT, font=font("micro"), wraplength=480,
             justify="left").pack(anchor="w", pady=(4, 6))

    tk.Label(skpad, text="Name", bg=CARD, fg=SUBTEXT,
             font=font("micro")).pack(anchor="w")
    skrow = tk.Frame(skpad, bg=CARD)
    skrow.pack(fill="x", pady=(2, 6))
    sk_e = tk.Entry(skrow, bg=INPUT_BG, fg=TEXT, relief="flat",
                    insertbackground=TEXT, font=font("value"))
    sk_e.pack(side="left", fill="x", expand=True, ipady=5)
    sk_e.insert(0, S._storekeeper_name())

    def save_sk_name():
        """Rename the Storekeeper. Behind this window's door, like everything here.

        Not a fifth Capability, for the reason the rest of this window gives. It writes through `_save_server_cfg`, which is the
        one writer of that file and logs the change itself.

        An empty name is refused rather than stored: the fallback exists for a
        file written before this key did, and clearing the field to reach it
        would be an admin asking for a name they cannot see. Rows already
        recorded are untouched - the name on a Transaction is what it was
        recorded under, and rewriting history to match a new name is the one
        thing this must not do.
        """
        wanted = sk_e.get().strip()
        if not wanted:
            msg.config(text="✗  The Storekeeper needs a name. Transactions "
                            "already recorded keep the name they were recorded "
                            "under either way.", fg=DANGER)
            return
        S._save_server_cfg(storekeeper_name=wanted)
        msg.config(text="✓  The Storekeeper is %s. New Transactions are "
                        "recorded under that name and the System Log reads "
                        "\"%s\". Transactions already recorded keep the name "
                        "they were recorded under."
                        % (wanted, S._storekeeper_actor(wanted)), fg=SUCCESS)

    tk.Button(skrow, text="Save", bg=ACCENT, fg="white",
              font=font("strong"), relief="flat", cursor="hand2",
              command=save_sk_name).pack(side="left", padx=(8, 0),
                                         ipadx=12, ipady=4)

    add_var = tk.IntVar(value=1 if S._storekeeper_can_add_engineer() else 0)

    def toggle_add_engineer():
        """Flip whether the Storekeeper may create an Engineer (ADR-0017).

        On this card rather than beside the Cancel switch, for the adjacency
        the rest of this window keeps: what it changes is who may add a row to
        the list above, so it belongs in the window that list is in. It shares
        the Cancel switch's rule rather than its place - both directions ask,
        switching it back on being as much a change as switching it off - and
        it asks with the password already typed at the top of this window
        rather than prompting again, which is what every other control here
        does.
        """
        wanted = bool(add_var.get())
        S._save_server_cfg(storekeeper_can_add_engineer=wanted)
        msg.config(text="\u2713  The Storekeeper %s add an engineer. Changing "
                        "one - the profile, the permissions, the own password "
                        "- is this window either way. Published on the "
                        "heartbeat, so that client picks it up on its next "
                        "poll; the server enforces it regardless."
                        % ("can now" if wanted else "can no longer"),
                   fg=SUCCESS)

    tk.Checkbutton(skpad, text="The Storekeeper may add an engineer",
                   variable=add_var, command=toggle_add_engineer, bg=CARD,
                   fg=SUBTEXT, selectcolor=INPUT_BG, activebackground=CARD,
                   activeforeground=TEXT,
                   font=font("body")).pack(anchor="w", pady=(2, 0))
    tk.Label(skpad, text="Creating only, and with no password of any kind on "
                         "the new row. What it hands over is the ability to "
                         "name somebody Transactions are then recorded "
                         "against - and a Transaction already needs no "
                         "credential at all (ADR-0002), so this is what stops "
                         "the store waiting on an admin to be able to name "
                         "who a movement was for.",
             bg=CARD, fg=SUBTEXT, font=font("micro"), wraplength=480,
             justify="left").pack(anchor="w", pady=(2, 4))

    tk.Label(skpad, text="Auto-approved transactions may be cancelled with no "
                         "password for (minutes)", bg=CARD, fg=SUBTEXT,
             font=font("micro")).pack(anchor="w", pady=(6, 0))
    winrow = tk.Frame(skpad, bg=CARD)
    winrow.pack(fill="x", pady=(2, 4))
    win_e = tk.Entry(winrow, bg=INPUT_BG, fg=TEXT, relief="flat", width=8,
                     insertbackground=TEXT, font=font("value"))
    win_e.pack(side="left", ipady=5)
    win_e.insert(0, str(S._storekeeper_cancel_window_mins()))

    def save_sk_window():
        """Set the auto-approve cancel window (#198).

        On this card rather than beside the Cancel switch in Manage
        Transaction History, for the adjacency the Add-Engineer switch above
        keeps: what it changes is what *this installation* may do without a
        credential, which is the subject of this card, and the Storekeeper's
        name is already set here.

        A whole number of minutes, and **0 is how it is switched off** rather
        than a tickbox beside a number: the file says off by one number, so the
        form says it by one number too, and there is no state where a written
        length and a flag disagree about whether it applies.

        Nothing outside `_storekeeper_cancel_window_mins`'s own reading is done
        here: a value it would read as off is refused on the form instead, so
        an Admin who typed something that is not a number is told rather than
        quietly given the closed answer.
        """
        raw = win_e.get().strip()
        try:
            mins = int(raw)
        except ValueError:
            msg.config(text="✗  A whole number of minutes, or 0 for no "
                            "window at all.", fg=DANGER)
            return
        if mins < 0:
            msg.config(text="✗  A window cannot be negative. 0 is no "
                            "window at all.", fg=DANGER)
            return
        S._save_server_cfg(storekeeper_cancel_window_mins=mins)
        msg.config(text=("✓  An auto-approved transaction can be "
                         "cancelled with no password for %d minute%s after it "
                         "was recorded. A transaction an engineer actually "
                         "confirmed still needs the admin password, whatever "
                         "the clock says." % (mins, "" if mins == 1 else "s"))
                   if mins else
                   ("✓  No window. Every confirmed transaction needs the "
                    "admin password to cancel, which is what this server did "
                    "before the setting existed."), fg=SUCCESS)

    tk.Button(winrow, text="Save", bg=ACCENT, fg="white",
              font=font("strong"), relief="flat", cursor="hand2",
              command=save_sk_window).pack(side="left", padx=(8, 0),
                                           ipadx=12, ipady=4)
    tk.Label(skpad, text="An Auto-Approve engineer has no Notifier and is "
                         "never asked, so a transaction against one is "
                         "Confirmed a millisecond after the scan - and "
                         "undoing that mis-scan then needed the admin "
                         "password, where every other engineer's is a pill in "
                         "the Storekeeper's own window. This is that window, "
                         "in minutes. It widens what a cancel with no "
                         "password reaches; it is not a way round the switch "
                         "above, which still answers first.",
             bg=CARD, fg=SUBTEXT, font=font("micro"), wraplength=480,
             justify="left").pack(anchor="w", pady=(2, 4))

    def refresh_admin():
        adm_lbl.config(text=admin_line())

    def repaint():
        for child in people.winfo_children():
            child.destroy()
        rename_entries.clear()
        pw_entries.clear()
        rows = S._member_rows()
        if not rows:
            tk.Label(people, text="No Engineers yet. The first one is added "
                                  "below.",
                     bg=BG, fg=SUBTEXT, font=font("body"),
                     wraplength=520, justify="left").pack(anchor="w",
                                                          pady=(0, 8))
        for r in rows:
            engineer_card(r)
        refresh_admin()
        # Asked again rather than once, which is the one thing fit's "call it
        # once" assumes: this window's children change while it is open, so a
        # size taken at build time would be a row short the moment an Engineer
        # is added, and the row it lost would be the last one. The viewport is
        # re-asked first, so what fit is told about is the scrolling body's
        # height rather than the list's: an Engineer added past the screen
        # lengthens the scroll, not the window.
        size_body()
        # The width is handed to fit rather than left for it to measure: a
        # frame windowed into a canvas does not pass its request up, so this
        # window's own reqwidth is now the canvas's configured width whatever
        # is inside it, and a card wider than the viewport would be clipped
        # instead of widening the window - the only scrollbar here is vertical.
        # 560 stays the floor it always was.
        ui_kit.fit(win, max(560, body.winfo_reqwidth() + 24
                            + bar.winfo_reqwidth()))

    def unsaved():
        """An Engineer's name edited and not yet renamed, or the
        Storekeeper's.

        Or an Own Password typed against one and never Set (A5), which
        came here with the window that used to hold it - Set writes through
        `_set_member_password` at once and empties the field, so a field
        with anything in it is a password that has not been set.

        Adding an Engineer moved to its own popup, tracked there rather
        than here - this window no longer holds a typed-but-unadded name
        at all. Auto-Approve, the Access Profile and the Permission ticks
        are not in here and cannot be: each of those writes through
        `_save_member` the moment it is clicked, so there is no moment at
        which one of them is unsaved.
        """
        for var, original, _mid in rename_entries:
            if var.get().strip() and var.get().strip() != original:
                return True
        if any(e.get() for e in pw_entries.values()):
            return True
        if win_e.get().strip() != str(S._storekeeper_cancel_window_mins()):
            return True
        return sk_e.get().strip() != S._storekeeper_name()

    def save_unsaved():
        ok_all = True
        for var, original, mid in list(rename_entries):
            if var.get().strip() and var.get().strip() != original:
                if not do_rename(mid, var, original):
                    ok_all = False
        # Names before passwords: a rename repaints, and a repaint rebuilds
        # every card, so reading the password fields first would be reading
        # widgets that a later rename is about to destroy.
        for name in [n for n, e in pw_entries.items() if e.get()]:
            if name in pw_entries and not set_own_password(name, False):
                ok_all = False
        if win_e.get().strip() != str(S._storekeeper_cancel_window_mins()):
            save_sk_window()
        if sk_e.get().strip() != S._storekeeper_name():
            save_sk_name()
        return ok_all and not unsaved()

    close = _track_unsaved(win, "Manage Users", unsaved, save_unsaved)
    ui_kit.escape_closes(win, close)

    tk.Button(foot, text="Close", bg=CARD2, fg=SUBTEXT,
              font=font("body"), relief="flat", cursor="hand2", pady=7,
              command=close,
              activebackground=LINE).pack(side="right", padx=18, pady=(0, 12))

    repaint()          # builds the Engineer cards, and asks for the size
