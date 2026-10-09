"""The Notifier's Remote Admin surface - the console an engineer opens from
their own tray icon, gated by a capability password (rule 8, ADR-0006,
ADR-0015).

Lifted out of notifier_app.py by #218 (044): 2,247 lines that were one concern
with one caller - the tray menu - and nothing else reaching into them. The move
is verbatim: no window changes size, no dialog changes wording, no panel asks
the server anything it did not ask before.

``notifier_remote`` cannot import ``notifier_app`` the way an ordinary module
would. Source mode runs notifier_app.py as ``__main__`` through
``runpy.run_path`` (``applaunch.py``, ``docs/runbooks/source-mode.md``), so an
``import notifier_app`` in here would start a **second** tray client - its own
poll loop, its own tray icon, its own popups against the same engineer - rather
than reach the one already running. #206 hit that wall for ``server_cert.py``
and #207 for ``server_gui.py``, and this module takes the second of the two
shapes they set: ``bind()`` stores the **module object itself**, and every name
that stays defined in notifier_app.py is written ``N.<name>``, looked up on
that live module at call time. So a check that does ``NT.fetch_members = spy``,
or a Settings save that goes through ``NT.save_config``, is seen here exactly
as it was before the move, because ``N`` and ``NT`` are the same object.

The colours are the one thing not reached that way, and deliberately.
``ui_kit.Theme`` binds the palette into **an app's module globals** - that is
what the class is for, and it is the reason the several hundred widget
constructions below can say ``bg=BG`` at all. Those names are written down
nowhere in notifier_app.py; they are put into its globals at runtime out of
``ui_kit.DARK``, so ``N.BG`` would be reaching through one module's namespace
for a value that belongs to neither of them. ``bind()`` seeds this module's
globals from the palette that is live and hands that same seeding to
``THEME.watch()``, which the Theme already runs after every swap - so a theme
change repaints an open Remote Admin window, and a window opened after one is
born in the palette that is current, both exactly as before the move.
"""

import base64
import os
import tkinter as tk
from tkinter import filedialog, ttk

import ui_kit
from common import api, log_event
# The faces rather than the colours. A theme switch never moves a face - which
# is why ``ui_kit.Theme`` seeds this one name once and never rebinds it - so it
# is an ordinary import here rather than something ``_bind_palette`` below has
# to keep up to date.
from ui_kit import font

N = None


def bind(notifier_module):
    """Give this module the running notifier_app.py, and the palette with it.

    Called once, at import, from notifier_app.py itself - ``import
    notifier_remote; notifier_remote.bind(sys.modules[__name__])``, written
    under the ``THEME`` this reaches for rather than under the import. What is
    bound is the module object, not a snapshot of its names, so a value
    notifier_app.py changes after this call is what every ``N.<name>`` lookup
    here sees.
    """
    global N
    N = notifier_module
    # Seeded before the swap that may never come: the tray app can run its
    # whole life in the mode it started in, and a window drawn in that life
    # still needs the names.
    _bind_palette()
    N.THEME.watch(_bind_palette)


def _bind_palette():
    """This module's colour names, out of the palette that is live.

    Written through ``globals()`` rather than restated as literals for the
    reason ``ui_kit.DARK`` exists at all: ``retint`` repaints a widget by
    reading its colour back off it and looking that up in the table, so a
    widget painted from a value this file wrote down itself has no entry, is
    skipped, and stays dark inside a light window.
    """
    g = globals()
    for name, colour in N.THEME.palette().items():
        g[name] = colour


# ─── Remote Admin (R2) ───────────────────────────────────────────────────────────

#: The doors a capability password opens over the network (R1, ADR-0015),
#: keyed by this window's own names for its own panels rather than by the
#: capability names. That is deliberate and is not a spelling choice: no route
#: names a capability and nothing on the wire carries one, so a copy of
#: CAPABILITY_LABELS here would be a second copy of a fact this client can
#: never see and can never check - which is what rule 10 exists to prevent.
#: What this app knows is which doors answered, which it learnt by knocking.
#: Seven since #174 - `users`, `mail`, `proposals` and `clients` are the four
#: areas the Server Settings capability covers, each landing as its own
#: ticket against a credential that already existed. That capability is
#: complete with the last of them; a panel added after this one is a new
#: capability rather than a fifth area of this one.
REMOTE_PANELS = ("config", "history", "import", "users", "mail",
                 "proposals", "clients")
REMOTE_PANEL_LABELS = {"config":    "Host & Port",
                       "history":   "Transaction History",
                       "import":    "Import Archive",
                       "users":     "Engineers",
                       "mail":      "Mail",
                       "proposals": "Asset Proposals",
                       "clients":   "Connected Clients"}


def _server_words(r, fallback="Refused."):
    """The server's own sentence, which is the only one that knows why.

    The idiom this app already uses for /auth/change_password: a refusal is
    shown verbatim rather than translated, because a wrong password, a row
    that is no longer Pending and a channel that is not HTTPS each need a
    different thing done about them and "failed" is the one answer nobody can
    act on.
    """
    try:
        return (r.json() or {}).get("error") or fallback
    except Exception:
        return fallback


def probe_remote_admin(server_url, password):
    """What this password opens, asked of each door with a body it will refuse.

    There is deliberately no endpoint that answers "what does this open?".
    A route naming a capability would be a way to read the delegation map over
    the wire, and `tools/server-checks.py` asserts that no route does. What
    there is instead is that all three R1 endpoints authorise **before** they
    look at the body, so each can be knocked on with a body it is going to
    turn down: no ids, no file, and - for the first - a plain read that the
    Host & Port panel needs anyway, so that one is not a probe at all.

    The answers separate cleanly. A password that opens the door gets 400 for
    the body it sent; one that does not gets 401 `bad_password` before the
    body is reached; and over plain `http://` every one of them is 403
    `insecure` before the password is examined, which is R1's refusal and is
    why this window offers nothing there.

    The Engineers door is `POST /members/rename` with no id (#171), chosen
    over the other two `/members` routes for exactly that property: it
    authorises first and answers `no_id` afterwards, where `POST /members`
    would have to be knocked on with a name and could **write a row**. A knock
    that changes something is not one.

    **It costs one `remote.action` entry per door**, at `warn`, written before
    each call runs - so opening this window on a password that opens all three
    writes three of them. That is written down here rather than hidden,
    because it is the honest record of a capability password being used
    against those doors from this machine, and the alternative is a probe that
    leaves no trace of a delegated credential being used.

    The Mail door is `GET /admin/mail` (#172), which is the second knock that
    is not one: like Host & Port it is a plain read the panel behind it needs
    anyway, so opening this window costs one entry for Mail rather than a
    probe and a load. What comes back is put under `config["mail"]` for that
    panel to draw, which is why this answers a dict rather than two.

    The Connected Clients door is `GET /clients` (#174), which is the third
    knock that is not one: like Host & Port and Mail it is a plain read the
    panel behind it needs anyway, so opening this window costs one entry for
    it rather than a probe and a load. That route is **never open** - unlike
    `GET /assets/proposals` beside the door below, the registry is a map of
    the hostnames, Windows account names and addresses of machines on the
    internal network - which is exactly what makes it answer the question a
    knock is asked for. Its body is put under `config["clients"]` for the
    panel to draw, the way the mail settings are.

    The Asset Proposals door is `POST /assets/proposals/decide` with no id
    (#173), which is a knock of the first kind and has to be: `GET
    /assets/proposals` beside it needs **no credential at all**, so it would
    answer for any password and say nothing about whether this one may
    decide. That route authorises before it looks at the body and answers
    `no_id` afterwards, so the knock decides nothing - which is the property
    the Engineers door was chosen for, one table over.

    Returns `(opens, config, refusal)`: the panel keys that answered, the
    `{host, port}` the first door handed back where it opened - with the mail
    settings beside them under `mail` - and the server's own sentence where
    nothing did. Raises whatever the transport raises - a server that cannot
    be reached is not a wrong password, and the window says so differently.
    """
    url = server_url.rstrip("/")
    opens, cfg, refusal = [], None, ""
    r = api("get", "%s/admin/server_config" % url, json={"password": password},
            timeout=15)
    if r.ok:
        opens.append("config")
        try:
            cfg = r.json()
        except Exception:
            cfg = {}
    else:
        refusal = _server_words(r)
    for key, path, body in (
            ("history",   "/transactions/delete",     {"ids": []}),
            ("import",    "/records/import",          {}),
            ("users",     "/members/rename",          {}),
            ("proposals", "/assets/proposals/decide", {})):
        r = api("post", url + path, json=dict(body, password=password),
                timeout=15)
        # 400 is the body being refused, which is the door having opened: the
        # authorisation ran first and had nothing to say.
        if r.status_code == 400:
            opens.append(key)
        else:
            refusal = _server_words(r)
    for key, path in (("mail", "/admin/mail"), ("clients", "/clients")):
        r = api("get", url + path, json={"password": password}, timeout=15)
        if r.ok:
            opens.append(key)
            cfg = dict(cfg or {})
            try:
                cfg[key] = r.json() or {}
            except Exception:
                cfg[key] = {}
        else:
            refusal = _server_words(r)
    return tuple(k for k in REMOTE_PANELS if k in opens), cfg, refusal


