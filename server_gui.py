"""The Server GUI - the Tkinter console that server.py's interactive mode opens.

Lifted out of server.py by #207 (036): 7,689 lines that were one concern with one
entry point, ``run_gui()``, called once from server.py's entry point and reached by
nothing else. The move is verbatim - no window changes size, no dialog changes
wording, no route changes behaviour.

``server_gui`` cannot import ``server`` the way an ordinary module would: source
mode runs server.py as ``__main__`` through ``runpy.run_path`` (``applaunch.py``),
so an ``import server`` in here would execute a **second** copy of the whole
server - its own Flask app, its own SQLite connections, its own background jobs -
rather than reach the one already running. #206 hit the same wall for
``server_cert.py`` and solved it by handing over the handful of names that module
needed through ``bind()``. This module reaches for dozens of server names -
``ADMIN_CFG``, ``PORT``, every ``_save_*``/``_log_*``/``_sync_*`` helper - across
windows that were never written to take them as arguments, so binding them one by
one would just be a second copy of server.py's own globals, drifting the moment
one of them changed. Instead ``bind()`` stores the **module object itself**, and
every reference to a name that stays defined in server.py is written ``S.<name>``,
looked up on that live module at call time - so a test that does
``M.ADMIN_CFG = {...}`` or ``M._gui_snapshot = spy`` is seen by this window exactly
as it was before the move, because ``S`` and ``M`` are the same object.

Every ``tkinter`` import sits inside the function that draws, never at module top
(CODING_STANDARDS "Headless safety") - this module has to import cleanly with no
display, because server.py imports it unconditionally at module level.

**The nine window modules.** #235 (060) took the twelve asset and admin
windows out of here into ``gui_proposals``, ``gui_assets``, ``gui_users``,
``gui_clients``, ``gui_log``, ``gui_backup``, ``gui_mail``, ``gui_records``
and ``gui_settings`` - one module per window, or per pair of windows over the
same table. What is left is the console's shell: the door, the unsaved
tracking, the small readers several windows share, and ``run_gui``, the root
window that opens all twelve. Three of the twelve had been nested inside
``run_gui`` until it had grown to 811 lines and 33 nested definitions; they
read nothing from that scope except the Tk root, so they were ordinary
functions taking it as an argument long before they moved out of the file.

The twelve names are **imported back into this module** rather than reached
through the module that now holds each one. ``run_gui`` calls them the way it
called them the line before this file was split, and so does everything
outside it: server.py re-exports nine of them and ``tools/server-checks.py``
opens six as ``M.<window>``. A window is a function and never moves, so a name
bound at import is the object behind it for the life of the process - which is
what makes this a re-export rather than the snapshot ``bind()`` exists to
avoid.

**None of the nine calls ``bind()``.** server.py calls this module's, once,
before any window opens, and a second door onto the same server module would
be a second thing to keep pointed at the right place. Each of them writes
``from server_gui import S`` as the first line of the window instead - at call
time, because at the moment this file imports them ``S`` is still ``None``,
and because a name looked up then is the live one for the same reason
``S.<name>`` is. That is also why the import of the nine sits below ``THEME``
rather than at the top of this file: they seed their colours at their own
import, so ``THEME`` has to exist by then.

The palette is the one thing they cannot reach through ``S`` at all.
``ui_kit.Theme`` binds it into **this** module's globals, so ``BG`` is a name
here rather than a value to hand over; each of the nine keeps a
``_bind_palette()`` of its own, seeded at import and registered with
``THEME.watch``, which is the shape ``notifier_remote.py`` and
``storekeeper_export.py`` already take. ``font`` goes the ordinary way,
imported from ``ui_kit``, because a theme switch never moves a face.
"""

import os
import re
import socket
import sys
import threading
from datetime import datetime

import ui_kit

S = None


def bind(server_module):
    """Give this module the running server.py, so ``S.<name>`` reads it live.

    Called once, at import, from server.py itself - ``import server_gui;
    server_gui.bind(sys.modules[__name__])``. What is bound is the module
    object, not a snapshot of its names, so a value server.py changes after
    this call (``ADMIN_CFG`` on a save, ``PORT`` on a restart, a test's
    ``M.DB_PATH = ...``) is what every ``S.<name>`` lookup here sees - the same
    guarantee #206's ``server_cert.bind()`` gives by binding each name
    individually, but this module reaches for too many server names for a
    parameter list to be the honest shape of that.
    """
    global S
    S = server_module


# --- The console door --------------------------------------------------------

# Whether the admin password has been proved at this console since the process
# started. A list rather than a bare name so the nested dialogs that read it do
# not each need a `global`, the same shape `_last_sig` and `disp` use in
# run_gui.
_CONSOLE_UNLOCKED = [False]


def _console_unlock(parent, what):
    """Ask for the admin password once, and hold this console open afterwards.

    Server Administration is the door. An Admin proves the password here and
    every control behind it opens without asking again - six windows each
    asking for the same password is a sitting of maintenance spent typing it,
    and four of them were also accepting a credential that was never meant to
    open anything at this console (ADR-0015).

    Held for the life of the **process**, not of a window: the controls are not
    all children of one dialog - the action row reaches Manage Transaction
    History and Import Transaction Archive directly - so a flag scoped to the
    Server Administration window would re-ask the moment it was closed, which
    is the thing this removes. What bounds it is that this is a window on a
    machine somebody has to be standing at, the same argument Display Settings
    asks for nothing on, and nothing here outlives the process.

    Rule 7 is untouched. Change Admin Password still asks for the current
    password inside itself whatever this answered, so an unlocked console is
    never a way to change the credential it was unlocked with.

    A capability password does not open this, and is not offered: it is not a
    console credential (ADR-0015).

    Returns True where the console is open. The only writer of the flag.
    """
    if _CONSOLE_UNLOCKED[0]:
        return True
    import tkinter.messagebox as mb
    pw = simple_password_prompt(
        parent, "Server Administration",
        "%s  The admin password is asked for once. Every control behind "
        "it then opens without asking again, until this server window "
        "is closed."
        % (what,))
    if pw is None:
        return False
    if not S._admin_password_ok(pw):
        mb.showerror("Server Administration",
                     "✗  Incorrect admin password.")
        return False
    _CONSOLE_UNLOCKED[0] = True
    # Worth an entry of its own: after this, every console action is recorded
    # as the Admin with no password behind it, so this line is where the Admin
    # actually proved who they were. _admin_password_ok has already written the
    # refusal for the other answer.
    S._log_event("console.unlocked", what, actor="Admin (Server GUI)")
    return True


def _admin_again(parent, what):
    """Ask for the admin password on this open, whatever the console holds.

    For the two rows whose blast radius is the database itself - Database
    Location, which a wrong value in stops the server starting (ADR-0004),
    and Backup / Restore, which can put a different `admin_config.json` back
    (ADR-0019). `_console_unlock` holds for the sitting; these two ask each
    time, so a console left unlocked is not a console whose database can be
    moved or replaced by whoever walks up to it. The console's own flag is
    neither read nor written here.

    Returns True where the password was the admin one.
    """
    import tkinter.messagebox as mb
    pw = simple_password_prompt(
        parent, what,
        "%s asks for the admin password every time it is opened." % (what,))
    if pw is None:
        return False
    if not S._admin_password_ok(pw):
        mb.showerror(what, "✗  Incorrect admin password.")
        return False
    return True


def _capability_state():
    """Which capabilities have a password of their own.

    Read by the dialog that sets them and by nothing else. It is deliberately
    not published: which actions have been delegated is a map of how this
    server is administered, and no client has any use for it.
    """
    have = S.ADMIN_CFG.get('capability_hashes') or {}
    return {c: bool(have.get(c)) for c in S.CAPABILITIES}


def _capability_holders():
    """The holder name beside each capability, "" for the unnamed ones. R1.

    Beside `_capability_state` rather than folded into it: that one answers
    whether an action has been delegated, which is what the window's pill reads
    and what every existing caller asks, and a shape change there would be a
    second thing to get right in every one of them. Not published either, for
    that function's reason - who holds which credential is a map of how this
    server is administered.
    """
    return {c: S._capability_holder(c) for c in S.CAPABILITIES}


def simple_password_prompt(parent, title, message, caption="Admin password"):
    """Modal password prompt. Returns the entered string, or None if cancelled.

    `caption` names which password is wanted: a capability that can be delegated
    accepts two, and a field captioned "Admin password" would be a lie to
    whoever holds the other one.

    **This is the one password field in these four apps with no show toggle**
    (#202), and it is not an omission: `simpledialog` builds its own entry and
    hands nothing back but the string, so there is no widget here for
    `ui_kit.reveal` to be put on. Anything that wanted one would have to stop
    being a `simpledialog` and become a Toplevel of this file's own, which is a
    window rewritten for a convenience rather than for what it asks.
    """
    from tkinter import simpledialog
    return simpledialog.askstring(title, message + "\n\n" + caption + ":",
                                  show="●", parent=parent)


# ─── Server GUI ───────────────────────────────────────────────────────────────
# ---- Colours, and the theme --------------------------------------------------
# Named constants rather than the literals that used to be inline here, so the
# window and the dialogs behind it cannot drift apart again.
#
# What changed is that they are no longer constants. ui_kit holds the same
# fourteen names in a light table as well; THEME rebinds them, so a widget built
# after a switch is born the right colour, and ui_kit.retint repaints the ones
# built before it. Rebuilding the window instead would destroy whatever is
# selected in Manage Transaction History - which is the table an admin is
# about to delete rows from.

#: Four colours that are this window's own rather than the product's. They were
#: inline hex literals before ui_kit existed, so they are merged into the shared
#: tables rather than added to them.
_EXTRA_DARK = {"SUCCESS_BG":  "#16a34a",   # Import Archive's header and button
               "SUCCESS_HOT": "#15803d",   # ...pressed
               "DANGER_BG":   "#dc2626",   # Delete Records' header and button
               "DANGER_HOT":  "#b91c1c"}   # ...pressed
_EXTRA_LIGHT = {"SUCCESS_BG":  "#166534",
                "SUCCESS_HOT": "#14532d",
                "DANGER_BG":   "#a52017",
                "DANGER_HOT":  "#7f1d1d"}

THEME = ui_kit.Theme(globals(), _EXTRA_DARK, _EXTRA_LIGHT,
                     restyle=lambda root: _style_server_gui(root))

# The fourteen shared names and this app's own four are bound into this
# module by the THEME above, out of ui_kit.DARK merged with the extras it
# was handed - this file writes no second copy of that table. MONO is this
# app's identifiers and addresses, always monospace; FAINT its subtitles,
# row counts and deadlines.


def _tag_ages(tree, names):
    """A Treeview's tag colours, and the hook that re-applies them.

    A tag colour is not a widget option, so ui_kit.retint cannot read it back
    off the widget - a switch would otherwise leave a stale Client's age in the
    dark red, which measures 3.3:1 against a white table.
    """
    for tag, token in names:
        tree.tag_configure(tag, foreground=globals()[token])
    tree._retint_hook = lambda _rev, _new: _tag_ages(tree, names)
    return tree


#: `Pill` was a thin wrapper here rather than a tk.Canvas subclass, because this
#: module has no top-level tkinter and a class body naming tk.Canvas would need
#: one. ui_kit.Pill keeps exactly that shape for exactly that reason, and is now
#: the single copy the two clients share as well - it can also redraw at a width
#: and a palette it was not born with, which is what both halves of this change
#: are built on.
_round_rect = ui_kit.round_rect
Pill = ui_kit.Pill


def _status_of(row):
    # Cancelled first: after the admin path lands, a Confirmed Transaction can be
    # Cancelled too, and what the row then is is cancelled.
    if row["cancelled"]:
        return "cancelled"
    if row["rejected"]:
        return "rejected"
    if row["confirmed"]:
        return "confirmed"
    return "pending"




