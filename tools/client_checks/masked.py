r"""Every masked field on the three apps, and the toggle that shows it
(#202).

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
from client_checks.stage import (IN, NR, NT, SK, bad, close, eq, head, ok,
                                 opened, quiesce, tk_or_skip, widgets)


def masked_entries(tk, win):
    """Every `tk.Entry` under win that is masking what is typed into it."""
    return [w for w in widgets(win)
            if isinstance(w, tk.Entry) and str(w.cget("show"))]


def toggle_of(tk, entry):
    """The control `ui_kit.reveal` placed inside this entry, or None.

    A child of the entry rather than a sibling, which is the whole of why one
    helper served every call site laid out with `pack` and with `grid` alike,
    and why not one of them had to change its geometry manager.
    """
    for c in entry.winfo_children():
        if isinstance(c, tk.Label):
            return c
    return None


def reveals(tk, label, entry):
    """One masked field unmasks on a real click and re-masks on the next."""
    mask = str(entry.cget("show"))
    # `event_generate` queues the event (`-when tail`), and
    # `update_idletasks` runs idle work without draining that queue -
    # so the click has to be pumped with a full `update` or the field
    # is read back before the binding has run at all.
    lab = toggle_of(tk, entry)
    if lab is None:
        bad("%s has a masked field with no show toggle on it" % label)
        return False
    if not lab.winfo_ismapped():
        # Tk discards a pointer event generated at an unmapped window, so a
        # click here would be measuring nothing and passing. Said outright
        # rather than skipped: a field this could not be driven at is a field
        # this group did not cover.
        bad("%s: the toggle is not on screen, so no click could be driven "
            "at it" % label)
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


def check_every_client_password_field_can_be_shown():
    """Every masked field on these three apps carries the toggle (#202).

    Driven on the real windows rather than read off the source, because what
    is being asserted is a widget inside another widget: `ui_kit.reveal` places
    its control **inside** the `tk.Entry`, so a source read would see the call
    and not whether the control is there, wired, and putting the mask back.

    Three things per field, and the third is the one a toggle gets wrong: it
    opens **masked**, it unmasks on a real click on the control rather than on
    a call to a handler behind it, and clicking again puts back **the field's
    own** mask - read off the entry rather than assumed, so the one site that
    masks with `\u2022` rather than the `\u25cf` the other twenty-seven use
    round-trips rather than being quietly restyled. A field that unmasks and
    stays unmasked is worse than no toggle at all, these being windows opened
    on somebody else's desk.

    The installer's three forms are each measured, since the component radio
    rebuilds the form under it and the two password fields of a Server install
    exist only on one of the three.

    The counts are asserted rather than left implicit: a group that walks every
    window and finds no masked field passes by finding nothing, which is this
    file's own standing complaint about a check that cannot fail.
    """
    head("every client password field can be shown (#202)")
    tk = tk_or_skip()
    if tk is None:
        return

    seen = 0

    # -- the Storekeeper -----------------------------------------------------
    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = SK.StorekeeperApp(root)
    root.update_idletasks()
    root.update()

    row = {"id": 1, "asset_number": "IT-0001", "serial_number": "SN-1",
           "asset_type": "Laptop", "team_member": "Brian Dawson",
           "direction": "Out Store", "rejected": 0, "confirmed": 1,
           "timestamp": "x"}

    def cancel_confirmed():
        app._all_rows = [dict(row)]
        app._selected_row = lambda: app._all_rows[0]
        app._cancel_selected()

    for label, opener in (("the Storekeeper's Admin Login", app._open_settings),
                          ("the Storekeeper's Cancel Transaction",
                           cancel_confirmed)):
        wins = opened(tk, root, label, opener)
        for w in wins:
            for ent in masked_entries(tk, w):
                seen += 1
                reveals(tk, label, ent)
        close(root, wins)
    quiesce(root)

    # -- the Notifier --------------------------------------------------------
    napp = NT.NotifierApp()
    nroot = napp.root
    nroot.deiconify()
    nroot.update_idletasks()
    nroot.update()

    plan = [
        ("the Notifier's logon window", napp._show_setup_wizard),
        ("Change My Password",
         lambda: NT.OwnPasswordWindow(nroot, "http://127.0.0.1:1",
                                      "Brian Dawson")),
        ("Remote Admin, locked",
         lambda: NR.RemoteAdminWindow(nroot, "http://127.0.0.1:1")),
    ]
    # One panel at a time rather than `opens=NR.REMOTE_PANELS`: this window
    # shows one panel and keeps the rest unmapped, and a click generated at an
    # unmapped widget is discarded by Tk - so the whole-window opening reads a
    # field that was never clicked.
    for panel in NR.REMOTE_PANELS:
        plan.append(("Remote Admin, %s" % panel,
                     lambda p=panel: NR.RemoteAdminWindow(
                         nroot, "http://127.0.0.1:1", opens=[p],
                         config={"host": "0.0.0.0", "port": 8081})))
    for label, opener in plan:
        wins = opened(tk, nroot, label, opener)
        for w in wins:
            for ent in masked_entries(tk, w):
                seen += 1
                reveals(tk, label, ent)
        close(nroot, wins)
    napp.running = False
    quiesce(nroot)

    # -- the installer -------------------------------------------------------
    iroot = tk.Tk()
    iapp = IN.InstallerApp(iroot)
    for component in ("notifier", "storekeeper", "server"):
        iapp.v_component.set(component)
        iapp._on_component_change()
        iroot.update_idletasks()
        label = "Setup, %s selected" % component
        for ent in masked_entries(tk, iroot):
            seen += 1
            reveals(tk, label, ent)
    quiesce(iroot)

    if seen:
        ok("every one of the %d masked fields these windows open with carries "
           "the toggle and puts its own mask back" % seen)
    else:
        bad("no masked field was found at all, so nothing was measured")


def check_the_remote_mail_password_opens_empty():
    """The one replayable secret a client can set is never shown one (#202).

    `smtp_secret.dat` is a secret the **server** holds rather than checks
    (ADR-0013), and the property it exists to have is that nothing reads it
    back: `GET /admin/mail` answers *whether* a password is stored and never
    what it is. So the Remote Admin Mail panel is never told either, its field
    opens **empty**, and the toggle beside it can only ever show what somebody
    typed a moment ago - which is the sharpest case of what #202 is, this being
    the one on the network.

    Driven against an answer saying a password **is** stored, since an empty
    field on a server holding none is the answer either way and would pass a
    panel that had been handed the secret.
    """
    head("the remote Mail panel's password opens empty (#202)")
    tk = tk_or_skip()
    if tk is None:
        return

    def answer(method, path, payload=None, **kw):
        if path == "/admin/mail":
            return {"host": "relay.example", "port": 587,
                    "from": "assets@example", "username": "assets",
                    "starttls": True, "password_stored": True,
                    "can_store": True}
        return {}

    real = NR.api
    app = NT.NotifierApp()
    root = app.root
    root.deiconify()
    root.update_idletasks()
    try:
        NR.api = answer
        wins = opened(tk, root, "Remote Admin, Mail",
                      lambda: NR.RemoteAdminWindow(
                          root, "https://127.0.0.1:1",
                          opens=["mail"], config={}))
        fields = []
        for w in wins:
            fields.extend(masked_entries(tk, w))
        if not fields:
            bad("the Mail panel opened no masked field, so nothing was "
                "measured")
        for ent in fields:
            eq("the SMTP password field opens empty, whatever is stored",
               ent.get(), "")
            lab = toggle_of(tk, ent)
            if lab is None:
                bad("the SMTP password field carries no toggle")
                continue
            lab.event_generate("<Button-1>", x=2, y=2)
            root.update()
            eq("  and revealing it shows nothing, this panel never having "
               "been told what is stored", ent.get(), "")
        close(root, wins)
    finally:
        NR.api = real
        app.running = False
        quiesce(root)