class RemoteAdminWindow:
    """What a capability password opens, from the machine an admin stands at.

    R2. The three remote actions R1 exposes and nothing else: the host and
    port, the Transaction history, and restoring an archive. This app is here
    because it is already on every machine an admin might be at, already holds
    the pinned certificate and already knows the server URL - the alternative
    it removes is the walk to the server console.

    **Nothing here can stop a Transaction being confirmed.** It takes no grab,
    the poll loop and the popup queue never consult it, every question it asks
    is a Toplevel without a grab either, and a server that cannot be reached
    ends as a line on this window. An engineer who stops being asked to
    confirm anything is the one failure this app exists to prevent, and a
    window for somebody else's convenience is never allowed to become it -
    the same rule OwnPasswordWindow is held to, one window over.

    **It is not a second Server GUI.** No Mail Settings, no Lookup Sheet, and
    no admin password change: the admin password is never typed into a client
    (rule 7), so the one door it would open is the one door this window does
    not have. Manage Users **is** here since #171, behind the Server Settings
    capability and nothing less, and what that delegates is written on the
    panel rather than left to be discovered - whoever holds that password can
    set an Engineer's Own Password and then be that Engineer, which is a
    second Admin rather than one delegated action. It was decided deliberately
    and every act is a System Log entry attributed to the delegate.

    The password is asked for before anything is shown and what is shown is
    only what it opened. **A password that opens nothing is refused as a
    password**, on this form, rather than by opening an empty window: an empty
    window reads as a server with nothing in it, where the truth is that this
    credential reaches none of it.

    **`manage_records` opens all three of Delete, Correct and Cancel** (#169).
    Cancel was the one action here no capability password opened: it is
    enforced inside `_cancel_transaction`, which the unauthenticated endpoint
    shares, so this window went the way the Storekeeper's Cancel pill does - a
    Pending Transaction while the switch is on, and the console for a Confirmed
    one. What that meant in practice is that the delegate who had just deleted
    a row outright was sent to walk to the server to retract one, which is the
    argument that put Correct on the network in the first place. The password
    is sent now, and the server takes it exactly as it takes the admin
    password: a Confirmed row opens, and the switch does not apply.

    `opens` is how `tools/client-checks.py` measures the unlocked window
    without a server to unlock it against. It is None for every real opening,
    which is the locked form.
    """

    def __init__(self, root, server_url, opens=None, config=None):
        self.server_url = server_url.rstrip("/")
        self.password   = ""
        self.cfg        = config or {}
        self.opens      = ()
        self.rows       = []
        self._archive   = ""

        win = tk.Toplevel(root)
        ui_kit.single(win, "remote_admin")
        self.win = win
        win.title("Remote Admin")
        win.configure(bg=BG)
        # Draggable on both axes: the history panel is a table, and a table
        # whose width is written down is the Dashboard's argument one window
        # over. The height is never written down either - ui_kit.fit takes it
        # from what the children ask for. The minsize is the floor the gate
        # holds the bottom control at.
        win.resizable(True, True)
        win.minsize(560, 380)
        # No `-topmost` (#193). Only the confirm/reject popup is always on
        # top in this product, and that is what makes it mean something:
        # a window somebody opened is already in front of them, and one
        # pinned over every other app is one they cannot put down to go
        # and read what it is asking about.

        hdr = tk.Frame(win, bg=ACCENT, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🛡  Remote Admin", bg=ACCENT,
                 fg="white", font=font("title")).pack(
                     side="left", padx=16, pady=12)

        # Both from the bottom and before the form, so whatever submits is the
        # first child served rather than the last: pack gives a shortfall to
        # whatever went in last. See ui_kit.fit.
        self.foot = tk.Frame(win, bg=BG)
        self.foot.pack(side="bottom", fill="x")
        self.err = tk.Label(win, text="", bg=BG, fg=DANGER,
                            font=font("body"), wraplength=520,
                            justify="left")
        self.err.pack(side="bottom", anchor="w", padx=20, pady=(2, 0))
        ui_kit.rewrap(self.err, 40)

        self.body = tk.Frame(win, bg=BG)
        self.body.pack(fill="both", expand=True)

        ui_kit.escape_closes(win)
        if opens is None:
            self._ask_password()
        else:
            self._open_with(opens, config or {})

    # -- the door ---------------------------------------------------------
    def _ask_password(self):
        ui_kit.rewrap(tk.Label(
            self.body,
            text=("A capability password opens the actions an Admin delegated "
                  "it and no others: the host and port, the Transaction "
                  "history, or restoring an archive. This window shows only "
                  "what the password you type opens.\n\n"
                  "HTTPS only - over a plain http:// server URL the server "
                  "refuses a capability password before it is even examined, "
                  "and nothing here is offered. The admin password is never "
                  "typed into a client."),
            bg=BG, fg=SUBTEXT, font=font("body"), wraplength=520,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(12, 0))

        frm = tk.Frame(self.body, bg=CARD2, padx=20, pady=14)
        frm.pack(fill="x", padx=20, pady=12)
        tk.Label(frm, text="Capability Password", bg=CARD2, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(6, 3))
        self.pw_e = tk.Entry(frm, show="●", bg=INPUT_BG, fg=TEXT,
                             relief="flat", font=font("value"),
                             insertbackground=TEXT)
        self.pw_e.pack(fill="x", ipady=7)
        ui_kit.reveal(self.pw_e)
        self.pw_e.bind("<Return>", lambda _: self._unlock())

        tk.Button(self.foot, text="Unlock", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=self._unlock,
                  activebackground=ACCENT2).pack(fill="x", padx=20,
                                                 pady=(4, 12))
        ui_kit.fit(self.win, 560)
        self.pw_e.focus_set()

    def _unlock(self):
        pw = self.pw_e.get()
        try:
            opens, cfg, refusal = probe_remote_admin(self.server_url, pw)
        except Exception:
            # Not a wrong password, and the difference is the whole of what
            # this line says: nothing was opened, and nothing else changed.
            self.err.config(text="⚠  Cannot reach the server. "
                                 "Nothing was opened - confirming and "
                                 "rejecting are unaffected.", fg=WARNING)
            return
        if not opens:
            # Refused as a password rather than by opening an empty window.
            # The server's own words say which of the two it was: a credential
            # that opens none of these, or a channel that is not HTTPS.
            self.err.config(text="✗  " + (refusal or
                                                          "Refused."),
                            fg=DANGER)
            return
        self.password = pw
        self.err.config(text="")
        self._open_with(opens, cfg or {})

    # -- what it opened ---------------------------------------------------
    def _open_with(self, opens, cfg):
        """Paint the panels this password opened, and nothing else."""
        self.opens = tuple(k for k in REMOTE_PANELS if k in opens)
        self.cfg = cfg or {}
        self.password = self.password or ""
        # The **body itself** goes, rather than its children: `ui_kit.rewrap`
        # binds `<Configure>` on the box a paragraph sits in, not on the
        # paragraph, so a label destroyed out from under its box leaves a live
        # relay reaching for a widget that is gone - which Tk reports as an
        # `invalid command name` out of an event callback, long after whatever
        # caused it. Replacing the box takes the binding with it. The footer's
        # children carry no such binding, being buttons, and the frame stays so
        # that what submits is still packed from the bottom.
        self.body.destroy()
        for w in list(self.foot.winfo_children()):
            w.destroy()
        # The opened console scrolls (095): on its Mail panel it asked for
        # 931px, taller than the 688px a 768px screen leaves once `fit` has
        # clamped it. The footer and the error line were packed from the
        # bottom in `__init__`, before this, so they stay outside it.
        self.scroll = ui_kit.ScrollRegion(self.win, BG)
        self.body = self.scroll.body
        self.scroll.pack(padx=0, pady=0)

        self._panes = {}
        # **The console's own navigation, on the engineer's machine** (080).
        # This was seven flat `tk.Button`s on the shell with the selected one
        # a brighter foreground, which is a device nothing else in this
        # product uses - and this window is the Server console reached from
        # somebody's own laptop, so reading as a different product is the
        # defect rather than a preference. `ui_kit.SectionBar` is the widget
        # 076 built for exactly this, and the six Server sections (#252) are
        # the same widget with different names rather than a second one that
        # looks like it.
        #
        # The bar is keyed by **label** because that is what it draws, and
        # `show` still takes the panel key every caller here already holds,
        # so the two dicts below are the one translation between them and the
        # only place the pairing is written down.
        self._label_key = dict((REMOTE_PANEL_LABELS[k], k)
                               for k in self.opens)
        self._key_label = dict((k, REMOTE_PANEL_LABELS[k])
                               for k in self.opens)
        self.bar = ui_kit.SectionBar(
            self.body, [REMOTE_PANEL_LABELS[k] for k in self.opens],
            BG, CARD, TEXT, SUBTEXT, LINE,
            command=lambda name: self.show(self._label_key[name]))
        self.bar.pack(fill="x")
        for key in self.opens:
            # `CARD` rather than the shell the panes stood on before: the
            # selected cell above is `CARD` against the `BG` strip, so a pane
            # in `BG` would leave that cell a tab floating over a hole. The
            # panel is what the section is a section *of*.
            pane = tk.Frame(self.body, bg=CARD)
            self._panes[key] = pane
            getattr(self, "_build_" + key)(pane)

        tk.Button(self.foot, text="Close", bg=CARD2, fg=TEXT,
                  font=font("value"), relief="flat", cursor="hand2",
                  pady=8, command=self.win.destroy,
                  activebackground=LINE).pack(fill="x", padx=20, pady=(6, 12))
        self.show(self.opens[0])
        # Asked again rather than kept from the locked form, the way Manage
        # Users asks again when a row is added: the body is a different form
        # now, and a size taken before it was built is a size for the password
        # field.
        #
        # **The floor is the bar's own width, and `fit` cannot ask for it.**
        # `SectionBar`'s strip is `pack_propagate(False)` so that it can hold
        # its 38px height, and a frame that does not propagate reports a
        # requested width of 1 - so the window would be sized to the form
        # alone. Seven sections come to 895px at 100% against the 720 this
        # asked for, which placed Asset Proposals 18px short and did not map
        # Connected Clients at all: the last panel a password opens would be
        # the one with no way to reach it. Summed off the cells rather than
        # written down, because the figure is seven labels in whatever face
        # and scaling this machine is running.
        self.win.update_idletasks()
        bar_w = sum(cell.winfo_reqwidth()
                    for cell, _lbl, _mark in self.bar.cells.values())
        # Clamped to the display for `fit`'s own reason one axis over: a
        # window wider than the screen is one whose right edge cannot be
        # dragged back. Past that the sections clip, which is a scroll this
        # window does not have - but it is a visible shortfall on a resizable
        # window rather than a control nobody can reach.
        self.scroll.size()
        ui_kit.fit(self.win, min(self.scroll.width(max(720, bar_w)),
                                 self.win.winfo_screenwidth() - 80))

    def show(self, key):
        """Raise one panel, and paint the bar to say which.

        Safe to call from the bar's own callback: `SectionBar.select` does
        not call `command`, so this re-selecting the section that just fired
        is a repaint of what is already painted rather than a loop.
        """
        for pane in self._panes.values():
            pane.pack_forget()
        self._panes[key].pack(fill="both", expand=True)
        self.bar.select(self._key_label[key])

    def _call(self, method, path, body, said):
        """One remote action, reported in the server's own words when refused.

        Answers with what came back, or None where nothing happened. The
        password goes on every one of them: R1 authorises each call on its
        own, so there is no session here to lose and nothing that has to be
        held open.
        """
        try:
            r = api(method, self.server_url + path,
                    json=dict(body or {}, password=self.password), timeout=20)
        except Exception:
            self.err.config(text="⚠  Cannot reach the server. "
                                 "Nothing was changed.", fg=WARNING)
            return None
        if not r.ok:
            self.err.config(text="✗  " + _server_words(r),
                            fg=DANGER)
            return None
        self.err.config(text="✓  " + said, fg=SUCCESS)
        try:
            return r.json()
        except Exception:
            return {}

    # -- a question without a grab ----------------------------------------
    def _prompt(self, title, text, field, secret=False):
        """Ask, without taking a grab.

        `secret` is the one caller that asks for a password rather than a name
        or a reason - Set Own Password, on the Engineers panel. It was asked
        for through the same unmasked field as everything else here, which is
        a password typed in the clear on a window an Admin opens standing over
        somebody else's desk; it is masked now and carries the toggle every
        other password field in these four apps has since #202.

        `messagebox` and `simpledialog` both grab, and a grab here would be
        this window stopping an engineer answering a popup - the one thing it
        may never do. `wait_window` on its own runs a nested event loop, so
        the command tick's after() callbacks go on firing and a Transaction
        that arrives while this is open is still put in front of them.
        """
        dlg = tk.Toplevel(self.win)
        dlg.title(title)
        dlg.configure(bg=BG)
        dlg.resizable(True, False)
        dlg.minsize(360, 170)
        # No `-topmost` (#193). Only the confirm/reject popup is always on
        # top in this product, and that is what makes it mean something:
        # a window somebody opened is already in front of them, and one
        # pinned over every other app is one they cannot put down to go
        # and read what it is asking about.
        out = {"value": None}

        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")
        ui_kit.rewrap(tk.Label(dlg, text=text, bg=BG, fg=TEXT,
                               font=font("body"), wraplength=340,
                               justify="left"), 40).pack(
                                   anchor="w", padx=20, pady=(14, 8))
        e = None
        if field:
            e = tk.Entry(dlg, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT,
                         **({"show": ui_kit.MASK} if secret else {}))
            e.pack(fill="x", padx=20, ipady=7)
            if secret:
                ui_kit.reveal(e)

        def take():
            out["value"] = e.get().strip() if field else True
            dlg.destroy()

        tk.Button(foot, text="OK", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=8, command=take,
                  activebackground=ACCENT2).pack(fill="x", padx=20,
                                                 pady=(8, 6))
        tk.Button(foot, text="Cancel", bg=CARD2, fg=TEXT,
                  font=font("body"), relief="flat", cursor="hand2", pady=6,
                  command=dlg.destroy,
                  activebackground=LINE).pack(fill="x", padx=20, pady=(0, 12))
        if e is not None:
            e.bind("<Return>", lambda _: take())
            e.focus_set()
        ui_kit.fit(dlg, 380)
        ui_kit.escape_closes(dlg)
        dlg.wait_window()
        return out["value"]

    # -- Host & Port -------------------------------------------------------
    def _build_config(self, pane):
        ui_kit.rewrap(tk.Label(
            pane,
            text=("Saved for the next start. The server running now is "
                  "unchanged until somebody restarts it, which is what makes "
                  "this the mildest of the three."),
            bg=CARD, fg=SUBTEXT, font=font("body"), wraplength=520,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(6, 0))

        frm = tk.Frame(pane, bg=CARD2, padx=20, pady=14)
        frm.pack(fill="x", padx=20, pady=10)

        def field(label, value):
            tk.Label(frm, text=label, bg=CARD2, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 3))
            e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
            e.insert(0, "" if value is None else str(value))
            e.pack(fill="x", ipady=7)
            return e

        self.host_e = field("Host  ·  the address the server "
                            "binds to", self.cfg.get("host", ""))
        self.port_e = field("Port", self.cfg.get("port", ""))
        tk.Button(frm, text="Save Host and Port", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=8, command=self._save_config,
                  activebackground=ACCENT2).pack(fill="x", pady=(12, 0))

    def _save_config(self):
        # The port is held to being a number here so the field says so at
        # once; the range is the server's, through _validate_port, and its
        # refusal is what gets shown.
        try:
            port = int(self.port_e.get().strip())
        except ValueError:
            self.err.config(text="✗  The port has to be a "
                                 "number.", fg=DANGER)
            return
        self._call("post", "/admin/server_config",
                   {"host": self.host_e.get().strip(), "port": port},
                   "Saved. The server uses it at its next restart.")

    # -- Transaction History ----------------------------------------------
    def _build_history(self, pane):
        N._style_notifier()
        ui_kit.rewrap(tk.Label(
            pane,
            text=("Delete, Correct and Cancel are what this password opens. "
                  "A Cancel made here overrides the Storekeeper switch and "
                  "opens a Confirmed Transaction, the way the admin password "
                  "does, and is recorded against the password that was used. "
                  "Correct is still a Pending Transaction only - a Confirmed "
                  "one is Cancelled and recorded again."),
            bg=CARD, fg=SUBTEXT, font=font("body"), wraplength=640,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(6, 0))

        cols = ("ID", "Asset No.", "Serial", "Type", "Engineer", "Direction",
                "When", "Status")
        widths = (50, 110, 110, 90, 140, 90, 130, 90)
        wrap = tk.Frame(pane, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=20, pady=(8, 0))
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 style="DB.Treeview", height=9)
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w", stretch=(c == "Engineer"))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        N._tag_status(self.tree)

        bar = tk.Frame(pane, bg=CARD)
        bar.pack(fill="x", padx=20, pady=8)
        for text, cmd in (("↻  Refresh", self._load_rows),
                          ("⦸  Cancel", self._cancel_selected),
                          ("✎  Correct", self._correct_selected),
                          ("🗑  Delete", self._delete_selected)):
            tk.Button(bar, text=text, bg=CARD2, fg=TEXT, font=font("body"),
                      relief="flat", cursor="hand2", padx=12, pady=6,
                      activebackground=LINE, command=cmd).pack(side="left",
                                                               padx=(0, 8))
        self._load_rows()

    def _load_rows(self):
        """The list, which needs no password at all - `GET /transactions` is
        an ordinary read (ADR-0002). What the capability opens is what is
        done to a row, not the sight of it."""
        try:
            r = api("get", "%s/transactions" % self.server_url,
                    params={"include_cancelled": 1}, timeout=15)
            self.rows = r.json() if r.ok else []
        except Exception:
            self.rows = []
            self.err.config(text="⚠  Cannot reach the server.",
                            fg=WARNING)
        self.rows.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        self.tree.delete(*self.tree.get_children())
        for t in self.rows:
            st = self._row_status(t)
            when = (t.get("timestamp") or "")[:16].replace("T", "  ")
            self.tree.insert("", "end", iid=str(t.get("id")),
                             tags=(st if st != "cancelled" else "day",),
                             values=(t.get("id"), t.get("asset_number", ""),
                                     t.get("serial_number", ""),
                                     t.get("asset_type", ""),
                                     t.get("team_member", ""),
                                     t.get("direction", ""), when,
                                     st.title()))

    @staticmethod
    def _row_status(t):
        """Cancelled first, which `_status_of` beside it does not report.

        That function answers the question the popup queue asks, where a
        cancelled row never arrives; this window lists them on purpose, and a
        row the store has retracted must not read as Pending in the one window
        that offers to Cancel it.
        """
        if t.get("cancelled"):
            return "cancelled"
        return N._status_of(t)

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            self.err.config(text="⚠  Pick a Transaction "
                                 "first.", fg=WARNING)
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _cancel_selected(self):
        tid = self._selected()
        if tid is None:
            return
        reason = self._prompt(
            "Cancel Transaction",
            "Why is #%d being cancelled? A cancel says the movement it "
            "records never happened - it is not the engineer denying it, "
            "which is a Reject." % tid, True)
        if not reason:
            return
        # The password goes with it since #169: `manage_records` opens Cancel
        # beside Delete and Correct, so a Confirmed row opens and the
        # Storekeeper switch does not apply. `cancelled_by` is deliberately not
        # sent - the server names the actor from the credential that opened the
        # door, and a name in the body would be ignored anyway. Every refusal
        # is still shown in the server's own words: only it knows whether the
        # row is the newest for its asset.
        try:
            r = api("post", "%s/transactions/cancel" % self.server_url,
                    json={"id": tid, "reason": reason,
                          "password": self.password}, timeout=20)
        except Exception:
            self.err.config(text="⚠  Cannot reach the server. "
                                 "Nothing was changed.", fg=WARNING)
            return
        if not r.ok:
            self.err.config(text="✗  " + _server_words(r),
                            fg=DANGER)
            return
        self.err.config(text="✓  #%d cancelled." % tid,
                        fg=SUCCESS)
        self._load_rows()

    def _correct_selected(self):
        tid = self._selected()
        if tid is None:
            return
        row = next((t for t in self.rows if t.get("id") == tid), None)
        if row is None:
            return
        RemoteCorrectionWindow(self.win, self.server_url, self.password, row,
                               on_done=self._load_rows)

    def _delete_selected(self):
        tid = self._selected()
        if tid is None:
            return
        if not self._prompt(
                "Delete Transaction",
                "Delete #%d? The row stops existing and no archive is taken "
                "here - the System Log entry naming this credential is the "
                "whole record that it happened." % tid, False):
            return
        if self._call("post", "/transactions/delete", {"ids": [tid]},
                      "#%d deleted." % tid) is not None:
            self._load_rows()

    # -- Engineers ---------------------------------------------------------
    def _build_users(self, pane):
        """#171. The panel is its own class; this is the hook `_open_with`
        reaches by name, like the three beside it."""
        N._style_notifier()
        self.users = RemoteUsersPanel(self, pane)

    # -- Mail --------------------------------------------------------------
    def _build_mail(self, pane):
        """#172. The panel is its own class, for the Engineers panel's reason:
        it holds a form, the three password states and a sub-window."""
        self.mail = RemoteMailPanel(self, pane)

    # -- Asset Proposals ---------------------------------------------------
    def _build_proposals(self, pane):
        """#173. Its own class, for the Engineers panel's reason: a list that
        rebuilds itself after every write, and a card per delivery."""
        N._style_notifier()
        self.proposals = RemoteProposalsPanel(self, pane)

    # -- Connected Clients -------------------------------------------------
    def _build_clients(self, pane):
        """#174. Its own class, for the Engineers panel's reason: two lists
        that rebuild themselves after every write, and a selection the second
        of them follows."""
        N._style_notifier()
        self.clients = RemoteClientsPanel(self, pane)

    # -- Import Archive ----------------------------------------------------
    def _build_import(self, pane):
        ui_kit.rewrap(tk.Label(
            pane,
            text=("An archive is rows that were deleted from the store. They "
                  "are appended with new ids and never written back over a "
                  "row that is still there, so restoring one twice is two "
                  "sets of rows rather than one overwritten."),
            bg=CARD, fg=SUBTEXT, font=font("body"), wraplength=520,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(6, 0))

        frm = tk.Frame(pane, bg=CARD2, padx=20, pady=14)
        frm.pack(fill="x", padx=20, pady=10)
        self.arch_lbl = tk.Label(frm, text="No file chosen.", bg=CARD2,
                                 fg=SUBTEXT, font=font("body"), anchor="w")
        self.arch_lbl.pack(fill="x", pady=(0, 10))
        tk.Button(frm, text="Choose an .xlsx archive...", bg=INPUT_BG, fg=TEXT,
                  font=font("body"), relief="flat", cursor="hand2", pady=7,
                  command=self._pick_archive,
                  activebackground=LINE).pack(fill="x")
        tk.Button(frm, text="Upload and Restore", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=8, command=self._upload_archive,
                  activebackground=ACCENT2).pack(fill="x", pady=(10, 0))

    def _pick_archive(self):
        path = filedialog.askopenfilename(
            parent=self.win, title="Choose a transaction archive",
            filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")])
        if not path:
            return
        self._archive = path
        self.arch_lbl.config(text=os.path.basename(path), fg=TEXT)

    def _upload_archive(self):
        if not self._archive:
            self.err.config(text="⚠  Choose an archive first.",
                            fg=WARNING)
            return
        try:
            with open(self._archive, "rb") as f:
                blob = base64.b64encode(f.read()).decode("ascii")
        except Exception as ex:
            self.err.config(text="✗  That file could not be "
                                 "read: %s" % ex, fg=DANGER)
            return
        got = self._call("post", "/records/import",
                         {"file_data": blob,
                          "filename": os.path.basename(self._archive)},
                         "Archive restored.")
        if got:
            self.err.config(text="✓  %d record(s) restored."
                                 % got.get("imported", 0), fg=SUCCESS)


class RemoteUsersPanel:
    """The Engineer list, from the machine an admin stands at. #171.

    The Server GUI's Manage Users window narrowed to the Engineer half of it:
    a card per Engineer carrying Auto-Approve, the Access Profile with its
    Permission ticks, the Own Password's three states, a rename and a delete,
    plus one row that adds. The Admin card and the Storekeeper card are not
    here - neither is an Engineer, one is a password this client must never
    type (rule 7) and the other is a server setting rather than a row.

    **A class rather than four more methods on the window**, which is the one
    departure from the three panels above: this is a form that rebuilds itself
    after every write, and the state it holds between writes - the list, the
    captions, one set of widget variables per Engineer - is per-panel rather
    than per-window. The three older panels each hold a handful of attributes
    on the window and this would have added a dozen.

    It borrows the window for three things and nothing else: `_call` to make a
    request and word its refusal, `_prompt` to ask a question without taking a
    grab, and `err` to say what happened. So **nothing here can stop a
    Transaction being confirmed** either, which is the rule that window is
    held to and the reason none of this reaches for `messagebox`.

    The Permission names and their captions come from `GET /permissions`
    rather than from a copy here: rule 8 says those live in `server.py` and no
    client carries a copy, and `cascade-audit.py` fails an app that grows one.
    A server too old to answer that route leaves the ticks captioned by their
    own names, which is what the console does for an uncaptioned name and is
    the same decision one step further out.
    """

    def __init__(self, panel, pane):
        self.panel = panel          # the RemoteAdminWindow
        self.pane  = pane
        self.perms = []
        self.rows  = []

        ui_kit.rewrap(tk.Label(
            pane,
            text=("Whoever holds this password can set an Engineer's Own "
                  "Password and then open that Engineer's client as them. "
                  "That is a second Admin rather than one delegated action, "
                  "and it was handed over on purpose - every change made here "
                  "is a System Log entry attributed to this password and not "
                  "to the Admin. Transactions already recorded are never "
                  "touched: deleting an Engineer removes the row, and a "
                  "rename carries their history with them."),
            bg=CARD, fg=SUBTEXT, font=font("body"), wraplength=640,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(6, 0))

        add = tk.Frame(pane, bg=CARD2, padx=14, pady=10)
        add.pack(fill="x", padx=20, pady=(10, 4))
        tk.Label(add, text="Add an Engineer", bg=CARD2, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w")
        row = tk.Frame(add, bg=CARD2)
        row.pack(fill="x", pady=(4, 0))
        self.new_e = tk.Entry(row, bg=INPUT_BG, fg=TEXT, relief="flat",
                              font=font("value"), insertbackground=TEXT)
        self.new_e.pack(side="left", fill="x", expand=True, ipady=6)
        self.new_auto = tk.IntVar(value=0)
        tk.Checkbutton(row, text="Auto-Approve", variable=self.new_auto,
                       bg=CARD2, fg=TEXT, selectcolor=INPUT_BG,
                       activebackground=CARD2, activeforeground=TEXT,
                       font=font("body"), relief="flat", bd=0,
                       highlightthickness=0).pack(side="left", padx=(10, 0))
        tk.Button(row, text="Add", bg=ACCENT, fg="white",
                  font=font("strong"), relief="flat", cursor="hand2",
                  padx=14, pady=5, command=self._add,
                  activebackground=ACCENT2).pack(side="left", padx=(10, 0))
        self.new_e.bind("<Return>", lambda _: self._add())

        # The list scrolls, which is Manage Users' answer to the same shape at
        # the console: a card per Engineer has no bound at all, and this one
        # sits inside a pane inside a window that already carries three other
        # panels. The window's own footer is outside this and was packed from
        # the bottom, so Close can be neither squeezed out nor scrolled away.
        wrap = tk.Frame(pane, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=20, pady=(4, 8))
        self.canvas = tk.Canvas(wrap, bg=CARD, highlightthickness=0,
                                height=260)
        bar = ttk.Scrollbar(wrap, orient="vertical",
                            command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=CARD)
        self._window = self.canvas.create_window((0, 0), window=self.body,
                                                 anchor="nw")
        self.body.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(
            self._window, width=e.width))
        # On this window rather than with `bind_all`, for the console's
        # reason: a global binding would outlive it and fire into a canvas
        # that is gone.
        self.canvas.bind("<MouseWheel>", self._wheel)

        self._load_permissions()
        self.reload()

    # -- what the server says ---------------------------------------------
    def _wheel(self, e):
        """Scroll this list, and only this list (095).

        The window around it scrolls too, bound on the toplevel, and Tk
        delivers the wheel to the canvas and then to the toplevel - so
        without the `"break"` both would move.
        """
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        return "break"

    def _load_permissions(self):
        """The Permission names and captions, which need no credential.

        A failure is not an error here: the ticks are drawn from each
        Engineer's own `permissions` list either way, so what is lost is the
        caption beside the name. Rule 8's point is that the names are not
        written down in this file, and they still are not.
        """
        try:
            r = api("get", "%s/permissions" % self.panel.server_url,
                    timeout=10)
            self.perms = r.json() if r.ok else []
        except Exception:
            self.perms = []

    def reload(self):
        """Re-read the list and repaint. Called after every write.

        The state of a card - which of the three Own Password states, whether
        the profile is custom, which Permissions are ticked - is derived from
        the row each time it is read rather than kept beside the widget, which
        is the rule the console's own cards keep.
        """
        try:
            r = api("get", "%s/members" % self.panel.server_url, timeout=10)
            self.rows = r.json() if r.ok else []
        except Exception:
            self.rows = []
            self.panel.err.config(text="⚠  Cannot reach the server.",
                                  fg=WARNING)
        for w in list(self.body.winfo_children()):
            w.destroy()
        for m in self.rows:
            self._card(m)

    # -- one Engineer ------------------------------------------------------
    def _card(self, m):
        name = m.get("name", "")
        card = tk.Frame(self.body, bg=CARD, padx=14, pady=10)
        card.pack(fill="x", pady=(0, 8))

        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text=name, bg=CARD, fg=TEXT,
                 font=font("heading")).pack(side="left")
        for text, cmd in (("🗑  Delete", lambda: self._delete(m)),
                          ("✎  Rename", lambda: self._rename(m))):
            tk.Button(head, text=text, bg=CARD2, fg=TEXT,
                      font=font("micro"), relief="flat", cursor="hand2",
                      padx=10, pady=3, activebackground=LINE,
                      command=cmd).pack(side="right", padx=(6, 0))

        auto = tk.IntVar(value=1 if m.get("auto_approve") else 0)
        tk.Checkbutton(card, text="Auto-Approve  ·  no Notifier, and their "
                                  "Transactions are confirmed at once",
                       variable=auto, bg=CARD, fg=SUBTEXT,
                       selectcolor=INPUT_BG, activebackground=CARD,
                       activeforeground=TEXT, font=font("micro"),
                       relief="flat", bd=0, highlightthickness=0,
                       anchor="w", justify="left",
                       command=lambda: self._save(
                           m, auto_approve=bool(auto.get()))).pack(
                               anchor="w", pady=(6, 0))

        # -- the Access Profile
        held = list(m.get("permissions") or [])
        prof = tk.StringVar(value=m.get("profile") or "default")
        pfrm = tk.Frame(card, bg=CARD)
        pfrm.pack(fill="x", pady=(6, 0))
        tk.Label(pfrm, text="Access Profile", bg=CARD, fg=SUBTEXT,
                 font=font("micro")).pack(anchor="w")
        ticks = tk.Frame(card, bg=CARD)

        def profile_changed():
            # Switching to Default sends no permission list at all, so what
            # was ticked survives and comes back with Custom - the console's
            # rule, and `_member_permissions` reading the column only on a
            # custom profile is what makes it true.
            if prof.get() == "custom":
                ticks.pack(fill="x", padx=(16, 0))
                self._save(m, profile="custom", permissions=held)
            else:
                ticks.pack_forget()
                self._save(m, profile="default")

        for value, text in (("default", "Default"), ("custom", "Custom")):
            tk.Radiobutton(pfrm, text=text, value=value, variable=prof,
                           bg=CARD, fg=TEXT, selectcolor=INPUT_BG,
                           activebackground=CARD, activeforeground=TEXT,
                           font=font("body"), relief="flat", bd=0,
                           highlightthickness=0,
                           command=profile_changed).pack(side="left",
                                                         padx=(0, 12))

        # Looped over what the server served, captioned by what it called
        # each one - a name with no caption is offered as itself rather than
        # dropping out of the form, which is rule 8 at the console said one
        # step further out.
        for p in (self.perms or [{"name": n, "label": n} for n in held]):
            pname = p.get("name")
            var = tk.IntVar(value=1 if pname in held else 0)

            def toggled(pname=pname, var=var):
                if var.get() and pname not in held:
                    held.append(pname)
                elif not var.get() and pname in held:
                    held.remove(pname)
                self._save(m, profile="custom", permissions=list(held))

            tk.Checkbutton(ticks, text=p.get("label") or pname, variable=var,
                           bg=CARD, fg=SUBTEXT, selectcolor=INPUT_BG,
                           activebackground=CARD, activeforeground=TEXT,
                           font=font("micro"), relief="flat", bd=0,
                           highlightthickness=0, anchor="w", justify="left",
                           wraplength=520,
                           command=toggled).pack(anchor="w")
        if prof.get() == "custom":
            ticks.pack(fill="x", padx=(16, 0))

        # -- the Own Password, in the three states it actually has
        if not m.get("has_password"):
            state = "No Own Password  ·  the admin password opens their " \
                    "Settings"
        elif m.get("must_change_password"):
            state = "Temporary  ·  waiting to be replaced by the Engineer"
        else:
            state = "Set by the Engineer"
        pw = tk.Frame(card, bg=CARD)
        pw.pack(fill="x", pady=(8, 0))
        tk.Label(pw, text="Own Password:  " + state, bg=CARD, fg=SUBTEXT,
                 font=font("micro"), wraplength=460,
                 justify="left").pack(side="left")
        if m.get("has_password"):
            tk.Button(pw, text="Clear", bg=CARD2, fg=TEXT,
                      font=font("micro"), relief="flat", cursor="hand2",
                      padx=10, pady=3, activebackground=LINE,
                      command=lambda: self._set_password(m, "")).pack(
                          side="right", padx=(6, 0))
        tk.Button(pw, text="Set", bg=CARD2, fg=TEXT, font=font("micro"),
                  relief="flat", cursor="hand2", padx=10, pady=3,
                  activebackground=LINE,
                  command=lambda: self._set_password(m)).pack(side="right",
                                                              padx=(6, 0))

    # -- the writes --------------------------------------------------------
    def _save(self, m, **changes):
        """One `POST /members`, carrying only what this control changed.

        `auto_approve` goes on every one of them because `_save_member` has no
        `_KEEP` for it, the way the Storekeeper's own Add Engineer sends it;
        every other field left out keeps its value, which is that endpoint's
        convention and what lets a tick be a tick rather than a whole form.
        """
        body = {"name": m.get("name", ""),
                "auto_approve": m.get("auto_approve")}
        body.update(changes)
        if self.panel._call("post", "/members", body,
                            "%s saved." % m.get("name", "")) is not None:
            self.reload()

    def _add(self):
        name = self.new_e.get().strip()
        if not name:
            self.panel.err.config(text="⚠  Enter a name.", fg=WARNING)
            return
        if self.panel._call("post", "/members",
                            {"name": name,
                             "auto_approve": bool(self.new_auto.get())},
                            "%s added." % name) is not None:
            self.new_e.delete(0, "end")
            self.new_auto.set(0)
            self.reload()

    def _rename(self, m):
        new = self.panel._prompt(
            "Rename Engineer",
            "What should %s be called? The id is what is renamed, so their "
            "Own Password, their profile and every Transaction recorded "
            "against them come with it. The System Log is not rewritten - "
            "the rename is recorded in it instead."
            % m.get("name", ""), True)
        if not new:
            return
        if self.panel._call("post", "/members/rename",
                            {"id": m.get("id"), "name": new},
                            "Renamed to %s." % new) is not None:
            self.reload()

    def _delete(self, m):
        if not self.panel._prompt(
                "Delete Engineer",
                "Delete %s? The row goes and their Own Password with it. "
                "Transactions already recorded against them are kept exactly "
                "as they are - what stops is their being offered as an "
                "Engineer to record a new one against."
                % m.get("name", ""), False):
            return
        if self.panel._call("post", "/members/delete",
                            {"name": m.get("name", "")},
                            "%s deleted." % m.get("name", "")) is not None:
            self.reload()

    def _set_password(self, m, value=None):
        """Set or clear one Engineer's Own Password.

        A password set here is **Temporary**: the server arms
        `must_change_password`, so the Engineer is made to replace it the
        first time they authenticate with it (ADR-0009). That is the reset
        path, and it is the same helper the console writes through - so what a
        password set here means cannot differ from what it means there.
        """
        if value is None:
            value = self.panel._prompt(
                "Set Own Password",
                "A new Own Password for %s. It is Temporary - they are made "
                "to replace it the first time they use it - and it never "
                "affects the admin password."
                % m.get("name", ""), True, secret=True)
            if not value:
                return
        self._save(m, member_password=value)


class RemoteMailPanel:
    """The mail server, from the machine an admin stands at. #172.

    The Server GUI's Mail Settings window narrowed to what can travel: the
    relay, the address it sends as, STARTTLS, a username, the password, and a
    test send that reports the relay's own words. Notification Rules sits
    behind a button here exactly as it sits behind that window's footer, and
    for its reason - the relay and the subscription list change for entirely
    different reasons, months apart.

    **The stored password is never shown and is never read back**, which is
    not this window being careful but the only thing `GET /admin/mail` will
    answer: it is the one replayable secret this server holds (ADR-0013), so
    what the form is told is whether one is stored and whether this machine
    can store one at all. Leaving the field empty keeps whatever is there,
    which is why Clear is a control of its own rather than an empty save.

    A class rather than more methods on the window, for the Engineers panel's
    reason, and it borrows the same three things: `_call`, `_prompt` and
    `err`. So nothing here can stop a Transaction being confirmed either.
    """

    def __init__(self, panel, pane):
        self.panel = panel          # the RemoteAdminWindow
        self.pane  = pane
        self.cfg   = dict((panel.cfg or {}).get("mail") or {})

        ui_kit.rewrap(tk.Label(
            pane,
            text=("Everything this server sends goes out through this relay. "
                  "Whoever holds this password can point it somewhere else "
                  "and mail the department as the Asset Server, so every "
                  "change here is a System Log entry attributed to this "
                  "password rather than to the Admin. The stored password is "
                  "never sent back to this window - leave the field empty to "
                  "keep it."),
            bg=CARD, fg=SUBTEXT, font=font("body"), wraplength=640,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(6, 0))

        frm = tk.Frame(pane, bg=CARD2, padx=20, pady=14)
        frm.pack(fill="x", padx=20, pady=10)

        def field(label, value):
            tk.Label(frm, text=label, bg=CARD2, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 3))
            e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
            e.insert(0, "" if value is None else str(value))
            e.pack(fill="x", ipady=7)
            return e

        self.host_e = field("Mail server", self.cfg.get("host", ""))
        self.port_e = field("Port", self.cfg.get("port", ""))
        self.from_e = field("Sends as", self.cfg.get("from", ""))
        self.user_e = field("Username  ·  empty where the relay asks for "
                            "none", self.cfg.get("username", ""))

        self.tls = tk.IntVar(value=1 if self.cfg.get("starttls") else 0)
        tk.Checkbutton(frm, text="STARTTLS  ·  upgrade the connection "
                                 "before logging in",
                       variable=self.tls, bg=CARD2, fg=TEXT,
                       selectcolor=INPUT_BG, activebackground=CARD2,
                       activeforeground=TEXT, font=font("body"),
                       relief="flat", bd=0,
                       highlightthickness=0).pack(anchor="w", pady=(10, 0))

        tk.Label(frm, text="Password", bg=CARD2, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(10, 3))
        self.pw_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                             show="•", font=font("value"),
                             insertbackground=TEXT)
        self.pw_e.pack(fill="x", ipady=7)
        # This panel is never told what is stored (ADR-0013) - it asks
        # `GET /admin/mail`, which answers *whether* a password is there and
        # never what it is - so the field opens empty and the toggle can only
        # ever show what somebody typed into it just now (#202). It is the
        # sharpest case of that rule, being the one on the network.
        ui_kit.reveal(self.pw_e)
        self.pw_note = tk.Label(frm, text="", bg=CARD2, fg=FAINT,
                                font=font("micro"), anchor="w",
                                wraplength=560, justify="left")
        self.pw_note.pack(fill="x", pady=(4, 0))
        self._say_password()

        row = tk.Frame(frm, bg=CARD2)
        row.pack(fill="x", pady=(12, 0))
        tk.Button(row, text="Save Mail Settings", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=8, command=self._save,
                  activebackground=ACCENT2).pack(side="left", fill="x",
                                                 expand=True)
        tk.Button(row, text="Clear Password", bg=CARD2, fg=TEXT,
                  font=font("body"), relief="flat", cursor="hand2",
                  padx=14, pady=8, command=self._clear,
                  activebackground=LINE).pack(side="left", padx=(10, 0))

        tf = tk.Frame(pane, bg=CARD2, padx=20, pady=12)
        tf.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(tf, text="Send a test mail to", bg=CARD2, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(0, 3))
        self.test_e = tk.Entry(tf, bg=INPUT_BG, fg=TEXT, relief="flat",
                               font=font("value"), insertbackground=TEXT)
        self.test_e.pack(fill="x", ipady=6)
        ui_kit.rewrap(tk.Label(
            tf, text=("Saves what is above first, then sends, and reports "
                      "whatever the mail server says back. A test that passes "
                      "against this form and fails against what is on the "
                      "server is worse than no test."),
            bg=CARD2, fg=FAINT, font=font("micro"), anchor="w",
            wraplength=560, justify="left"), 40).pack(fill="x", pady=(4, 0))
        tk.Button(tf, text="Send Test Mail", bg=CARD2, fg=TEXT,
                  font=font("value"), relief="flat", cursor="hand2",
                  pady=7, command=self._test,
                  activebackground=LINE).pack(fill="x", pady=(8, 0))

        tk.Button(pane, text="Notification Rules...", bg=CARD2, fg=TEXT,
                  font=font("value"), relief="flat", cursor="hand2",
                  pady=8, command=self._rules,
                  activebackground=LINE).pack(fill="x", padx=20, pady=(0, 10))

    # -- the three password states ----------------------------------------
    def _say_password(self):
        """Which of the three the note says, derived from what came back.

        No Own Password's shape one feature over: a machine that cannot store
        one at all, a password already stored, and none stored - three states
        and not two, and the first of them needs its own sentence because the
        remedy is a relay that asks for no password rather than a better one.
        """
        if not self.cfg.get("can_store", True):
            self.pw_e.config(state="disabled")
            self.pw_note.config(
                text=("That server cannot store a mail password: Windows "
                      "DPAPI is not available there, which needs pywin32. It "
                      "is never written in plaintext instead. A relay that "
                      "asks for no password works as it does anywhere else."),
                fg=WARNING)
        elif self.cfg.get("password_stored"):
            self.pw_note.config(text="A password is stored, encrypted for "
                                     "that machine. Type a new one to replace "
                                     "it, or use Clear.", fg=SUCCESS)
        else:
            self.pw_note.config(text="No password stored. One typed here is "
                                     "encrypted for that machine and kept in "
                                     "smtp_secret.dat, never in "
                                     "server_config.json.", fg=FAINT)

    # -- writes -------------------------------------------------------------
    def _body(self, password=None):
        body = {"host": self.host_e.get().strip(),
                "port": self.port_e.get().strip(),
                "from": self.from_e.get().strip(),
                "username": self.user_e.get().strip(),
                "starttls": bool(self.tls.get())}
        if password is not None:
            body["smtp_password"] = password
        return body

    def _save(self, clear=False, said="Saved. Applied at once - no restart "
                                      "needed."):
        """Write the form. Answers True where it was written.

        The password is sent only where there is one to send: an empty field
        means leave it, and `POST /admin/mail` reads an absent key that way
        for the reason `POST /members` reads an absent one - a form that is
        never shown a password cannot tell "leave it" from "clear it".
        """
        typed = "" if self.pw_e.cget("state") == "disabled" else self.pw_e.get()
        pw = "" if clear else (typed or None)
        got = self.panel._call("post", "/admin/mail", self._body(pw), said)
        if got is None:
            return False
        if pw is not None:
            self.pw_e.delete(0, "end")
        self.cfg["password_stored"] = bool(got.get("password_stored"))
        self._say_password()
        return True

    def _clear(self):
        self._save(clear=True, said="Saved, and the stored password removed.")

    def _test(self):
        to = self.test_e.get().strip()
        if not to:
            self.panel.err.config(text="⚠  An address to send the test "
                                       "to is required.", fg=WARNING)
            return
        if not self._save(said="Saved."):
            return
        got = self.panel._call("post", "/admin/mail/test", {"to": to},
                               "Test mail accepted for %s." % to)
        if got and got.get("status") == "failed":
            # The relay's own words. The request did what it was asked, so
            # this comes back 200 and has to be read off the body rather than
            # off the status - "failed" is the one answer nobody can act on.
            self.panel.err.config(text="✗  " + (got.get("error") or
                                                     "Refused."), fg=DANGER)

    def _rules(self):
        if ui_kit.raise_open("remote_notify_rules") is not None:
            return
        RemoteNotifyRulesWindow(self.panel)


class RemoteClientsPanel:
    """Which installations are out there, and what they have been told. #174.

    The Server GUI's Connected Clients window from somewhere else: the list,
    the certificate each installation says it pins, the commands queued
    against the selected one, and the controls that window offers - **Log Off
    Selected**, **Reset Identity**, **Update Selected** (#177) and **Push
    Certificate**.

    **None of them ends a Windows session**, which the labels say and this
    panel says again above them: `logoff` closes the app down through its own
    quit path, `reset_identity` throws the identifier away so the next
    check-in registers a new installation, `trust_cert` appends a staged
    certificate to the file that installation already pins, and `update_now`
    has that installation apply the published release and restart itself.
    `COMMANDS` is the server's and this window adds nothing to it - a command
    it does not know is refused at `_queue_command`, in that helper's own
    words.

    **Nothing here is a live connection.** A Client is listed because it
    checked in, so the only question the age answers is how long ago, and it
    is coloured the way the console colours it - green inside a quarter of an
    hour, amber inside a day, red past that - because a Notifier that is not
    running is an engineer who is not being asked to confirm anything while
    the store carries on recording movements.

    **The certificate column cannot see an append** (C3), which is stated here
    because the panel would otherwise read as a fleet status: a Client reports
    the fingerprint of the **first** certificate in its pinned file and
    `trust_cert` appends, so what says who has answered a push is the command
    list below, each row staying `queued` until that machine checks in. The
    column answers the other question - who would be stranded if the
    certificate were replaced today - and the line under the list carries the
    whole 95-character value for the selected row, which is where one
    fingerprint is actually compared against another.

    **Push Certificate is not a per-Client control** and needs no selection:
    what it is for is the whole fleet learning to accept a certificate before
    the binding moves, and doing that one machine at a time is how one gets
    missed. It is `POST /clients/push_cert`, a route of its own rather than a
    `client_id` of `*`, so commanding one machine and commanding every machine
    cannot be confused by a field left out.

    It borrows the window for `_call`, `_prompt` and `err`, like the Engineers
    panel, and reaches for `messagebox` nowhere - **nothing here can stop a
    Transaction being confirmed**, which is the rule that window is held to.
    """

    COLS = (("Hostname", 150), ("App", 90), ("Version", 70),
            ("Certificate", 110), ("Engineer", 130), ("Account", 110),
            ("Address", 110), ("Reported Address", 110), ("Last seen", 130))
    CMD_COLS = (("Command", 130), ("Issued", 130), ("By", 200),
                ("Expires", 130), ("State", 90))

    def __init__(self, panel, pane):
        self.panel = panel          # the RemoteAdminWindow
        self.pane = pane
        self.rows = []
        self.served = ""
        self.staged = ""

        ui_kit.rewrap(tk.Label(
            pane,
            text=("A Client is listed because it checked in, so the age is "
                  "how long ago rather than whether it is connected now. "
                  "None of these commands ends a Windows session: Log Off "
                  "closes the app, Reset Identity makes the next check-in a "
                  "new installation, Update applies the published release and "
                  "the app restarts itself with nobody asked, and Push "
                  "Certificate has every machine add the staged certificate "
                  "to the one it already pins - nothing is replaced and "
                  "nothing is bound."),
            bg=CARD, fg=SUBTEXT, font=font("body"), wraplength=640,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(6, 0))

        wrap = tk.Frame(pane, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=20, pady=(8, 0))
        self.tree = ttk.Treeview(
            wrap, columns=[c for c, _w in self.COLS], show="headings",
            style="DB.Treeview", height=7)
        for c, w in self.COLS:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w",
                             stretch=(c == "Hostname"))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        N._tag_clients(self.tree)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._selection())

        # The whole fingerprint, monospace, for the reason the console's own
        # line is there: the column carries two pairs so it fits, and a
        # comparison is made against all of it.
        self.certline = tk.Label(pane, text="", bg=CARD, fg=MONO,
                                 font=font("mono"), anchor="w",
                                 justify="left")
        self.certline.pack(fill="x", padx=20, pady=(6, 0))
        self.count = tk.Label(pane, text="", bg=CARD, fg=SUBTEXT,
                              font=font("body"), anchor="w")
        self.count.pack(fill="x", padx=20, pady=(2, 0))

        tk.Label(pane, text="Commands issued to the selected Client", bg=CARD,
                 fg=SUBTEXT, font=font("emph"),
                 anchor="w").pack(fill="x", padx=20, pady=(10, 2))
        cwrap = tk.Frame(pane, bg=CARD)
        cwrap.pack(fill="x", padx=20)
        self.cmds = ttk.Treeview(
            cwrap, columns=[c for c, _w in self.CMD_COLS], show="headings",
            style="DB.Treeview", height=4)
        for c, w in self.CMD_COLS:
            self.cmds.heading(c, text=c)
            self.cmds.column(c, width=w, anchor="w", stretch=(c == "By"))
        csb = ttk.Scrollbar(cwrap, orient="vertical", command=self.cmds.yview)
        self.cmds.configure(yscrollcommand=csb.set)
        self.cmds.pack(side="left", fill="both", expand=True)
        csb.pack(side="right", fill="y")
        N._tag_clients(self.cmds)

        bar = tk.Frame(pane, bg=CARD)
        bar.pack(fill="x", padx=20, pady=8)
        for text, cmd in (("↻  Refresh", self.reload),
                          ("⏻  Log Off Selected",
                           lambda: self._command("logoff")),
                          ("↺  Reset Identity",
                           lambda: self._command("reset_identity")),
                          ("⬆  Update Selected",
                           lambda: self._command("update_now")),
                          ("⇪  Push Certificate", self._push)):
            tk.Button(bar, text=text, bg=CARD2, fg=TEXT,
                      font=font("body"), relief="flat", cursor="hand2",
                      padx=12, pady=6, activebackground=LINE,
                      command=cmd).pack(side="left", padx=(0, 8))

        self._take(self.panel.cfg.get("clients") or {})

    # -- what the server says ---------------------------------------------
    def reload(self):
        """Re-read the registry and repaint. Called after every command.

        `GET /clients` needs the same credential this panel was opened by -
        it is never open (#174) - so it goes through the window's own `_call`
        rather than a bare `api`, which is the difference from the Asset
        Proposals panel one class up, whose list is a credential-less read.
        """
        got = self.panel._call("get", "/clients", {}, "Re-read.")
        if got is None:
            return
        self._take(got)

    def _take(self, got):
        """Draw what a `GET /clients` body says.

        Split from `reload` because the window already has one: the probe's
        knock on this door **is** the load, so opening the panel costs one
        `remote.action` rather than two, and that body is handed straight
        here through `cfg`.
        """
        self.rows = got.get("clients") or []
        if not isinstance(self.rows, list):
            self.rows = []
        self.served = got.get("served") or ""
        self.staged = got.get("staged") or ""
        keep = (self.tree.selection() or ("",))[0]
        self.tree.delete(*self.tree.get_children())
        for r in self.rows:
            self.tree.insert("", "end", iid=str(r.get("client_id") or ""),
                             tags=(self._age_tag(r.get("age_secs")),),
                             values=(r.get("hostname") or "",
                                     r.get("app") or "",
                                     r.get("version") or "",
                                     self._cert_cell(
                                         r.get("cert_fingerprint") or ""),
                                     r.get("member") or "",
                                     r.get("os_user") or "",
                                     r.get("address") or "",
                                     r.get("reported_address") or "—",
                                     (r.get("last_seen")
                                      or "")[:16].replace("T", "  ")))
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        self._say_counts()
        self._selection()

    def _say_counts(self):
        """How many hold what is being served, and whether anything is staged.

        Both are read off this answer rather than computed here: `served` and
        `staged` are the server's own two fingerprints, and a panel working
        one out for itself would be answering the question with itself.
        """
        if not self.served:
            bits = ["%d installation(s)" % len(self.rows),
                    "this server is serving no certificate"]
        else:
            hold = sum(1 for r in self.rows
                       if (r.get("cert_fingerprint") or "") == self.served)
            bits = ["%d of %d hold the certificate being served"
                    % (hold, len(self.rows))]
        bits.append("a certificate is staged" if self.staged
                    else "nothing is staged")
        self.count.config(text="  ·  ".join(bits))

    @staticmethod
    def _age_tag(secs):
        try:
            secs = float(secs)
        except (TypeError, ValueError):
            return "stale"
        if secs < 900:
            return "fresh"
        if secs < 86400:
            return "today"
        return "stale"

    def _cert_cell(self, held):
        """The console's own cell: a verdict and the last two pairs.

        `—` for a Client that has reported none - nothing pinned is
        nothing to strand - and the pairs alone where this server has no
        certificate at all, since saying NO to every Client about a
        certificate that does not exist would read as a fleet about to be
        stranded.
        """
        if not held:
            return "—"
        tail = ".." + held[-5:]
        if not self.served:
            return tail
        return ("OK  " if held == self.served else "NO  ") + tail

    # -- the selection -----------------------------------------------------
    def _selection(self):
        sel = self.tree.selection()
        row = None
        if sel:
            for r in self.rows:
                if str(r.get("client_id") or "") == sel[0]:
                    row = r
                    break
        self.certline.config(
            text=((row or {}).get("cert_fingerprint")
                  or "No certificate reported by the selected installation."))
        self.cmds.delete(*self.cmds.get_children())
        for c in ((row or {}).get("commands") or []):
            state = c.get("state") or "queued"
            self.cmds.insert("", "end", tags=(state,),
                             values=(c.get("command") or "",
                                     (c.get("issued_at")
                                      or "")[:16].replace("T", "  "),
                                     c.get("issued_by") or "",
                                     (c.get("expires_at")
                                      or "")[:16].replace("T", "  "),
                                     state.title()))
        return row

    # -- the controls ------------------------------------------------------
    def _command(self, command):
        """One command for one Client, through the one writer.

        The refusal is the server's own sentence for `_call`'s reason and for
        this door's in particular: a Client that has never checked in, a
        command already waiting, one this build does not know, an `update_now`
        this server holds no package for and an `update_now` beside a queued
        logoff are five different things to do something about, and
        `_queue_command` words all five.
        """
        row = self._selection()
        if not row:
            self.panel.err.config(
                text="⚠  Select an installation first.", fg=WARNING)
            return
        if not self.panel._prompt(
                N.COMMAND_ASKS[command] % (row.get("hostname")
                                         or row.get("client_id") or "it"),
                "It is collected on that installation's next check-in, and "
                "handed over exactly once. Nothing here ends a Windows "
                "session.", False):
            return
        if self.panel._call("post", "/clients/command",
                            {"client_id": row.get("client_id"),
                             "command": command},
                            "Queued.") is not None:
            self.reload()

    def _push(self):
        """Queue `trust_cert` for every installation that has checked in.

        Deliberately not a per-Client control (C3): every Client rather than
        the ones that are behind, because the certificate column cannot see an
        append and a count off it would be the opposite of a fleet status.
        The duplicate guard in `_queue_command` is what makes a re-push safe -
        a second command while the first is waiting is refused, and the append
        itself is idempotent.
        """
        if not self.panel._prompt(
                "Push Certificate",
                "Every installation that has checked in is told to fetch the "
                "staged certificate and add it to the one it already pins. "
                "Nothing is replaced, nothing is bound, and every client goes "
                "on working. Each row stays queued until that machine checks "
                "in, which is what says who has answered.", False):
            return
        if self.panel._call("post", "/clients/push_cert", {},
                            "Queued for every installation.") is not None:
            self.reload()


class RemoteProposalsPanel:
    """What the Storekeeper is holding, answered from somewhere else. #173.

    The Server GUI's Asset Proposals window narrowed to the pending list: what
    is waiting, and Approve or Reject with a reason. Rejected and approved
    rows are not drawn here - the console keeps them because the record is
    what stops an asset being proposed weekly, and that record is read where
    the register is, while what somebody opens this panel for is the queue.

    **A delivery is one card.** Rows sharing a proposer and a `proposed_at`
    arrived as one file (029), which is a fact those rows already carry rather
    than a column, so they are grouped on it here exactly as the console
    groups on it - and each child keeps its own two buttons, because a
    delivery may be nineteen assets an Admin recognises and one they do not.
    Approving a whole delivery is one click and as many calls as there are
    rows, since the endpoint answers one id: `_decide_proposal` is per row on
    both sides, so a refusal reaches only the row it is about and the rest of
    the file still lands.

    **What this password can do here is the largest thing behind it**, and the
    panel says so on its face: approving writes the register through
    `_save_asset`, so it adds an asset that can then be transacted and, where
    the type is new, one every client afterwards offers. Replacing the sheet
    is not here and is not delegable at all (rule 11).

    It borrows the window for `_call`, `_prompt` and `err`, like the Engineers
    panel, and reaches for `messagebox` nowhere - **nothing here can stop a
    Transaction being confirmed**, which is the rule that window is held to.
    """

    def __init__(self, panel, pane):
        self.panel = panel          # the RemoteAdminWindow
        self.pane  = pane
        self.rows  = []

        ui_kit.rewrap(tk.Label(
            pane,
            text=("Approving writes the Lookup Sheet: the asset can be "
                  "transacted from that moment, and a type nothing else has "
                  "is a type every client is offered. Rejecting keeps the row "
                  "and the reason, which is the whole of what the Storekeeper "
                  "is told. Replacing the sheet is not here - that takes the "
                  "admin password at the console and nothing else."),
            bg=CARD, fg=SUBTEXT, font=font("body"), wraplength=640,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(6, 0))

        head = tk.Frame(pane, bg=CARD)
        head.pack(fill="x", padx=20, pady=(8, 0))
        self.count = tk.Label(head, text="", bg=CARD, fg=TEXT,
                              font=font("heading"))
        self.count.pack(side="left")
        tk.Button(head, text="↻  Refresh", bg=CARD2, fg=TEXT,
                  font=font("micro"), relief="flat", cursor="hand2",
                  padx=10, pady=3, activebackground=LINE,
                  command=self.reload).pack(side="right")

        # Scrolls for the Engineers panel's reason: a card per delivery has no
        # bound, and the window's footer is outside this and packed from the
        # bottom, so Close can be neither squeezed out nor scrolled away.
        wrap = tk.Frame(pane, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=20, pady=(6, 8))
        self.canvas = tk.Canvas(wrap, bg=CARD, highlightthickness=0,
                                height=260)
        bar = ttk.Scrollbar(wrap, orient="vertical",
                            command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=CARD)
        self._window = self.canvas.create_window((0, 0), window=self.body,
                                                 anchor="nw")
        self.body.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(
            self._window, width=e.width))
        self.canvas.bind("<MouseWheel>", self._wheel)

        self.reload()

    # -- what the server says ---------------------------------------------
    def _wheel(self, e):
        """Scroll this list, and only this list (095).

        The window around it scrolls too, bound on the toplevel, and Tk
        delivers the wheel to the canvas and then to the toplevel - so
        without the `"break"` both would move.
        """
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        return "break"

    def reload(self):
        """Re-read the pending list and repaint. Called after every decision.

        `GET /assets/proposals` needs no credential, which is why the panel
        this draws is behind one anyway: what the password opens is the
        decision, and the probe asked the decision door about that rather than
        this one.
        """
        try:
            r = api("get", "%s/assets/proposals?status=pending"
                    % self.panel.server_url, timeout=10)
            self.rows = r.json() if r.ok else []
        except Exception:
            self.rows = []
            self.panel.err.config(text="⚠  Cannot reach the server.",
                                  fg=WARNING)
        if not isinstance(self.rows, list):
            self.rows = []
        for w in list(self.body.winfo_children()):
            w.destroy()
        self.count.config(text=("Nothing is waiting." if not self.rows else
                                "%d waiting on an answer" % len(self.rows)))
        for group in self._deliveries():
            self._card(group)

    def _deliveries(self):
        """The rows grouped as they arrived, newest first.

        A batch has no column of its own: a delivery is every row carrying the
        one `proposed_at` it was stamped with, which is what the console
        groups on and what this reads. Order is the list's own, so a group is
        where its first row sat.
        """
        out, seen = [], {}
        for m in self.rows:
            key = (m.get("proposed_by", ""), m.get("proposed_at", ""))
            if key in seen:
                seen[key].append(m)
            else:
                seen[key] = [m]
                out.append(seen[key])
        return out

    # -- one delivery ------------------------------------------------------
    def _card(self, group):
        card = tk.Frame(self.body, bg=CARD, padx=14, pady=10)
        card.pack(fill="x", pady=(0, 8))

        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x")
        who  = group[0].get("proposed_by") or "somebody"
        when = (group[0].get("proposed_at") or "")[:16].replace("T", " ")
        tk.Label(head,
                 text=("%s  ·  %s" % (who, when) if len(group) == 1 else
                       "%s  ·  %s  ·  %d assets in one delivery"
                       % (who, when, len(group))),
                 bg=CARD, fg=TEXT,
                 font=font("heading")).pack(side="left")
        if len(group) > 1:
            for text, cmd in (("Reject all",
                               lambda: self._decide(group, False)),
                              ("Approve all",
                               lambda: self._decide(group, True))):
                tk.Button(head, text=text, bg=CARD2, fg=TEXT,
                          font=font("micro"), relief="flat", cursor="hand2",
                          padx=10, pady=3, activebackground=LINE,
                          command=cmd).pack(side="right", padx=(6, 0))

        for m in group:
            self._row(card, m)

    # -- one proposal ------------------------------------------------------
    def _row(self, card, m):
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(6, 0))
        # Asset No. and Serial No. first, which is rule 4 and is also the
        # order the console lists them in and the order the form that proposed
        # them asked for.
        bits = [m.get("asset_number") or "—", m.get("serial_number") or "—",
                m.get("asset_type") or "", m.get("asset_model") or ""]
        tk.Label(row, text="   ".join(b for b in bits if b), bg=CARD,
                 fg=SUBTEXT, font=font("body"),
                 anchor="w", justify="left").pack(side="left", fill="x",
                                                  expand=True)
        for text, approve in (("Reject", False), ("Approve", True)):
            tk.Button(row, text=text,
                      bg=(ACCENT if approve else CARD2),
                      fg=("white" if approve else TEXT),
                      font=font("micro"), relief="flat", cursor="hand2",
                      padx=12, pady=3,
                      activebackground=(ACCENT2 if approve else LINE),
                      command=(lambda a=approve, row=m:
                               self._decide([row], a))).pack(side="right",
                                                             padx=(6, 0))

    # -- the decision ------------------------------------------------------
    def _decide(self, group, approve):
        """Approve or reject these rows, one call each.

        The reason is asked **once** for the group, since a delivery is
        refused for one reason, and it is asked before anything is sent: a
        rejection with no reason is refused by the server and the Storekeeper
        would be told nothing either way.

        Each row is its own call, so a refusal reaches only the row it is
        about - which is what the race this has needs: an identifier that got
        into the register while the proposal waited refuses in `_save_asset`'s
        own words and leaves that proposal **pending**, while the rest of the
        delivery still lands.
        """
        reason = ""
        if not approve:
            reason = self.panel._prompt(
                "Reject", "Why? It is the whole of what the Storekeeper is "
                          "told, and the row is kept carrying it.", True)
            if not reason:
                return
        elif len(group) > 1 and not self.panel._prompt(
                "Approve delivery",
                "Approve all %d? Each becomes an asset that can be "
                "transacted, and a type nothing else has is offered to every "
                "client afterwards." % len(group), False):
            return
        done = 0
        for m in group:
            got = self.panel._call(
                "post", "/assets/proposals/decide",
                {"id": m.get("id"), "decision": ("approve" if approve
                                                 else "reject"),
                 "reason": reason},
                "%s %s." % (m.get("asset_number") or m.get("serial_number")
                            or ("#%s" % m.get("id")),
                            "approved" if approve else "rejected"))
            if got is None:
                # The refusal is already on screen in the server's own words.
                # The rows behind it are still tried: this one is about that
                # asset - a duplicate identifier, most likely - and says
                # nothing about the next.
                continue
            done += 1
        if done:
            self.panel.err.config(
                text="✓  %d %s." % (done, "approved" if approve
                                    else "rejected"), fg=SUCCESS)
        self.reload()