def _ago_ts(ts):
    """"12m ago" for an ISO timestamp, "" when it cannot be read.

    Taken out of _ago because the Clients list renders last_seen exactly this
    way, and telling a Client seen a minute ago from one last heard from a week
    ago is the whole point of that column.
    """
    s = S._since_ts(ts)
    if s is None:
        return ""
    m = int(s // 60)
    if m < 1:
        return "just now"
    if m < 60:
        return "%dm ago" % m
    if m < 48 * 60:
        return "%dh ago" % (m // 60)
    return "%dd ago" % (m // 1440)


def _when_ts(ts, fmt="%d %b %H:%M"):
    try:
        return datetime.fromisoformat(ts).strftime(fmt)
    except (ValueError, TypeError):
        return str(ts)[:16]


def _ago(row):
    return _ago_ts(row["timestamp"])


def _when(row, fmt="%d %b %H:%M"):
    return _when_ts(row["timestamp"], fmt)


def _client_colour(ts):
    """The one question the Clients list is actually asked: is that machine
    running now, or has nobody heard from it in a week.

    Red for a Client not seen in a day, because a Notifier that is not running
    is an engineer who is not being asked to confirm anything - the store keeps
    working and the verification step quietly stops.
    """
    s = S._since_ts(ts)
    if s is None:
        return FAINT
    if s < 15 * 60:
        return SUCCESS
    if s < 24 * 3600:
        return WARNING
    return DANGER


def _loopback_get(path, ctx=None):
    """GET `path` from this machine's own port: the console's two liveness
    probes, refresh_stats' /stats and Server Settings' /health.

    The parsed body on a 2xx or 3xx, None on any other status, and raises
    when nothing answers. `ctx` is the caller's TLS context; a caller with
    none asks over plain HTTP, through `requests` as it always did.

    HTTPS goes through http.client because `requests` 2.32 cannot be handed
    a context that verifies nothing (#280). `verify` defaults to True, so
    its HTTPAdapter passes cert_reqs=CERT_REQUIRED on every request and
    urllib3 applies that over the context's CERT_NONE: behind IIS on a
    self-signed certificate every tick failed CERTIFICATE_VERIFY_FAILED,
    and the probe captioned a healthy server NOT RESPONDING.
    """
    if ctx is None:
        import requests
        r = requests.get("http://127.0.0.1:%d%s" % (S.PORT, path), timeout=2)
        return r.json() if r.ok else None
    import http.client
    import json
    conn = http.client.HTTPSConnection("127.0.0.1", S.PORT, context=ctx,
                                       timeout=2)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
    finally:
        conn.close()
    return json.loads(body) if resp.status < 400 else None


def _style_server_gui(root):
    """The ttk block the window needs. bordercolor/lightcolor/darkcolor are the
    clam bevel - left at their defaults they draw a pale 3-D box round every
    scrollbar and treeview heading."""
    from tkinter import ttk
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        return
    style.configure("S.Treeview", background=CARD, foreground=TEXT,
                    fieldbackground=CARD, rowheight=28, borderwidth=0,
                    font=font("body"))
    style.configure("S.Treeview.Heading", background=CARD2, foreground=SUBTEXT,
                    relief="flat", borderwidth=0, padding=(6, 8),
                    font=font("emph"))
    style.map("S.Treeview", background=[("selected", ACCENT)],
              foreground=[("selected", "white")])
    style.map("S.Treeview.Heading", background=[("active", CARD2)])
    # Readonly pickers for Add Transaction. Left unstyled, clam draws a pale
    # 3-D box and a white field on a dark card, which is the same defect the
    # bordercolor/lightcolor/darkcolor triple above exists to fix.
    style.configure("S.TCombobox", fieldbackground=INPUT_BG, background=CARD2,
                    foreground=TEXT, bordercolor=LINE, lightcolor=CARD2,
                    darkcolor=CARD2, arrowcolor=SUBTEXT, relief="flat",
                    borderwidth=0, padding=5)
    style.map("S.TCombobox", fieldbackground=[("readonly", INPUT_BG)],
              foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", INPUT_BG)],
              selectforeground=[("readonly", TEXT)])
    style.configure("Vertical.TScrollbar", background=CARD2, troughcolor=BG,
                    bordercolor=BG, lightcolor=CARD2, darkcolor=CARD2,
                    arrowcolor=SUBTEXT, relief="flat", borderwidth=0,
                    arrowsize=12, width=11)


# ─── Unsaved changes, across the windows the console opens ───────────────────
#
# Every writer behind these windows is immediate and goes through one
# enforcement point - `_save_member`, `_save_asset`, `_save_server_cfg`,
# `_set_member_password` - so what is unsaved on one of them is never a staged
# edit of a record. It is text in a field, or a row in a list, that no button
# has been pressed on yet. A staged edit buffer across the console would give
# each of those helpers a second, "pending" write path: two ways to write one
# fact, which is what the cascade rule exists to stop. A flag says the same
# thing and adds no path at all.
#
# It is **read back off the widgets** rather than armed by a <KeyRelease>: a
# flag set when a key goes down is a second copy of what the field already
# says, and it is the copy that is wrong after an undo, a paste, or a save that
# emptied the field - the same reason every state on these windows is derived
# from the table rather than kept beside the widget.
#
# **The window is the whole of it, and 089 is where that was decided.**
# There was a `_console_close` here, and a `_console_unsaved` feeding it:
# `server_administration` took a grab on everything it opened, so its own X
# was the one way to close over a half-typed window, and it answered for that
# by asking about all of them at once. 077 deleted that window and the console
# became the main window, whose close is a hide to the tray - which leaves
# every one of these open and reachable rather than shutting a door on it, so
# the event that behaviour hung on stopped happening. It is not re-homed on
# the hide, which asks a different question from the one it was written to
# ask, and not on `_quit_server`, which ends in `os._exit(0)` after a
# confirmation the operator has already answered: a save-all in front of a
# deliberate hard exit is a decision about what Quit means, and belongs to
# whoever makes that one. What is left is the half that always did the work -
# each window asking on its own way out, by both of its own controls.
_CONSOLE_UNSAVED = []


class _Unsaved(object):
    """One console window: what it is called, and how to ask it two things."""

    def __init__(self, win, label, dirty, save):
        self.win = win
        self.label = label
        self.dirty = dirty
        self.save = save


def _track_unsaved(win, label, dirty, save):
    """Ask before this window closes over something typed into it.

    Returns the close that window's own Close button must use. The title bar's
    X arrives as `WM_DELETE_WINDOW`, which is the window manager's message and
    is delivered whatever grab is held; a button calling `win.destroy` walks
    past every protocol there is, and the two controls that close one window
    must not disagree about whether it asks first.
    """
    entry = _Unsaved(win, label, dirty, save)
    _CONSOLE_UNSAVED.append(entry)

    def forget(event=None):
        # <Destroy> fires for every child as well, so the window itself is what
        # is being listened for.
        if event is not None and event.widget is not win:
            return
        if entry in _CONSOLE_UNSAVED:
            _CONSOLE_UNSAVED.remove(entry)

    def close():
        import tkinter.messagebox as mb
        if entry.dirty():
            answer = mb.askyesnocancel(
                "Unsaved changes",
                "%s has changes that have not been saved.\n\n"
                "Save them now?  No discards them." % label, parent=win)
            if answer is None:
                return
            if answer and not entry.save():
                # The window has already said why, in its own words: it is the
                # one that knows whether the admin password was wrong or the
                # port was not a port. Left open on that answer, because a
                # refusal that closes the window anyway has discarded exactly
                # what the admin asked to keep.
                return
        forget()
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Destroy>", forget, add="+")
    return close


# ─── The twelve windows, in nine modules ─────────────────────────────────────
# Not at the top of the file, and the reason is the docstring's: each of these
# seeds its palette at its own import, so `THEME` has to be built first, and
# three of them reach back at import for a helper defined between the two -
# `_track_unsaved` directly above being the last of them. Nothing below this
# line is read by any of the nine at import; `S` they read at call time, which
# is what lets this import and theirs point at each other with neither having
# to finish first.
from gui_assets import manage_assets
from gui_backup import backup_restore
from gui_clients import client_list
from gui_log import system_log
from gui_mail import mail_settings, notification_rules
from gui_proposals import asset_proposals, asset_sync
from gui_records import (manage_records, _transaction_client,
                         _transaction_log_rows)
from gui_settings import server_settings
from gui_users import capability_passwords, manage_users

#: Which of the header band's four counts the band gives up first when it
#: cannot hold all of them, most-worth-keeping first - so `out of store`
#: is the first to go and `waiting` never does. That last part is not a
#: preference: the band's own comment already states `waiting` is the one
#: count anybody has to do anything about, and this is that sentence made
#: load-bearing rather than restated beside it.
#:
#: **Captions rather than the `/stats` keys** the cells are built from,
#: because a caption is what is on the window: `tools/server_checks/`
#: `console.py` finds a cell by reading its caption back off the real
#: window, and it reads this order off this name - a priority written
#: down in both files is a priority that drifts.
_COUNT_KEEP = ("waiting", "recorded", "cleared", "out of store")


def run_gui():
    """The Server window, on variant I (Split) - six sections and one bar.

    What ships before this is variant O and then E: health leads at a size
    that answers "is it up" from across the room, the counts are numerals
    beside the identifier rather than four tiles, and the window spends itself
    on what the system is doing. None of that is in dispute and none of it
    moves. What does is the other half - how the fourteen dialogs behind this
    window are reached. They were six buttons on a footer row and three more
    behind `Database Location`, which opened the Lookup Sheet, which opened
    Asset Proposals and Asset Sync: an asset is not a filesystem path, and a
    row of six names is not a map of fourteen windows.

    So the fourteen are grouped by the noun an Admin is holding when they go
    looking for one - Overview, Assets, Transactions, People, Clients,
    System - and the group is picked off `ui_kit.SectionBar` (076). Overview
    is the window that was here: the Server URL in the identifier's face, the
    four counts, and the Activity list with the detail beside it. The other
    five are a column of entries, each naming the window behind it.

    The dialogs themselves are deliberately untouched; what changed is where
    they are opened from and, for the two hub menus that held nothing but a
    password and a list of them, that they are not opened from anywhere.
    """
    import tkinter as tk
    from tkinter import messagebox

    # Who owns this process, answered once. Three things in this window used
    # to assume the answer was "we do" - the banner, the tray's Quit and
    # Server Settings - and under IIS each was wrong in its own way, so
    # they read one answer rather than each reaching for the file.
    _iis      = S._iis_host()
    _iis_site = str((_iis or {}).get("site") or "").strip()
    _iis_pool = str((_iis or {}).get("app_pool") or "").strip()
    # An iis.json written before install-iis.ps1 recorded the site name
    # carries an app pool and no site; update.ps1 takes that at its word and
    # so does this. The pool is what Start-WebAppPool needs, so where there
    # is none the line says so rather than naming a control that is a guess.
    _iis_line = ""
    if _iis is not None:
        _iis_line = "Hosted by IIS"
        if _iis_site:
            _iis_line += "  ·  site " + _iis_site
        if _iis_pool:
            _iis_line += ("  ·  Start-WebAppPool / Stop-WebAppPool "
                          + _iis_pool)
        else:
            _iis_line += ("  ·  iis.json records no app pool, so this "
                          "window cannot name what starts and stops it")

    root = tk.Tk()
    root.title("Asset Manager \u2014 Asset Server  v" + S.APP_VERSION)
    root.geometry("1000x680")
    root.minsize(940, 600)
    root.configure(bg=BG)
    _style_server_gui(root)

    def _callback_failed(exc, val, tb):
        """Where a dialog's callback raising ends, instead of nowhere.

        Tk's own handler prints the traceback to stderr, and this window is
        started by pythonw.exe, which has none - so a save that could not
        write its file left the dialog sitting open with nothing said at all,
        and the operator read that as the action being refused. Every file
        this console writes sits in the install directory, so a console
        account without Modify on it is the case this exists for and the one
        the message names: the errno alone says permission denied and does not
        say whose permission, or that nothing was changed.

        It reports and returns rather than re-raising, which is what leaves
        the dialog open with what was typed still in it - the callback is
        already over, and the window is the one thing the operator can act on.
        Everything in it is guarded, because a reporting path that raises is
        the silence it was written to remove.
        """
        import traceback
        try:
            traceback.print_exception(exc, val, tb)
        except Exception:
            pass
        detail = "%s: %s" % (getattr(exc, "__name__", exc), val)
        if isinstance(val, PermissionError):
            detail += ("\n\nNothing was saved and nothing was changed. "
                       "The account this window is running as cannot write in\n"
                       + S.BASE_DIR)
        try:
            S._log_event("console.action_failed", detail[:S._LOG_DETAIL_MAX],
                       actor="Admin (Server GUI)", level="error")
        except Exception:
            pass
        try:
            messagebox.showerror("Asset Server",
                                 "That action did not complete.\n\n" + detail)
        except Exception:
            pass

    root.report_callback_exception = _callback_failed
    # `True`, so the twelve dialogs this window opens inherit it rather than
    # each asking. A Toplevel created before this call would not - there is
    # none; every one of them is opened from a callback.
    ui_kit.set_window_icon(root)

    _tray_icon = [None]
    _minimised_to_tray = [False]

    def _show_window():
        root.after(0, lambda: (root.deiconify(), root.lift(), root.focus_force()))
        _minimised_to_tray[0] = False

    def _hide_window():
        root.after(0, root.withdraw)
        _minimised_to_tray[0] = True

    def _quit_server(*_):
        # Under IIS this window is a monitor: os._exit(0) below closes it and
        # the app pool goes on serving. "Stop the Asset Server?" is
        # then a question this process cannot answer yes to - the operator
        # says yes, the window vanishes, the server is still up - so it asks
        # what it will actually do and names what would really stop it.
        if _iis is not None:
            title = "Close this window"
            question = ("Close the Asset Server status window?\n\n"
                        "IIS owns this process, so this closes the window "
                        "and stops nothing — the server goes on "
                        "serving.\n\n"
                        "To stop it, run on this machine:\n"
                        "    Stop-WebAppPool -Name %s\n"
                        "and Start-WebAppPool to bring it back."
                        % (_iis_pool or "<the app pool in iis.json>"))
        else:
            title, question = "Quit", "Stop the Asset Server?"
        if messagebox.askyesno(title, question):
            if _tray_icon[0]:
                threading.Thread(target=_tray_icon[0].stop, daemon=True).start()
            os._exit(0)

    def _on_close():
        if S.HAS_TRAY:
            _hide_window()
        else:
            _quit_server()

    root.protocol("WM_DELETE_WINDOW", _on_close)

    if S.HAS_TRAY:
        def _build_server_tray():
            def _toggle(*_):
                if _minimised_to_tray[0]:
                    _show_window()
                else:
                    _hide_window()
            menu = S.pystray.Menu(
                S.pystray.MenuItem("📦  Asset Manager  —  Asset Server", None, enabled=False),
                S.pystray.Menu.SEPARATOR,
                S.pystray.MenuItem("🖥  Show / Hide",  _toggle, default=True),
                S.pystray.Menu.SEPARATOR,
                S.pystray.MenuItem("❌  Exit Server",  _quit_server),
            )
            # CHECKING, which is what the banner opens at: nothing has
            # answered on the port yet, so the icon carries no light
            # either. set_health writes both the title and the icon
            # from then on, so the tooltip, the light and the banner
            # cannot hold different answers to the one question this
            # window exists to ask.
            icon = S.pystray.Icon("AssetServer", S._make_server_tray_icon(),
                                "Asset Manager — Asset Server  ●  CHECKING",
                                menu)
            _tray_icon[0] = icon
            icon.run()
        threading.Thread(target=_build_server_tray, daemon=True).start()

    hostname = socket.gethostname()
    try:    local_ip = socket.gethostbyname(hostname)
    except Exception: local_ip = "127.0.0.1"

    # Before any widget exists, so the window is born in the right palette
    # rather than being repainted a moment after it appears.
    THEME.set(ui_kit.read_mode(S._SERVER_CFG))
    THEME.register(root)

    # Who is terminating TLS, rather than what this install's own files say
    # about a listener this process may not have bound - see _iis_tls_bound.
    # Off IIS the expression below is exactly what it was.
    _ssl_active = bool(S._iis_tls_bound() or
                       (S._SERVER_CFG.get('ssl_enabled') and
                        os.path.exists(S.SSL_CERT_PATH) and
                        os.path.exists(S.SSL_KEY_PATH)))
    _proto      = "https" if _ssl_active else "http"
    # The machine's own name, not the literal this used to carry: installed
    # anywhere but asset-server, the URL the card showed and Copy URL handed
    # an operator to give to clients named a machine that is not this one.
    # Not `host` from server_config.json either - that is the bind address,
    # 0.0.0.0 by default, which is not a name anything can be reached by.
    server_url  = f"{_proto}://{hostname}:{S.PORT}"

    # The live display settings. Held in a dict rather than read from
    # _SERVER_CFG on every tick because that is loaded once at import: the
    # dialog below writes the file for the next start *and* updates this, which
    # is what makes a change take effect without a restart.
    disp = {
        "feed_limit": S._validate_range(S._SERVER_CFG.get("feed_limit"),
                                     *S.FEED_LIMIT_RANGE, label="Feed length")[0]
                      or S.FEED_LIMIT_DEFAULT,
        "refresh_secs": S._validate_range(S._SERVER_CFG.get("refresh_secs"),
                                       *S.REFRESH_SECS_RANGE,
                                       label="Refresh interval")[0]
                        or S.REFRESH_SECS_DEFAULT,
    }

    def copy_url():
        root.clipboard_clear()
        root.clipboard_append(server_url)
        say("Copied " + server_url)

    def change_admin_password():
        """Rule 7's one door, and the one child of the console that re-asks.

        An unlocked console does not open this: the admin password is what
        Server Administration was unlocked with, and a window that could change
        it without proving it again would make the unlock permanent for whoever
        was standing here next.
        """
        import tkinter.messagebox as mb
        if ui_kit.raise_open("change_admin_password") is not None:
            return
        dlg = tk.Toplevel(root)
        ui_kit.single(dlg, "change_admin_password")
        dlg.title("Change Admin Password")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(root)

        hdr = tk.Frame(dlg, bg=ACCENT, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🔑  Change Admin Password",
                 bg=ACCENT, fg="white",
                 font=font("title")).pack(side="left", padx=14,
                                                     pady=12)

        # Packed before the fields and from the bottom, so the button is the
        # first child given the space it asked for rather than the last.
        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")

        frm = tk.Frame(dlg, bg=CARD, padx=20, pady=14)
        frm.pack(fill="x", padx=18, pady=14)

        def pw_field(label):
            tk.Label(frm, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 2))
            e = tk.Entry(frm, show="●", bg=INPUT_BG, fg=TEXT,
                         relief="flat", font=font("value"),
                         insertbackground=TEXT)
            e.pack(fill="x", ipady=7)
            ui_kit.reveal(e)
            return e

        cur_e = pw_field("Current Password")
        new_e = pw_field("New Password  (min %d characters)"
                         % S.PASSWORD_MIN)
        cnf_e = pw_field("Confirm New Password")

        err_lbl = tk.Label(dlg, text="", bg=BG, fg=DANGER,
                           font=font("body"))
        err_lbl.pack(pady=(2, 0))

        def do_change():
            cur = cur_e.get()
            new = new_e.get()
            cnf = cnf_e.get()
            if not cur or not new or not cnf:
                err_lbl.config(text="✗  All fields are required.")
                return
            if new != cnf:
                err_lbl.config(text="✗  New password and confirmation do "
                                    "not match.")
                return
            # PASSWORD_MIN, not the 4 it said twice: this is rule 7's only
            # door for the admin password, and that constant exists so the
            # bound is one fact. Left as a literal, raising it would hold
            # every Own Password to the new number and leave the credential
            # each of those is measured against on the old one - the reverse
            # of the drift the constant was introduced to prevent, in the
            # window an admin opens to think about who holds which password.
            if len(new) < S.PASSWORD_MIN:
                err_lbl.config(text="✗  New password must be at least "
                                    "%d characters." % S.PASSWORD_MIN)
                return
            # Deliberately not the console unlock: changing the admin password
            # takes the admin password, whatever opened the console around it.
            # A door that could change the credential it was opened with would
            # be that credential with an extra step.
            if not S._admin_password_ok(cur):
                err_lbl.config(text="✗  Current password is incorrect.")
                return
            S._update_admin_cfg(password_hash=S.hash_password(new),
                              first_run=False)
            S._log_event("admin.password_changed", "from the Server GUI",
                       actor="Admin (Server GUI)", level="warn")
            dlg.destroy()
            mb.showinfo("Done", "✓  Admin password changed successfully.")

        tk.Button(foot, text="Change Password",
                  bg=ACCENT, fg="white", font=font("heading"),
                  relief="flat", cursor="hand2", pady=9,
                  command=do_change,
                  activebackground=ACCENT2).pack(fill="x", padx=18,
                                                 pady=(4, 12))
        ui_kit.fit(dlg, 400)
        cur_e.focus_set()

    def change_db_location():
        """Where assets.db lives.

        Reached from the Database chip in the status card rather than from the
        action row, which is full at five labels, and this is the one fact on
        the chip row an admin can change, so the chip is where they will look
        for it.

        Asks for the admin password on every open (`_admin_again`, 090),
        not once a sitting: a console left unlocked is not one whose database
        can be moved by whoever walks up to it. It has no endpoint that could
        be reached without this console - there is deliberately no db_path
        field on
        POST /admin/server_config, because a remote caller could point a
        running server at a file it cannot read and then not be able to reach
        it again to undo that.

        It never moves the file. Copying a live SQLite database out from under a
        running server can capture a half-written page, and a move would leave
        the -wal and -shm files behind. So the setting points at a file the
        admin has already put there, and the server refuses to start when it is
        not there rather than making an empty one - see _require_db.
        """
        import tkinter.messagebox as mb
        if ui_kit.raise_open("change_db_location") is not None:
            return
        dlg = tk.Toplevel(root)
        ui_kit.single(dlg, "change_db_location")
        dlg.title("Database Location")
        dlg.geometry("620x520")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(root)

        hdrb = tk.Frame(dlg, bg=ACCENT, height=44)
        hdrb.pack(fill="x")
        hdrb.pack_propagate(False)
        tk.Label(hdrb, text="🗄  Database Location",
                 bg=ACCENT, fg="white",
                 font=font("title")).pack(side="left", padx=14, pady=12)

        frmb = tk.Frame(dlg, bg=CARD, padx=20, pady=14)
        frmb.pack(fill="x", padx=18, pady=(14, 8))
        tk.Label(frmb, text="Full path to the database file  (empty = beside the server)",
                 bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(0, 2))
        db_e = tk.Entry(frmb, bg=INPUT_BG, fg=TEXT, relief="flat",
                        font=font("code"), insertbackground=TEXT)
        # Prefilled from the file, not from DB_PATH. A path saved a moment ago
        # and not yet restarted into is what the admin will come back looking
        # for, and showing the in-use path instead makes a second visit look
        # like the first save did not take. The in-use path is a caption
        # beneath, where it cannot be mistaken for the field's value.
        _saved = str(S._load_server_cfg().get("db_path", "") or "").strip()
        db_e.insert(0, _saved)
        db_e.pack(fill="x", ipady=7)
        tk.Label(frmb, text="in use now:  %s" % S.DB_PATH,
                 bg=CARD, fg=FAINT, font=font("mono"),
                 wraplength=520, justify="left").pack(anchor="w", pady=(7, 0))
        tk.Label(frmb, text="default:     %s" % S.DB_DEFAULT_PATH,
                 bg=CARD, fg=FAINT, font=font("mono"),
                 wraplength=520, justify="left").pack(anchor="w", pady=(2, 0))
        _pending = ""
        if _saved:
            _wp, _we = S._validate_db_path(_saved)
            if _we:
                _pending = ("⚠  saved, but not usable - the server will refuse "
                            "to start until this is fixed")
            elif _wp != S.DB_PATH:
                _pending = "⚠  saved, waiting for a restart"
        elif S.DB_PATH != S.DB_DEFAULT_PATH:
            _pending = "⚠  cleared, waiting for a restart"
        if _pending:
            tk.Label(frmb, text=_pending, bg=CARD, fg=WARNING,
                     font=font("micro"), wraplength=520,
                     justify="left").pack(anchor="w", pady=(5, 0))

        tk.Label(dlg, text=("Local drives only. SQLite cannot lock a file over "
                            "SMB, so a UNC path or a mapped drive is refused - "
                            "two writers on one share interleave the file "
                            "instead of queueing."),
                 bg=BG, fg=SUBTEXT, font=font("micro"),
                 wraplength=540, justify="left").pack(padx=18, anchor="w")
        tk.Label(dlg, text=("⚠  Saving does not move the database. Stop the "
                            "server, move the file (and its -wal and -shm "
                            "files, if there are any), then start it again. "
                            "Only the database moves - the lookup sheet, the "
                            "certificate and both config files stay beside the "
                            "server."),
                 bg=BG, fg=WARNING, font=font("micro"),
                 wraplength=540, justify="left").pack(padx=18, pady=(9, 2),
                                                      anchor="w")
        errb = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=font("body"),
                        wraplength=540, justify="left")
        errb.pack(padx=18, anchor="w")

        def do_save_db():
            raw = db_e.get().strip()
            if not raw:
                S._save_server_cfg(db_path="")
                dlg.destroy()
                mb.showinfo("Saved",
                            "✓  The database path is back to the default.\n\n"
                            "%s\n\nRestart the server to apply."
                            % S.DB_DEFAULT_PATH)
                return
            p, err = S._validate_db_path(raw)
            if err:
                errb.config(text="✗  " + err)
                return
            S._save_server_cfg(db_path=p)
            dlg.destroy()
            if os.path.exists(p):
                mb.showinfo("Saved",
                            "✓  Database path saved.\n\n%s\n\n"
                            "Restart the server to apply." % p)
            else:
                # Saved even so. The admin may well be setting the path before
                # moving the file, and refusing would force one ordering onto
                # a job that works either way. But say plainly that the server
                # will not start until the file is there, because the other way
                # to find that out is a restart that fails.
                mb.showwarning("Saved - nothing there yet",
                               "✓  Database path saved.\n\n%s\n\n"
                               "⚠  There is no file at that path yet. Move the "
                               "database there before restarting: the server "
                               "refuses to start while it is missing, rather "
                               "than making an empty one." % p)

        tk.Button(dlg, text="Save  (restart to apply)",
                  bg=ACCENT, fg="white", font=font("heading"),
                  relief="flat", cursor="hand2", pady=9,
                  command=do_save_db,
                  activebackground=ACCENT2).pack(fill="x", padx=18, pady=(10, 4))
        db_e.focus_set()

    def add_transaction():
        """Record a movement that already happened, including a backdated one.

        The gap this closes: only the Storekeeper's client can create a
        Transaction, and only at the moment of the movement, so a movement made
        while the server was down has no way in and the history is quietly
        incomplete.

        It calls _create_transaction, the same function POST /transactions
        calls, so the lookup-sheet rule is the same rule - this window must not
        become the one door an asset absent from the sheet can come through. An
        asset genuinely missing from the sheet is fixed by uploading a sheet
        that has it, not by loosening this.

        The Storekeeper column records the Admin rather than defaulting to
        Storekeeper User. That column is what somebody reaches for when
        reconstructing a dispute, and attributing an Admin's backdated entry to
        the Storekeeper makes it lie in exactly that situation.
        """
        import calendar
        import tkinter.messagebox as mb
        from tkinter import ttk
        if ui_kit.raise_open("add_transaction") is not None:
            return
        dlg = tk.Toplevel(root)
        ui_kit.single(dlg, "add_transaction")
        dlg.title("Add Transaction")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(root)

        hdra = tk.Frame(dlg, bg=ACCENT, height=44)
        hdra.pack(fill="x")
        hdra.pack_propagate(False)
        tk.Label(hdra, text="＋  Add Transaction",
                 bg=ACCENT, fg="white",
                 font=font("title")).pack(side="left", padx=14, pady=12)

        # Packed before the form, and from the bottom: pack order is the order
        # children are given the space they asked for, so the submit button is
        # first in the queue rather than last. Sizing the window to the form
        # makes that rarely matter - but a screen shorter than this dialog
        # cannot be talked out of it, and there the control that closes the
        # dialog is the one thing that must survive.
        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")

        # The form scrolls (095): at 762px it is taller than the 688px a 768px
        # screen leaves once `fit` has clamped it, and pack gives the shortfall to
        # whatever it served last. The footer above is outside the region and was
        # packed before it, so it stays on the screen however short that is.
        scroll = ui_kit.ScrollRegion(dlg, BG)
        body = scroll.body
        scroll.pack(padx=0, pady=0)

        frma = tk.Frame(body, bg=CARD, padx=20, pady=12)
        frma.pack(fill="x", padx=18, pady=(12, 6))

        def field(label, hint=""):
            tk.Label(frma, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 2))
            e = tk.Entry(frma, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
            e.pack(fill="x", ipady=6)
            if hint:
                tk.Label(frma, text=hint, bg=CARD, fg=FAINT,
                         font=font("micro")).pack(anchor="w", pady=(2, 0))
            return e

        def picker(label, values, initial):
            tk.Label(frma, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 2))
            var = tk.StringVar(value=initial)
            cb = ttk.Combobox(frma, textvariable=var, values=list(values),
                              state="readonly", style="S.TCombobox",
                              font=font("value"))
            cb.pack(fill="x")
            return var

        # Asset No. and Serial No. first, in that order - rule 4, and the same
        # order as the Storekeeper's form.
        asset_e  = field("Asset Number")
        serial_e = field("Serial Number",
                         "at least one of the two is required (rule 5)")
        # What the lookup sheet makes of what has been typed so far. It sits
        # under the two identifiers because that is what it is about; what
        # fills it is the resolve block below the pickers, which needs the
        # type picker to exist first.
        resolve_l = tk.Label(frma, text="", bg=CARD, fg=FAINT,
                             font=font("micro"), wraplength=500,
                             justify="left")
        resolve_l.pack(anchor="w", pady=(4, 0))

        conn = S.get_db()
        members = [r["name"] for r in conn.execute(
            "SELECT name FROM team_members ORDER BY name").fetchall()]
        conn.close()

        # Asset Type is not a field somebody fills (#197). Rule 6 corrects it
        # from the lookup sheet on every write, so a picker here offers a
        # choice the server overwrites - a field that lies to whoever typed in
        # it - and the same act through the Storekeeper's door has shown a
        # read-only display since that form was written. The same act through
        # two doors should not offer two different forms, so this is that
        # display: an em dash until an identifier resolves, filled by
        # `do_resolve` below out of `_load_lookup_table()` on the 400ms
        # debounce the two identifiers already share.
        #
        # It is still a `StringVar` called `type_v`, so `do_add` reads the type
        # exactly as it did and `_create_transaction` stays the one writer:
        # what changed is what is offered, never what is enforced. An asset the
        # sheet does not hold leaves it empty and is refused at the helper, the
        # way it always was.
        tk.Label(frma, text="Asset Type  (from the lookup sheet)", bg=CARD,
                 fg=SUBTEXT, font=font("body")).pack(anchor="w", pady=(6, 2))
        type_v = tk.StringVar(value="")
        type_l = tk.Label(frma, text="\u2014", bg=CARD, fg=FAINT, anchor="w",
                          justify="left", font=font("value"))
        type_l.pack(anchor="w", fill="x")

        def _paint_type(*_a):
            """Derived from the variable rather than set beside it.

            `_paint_resolved` one app over, for its reason: a display written
            at each call site is a display that can disagree with the value
            `do_add` is about to send.
            """
            atype = type_v.get()
            type_l.config(text=atype or "\u2014", fg=TEXT if atype else FAINT)

        type_v.trace_add("write", _paint_type)

        # Resolve against the lookup sheet as the admin types - the same 400ms
        # debounce the Storekeeper's form has, for the same reason: typing both
        # identifiers blind and learning on Submit that the sheet does not know
        # the asset is the slowest way to find out.
        #
        # It reads the sheet in process, _load_lookup_table() being in this
        # file. GET /lookup would be this window asking its own Flask a
        # question it is holding the file for, and would stop answering the
        # moment the GUI is the monitor-only one.
        #
        # Nothing here decides anything: _create_transaction still corrects
        # asset number, serial number and type from the sheet, and still
        # refuses an asset the sheet does not know (rule 6). This only shows
        # that verdict while there is still something to do about it.
        resolve_job = [None]

        def do_resolve(q):
            resolve_job[0] = None
            if not resolve_l.winfo_exists():
                return   # the dialog closed inside the debounce
            entry = S._load_lookup_table().get(q.lower())
            if not entry:
                # Back to the em dash: a type left over from an identifier that
                # has since been retyped is the one thing a read-only display
                # can still get wrong.
                type_v.set("")
                resolve_l.config(
                    fg=WARNING,
                    text="!  %s is not in the lookup sheet - the server will "
                         "refuse this one" % q)
                return
            an = entry.get("asset_number", "")
            sn = entry.get("serial_number", "")
            # The sibling is filled only while it is empty. An admin who typed
            # both is corrected by _create_transaction on Submit, which is the
            # rule for mistyped pairs; overwriting them mid-keystroke here
            # would fight the person who is still typing.
            if an and not asset_e.get().strip():
                asset_e.insert(0, an)
            if sn and not serial_e.get().strip():
                serial_e.insert(0, sn)
            # Whatever the sheet says, not only a type this build happens
            # to have served: the sheet is the authority on the list (rule 2),
            # and the display shows what `_create_transaction` will write.
            type_v.set(entry.get("asset_type") or "")
            resolve_l.config(
                fg=SUCCESS,
                text="✓  %s  ·  %s  ·  asset %s  ·  serial %s"
                     % (entry.get("asset_model") or "no model",
                        entry.get("asset_type") or "—",
                        an or "—", sn or "—"))

        def schedule_resolve(src):
            if resolve_job[0]:
                dlg.after_cancel(resolve_job[0])
                resolve_job[0] = None
            q = src.get().strip()
            if len(q) < 2:
                type_v.set("")
                resolve_l.config(fg=FAINT, text="")
                return
            resolve_job[0] = dlg.after(400, lambda: do_resolve(q))

        asset_e.bind("<KeyRelease>", lambda _e: schedule_resolve(asset_e))
        serial_e.bind("<KeyRelease>", lambda _e: schedule_resolve(serial_e))

        member_v = picker("Engineer", members, members[0] if members else "")
        dir_v    = picker("Direction", ("Out Store", "In Store"), "Out Store")
        # When it happened, picked rather than typed (#197). A text field
        # holding `YYYY-MM-DD HH:MM` is a format to get right at the one moment
        # the admin is already reconstructing a movement from memory, and all
        # it buys is that each wrong spelling of a date is refused after the
        # fact rather than not offered.
        #
        # **Built out of `tk`/`ttk` rather than a calendar widget from PyPI**:
        # `requirements-server.txt` feeds a vendored `lib\` pinned to one Python
        # minor version (rule 13), so a dependency added for one dialog is one
        # every release has to go on building and one more thing that can stop
        # an install starting. Three comboboxes and two spinboxes cost nothing
        # and refuse an impossible date by not offering one, which is the whole
        # of what a calendar would buy here - this is a date somebody already
        # knows rather than one they are choosing off a month.
        tk.Label(frma, text="When it happened", bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(6, 2))
        whenf = tk.Frame(frma, bg=CARD)
        whenf.pack(fill="x")
        _now = datetime.now()
        year_v  = tk.StringVar(value="%04d" % _now.year)
        month_v = tk.StringVar(value="%02d" % _now.month)
        day_v   = tk.StringVar(value="%02d" % _now.day)
        hour_v  = tk.StringVar(value="%02d" % _now.hour)
        min_v   = tk.StringVar(value="%02d" % _now.minute)

        def _part(var, values, width):
            cb = ttk.Combobox(whenf, textvariable=var, values=values,
                              state="readonly", style="S.TCombobox",
                              width=width, font=font("value"))
            cb.pack(side="left", padx=(0, 6))
            return cb

        # Back five years and no further forward than this one: a future time
        # is refused below, so a year nothing may be dated in is a year not
        # worth offering.
        _part(year_v, ["%04d" % y
                       for y in range(_now.year - 5, _now.year + 1)], 6)
        _part(month_v, ["%02d" % m for m in range(1, 13)], 4)
        day_cb = _part(day_v, ["%02d" % d for d in range(1, 32)], 4)

        def _spin(var, hi):
            # Values rather than `from_`/`to`, so every entry is zero-padded by
            # construction and `readonly` leaves nothing to be typed into it -
            # the two together are what make the string below unparseable only
            # if this file is wrong.
            sp = ttk.Spinbox(whenf, textvariable=var,
                             values=["%02d" % n for n in range(hi + 1)],
                             width=4, wrap=True, state="readonly",
                             font=font("value"))
            sp.pack(side="left", padx=(0, 6))
            return sp

        _spin(hour_v, 23)
        tk.Label(whenf, text=":", bg=CARD, fg=SUBTEXT,
                 font=font("value")).pack(side="left", padx=(0, 6))
        _spin(min_v, 59)

        def _days_in_month(*_a):
            """Offer only the days the picked month actually has.

            February is why: a date that does not exist refused after the fact
            is exactly what a picker is here to replace, so 30 February is not
            offered rather than refused - and a day already picked past the end
            of a newly picked month moves back to the last one that exists,
            since silently keeping it would be the same impossible date one
            widget over.
            """
            try:
                y, m = int(year_v.get()), int(month_v.get())
            except ValueError:
                return
            last = calendar.monthrange(y, m)[1]
            day_cb.config(values=["%02d" % d for d in range(1, last + 1)])
            try:
                if int(day_v.get()) > last:
                    day_v.set("%02d" % last)
            except ValueError:
                day_v.set("01")

        year_v.trace_add("write", _days_in_month)
        month_v.trace_add("write", _days_in_month)
        _days_in_month()

        tk.Label(frma, text="backdating is the point; the future is refused",
                 bg=CARD, fg=FAINT,
                 font=font("micro")).pack(anchor="w", pady=(2, 0))

        notes_e  = field("Notes  (optional)")

        tk.Label(body, text=("⚠  A backdated Transaction left Pending for more "
                            "than 24 hours is confirmed by the Auto-Accept job "
                            "on its next hourly pass - date it more than a day "
                            "ago and the Engineer will not be asked."),
                 bg=BG, fg=WARNING, font=font("micro"),
                 wraplength=520, justify="left").pack(padx=18, pady=(8, 2),
                                                      anchor="w")
        erra = tk.Label(body, text="", bg=BG, fg=DANGER, font=font("body"),
                        wraplength=520, justify="left")
        erra.pack(padx=18, anchor="w")

        def do_add():
            # No password here: the Add Transaction entry asked for it at the
            # door (096), Backup / Restore's shape.
            # The five parts rather than a typed line (#197). Every one of
            # them is `readonly` and offered from a list, so the only way this
            # does not parse is a fault in this file - kept as an answer rather
            # than an exception for the reason every other refusal here is one:
            # the dialog stays open with what was picked still in it.
            raw = "%s-%s-%s %s:%s" % (year_v.get(), month_v.get(), day_v.get(),
                                      hour_v.get(), min_v.get())
            try:
                stamp = datetime.strptime(raw, "%Y-%m-%d %H:%M")
            except ValueError:
                erra.config(text="✗  %s is not a date." % raw)
                return
            if stamp > datetime.now():
                # A movement that has not happened yet is not a record of
                # anything, and it would sit in Pending outside the 24h window
                # for as long as the date is in the future.
                erra.config(text="✗  That time is in the future. A Transaction "
                                 "records a movement that has already happened.")
                return
            payload, status = S._create_transaction({
                "asset_type":    type_v.get(),
                "asset_number":  asset_e.get().strip(),
                "serial_number": serial_e.get().strip(),
                "team_member":   member_v.get(),
                "direction":     dir_v.get(),
                "notes":         notes_e.get().strip(),
                # Not the Storekeeper. See the docstring.
                "storekeeper":   "Admin (Server GUI)",
                # And the log says the same, rather than the column being
                # dressed with a role this caller does not hold.
            }, timestamp=stamp.isoformat(), actor="Admin (Server GUI)")
            if status != 201:
                erra.config(text="✗  " + payload.get("error", "Refused."))
                return
            dlg.destroy()
            mb.showinfo("Added",
                        "✓  Transaction #%d recorded as %s.\n\n%s  ·  %s  ·  %s"
                        % (payload["id"],
                           "Confirmed (the Engineer is Auto-Approve)"
                           if payload["auto_approved"] else "Pending",
                           member_v.get(), dir_v.get(),
                           stamp.strftime("%Y-%m-%d %H:%M")))

        tk.Button(foot, text="Add Transaction",
                  bg=ACCENT, fg="white", font=font("heading"),
                  relief="flat", cursor="hand2", pady=9,
                  command=do_add,
                  activebackground=ACCENT2).pack(fill="x", padx=18, pady=(10, 12))

        scroll.size()
        ui_kit.fit(dlg, scroll.width(580))
        asset_e.focus_set()

    # ─── Import Archive ───────────────────────────────────────────────────────
    def change_display_settings():
        """How much of the feed to show, and how often to redraw it.

        Deliberately not in the Server Settings window: that one warns that
        a restart is needed, which is true of the bind address and false of
        these two. One dialog carrying both would have to either drop the
        warning or apply it to settings it does not apply to.
        """
        import tkinter.messagebox as mb
        if ui_kit.raise_open("change_display_settings") is not None:
            return
        dlg = tk.Toplevel(root)
        ui_kit.single(dlg, "change_display_settings")
        dlg.title("Display Settings")
        dlg.geometry("420x430")
        dlg.configure(bg=BG)
        dlg.resizable(True, False)
        dlg.minsize(380, 430)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(root)

        hdrd = tk.Frame(dlg, bg=ACCENT, height=44)
        hdrd.pack(fill="x")
        hdrd.pack_propagate(False)
        tk.Label(hdrd, text="📊  Display Settings",
                 bg=ACCENT, fg="white",
                 font=font("title")).pack(side="left", padx=14, pady=12)

        frmd = tk.Frame(dlg, bg=CARD, padx=20, pady=14)
        frmd.pack(fill="x", padx=18, pady=14)

        def field(label, val):
            tk.Label(frmd, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 2))
            e = tk.Entry(frmd, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
            e.insert(0, str(val))
            e.pack(fill="x", ipady=7)
            return e

        feed_e = field("Feed length  (%d–%d Transactions)" % S.FEED_LIMIT_RANGE,
                       disp["feed_limit"])
        secs_e = field("Refresh interval  (%d–%d seconds)" % S.REFRESH_SECS_RANGE,
                       disp["refresh_secs"])

        # **The theme is not here any more** (090). It is the pill on the app
        # bar, the Storekeeper's shape: it is about the window rather than
        # the feed, and a control about the window is on the window.

        # rewrap: this dialog's width drags, so 360 is the floor and the rest
        # comes from the dialog. No padx on the pack, so no inset.
        ui_kit.rewrap(tk.Label(
            dlg, text="Applied on the next refresh. No restart needed.",
            bg=BG, fg=SUBTEXT, font=font("micro"),
            wraplength=360)).pack(pady=(0, 2))
        errd = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=font("body"))
        errd.pack()

        def do_save_disp():
            limit, err = S._validate_range(feed_e.get(), *S.FEED_LIMIT_RANGE,
                                         label="Feed length")
            if err:
                errd.config(text="✗  " + err)
                return
            secs, err = S._validate_range(secs_e.get(), *S.REFRESH_SECS_RANGE,
                                        label="Refresh interval")
            if err:
                errd.config(text="✗  " + err)
                return
            S._save_server_cfg(feed_limit=limit, refresh_secs=secs)
            disp["feed_limit"], disp["refresh_secs"] = limit, secs
            _last_sig[0] = None          # force one repaint at the new length
            refresh_feed()
            dlg.destroy()
            say("Feed shows %d, refreshing every %ds." % (limit, secs))

        tk.Button(dlg, text="Save", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=do_save_disp,
                  activebackground=ACCENT2).pack(fill="x", padx=18, pady=(0, 12))
        feed_e.focus_set()

    def import_archive():
        import tkinter.messagebox as mb
        import tkinter.filedialog as fd
        if not _console_unlock(root, "Import Transaction Archive"):
            return
        path = fd.askopenfilename(parent=root, title="Open records archive",
                                  filetypes=[("Excel archive", "*.xlsx")])
        if not path:
            return
        try:
            n, refusal = S._import_records_xlsx(path, actor="Admin (Server GUI)")
        except Exception as ex:
            mb.showerror("Import Archive", f"✗  Import failed: {ex}")
            return
        if refusal:
            mb.showerror("Import Archive", f"✗  {refusal}")
            return
        mb.showinfo("Import Archive", f"✓  Imported {n} record(s) from the archive.")

    def _proposals_caption():
        """The Asset Proposals row's subtitle: what is waiting, counted now.

        Off the same `_load_proposals("pending")` the window's own line reads,
        so the row and the window cannot disagree about the number."""
        n = len(S._load_proposals("pending"))
        return ("nothing waiting on an answer" if not n
                else "%d waiting on an answer" % n)

    def open_proposals():
        """Asset Proposals, as a window over the console (090).

        `asset_proposals` builds the list unchanged; this is the Toplevel
        086 took away from it, and what goes with being one comes back -
        single, Escape, transient, and a size taken from the children."""
        if ui_kit.raise_open("asset_proposals") is not None:
            return
        win = tk.Toplevel(root)
        ui_kit.single(win, "asset_proposals")
        win.title("Asset Proposals")
        win.configure(bg=CARD)
        win.transient(root)
        ui_kit.escape_closes(win)
        lst = asset_proposals(win)
        lst.pack(fill="both", expand=True, padx=18, pady=(0, 6))
        lst._ui_reload()
        ui_kit.fit(win, 720)

    # -- the seven sections, and the bar that picks which one is on ---------
    # Variant I, the arrangement pass 3 chose (`prototypes/NOTES-3.md`,
    # 2026-09-22). The console's fourteen windows are grouped by the noun an
    # Admin is holding when they go looking for one, and the group is picked
    # off `ui_kit.SectionBar` rather than remembered. What it replaces is six
    # footer buttons with three of the fourteen behind `Database Location` -
    # the Lookup Sheet opened from it, and Asset Proposals and Asset Sync
    # opened from that again. An asset is not a filesystem path.
    #
    # **The two hub menus are gone rather than moved.** `server_administration`
    # and `lookup_sheet_menu` were each a password at a door and a column of
    # entries behind it; the bar is that column six times over, so what was
        # left of either was the door. The password did not go with them: an entry
    # that opens a window is marked `"admin"` below and asks `_admin_again`
    # on every open, and the window behind it asks nothing again (096) -
    # Backup / Restore's shape. `True`, `_console_unlock` once a sitting, is
    # left on Import Transaction Archive, beside the history pane that
    # shares that door (ADR-0015).
    #
    # **And the action row is gone.** It named six of the fourteen windows and
    # measured itself against the width it had; the bar names all six groups
    # at a width that does not depend on how many windows are in one, and an
    # entry carries its own subtitle on its own row.
    # **Manage Transaction History is not an entry** (088): it is the list
    # under the rows Transactions keeps, named in `LISTED` below rather than
    # here. Asset Proposals and the System Log were lists under rows too
    # (086, 087) and 090 took both out again: Asset Proposals is a row on
    # Assets that opens a window, its count the row's subtitle, and the
    # System Log is a section of its own, the Clients shape.
    #
    # Manage Transaction History sits under Add Transaction and Import
    # Transaction Archive, and is the one of the three with a door: until the
    # console is unlocked the pane is a single gated row where the table
    # will be.

    # name, and what is in it. A subtitle is a sentence or a callable that
    # counts something - `show_section` reads the callable each time the
    # section is opened, so a count is the answer now rather than the answer
    # when this window was built. `gated` is the console door, and it is the
    # entry that carries it now that neither hub is there to.
    SECTIONS = (
        ("Overview", ()),
        ("Assets", (
            ("Lookup Sheet", "add, correct or remove an asset",
             "admin", lambda: manage_assets(root)),
            ("Asset Sync", "the external system this register reads from",
             "admin", lambda: asset_sync(root)),
            # A row that opens a window again (090), not the pane under the
            # two above: the count is the subtitle, read each time Assets is
            # opened, so what is waiting is still read by arriving here.
            ("Asset Proposals", _proposals_caption,
             "admin", open_proposals),
        )),
        ("Transactions", (
            # **And Manage Transaction History is not an entry** (088). It
            # is the list under the two that are left, named in `LISTED`
            # below, and it carries its own door: the table is behind
            # `_console_unlock` inside the pane, where a gated row stands in
            # for it until the console is open.
            #
            # Off the Activity header and into its own section. It was beside
            # the feed on the argument that it is done while looking at one;
            # what that cost was a second door to a window the bar now names
            # in the group it belongs to, and the grouping is the point.
            ("Add Transaction", "a movement this console logs itself",
             "admin", add_transaction),
            ("Import Transaction Archive",
             "restore records from an .xlsx archive",
             True, import_archive),
        )),
        ("People", (
            # First, and still the one entry that asks again once it is open:
            # rule 7 - the credential this console was unlocked with is never
            # the credential an unlocked console can change.
            ("Change Admin Password",
             "the current one, then the new one twice",
             True, change_admin_password),
            ("Capability Passwords",
             "a credential for administering this server remotely",
             "admin", lambda: capability_passwords(root)),
            ("Manage Users",
             "the Engineers, the Admin and the Storekeeper",
             "admin", lambda: manage_users(root)),
        )),
        # No entries, because the section **is** the pane: Connected Clients
        # was the whole of the Clients group and became the Clients stage
        # itself with 085, so there is no row left to click and no hover line
        # left to count for. The door went with the row - it was
        # `_console_unlock` on the entry, and a pane that is already on the
        # stage has no moment at which to ask. What that costs is the one
        # deliberate thing this ticket gives up: the console's own admin
        # password is what opens the console, and reading which installations
        # have checked in is now inside it rather than one question further
        # in. Sending a command to one of them is not - Send Command is still
        # a dialog, and what it sends still goes to somebody else's machine.
        ("Clients", ()),
        ("System", (
            ("Server Settings",
             "host, port and the certificate clients pin",
             "admin", lambda: server_settings(root)),
            ("Display Settings",
             "feed length and refresh rate, applied at once",
             False, change_display_settings),
            # ADR-0004's setting, and the one a wrong value in stops the
            # server starting - so it asks for the admin password on every
            # open ("admin", `_admin_again`), not once a sitting (090).
            ("Database Location", "where the database sits",
             "admin", change_db_location),
            ("Mail Settings",
             "where this server sends from, and the password it replays",
             "admin", lambda: mail_settings(root)),
            # Reachable from Mail Settings as well, which is where the rules
            # are read against the account that sends them. Named here too
            # because it is one of the fourteen and the bar names all of them.
            ("Notification Rules",
             "which System Log entries reach a mailbox",
             "admin", lambda: notification_rules(root)),
            # And this one on every open too: it can put a different
            # database and `admin_config.json` back (ADR-0019).
            ("Backup / Restore",
             "a copy of this install, and putting one back",
             "admin", lambda: backup_restore(root)),
        )),
        # **The System Log is a section of its own** (090), the Clients shape:
        # no entries, the section is the pane. It asks for no password, for
        # the reason Display Settings does not: it shows what this console
        # already holds and changes nothing. Clear, the one door inside it
        # that does, still asks for the admin password.
        ("System Log", ()),
    )

    # -- the app bar: what this is, and whether it is up --------------------
    # The status word and its block are here and not on Overview, where the
    # banner they came off used to be. Whether this server is answering is the
    # one fact somebody wants while they are in Mail Settings or Manage Users,
    # and a second copy of it on Overview is exactly what the cascade rule
    # says a fact written down twice becomes. The Server URL stays on Overview
    # for the opposite reason: it is read a character at a time and pasted
    # into a client, which is not something done in passing.
    appbar = tk.Frame(root, bg=BG)
    appbar.pack(fill="x")
    ainner = tk.Frame(appbar, bg=BG, padx=24, pady=12)
    ainner.pack(fill="x")
    tk.Label(ainner, text="Asset Manager", bg=BG, fg=TEXT,
             font=font("emph", size=12)).pack(side="left")
    tk.Label(ainner, text="Asset server, %s" % hostname, bg=BG, fg=SUBTEXT,
             font=font("body")).pack(side="left", padx=(14, 0))
    # Packed from the right in the order they read leftwards, so the line
    # beside the block is the one that grows and the block does not move.
    live_lbl = tk.Label(ainner, text="", bg=BG, fg=SUBTEXT, font=font("body"))
    live_lbl.pack(side="right")
    status_word = tk.Label(ainner, text="CHECKING", bg=BG, fg=SUBTEXT,
                           font=font("emph", size=9))
    status_word.pack(side="right", padx=(8, 8))
    # A block rather than a dot: every mark on this window is a rectangle,
    # and the direction gutter in the list below is the same shape.
    dot_cv = tk.Canvas(ainner, width=8, height=8, bg=BG,
                       highlightthickness=0)
    dot_id = dot_cv.create_rectangle(0, 0, 8, 8, fill=SUCCESS, outline="")
    dot_cv.pack(side="right")

    # Dark, light or whatever Windows is set to, cycled in place - the
    # Storekeeper's control, in the Storekeeper's place (090). It was three
    # pills inside Display Settings; it is about this window and nothing
    # else, so it is on this window, and it asks for no password.
    def _paint_theme_btn():
        """The icon is the theme in force, the caption the setting behind it:
        "Follow Windows" resolved to dark and a plain "Dark" are two facts."""
        icon = "\u2600" if THEME.active == "light" else "\u263e"
        theme_btn.set_text(icon + "  " + ui_kit.MODE_LABELS[THEME.mode])
        theme_btn.fit_text()

    def _cycle_theme():
        modes = ui_kit.MODES
        mode = modes[(modes.index(THEME.mode) + 1) % len(modes)]
        THEME.set(mode)
        S._save_server_cfg(theme=mode)
        # After the retint: that walk repaints the pill in the new palette,
        # and which icon belongs on it is not a colour it can work out.
        _paint_theme_btn()

    theme_btn = Pill(ainner, "", BG, CARD2, LINE, fg=TEXT, w=158, h=30,
                     bold=False, command=_cycle_theme)
    theme_btn.pack(side="right", padx=(0, 16))
    _paint_theme_btn()

    # -- the line a section entry talks through ----------------------------
    # Packed before the stage and from the bottom, so a section with more
    # entries than fit cannot push it off the edge - which is the same reason
    # the action row was packed here before it.
    tail = tk.Frame(root, bg=BG)
    tail.pack(fill="x", side="bottom", padx=22, pady=(6, 8))
    status_line = tk.Label(tail, text="", bg=BG, fg=FAINT,
                           font=font("body"), anchor="w", justify="left")
    status_line.pack(fill="x")

    def say(text):
        status_line.config(text=text)

    # -- the stage the bar swaps ------------------------------------------
    panes = {}
    #: Per section, the `(label, subtitle)` pairs whose subtitle is a callable
    #: and has to be asked again each time the section is opened.
    counted = {}

    def show_section(name):
        """Put one section on the stage, and no other.

        `pack_forget` rather than a rebuild, `ui_kit.retint`'s reason one
        level up: a section rebuilt on every visit would take whatever is
        selected in it with it, and the Activity list on Overview is selected
        by definition - it restores the row the admin was reading.
        """
        pane = panes.get(name)
        if pane is None:
            return
        for key, frame in panes.items():
            if key != name:
                frame.pack_forget()
        for cap, subtitle in counted.get(name, ()):
            if cap.winfo_exists():
                cap.config(text=subtitle())
        # A pane that is the list rather than a row naming one says so, and
        # is asked to re-read before it is shown. The entry sections get the
        # same freshness out of the loop above, which asks each callable
        # subtitle again; this is that question for a section whose whole
        # content is the answer.
        reload_ = getattr(pane, "_ui_reload", None)
        if reload_ is not None:
            reload_()
        pane.pack(fill="both", expand=True)

    stage = tk.Frame(root, bg=CARD)
    stage.pack(fill="both", expand=True)

    def section_pane(name, entries, listed=None):
        """What a section that is not Overview holds: one row per window.

        And, since 088, a **list under them** where `listed` names a builder:
        Transactions carries Add Transaction and Import Transaction Archive
        and the history table beneath - which is what a section with more
        than one thing in it does with the one of them that is a list. The
        System Log comes through here with no rows (090), so its list is the
        whole section under the heading every section carries. Clients is
        not built through here at all - its list is `client_list`'s own form.

        The pane is the door and it names what is behind it rather than making
        the operator remember, which is the whole of what the fourteen windows
        were missing when six of them were on a footer and three were three
        dialogs deep.
        """
        pane = tk.Frame(stage, bg=CARD)
        inner = tk.Frame(pane, bg=CARD, padx=24, pady=18)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=name, bg=CARD, fg=TEXT,
                 font=font("section")).pack(anchor="w")
        tk.Frame(inner, bg=LINE, height=1).pack(fill="x", pady=(9, 0))
        asked = []
        for label, subtitle, gated, command in entries:
            row = tk.Frame(inner, bg=INPUT_BG)
            # Which section this row is on, read from outside this window.
            # `ListPane` stamps `_ui_list_row` for the same reason and it is
            # the same problem one shape along: a bound frame on this console
            # is a status chip unless it says otherwise, and the sweep in
            # `tools/server-checks.py` that opens every chip it can find has
            # to put a row's own section on the stage before it can click it.
            row._ui_section_row = name
            row.pack(fill="x", pady=(9, 0))
            pad = tk.Frame(row, bg=INPUT_BG, padx=16, pady=11)
            pad.pack(fill="x")
            tk.Label(pad, text=label, bg=INPUT_BG, fg=TEXT,
                     font=font("label")).pack(side="left")
            tk.Label(pad, text="Open", bg=INPUT_BG, fg=SUBTEXT,
                     font=font("micro")).pack(side="right")
            cap = tk.Label(pad, text="" if callable(subtitle) else subtitle,
                           bg=INPUT_BG, fg=SUBTEXT, font=font("micro"))
            cap.pack(side="left", padx=(16, 0))
            if callable(subtitle):
                asked.append((cap, subtitle))

            def go(_e=None, fn=command, g=gated, what=label):
                # The door, on the entry rather than on a menu in front of it.
                # `_console_unlock` is scoped to this process, so the first
                # gated entry of a sitting asks and none after it does.
                if g == "admin":
                    if not _admin_again(root, what):
                        return
                elif g and not _console_unlock(root, what):
                    return
                fn()

            # "a password", not "the admin password": four of these open on a
            # capability password as well (ADR-0006), and naming the admin one
            # here would tell a delegate their password is the wrong one
            # before they had tried it.
            def enter(_e=None, c=cap, g=gated):
                say(c.cget("text")
                    + (" - asks for a password" if g else ""))

            # Bound on every child rather than on the row alone, `ListPane`'s
            # reason: the labels sit on top of it, so a click on the name
            # would otherwise land on a widget with no binding - which is
            # where a person actually aims.
            def clickable(w):
                w.configure(cursor="hand2")
                w.bind("<Button-1>", go)
                w.bind("<Enter>", enter, add="+")
                for child in w.winfo_children():
                    clickable(child)
            clickable(row)
        counted[name] = tuple(asked)
        if listed is not None:
            lst = listed(inner)
            lst.pack(fill="both", expand=True, pady=(14, 0))
            # Forwarded rather than re-implemented: `show_section` asks the
            # section pane to re-read and the list is what has something to
            # re-read, the same `_ui_reload` the Clients pane answers with.
            pane._ui_reload = getattr(lst, "_ui_reload", None)
            # And the list itself, for the one caller outside the section
            # that has something to ask of it: a feed row on Overview asking
            # the history table for its record.
            pane._ui_list = lst
        return pane

    # -- Overview -----------------------------------------------------------
    over = tk.Frame(stage, bg=CARD)
    panes["Overview"] = over
    head = tk.Frame(over, bg=CARD, padx=24, pady=16)
    head.pack(fill="x")
    urow = tk.Frame(head, bg=CARD)
    urow.pack(fill="x")
    # The Server URL is an identifier before it is anything else - it is read
    # off this line a character at a time and pasted into a client's settings -
    # so it is the hero of this section, in the code face. It is **not**
    # rewritten when nothing answers: what this server is called does not stop
    # being true because the port went quiet, and the app bar says whether it
    # is answering.
    status_sub = tk.Label(urow, text=server_url, bg=CARD, fg=MONO,
                          font=font("figure"))
    status_sub.pack(side="left")
    # Beside the URL it copies. Everything a section opens is done about once
    # a month and this is the one thing on this window that is not.
    Pill(urow, "Copy URL", CARD, CARD2, LINE, fg=TEXT, w=92, h=26,
         bold=False, radius=0, command=copy_url).pack(side="left",
                                                      padx=(18, 0))
    # What the chip row #205 removed carried that the URL does not: this
    # machine's own address, and the protocol. One quiet line under the
    # identifier rather than six boxes beside it.
    tk.Label(head, text="%s · %s" % (
        local_ip,
        "HTTPS, pinned cert" if _ssl_active else "HTTP, internal"),
        bg=CARD, fg=FAINT, font=font("micro")).pack(anchor="w", pady=(6, 0))
    # Who is serving, said where this window already says whether anything
    # is. Under IIS the GUI is monitor-only and looks identical to the GUI
    # that is serving, so nothing here told the operator which one they had
    # open. Drawn only where there is an iis.json: a service install must
    # look as it did.
    if _iis_line:
        tk.Label(head, text=_iis_line, bg=CARD, fg=WARNING,
                 font=font("body")).pack(anchor="w", pady=(4, 0))
    # The counts, under the identifier they belong to. They are four integers
    # read at a glance, and colour appears on exactly one of them, which is
    # the variant's rule: `waiting` is the only count anybody has to do
    # anything about.
    _CELLS = (("total", "recorded", TEXT),
              ("pending", "waiting", WARNING),
              ("confirmed", "cleared", SUCCESS),
              ("out_now", "out of store", TEXT))
    # **Built here and packed by `_fit_counts` below** (#258), which is the
    # whole of what that ticket changed: they used to be packed as they were
    # built, and a row that could not hold them let `pack` answer for it by
    # shrinking whichever cell went in last - a count with its leading digit
    # cut off, which measures from outside exactly like one that fit. Two
    # dictionaries because a cell is asked two different questions:
    # `stat_labels` is keyed by what `/stats` calls the number, `count_cells`
    # by the caption under it, which is what `_COUNT_KEEP` orders and what
    # this window can be asked for from outside.
    #
    # The padding moved **inside** the cell, from a `padx` on the pack call
    # to a `padx` on the frame: `_fit_counts` sums what each cell asks for,
    # and padding a caller adds at pack time is not in `winfo_reqwidth`.
    stat_labels = {}
    count_cells = {}
    figs = tk.Frame(head, bg=CARD)
    figs.pack(fill="x", pady=(14, 0))
    for _key, _label, _colour in _CELLS:
        cell = tk.Frame(figs, bg=CARD, padx=15)
        # A count is data and is drawn in the code face, which is the same
        # argument the Server URL above makes: these four are read rather
        # than skimmed.
        v = tk.Label(cell, text="—", bg=CARD, fg=_colour,
                     font=font("figure"))
        v.pack(anchor="w")
        tk.Label(cell, text=_label, bg=CARD, fg=SUBTEXT,
                 font=font("emph", size=8)).pack(anchor="w")
        stat_labels[_key] = v
        count_cells[_label] = cell
    # One groove between each pair that is drawn, so three at most and fewer
    # when the row has dropped a count. Built once and re-packed rather than
    # destroyed and remade: a widget rebuilt on a resize is a widget rebuilt
    # on every pixel of a drag.
    count_rules = [tk.Frame(figs, bg=LINE, width=1)
                   for _ in range(len(_CELLS) - 1)]

    # The row **removes rather than shrinks** (#258), and #204 gave the same
    # answer one shape along when it dropped the database segment off the
    # status line rather than bounding a folder name this repo does not own.
    # The counts are the elastic half of this band and they go whole cells at
    # a time in `_COUNT_KEEP`'s order, out of store first and waiting last.
    # Nothing is lost that has no home: every one of the four is a count of
    # the feed below this band and of Manage Transaction History behind it.
    #
    # 077 is why there is nothing subtracted from the room. #258 computed
    # against a band that carried the Server URL, the status line and Copy
    # URL on the same row, so what the counts could have was what those had
    # left; here the counts have a row of their own under the URL row, and
    # what they are measured against is the whole inner width.
    _shown = [None]

    def _fit_counts(_e=None):
        """Pack as many counts as the row has room for, in `_COUNT_KEEP`.

        Bound to the row's own `<Configure>` and called again whenever
        `refresh_stats` writes a new number into a cell, those being the two
        things that move either side of the sum.

        Greedy over the cells' own `winfo_reqwidth` rather than a table of
        widths: what a cell asks for is `font.measure` of digits nobody here
        decides, at whatever scaling the display is set to, so the only
        honest source for it is the cell. A width written down in this file
        would be the action row's own retired figure again - one that
        outlived the seventh action by a year because nothing re-derived it.
        """
        room = figs.winfo_width()
        keep = []
        for _cap in _COUNT_KEEP:
            trial = keep + [_cap]
            # The cells carry their own padding inside `winfo_reqwidth`, so
            # what the grooves between them cost is all that is added: one
            # 1px frame between each pair that is drawn.
            wanted = (sum(count_cells[c].winfo_reqwidth() for c in trial)
                      + len(trial) - 1)
            # Before the row has been mapped its width is 1, which is not a
            # measurement - take all four and let the first <Configure> say
            # otherwise. And `keep` is never emptied: a band with no count on
            # it at all is a state nothing here is asking for.
            if room > 1 and wanted > room and keep:
                break
            keep.append(_cap)
        shown = [c for _k, c, _col in _CELLS if c in keep]
        if shown == _shown[0]:
            return
        _shown[0] = shown
        for _w in list(count_cells.values()) + count_rules:
            _w.pack_forget()
        spare = list(count_rules)
        # Packed from the left in `_CELLS`' order, which the stacked band
        # allows and #258's own row did not: its counts were right-aligned
        # against the far end of a shared row, so it packed them in reverse
        # to have them read forwards. These start at the left margin under
        # the identifier they belong to, so the order they are packed in is
        # the order they are read in.
        for _n, _cap in enumerate(shown):
            if _n:
                spare.pop().pack(side="left", fill="y", pady=3)
            count_cells[_cap].pack(side="left")

    # Two things move the sum and the row watches for both: the window's own
    # width, and what a cell asks for. A count that grows a digit is the
    # second, and it arrives as a `<Configure>` on the **cell** and nothing
    # at all on the row - so a row watching only itself refits when it is
    # dragged and never when the store fills up, which is the defect one turn
    # further along: `pack` answers the cell that grew by shrinking whichever
    # child went in last, and the order it drops in is not the order
    # `_COUNT_KEEP` states.
    #
    # Bound on every cell rather than only the drawn ones: a cell the row has
    # given up is not mapped and raises no <Configure> at all, and the four
    # counts are written by one tick, so whatever the row is still drawing
    # moves with it and asks the question for the rest.
    #
    # The re-entry this invites is answered by `_shown`: a refit that packs
    # the same counts as last time returns before it touches a widget, so the
    # <Configure> storm a repack sends settles on the first pass that changes
    # nothing.
    for _cell in count_cells.values():
        _cell.bind("<Configure>", _fit_counts)
    figs.bind("<Configure>", _fit_counts)
    _fit_counts()

    tk.Frame(over, bg=LINE, height=1).pack(fill="x")

    # The list, and the detail beside it (076). `ListPane` and `DetailPane`
    # in `ui_kit.py` are the shape, and this is the window that proves it end
    # to end.
    split = tk.Frame(over, bg=CARD)
    split.pack(fill="both", expand=True)
    lcol = tk.Frame(split, bg=CARD)
    lcol.pack(side="left", fill="y")
    fh = tk.Frame(lcol, bg=CARD, padx=24, pady=11)
    fh.pack(fill="x")
    tk.Label(fh, text="Activity", bg=CARD, fg=TEXT,
             font=font("section")).pack(side="left")
    # No longer names the database's filename: db_path can move it, and a
    # caption naming a file that is not the one being read is worse than no
    # caption.
    tk.Label(fh, text="Newest first", bg=CARD, fg=FAINT,
             font=font("micro")).pack(side="right")
    tk.Frame(lcol, bg=LINE, height=1).pack(fill="x", padx=(24, 0))
    listing = ui_kit.ListPane(lcol, CARD, INPUT_BG, TEXT, SUBTEXT, LINE,
                              command=lambda key: paint_detail(key))
    listing.pack(fill="both", expand=True)

    # **Connected clients, three of them** (090). The Clients section is the
    # registry; this is the glance at it from the window that is open all
    # day - the three installations heard from most recently, and a link to
    # the rest. Read off `_client_rows` directly, as the Clients pane is.
    # At the foot of the Activity column rather than in the head band:
    # the list is the one thing on Overview that scrolls, so it is what
    # gives up the height, and the detail pane beside it keeps all of
    # its own down to Open in history at the window's open size.
    ccard = tk.Frame(lcol, bg=CARD, padx=24, pady=10)
    ccard.pack(side="bottom", fill="x", before=listing.frame)
    tk.Frame(lcol, bg=LINE, height=1).pack(side="bottom", fill="x",
                                          padx=(24, 0), before=listing.frame)
    chead = tk.Frame(ccard, bg=CARD)
    chead.pack(fill="x")
    tk.Label(chead, text="Connected clients", bg=CARD, fg=TEXT,
             font=font("label")).pack(side="left")
    view_all = tk.Label(chead, text="View all", bg=CARD, fg=ACCENT,
                        font=font("micro"), cursor="hand2")
    view_all.pack(side="right")
    crows = tk.Frame(ccard, bg=CARD)
    crows.pack(fill="x", pady=(4, 0))

    def paint_clients():
        """Redraw the three rows. Called when Overview is shown and on the
        refresh tick, so the card is never older than the counts above it."""
        for w in crows.winfo_children():
            w.destroy()
        rows = list(S._client_rows())[:3]
        if not rows:
            tk.Label(crows, text="No installation has checked in yet.",
                     bg=CARD, fg=SUBTEXT, font=font("body"),
                     anchor="w").pack(fill="x")
            return
        for r in rows:
            line = tk.Frame(crows, bg=CARD)
            line.pack(fill="x", pady=(2, 0))
            tk.Label(line, text=r["hostname"] or "—", bg=CARD, fg=MONO,
                     font=font("code")).pack(side="left")
            tk.Label(line, text=r["app"] or "", bg=CARD, fg=SUBTEXT,
                     font=font("body")).pack(side="left", padx=(12, 0))
            tk.Label(line, text=_ago_ts(r["last_seen"]) or "—", bg=CARD,
                     fg=FAINT, font=font("micro")).pack(side="right")

    paint_clients()
    over._ui_reload = paint_clients
    tk.Frame(split, bg=LINE, width=1).pack(side="left", fill="y")
    detail = ui_kit.DetailPane(split, CARD, INPUT_BG, TEXT, SUBTEXT, FAINT,
                               LINE, hot=CARD2, ink=BG)
    detail.pack(side="left", fill="both", expand=True)

    #: The sections that hold a list under their rows, and what builds each.
    #: Clients and System Log are deliberately not here: they carry no rows
    #: at all, so the list is the whole section and is built below. Asset
    #: Proposals left with 090 - it is a row on Assets that opens a window.
    LISTED = {"Transactions": manage_records}

    for _name, _entries in SECTIONS:
        if _entries:
            panes[_name] = section_pane(_name, _entries,
                                        LISTED.get(_name))

    # Clients, which carries no entries because it carries the list itself.
    # Built here rather than by `section_pane` for the reason the empty
    # tuple above gives: there is no row to lay out, and what goes on the
    # stage is `client_list`'s own form.
    panes["Clients"] = client_list(stage)
    # System Log, the same shape through `section_pane` with no rows: the
    # heading and rule every other section carries, and the list under them.
    panes["System Log"] = section_pane("System Log", (), system_log)

    bar = ui_kit.SectionBar(stage.master, [n for n, _ in SECTIONS],
                            BG, CARD, TEXT, SUBTEXT, LINE,
                            command=show_section)
    # Packed after the stage and before it, which `pack` reads as above it:
    # the stage took `expand=True` and would otherwise be served the bar's
    # height as well.
    bar.box.pack(fill="x", before=stage)
    show_section("Overview")
    view_all.bind("<Button-1>", lambda _e: (bar.select("Clients"),
                                            show_section("Clients")))

    def _rebar():
        """A theme switch recolours widgets in place (`ui_kit.retint`) and the
        bar's own four colours were taken when it was built - so the next
        click would paint the selected cell out of the palette that has gone.
        Re-seeded from the module globals `THEME` rebinds, then asked to
        repaint the section that is on."""
        bar.shell, bar.panel = BG, CARD
        bar.text, bar.mute = TEXT, SUBTEXT
        bar.select(bar.current)
    THEME.watch(_rebar)

    # **The side panel is gone** (#205), and with it the three boxes it
    # held. Variant E is a header, one table and a rail: there is no
    # column beside the table, and a panel that is given whatever the
    # window has left over is the shape #114 and 165 were each spent on -
    # first the CLIENTS box unmapped at the 940x600 minimum, then the
    # whole panel drawn 5px narrower than the group pinned inside it.
    #
    # What each of the three was answering, and where it is answered now:
    # **Clients** is a rail button, `Connected clients`, which is where
    # the prototype puts it and is a door rather than a box. **Oldest
    # pending** is the table, which lists newest first and states how
    # long each pending row has been waiting on the row itself - a list
    # of the three oldest was a crop of a column the table already has.
    # **Out now, by engineer** is the one thing genuinely not carried
    # anywhere else: the count of what is out is a cell in the header
    # band, the engineer holding each asset is a column of the table, and
    # the split of the one by the other is not drawn any more. Said here
    # rather than quietly dropped, because it is the real cost of this
    # layout and somebody looking for it should find out why from the
    # place it used to be built.

    #: What a row's state is drawn in. The gutter beside it says the
    #: direction instead, which is the other half of the same row - see
    #: `_direction_colour`.
    _STATE_COLOUR = {"pending": WARNING, "confirmed": SUCCESS,
                     "rejected": DANGER, "cancelled": FAINT}

    def _state_word(row, st):
        """A **pending** row says how long it has been pending, and the others
        say what they are.

        How long a movement has waited is the question this window is actually
        asked of a pending row - it is what the 24h auto-accept is closest to,
        and the side panel that used to list the three oldest was dropped at
        #205 on the argument that the row already carries it. It does, so it
        goes on carrying it: the row has one right-hand slot under the
        direction word, and for a settled movement the word is the whole
        answer while for a waiting one it is not.
        """
        return st if st != "pending" else "pending, %s" % _ago(row)

    def _direction_colour(row, st):
        """The gutter carries the **direction**, which is the one thing on a
        row that must not be misread: an asset going out becomes an engineer's
        responsibility and one coming back stops being it, where
        pending-versus-confirmed is a word two labels along and is read as a
        word. WARNING for an outgoing asset rather than DANGER, matching
        `_dir_bits` in the Notifier (#180) - a movement out of the store is the
        ordinary thing this store does all day. A **rejected** row keeps
        DANGER: nothing moved, so there is no direction to state.
        """
        if st == "rejected":
            return DANGER
        if st == "cancelled":
            return FAINT
        return WARNING if row["direction"] == "Out Store" else SUCCESS

    # What the list is currently holding, by id and in the order it drew them.
    # Two shapes of the same rows because the pane asks two different
    # questions of them: which row was clicked, and what came before it.
    _feed_rows = {}
    _feed_order = []

    def _previously(row):
        """What this same asset did before this movement, out of what the feed
        is already holding.

        Read off the feed rather than asked of the database: `_gui_snapshot` is
        the one read this window makes, and a query per selection is a query
        per click on a window that already repaints on a timer. The cost is
        real and the pane states it rather than hiding it - a movement older
        than the feed is not listed here, and Manage Transaction History is the
        window that has all of them.
        """
        key = (row["asset_number"], row["serial_number"])
        out = []
        for other in _feed_order:
            if other["id"] == row["id"]:
                continue
            if (other["asset_number"], other["serial_number"]) != key:
                continue
            if str(other["timestamp"]) >= str(row["timestamp"]):
                continue
            out.append("%s, %s, %s" % (other["direction"],
                                       other["team_member"],
                                       _when(other, "%d %b %Y  %H:%M")))
            if len(out) == 4:
                break
        return out

    def paint_detail(tid):
        """The pane beside the list, for whichever row is selected."""
        row = _feed_rows.get(tid)
        if row is None:
            detail.clear("Select a movement on the left to see what it was.")
            return
        st = _status_of(row)
        out = row["direction"] == "Out Store"
        detail.show(
            str(row["asset_number"] or "no asset number"),
            sub=str(row["serial_number"] or ""),
            word="Out store" if out else "In store",
            word_fg=WARNING if out else SUCCESS,
            state=_state_word(row, st), state_fg=_STATE_COLOUR[st],
            gutter=_direction_colour(row, st),
            fields=(("Asset type", row["asset_type"]),
                    ("Model", row["asset_model"] or "\u2014"),
                    ("Engineer", row["team_member"]),
                    ("Storekeeper", row["storekeeper"]
                     or S.STOREKEEPER_DEFAULT),
                    ("Logged", "%s  (%s)" % (_when(row, "%d %b %Y  %H:%M"),
                                              _ago(row)))),
            history=_previously(row),
            # A11 lives here rather than on the row itself. The feed is where a
            # movement is noticed and this pane shows eleven facts about one;
            # everything an admin then wants to *do* with it - cancel it,
            # correct it, read who confirmed it and from which machine - is
            # still in that window, now behind a labelled control rather than
            # behind a click the row never announced. It opens behind the
            # console door like every other route to it: the admin password is
            # asked for once a sitting and not again (ADR-0015).
            actions=(("Open in history", False,
                      lambda _t=tid: open_in_history(_t)),))

    def open_in_history(tid):
        """Put Transactions on the stage and select one record there (A11).

        The history table is that section's pane since 088, so a feed row no
        longer opens a window on its record: it moves the stage and asks the
        pane. The stage first and the selection second, because `show_section`
        reloads the table and a reload after the selection would clear it.
        The door is the pane's to ask, inside `_select_transaction`.
        """
        bar.select("Transactions")
        show_section("Transactions")
        panes["Transactions"]._ui_list._select_transaction(tid)


    _last_sig = [None]

    def refresh_feed():
        """Repaint the feed, the holdings and the oldest-pending list, but only
        when the table has actually moved - see _gui_snapshot."""
        try:
            recent, held, oldest, sig = S._gui_snapshot(disp["feed_limit"])
        except Exception:
            return
        if sig == _last_sig[0]:
            return
        _last_sig[0] = sig

        # Which row was selected, read back before the pane is emptied: a
        # repaint is the feed having moved and not the admin having changed
        # their mind, so a selection that still exists survives one.
        was = listing.selected
        listing.clear()
        _feed_rows.clear()
        del _feed_order[:]
        _feed_order.extend(recent)
        for r in recent:
            st = _status_of(r)
            out = r["direction"] == "Out Store"
            _feed_rows[r["id"]] = r
            listing.add(
                str(r["asset_number"] or "\u2014"),
                sub=str(r["serial_number"] or "\u2014"),
                # "Out" and "In" stay exactly these two words - the gate finds
                # a feed row by them - and the colour beside the gutter is the
                # same one.
                word="Out" if out else "In",
                word_fg=WARNING if out else SUCCESS,
                state=_state_word(r, st), state_fg=_STATE_COLOUR[st],
                gutter=_direction_colour(r, st), key=r["id"])
        if not recent:
            detail.clear("no transactions yet")
            return
        pick = was if was in _feed_rows else recent[0]["id"]
        listing.select(pick)
        paint_detail(pick)

        # The holdings and the oldest-pending list were painted here into
        # the side panel, which is gone (#205). `_gui_snapshot` still
        # answers all three and is deliberately untouched: its signature
        # is what this guard reads, and `_asset_key_sql` behind it is the
        # one expression saying which asset a Transaction is about (#88),
        # asserted against the Out Now cell above by tools/server-checks.

    # `refresh_clients` stood here and painted the CLIENTS box on a tick
    # of its own, that box being the only route to Connected Clients.
    # Both are gone with the side panel (#205): the window is a rail
    # button now, so there is nothing to repaint and nothing for a
    # signature to guard. What the guard was protecting against survives
    # as the rule rather than the code - a tick that rebuilds a container
    # it has nothing new to put in is work this window does to itself
    # (#176, #189) - and the feed's own guard above is the remaining
    # instance of it.

    _tray_said = [None]
    _health_said = [None]

    def set_health(online):
        """The old window drew a hardcoded green "● RUNNING" and live counts
        whatever the port was doing. A count nobody could refresh reading as
        current is the same class of lie as the banner.

        The banner is written only where the answer has moved, which is the
        rule the tray half below and the CLIENTS box above both already keep
        and which this half was the last one left without. What it cost when
        this window was drawn on a render (074) was a full-window composite
        armed from inside itself: `banner` was a canvas, so a write to it
        re-asserted its own `-width`/`-height` over the size `pack` had
        propagated in, `pack` put that back on the next idle pass, and both
        hops were a `<Configure>` the render was listening for - one repaint
        and ten `PhotoImage` renders per five-second tick on a quiet server.
        The render is gone and the guard is not: a tick with nothing to say
        should write nothing. One guard covers all five writes because
        every one of them is a function of `online` alone - `server_url` and
        `PORT` do not move while this window is open. The tray keeps its own
        beside it rather than sharing this one: it is written the first time
        there is a tray to write to, whatever the answer was when this last
        ran, and that first write is what takes it off the CHECKING icon."""
        if _health_said[0] != online:
            _health_said[0] = online
            status_word.config(text="RUNNING" if online else "NOT RESPONDING",
                               fg=SUCCESS if online else DANGER)
            # `status_sub` is the Server URL and is **not** written here
            # (#205). It was replaced with "nothing answered on port N"
            # while the port was quiet, which took the one identifier on
            # this window off the screen at the moment somebody is reading
            # it to work out what to point a client at - and the line under
            # it already says nothing answered. What this server is called
            # does not stop being true because the port went down.
            dot_cv.itemconfig(dot_id, fill=SUCCESS if online else DANGER)
            live_lbl.config(text="serving on port %d" % S.PORT if online
                            else "nothing is answering",
                            fg=SUBTEXT if online else DANGER)
        # And the tray, from here rather than from a loop of its own.
        # That is the surface which is actually up: the window is
        # hidden to the tray on close, so the tooltip is the whole of
        # what an operator reads without restoring it, and it carried a
        # literal RUNNING refreshed every ten seconds and never asked
        # whether anything had answered. It was the hardcoded green dot
        # this docstring says the banner was rebuilt to remove, left
        # standing one surface over. The protocol is _ssl_active for
        # the reason the line above uses it - that describes the
        # listener that is running, where the tray re-read the
        # certificate files each tick and called itself HTTPS the
        # moment one was uploaded, a restart before the listener was.
        # Written when that answer has changed, and on the first call the
        # tray exists for - which is what takes it off the CHECKING icon.
        # `_make_server_tray_icon` is `ui_kit.app_icon`, supersampled at 4x,
        # so an unconditional write is a 256px draw of the whole artwork on
        # the Tk thread every tick: the same rule the CLIENTS box above now
        # keeps, landing on the same thread in the same moment, which is
        # what turns a repaint into a torn one.
        if _tray_icon[0] and _tray_said[0] != online:
            _tray_said[0] = online
            _tray_icon[0].title = (
                "Asset Manager — Asset Server  ●  %s  (%s)"
                % ("RUNNING" if online else "NOT RESPONDING",
                   "HTTPS" if _ssl_active else "HTTP"))
            # The same online read the title above was just built from, so
            # the light and the words on it are never two probes' answers.
            _tray_icon[0].icon = S._make_server_tray_icon(online)

    def refresh_stats():
        # This call is also the liveness probe, which is why it stays HTTP over
        # the pinned certificate rather than becoming another DB read.
        ok, payload = False, {}
        try:
            import ssl as _ssl
            # _ssl_active, not a second reading of the same files: that one
            # describes the listener as it was when this window opened, which
            # is why the tray stopped re-reading the certificate each tick and
            # calling itself HTTPS a restart before the listener was. This
            # probe went on re-reading them every five seconds, so the scheme
            # it asked over could differ from the scheme the banner it sets
            # reports - and under IIS both were wrong the same way.
            ctx = None
            if _ssl_active:
                # Verifies nothing, on purpose, and this is the one
                # place in this file where that has to be argued for.
                # It pinned SSL_CERT_PATH as its own trust anchor,
                # which is right only where this process is what
                # bound the listener. Under IIS the certificate the
                # site presents is whatever was bound to it - a pfx
                # imported by thumbprint, a certificate picked in IIS
                # Manager - and none of those is necessarily the file
                # beside the server; under -PfxPath that file may not
                # be on the machine at all, and the exists() below it
                # then simply skipped the anchor and left
                # CERT_REQUIRED against an empty store, which refuses
                # every certificate there is. Either way the
                # handshake failed and a healthy server was captioned
                # NOT RESPONDING - which is the defect #176 and #185
                # are about, reached one step further along: the
                # scheme is right now and the verification is what
                # turns the answer into a red banner.
                #
                # What this probe asks is whether the port is
                # answering, not whether the server on it is who it
                # says. It is loopback to 127.0.0.1, the request is
                # GET /stats, which carries no credential and needs
                # none, and what comes back is four integers on a
                # window on this same machine. That is not rule 1
                # turned off: rule 1 is a *client* deciding whether
                # to trust a server, and this is a server asking what
                # its own port is doing - the distinction
                # _port_serves_tls above and Invoke-PinnedRequest in
                # tools\_deploy.ps1 are both written around. It must
                # stay that: nothing authenticated may ever be asked
                # over this session, or the reasoning stops holding.
                ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
            body = _loopback_get("/stats", ctx)
            if body is not None:
                ok, payload = True, body
        except Exception:
            pass
        set_health(ok)
        for k, lbl in stat_labels.items():
            lbl.config(text=str(payload.get(k, "—")) if ok else "—")
        # A count that has grown a digit is a cell that asks for more room,
        # so the band is re-fitted on the tick that wrote it and not only
        # on a resize: the window an operator leaves open is one nothing
        # resizes for days, and the store it is counting fills up anyway.
        _fit_counts()
        refresh_feed()
        # Windows raises no event when the user switches Light and Dark mode, so
        # following it is a poll, and this tick already runs on the Tk thread.
        # `follow` is a no-op unless the setting is "system".
        if THEME.follow():
            _paint_theme_btn()
        paint_clients()
        root.after(disp["refresh_secs"] * 1000, refresh_stats)

    say("Hover an action to see what it does. Counts refresh every %ds."
        % disp["refresh_secs"])
    refresh_feed()
    root.after(1500, refresh_stats)   # first poll after 1.5 s — Flask is guaranteed ready

    root.mainloop()