class RemoteNotifyRulesWindow:
    """Which System Log events reach a mailbox. #172.

    The Server GUI's Notification Rules window over the wire: one row per
    event, the recipients beside it and the least level that counts, so a rule
    at `warn` passes `warn` and `error` and leaves the ordinary entries alone.

    A window of its own rather than a sixth panel, which is the console's own
    adjacency: it is reached from Mail and it is the same password, but the
    relay and the subscription list are decisions an Admin makes months apart.

    **The event names are typed rather than offered.** The console offers the
    names the log has actually seen, and the first time somebody wants mail
    about `update.failed` that event has by definition never happened - so
    this window names `docs/system-log-events.md` the way that one does,
    which is the whole of what stops a rule being impossible to write.

    It takes **no grab**, like every other question this window asks: a grab
    here would be Remote Admin stopping an engineer answering a popup, which
    is the one thing it must never do.
    """

    def __init__(self, panel):
        self.panel = panel
        self.rows  = []
        self.win = tk.Toplevel(panel.win)
        ui_kit.single(self.win, "remote_notify_rules")
        self.win.title("Notification Rules")
        self.win.configure(bg=BG)
        ui_kit.set_window_icon(self.win)
        ui_kit.escape_closes(self.win, self.win.destroy)

        # The footer first and from the bottom, so Close is the first child
        # served rather than the last - the rule every window in these apps
        # keeps. Packed before the heading above it as well as before the body
        # below it: `pack` serves in the order it was called whichever side a
        # child is on, so a heading and a paragraph packed first take their
        # height out of a short screen before the footer is offered any, and
        # this window's three buttons are what would go.
        foot = tk.Frame(self.win, bg=BG)
        foot.pack(side="bottom", fill="x")
        self.err = tk.Label(foot, text="", bg=BG, fg=SUBTEXT,
                            font=font("body"), anchor="w", wraplength=560,
                            justify="left")
        self.err.pack(fill="x", padx=20, pady=(4, 2))
        tk.Button(foot, text="Save Rules", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=8, command=self._save,
                  activebackground=ACCENT2).pack(fill="x", padx=20,
                                                 pady=(0, 4))
        tk.Button(foot, text="Add a rule", bg=CARD2, fg=TEXT,
                  font=font("body"), relief="flat", cursor="hand2", pady=6,
                  command=self._add,
                  activebackground=LINE).pack(fill="x", padx=20, pady=(0, 4))
        tk.Button(foot, text="Close", bg=CARD2, fg=TEXT,
                  font=font("value"), relief="flat", cursor="hand2",
                  pady=8, command=self.win.destroy,
                  activebackground=LINE).pack(fill="x", padx=20, pady=(0, 12))

        tk.Label(self.win, text="Notification Rules", bg=BG, fg=TEXT,
                 font=font("display")).pack(anchor="w", padx=20,
                                                     pady=(16, 2))
        ui_kit.rewrap(tk.Label(
            self.win,
            text=("One row per System Log event that should reach a mailbox. "
                  "The level is the least that counts. An event that has "
                  "never happened on that server can still be named - a rule "
                  "is a standing instruction, not an assertion that something "
                  "exists - and every name this build can write is in "
                  "docs/system-log-events.md, with what each means and the "
                  "level it is written at."),
            bg=BG, fg=SUBTEXT, font=font("body"), wraplength=560,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(0, 4))
        self.note = tk.Label(self.win, text="", bg=BG, fg=FAINT,
                             font=font("micro"), anchor="w",
                             wraplength=560, justify="left")
        self.note.pack(fill="x", padx=20, pady=(0, 6))

        # The body scrolls, which is the Engineers panel's answer one
        # window over and the console's own Notification Rules one app over: a
        # card per rule has no bound at all, so at 24 rules this asked for
        # 2492px of height and `fit` clamped it to the 1000px a 1080p screen
        # has - 1492px of rules that nothing could reach, the window being
        # draggable on both axes and the screen being what it is. The footer
        # above is outside this region and was packed before it, so Save Rules,
        # Add a rule and Close stay on the screen however many rules there are.
        self.scroll = ui_kit.ScrollRegion(self.win, BG)
        self.body = self.scroll.body
        self.scroll.pack(padx=20, pady=(0, 6))
        self._load()
        self._refit()

    def _refit(self):
        """The region measured beside `fit`, on the same repaint.

        Asked again on every Add and every Remove rather than once at build
        time: this window's children change while it is open, so a size taken
        when it was built is a row short the moment a rule is added.
        """
        self.scroll.size()
        ui_kit.fit(self.win, self.scroll.width(620))

    def _add(self):
        self._row({})
        self._refit()

    def _load(self):
        got = self.panel._call("get", "/admin/notify_rules", {},
                               "Rules loaded.")
        if got is None:
            return
        self.note.config(
            text="At most one mail per event every %d seconds, and %d in "
                 "total per hour across every rule. What a bound held back is "
                 "counted on the next mail that event does send."
                 % (got.get("min_secs", 60), got.get("hourly_max", 60)))
        for r in got.get("rules") or []:
            self._row(r)
        if not self.rows:
            self._row({})

    def _row(self, rule):
        card = tk.Frame(self.body, bg=CARD2, padx=12, pady=8)
        card.pack(fill="x", pady=(0, 6))
        ev = tk.Entry(card, bg=INPUT_BG, fg=TEXT, relief="flat",
                      font=font("value"), insertbackground=TEXT)
        ev.insert(0, str(rule.get("event", "") or ""))
        ev.pack(fill="x", ipady=5)
        line = tk.Frame(card, bg=CARD2)
        line.pack(fill="x", pady=(6, 0))
        to = tk.Entry(line, bg=INPUT_BG, fg=TEXT, relief="flat",
                      font=font("value"), insertbackground=TEXT)
        got = rule.get("to", "")
        to.insert(0, ", ".join(got) if isinstance(got, (list, tuple))
                  else str(got or ""))
        to.pack(side="left", fill="x", expand=True, ipady=5)
        lv = tk.StringVar(value=str(rule.get("level", "info") or "info"))
        ttk.Combobox(line, textvariable=lv, values=["info", "warn", "error"],
                     state="readonly", width=7,
                     font=font("body")).pack(side="left", padx=(8, 0))
        tk.Button(line, text="Remove", bg=CARD2, fg=DANGER,
                  font=font("body"), relief="flat", cursor="hand2",
                  padx=10, command=lambda: self._drop(card),
                  activebackground=LINE).pack(side="left", padx=(8, 0))
        self.rows.append((ev, lv, to, card))

    def _drop(self, card):
        self.rows = [r for r in self.rows if r[3] is not card]
        card.destroy()
        self._refit()

    def _save(self):
        """Send the whole list, which is what the endpoint takes.

        Which rows are dropped and which are refused is the server's, through
        `_save_notify_rules`: a blank row is the one this window opens with
        and is not a mistake to report, where a row with an event and no
        recipient is.
        """
        rules = [{"event": ev.get(), "to": to.get(), "level": lv.get()}
                 for ev, lv, to, _c in self.rows]
        got = self.panel._call("post", "/admin/notify_rules",
                               {"rules": rules}, "Rules saved.")
        if got is None:
            self.err.config(text="✗  Not saved. The panel behind this "
                                 "window says why.", fg=DANGER)
            return
        self.err.config(text="✓  %d rule(s) saved. Applied at once - "
                             "they are read from the file on every entry."
                             % got.get("rules", 0), fg=SUCCESS)


class RemoteCorrectionWindow:
    """Correcting one Pending Transaction from a client (R2).

    The console's Modify Selected form, narrowed to what
    `POST /transactions/modify` takes, and refused in the server's own words:
    only the server knows whether the row is still Pending, and rule 6's
    re-check of a changed identifier against the Lookup Sheet is its as well.
    A field left as it was is not sent, which is the endpoint's own
    convention - anything not sent keeps its value.

    Nothing here can stop a Transaction being confirmed either: no grab, and
    the poll loop and the popup queue never consult it.
    """

    #: The wire shape of `MODIFIABLE`, in the order rule 4 puts it in: the two
    #: identifiers first. A client that calls an endpoint carries that
    #: endpoint's shape - the cascade rule's own row - and the captions are
    #: this window's.
    FIELDS = (("asset_number",  "Asset No."),
              ("serial_number", "Serial No."),
              ("asset_type",    "Asset Type"),
              ("team_member",   "Engineer"),
              ("direction",     "Direction  ·  Out Store or In Store"),
              ("timestamp",     "When  ·  ISO, e.g. 2026-01-31T09:15:00"),
              ("notes",         "Notes"))

    def __init__(self, root, server_url, password, row, on_done=None):
        self.server_url = server_url.rstrip("/")
        self.password   = password
        self.row        = row or {}
        self.on_done    = on_done

        win = tk.Toplevel(root)
        self.win = win
        win.title("Correct Transaction")
        win.configure(bg=BG)
        win.resizable(True, False)
        win.minsize(420, 420)
        # No `-topmost` (#193). Only the confirm/reject popup is always on
        # top in this product, and that is what makes it mean something:
        # a window somebody opened is already in front of them, and one
        # pinned over every other app is one they cannot put down to go
        # and read what it is asking about.

        hdr = tk.Frame(win, bg=ACCENT, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="✎  Correct #%s"
                 % self.row.get("id", ""), bg=ACCENT, fg="white",
                 font=font("title")).pack(side="left", padx=16,
                                                     pady=12)

        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x")
        ui_kit.rewrap(tk.Label(
            win,
            text=("Only a Pending Transaction can be corrected. A Confirmed "
                  "one is the engineer's own answer and the remedy is to "
                  "cancel it and record the movement again."),
            bg=BG, fg=SUBTEXT, font=font("body"), wraplength=400,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(12, 0))

        frm = tk.Frame(win, bg=CARD2, padx=20, pady=12)
        frm.pack(fill="x", padx=20, pady=10)
        self.fields = {}
        for key, caption in self.FIELDS:
            tk.Label(frm, text=caption, bg=CARD2, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 3))
            e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
            e.insert(0, str(self.row.get(key, "") or ""))
            e.pack(fill="x", ipady=6)
            self.fields[key] = e

        self.err = tk.Label(win, text="", bg=BG, fg=DANGER,
                            font=font("body"), wraplength=400,
                            justify="left")
        self.err.pack(anchor="w", padx=20, pady=(2, 0))
        ui_kit.rewrap(self.err, 40)

        tk.Button(foot, text="Save Correction", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=self._submit,
                  activebackground=ACCENT2).pack(fill="x", padx=20,
                                                 pady=(4, 12))
        ui_kit.fit(win, 460)
        ui_kit.escape_closes(win)

    def _submit(self):
        changed = {k: e.get().strip() for k, e in self.fields.items()
                   if e.get().strip() != str(self.row.get(k, "") or "")}
        if not changed:
            self.err.config(text="⚠  Nothing has been changed.",
                            fg=WARNING)
            return
        body = dict(changed, password=self.password,
                    id=self.row.get("id"))
        try:
            r = api("post", "%s/transactions/modify" % self.server_url,
                    json=body, timeout=20)
        except Exception:
            self.err.config(text="⚠  Cannot reach the server. "
                                 "Nothing was changed.", fg=WARNING)
            return
        if not r.ok:
            self.err.config(text="✗  " + _server_words(r),
                            fg=DANGER)
            return
        self.win.destroy()
        if self.on_done:
            self.on_done()


# ─── Settings Window (Admin only) ────────────────────────────────────────────

class SettingsWindow:
    """Server URL, Poll Interval and the two popup timings.

    **No password opens it and no Assigned User is on it** (090). That field
    was the reason for the door - it decided whose Transactions this laptop
    is asked about - and who this is is the logon's question now, asked with
    that engineer's own password (Log off on the tray). What is left is this
    machine's plumbing, so the `url_only` narrowing for an unchecked window
    went with the check: every window is unchecked, and none of it names
    anybody.
    """

    def __init__(self, root, cfg, server_url, on_save):
        win = tk.Toplevel(root)
        ui_kit.single(win, "settings")
        win.title("Notifier Settings")
        win.configure(bg=BG)
        win.resizable(True, False)
        win.minsize(380, 380)
        # No grab: a modal window is how a popup stops being answerable - the
        # one failure this app exists to prevent.
        ui_kit.escape_closes(win)

        # Before the form and from the bottom, so Save is the first child
        # served. This form had 10px to spare of a written 380, which is the
        # next field away from being one of the short ones. See ui_kit.fit.
        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x")

        hdr = tk.Frame(win, bg=ACCENT, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⚙  Notifier Settings",
                 bg=ACCENT, fg="white",
                 font=font("title")).pack(side="left", padx=16, pady=12)

        frm = tk.Frame(win, bg=CARD2, padx=20, pady=16)
        frm.pack(fill="x", padx=20, pady=12)

        def lbl(text):
            tk.Label(frm, text=text, bg=CARD2, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(8, 3))

        lbl("Server URL")
        url_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
        url_e.insert(0, cfg.get("server_url", ""))
        url_e.pack(fill="x", ipady=8)

        lbl("Poll Interval (seconds, %d-%d)" % N.POLL_INTERVAL_RANGE)
        poll_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                          font=font("value"), insertbackground=TEXT)
        poll_e.insert(0, str(cfg.get("poll_interval", 15)))
        poll_e.pack(fill="x", ipady=8)

        # #194. The caption carries the 0 as well as the range, because 0 is
        # the default and is the one value outside the range that is accepted -
        # a field whose caption says 10 to 600 while the box reads 0 is a
        # window arguing with itself.
        lbl("Popup auto-hide (seconds, 0 to never hide, or %d-%d)"
            % N.POPUP_DISMISS_RANGE)
        hide_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                          font=font("value"), insertbackground=TEXT)
        hide_e.insert(0, str(cfg.get("popup_dismiss_secs",
                                     N.DEFAULT_CFG["popup_dismiss_secs"])))
        hide_e.pack(fill="x", ipady=8)

        lbl("Popup comes back after (minutes, %d-%d)" % N.POPUP_REPEAT_RANGE)
        back_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                          font=font("value"), insertbackground=TEXT)
        back_e.insert(0, str(cfg.get("popup_repeat_mins",
                                     N.DEFAULT_CFG["popup_repeat_mins"])))
        back_e.pack(fill="x", ipady=8)

        # An empty label reserves its own line height, so fit() below leaves
        # room for the one line a refusal is. Without it the Save callback
        # raised on int() and the traceback went to a console pythonw.exe does
        # not have: the window stayed open and Save read as dead.
        err_lbl = tk.Label(win, text="", bg=BG, fg=DANGER,
                           font=font("body"))
        err_lbl.pack(padx=20)

        def save():
            # Over the config that is already here rather than a fresh dict: a
            # dict built from these fields drops every key they are not about
            # - current_user, client_id, theme, setup_complete.
            new = dict(cfg)
            new["server_url"] = url_e.get().strip().rstrip("/")
            secs, err = N.validate_interval(poll_e.get().strip()
                                            or N.DEFAULT_CFG["poll_interval"])
            if err:
                # Refused on the window rather than raised: this is a Tk
                # callback, and what the engineer is owed is the sentence
                # naming the bound, not a dialog that stops responding.
                err_lbl.config(text="✗  " + err)
                return
            hide, err = N.validate_dismiss_secs(
                hide_e.get().strip()
                or N.DEFAULT_CFG["popup_dismiss_secs"])
            if err:
                err_lbl.config(text="✗  " + err)
                return
            back, err = N.validate_repeat_mins(
                back_e.get().strip()
                or N.DEFAULT_CFG["popup_repeat_mins"])
            if err:
                err_lbl.config(text="✗  " + err)
                return
            new["poll_interval"] = secs
            new["popup_dismiss_secs"] = hide
            new["popup_repeat_mins"]  = back
            # No password stands in front of this window, so a changed URL
            # is written down: it is the one setting here that decides which
            # server this laptop believes.
            if new["server_url"] != cfg.get("server_url", ""):
                log_event("settings.url_changed",
                          "%s -> %s  ·  no password was checked"
                          % (cfg.get("server_url", ""), new["server_url"]),
                          level="warn", actor=cfg.get("current_user", ""))
            N.save_config(new)
            on_save(new)
            win.destroy()

        tk.Button(foot, text="Save",
                  bg=ACCENT, fg="white",
                  font=font("title"),
                  relief="flat", cursor="hand2",
                  command=save, pady=10).pack(fill="x", padx=20, pady=8)
        ui_kit.fit(win, 430)


