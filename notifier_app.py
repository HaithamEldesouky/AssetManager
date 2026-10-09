"""
Asset Manager — Notifier App
System tray poller with confirmation popups.
Settings protected by admin password (verified against server).
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading, time, json, os, sys, webbrowser
import client_update
from datetime import datetime

# Wire layer shared with the Storekeeper and the installer - see common.py.
import common
from common import (api, resolve_server_url, sync_server_cert, MAX_LATER,
                    TEAM_MEMBERS, _ver_tuple, _load_update_state,
                    _save_update_state, checkin, forget_client_id, obey,
                    trust_next_cert, verify_password,
                    log_event, ship_log,
                    report_update_result, _has_client_package, _mark,
                    origin_suffix)
# The window kit shared with the Storekeeper and the Server GUI: the two palette
# tables, the live retint, and the button row that lays itself out against the
# width it actually has. See ui_kit.py.
import ui_kit
# The Pending decisions, below the window: what a Confirm or a Reject means,
# what becomes of an answer the server would not take, and which Transaction is
# offered next. No tkinter in it, so tools/client-checks.py drives all of it
# with no display at all (#208). Imported under its own name rather than
# `as pending`, `_poll_once` binding a local of that name.
import notifier_pending
# The Remote Admin surface, below the tray menu (#218): the window an
# engineer opens on the console from their own machine, and the seven
# panels behind it. It reaches back into this module through `bind()`,
# called under the palette it also takes from here - its own docstring
# has why an `import notifier_app` in there would start a second tray
# client rather than reach this one.
import notifier_remote

APP_VERSION = "2.10.1"   # compared against the server's /version to offer updates

# What this app is called on the wire, to /version's client_packages and to
# /download/client/<key>. The same two words name the zip tools/bundle-client.ps1
# builds (-App notifier) and the key server.py resolves it under.
UPDATE_APP_KEY = "notifier"

# The tray itself - the pystray import, the HAS_TRAY fallback, and the
# marshalling of a callback onto the Tk thread - lives in ui_kit now (#271),
# built once for the Storekeeper's tray (#272) to share rather than a second
# hand-built copy of this one.
HAS_TRAY = ui_kit.HAS_TRAY

# ─── Config ───────────────────────────────────────────────────────────────────

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
# An answer this engineer has given that the server would not take yet - a
# backup or a restore holding writes (ADR-0018), or a server that was not
# there. It is the Storekeeper's offline buffer one table over and for a
# sharper reason: a Transaction it drops is a movement with no record, while an
# answer dropped here is a Transaction left Pending that the 24h Auto-Accept
# confirms a day later with nobody having said yes - which is the one failure
# this app exists to prevent. Shipped by nothing and read back by this app
# alone, so it belongs beside config.json rather than in it.
ANSWER_BUFFER_PATH = os.path.join(BASE_DIR, "pending_answers.json")

DEFAULT_CFG = {
    "server_url":    "https://asset-server:8081",
    "current_user":  "Alice Carter",
    "poll_interval": 15,
    # How long the confirm/reject popup stays on screen before it hides itself,
    # and how long it waits before coming back (#194). `0` is never auto-hide,
    # which is what this popup did before this existed and is what an
    # installation nobody has configured goes on doing.
    "popup_dismiss_secs": 0,
    "popup_repeat_mins":  10,
    # system / dark / light. Not admin-gated, unlike everything else in
    # Settings: this changes what the engineer's own screen looks like, not what
    # this installation is configured to do.
    "theme":         "system",
}

# What Poll Interval may be set to, and the two values below the floor are what
# that field had no answer to at all. `0` turns _poll_loop into an unthrottled
# loop of GET /pending, POST /clients/checkin and ship_log against a server
# that asks this client for no credential on purpose (ADR-0002) - and it is
# applied live by _apply_cfg, so there is no restart at which anybody notices.
# A negative raises ValueError on that same worker, which is a daemon thread
# with nothing catching it: the poller dies while the tray icon goes on looking
# exactly as it did, and the engineer stops being asked to confirm anything,
# which is the one failure this app exists to prevent. The ceiling is the
# softer half - behind a Notifier that asks too rarely there is only the 24h
# Auto-Accept, and a Transaction resolved by a deadline is not one anybody
# verified.
POLL_INTERVAL_RANGE = (5, 300)


def validate_interval(value):
    """(int, None) or (None, message) - exactly one of the two is None.

    server.py's `_validate_range` contract, written here rather than imported:
    this file does not import the server (rule 10), which is the same reason
    installer.py checks its own port field inline rather than calling
    `_validate_port`.
    """
    lo, hi = POLL_INTERVAL_RANGE
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return None, ("Poll interval must be a whole number of seconds, "
                      "from %d to %d." % (lo, hi))
    if not (lo <= n <= hi):
        return None, "Poll interval must be from %d to %d seconds." % (lo, hi)
    return n, None


def poll_secs(cfg):
    """The interval this config asks for, held to POLL_INTERVAL_RANGE.

    Clamped on the way out as well as refused on the way in. The Settings form
    is one writer of this key and config.json is a file on the engineer's own
    machine, so the value the poll loop runs on has to be sound whatever is in
    there. An unreadable one is the default rather than a raise, for the reason
    applaunch.py exists: this is read before mainloop, and an exception here is
    an app that does not start and says nothing about why under pythonw.exe.
    """
    lo, hi = POLL_INTERVAL_RANGE
    try:
        return max(lo, min(hi, int(str(cfg.get("poll_interval")).strip())))
    except (ValueError, TypeError):
        return DEFAULT_CFG["poll_interval"]


# What the popup's auto-hide may be set to (#194), and the reasoning is the
# 24h Auto-Accept rather than taste. The rule this popup enforces is *the
# engineer is asked until they answer* - a window that goes away and comes
# back still enforces it, where one that goes away and does not is an engineer
# who was never asked and a Transaction confirmed by a deadline a day later
# with nobody having looked.
#
# So `popup_repeat_mins` has a **ceiling of 120**: at the worst value anybody
# can save, a Transaction is put back in front of the engineer twelve times
# inside the Auto-Accept window, and at the default of 10 it is offered over a
# hundred times. A floor of 1 rather than 0, a zero there being a popup that
# returns on the same Tk callback it hid on, which is the flashing window the
# one-at-a-time queue exists to remove.
#
# `popup_dismiss_secs` has **0 as its own answer** - never hide - beside a
# 10..600 range, and that is the one value outside the range that is accepted
# on purpose: today's behaviour has to stay reachable from the field, and it
# is the default. The floor is what a window has to be up for to be read at
# all, below which this is a popup that appears and vanishes; the ceiling is
# soft, 600 seconds being long enough that anything past it means the same
# thing as 0 and is better said as 0.
POPUP_DISMISS_RANGE = (10, 600)
POPUP_REPEAT_RANGE  = (1, 120)


def validate_dismiss_secs(value):
    """(int, None) or (None, message) - `validate_interval`'s contract."""
    lo, hi = POPUP_DISMISS_RANGE
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return None, ("Auto-hide must be a whole number of seconds: 0 to "
                      "never hide, or %d to %d." % (lo, hi))
    if n == 0:
        return 0, None
    if not (lo <= n <= hi):
        return None, ("Auto-hide must be 0 to never hide, or from %d to %d "
                      "seconds." % (lo, hi))
    return n, None


def validate_repeat_mins(value):
    """(int, None) or (None, message) - `validate_interval`'s contract."""
    lo, hi = POPUP_REPEAT_RANGE
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return None, ("Return interval must be a whole number of minutes, "
                      "from %d to %d." % (lo, hi))
    if not (lo <= n <= hi):
        return None, "Return interval must be from %d to %d minutes." % (lo, hi)
    return n, None


def dismiss_secs(cfg):
    """The auto-hide this config asks for, held to its range, `0` for never.

    Clamped on the way out as well as refused on the way in, and for
    `poll_secs`' reason one timer along: the Settings form is one writer of
    this key and `config.json` is a file on the engineer's own machine, so
    what the popup arms has to be sound whatever is in there. A value it
    cannot read is the default - which is 0, never hiding - rather than a
    raise, since a popup that fails to open is an engineer who is not asked.
    """
    lo, hi = POPUP_DISMISS_RANGE
    try:
        n = int(str(cfg.get("popup_dismiss_secs")).strip())
    except (ValueError, TypeError):
        return DEFAULT_CFG["popup_dismiss_secs"]
    return 0 if n <= 0 else max(lo, min(hi, n))


def repeat_mins(cfg):
    """How long a hidden popup waits before coming back, held to its range."""
    lo, hi = POPUP_REPEAT_RANGE
    try:
        return max(lo, min(hi, int(str(cfg.get("popup_repeat_mins")).strip())))
    except (ValueError, TypeError):
        return DEFAULT_CFG["popup_repeat_mins"]


def load_config():
    """This app's config.json, read over DEFAULT_CFG. See common.load_config."""
    return common.load_config(CONFIG_PATH, DEFAULT_CFG)

def save_config(cfg):
    common.save_config(CONFIG_PATH, cfg)


def fetch_permissions(server_url, name):
    """Permissions in force for one engineer, from GET /members.

    /members needs no password and carries no secrets - it reports whether an
    engineer has a password of their own, never the hash - so a client can read
    its own profile before anyone has logged in. This only decides what to show;
    every write is still checked on the server.
    """
    try:
        r = api("get", "%s/members" % server_url.rstrip("/"), timeout=5)
        if r.ok:
            for m in r.json():
                if m.get("name") == name:
                    return list(m.get("permissions") or [])
    except Exception:
        pass
    return []


def fetch_members(server_url):
    """Return the engineer list from the server's /members (names only).
    Falls back to the baked-in TEAM_MEMBERS if the server is unreachable."""
    try:
        r = api("get", f"{server_url.rstrip('/')}/members", timeout=5)
        if r.ok:
            names = [m["name"] for m in r.json() if m.get("name")]
            if names:
                return names
    except Exception:
        pass
    return list(TEAM_MEMBERS)

def check_for_update(server_url):
    """Return (latest, download_url, has_package) when the server advertises a
    newer version than APP_VERSION, else None.

    has_package is whether this server holds the source zip for this app, in
    which case the update is applied in place by client_update rather than by
    sending an engineer to a browser. It is read from the additive
    client_packages key, so a server built before that key simply says no and
    this client behaves exactly as it did."""
    try:
        r = api("get", f"{server_url.rstrip('/')}/version", timeout=5)
        if r.ok:
            data = r.json()
            latest = data.get("latest", "")
            if latest and _ver_tuple(latest) > _ver_tuple(APP_VERSION):
                dl = data.get("download_path", "")
                url = f"{server_url.rstrip('/')}{dl}" if dl else ""
                return (latest, url, _has_client_package(data, UPDATE_APP_KEY))
    except Exception:
        pass
    return None


# ─── Colours, and the theme ────────────────────────────────────
# Variant T's palette, which is variant C's - the Storekeeper ships it, and
# these are the other two windows of the same product. The names are the ones
# every dialog in this file already uses, so re-pointing them here restyles the
# reject dialog, the admin login, Settings and the setup wizard too.
#
# What changed is that they are no longer constants. ui_kit holds the same
# fourteen names in a light table as well; THEME rebinds them, so a widget built
# after a switch is born the right colour, and ui_kit.retint repaints the ones
# built before it. A rebuild would be the obvious way to change a theme and is
# the wrong one here: it could pull a popup out from under an engineer halfway
# through answering it, which is the same reason the Dashboard's tabs are built
# once and shown with pack_forget rather than rebuilt on every switch.

#: Three colours that are this app's own rather than the product's. They were
#: inline hex literals before ui_kit existed and they still belong here, so they
#: are merged into the shared tables rather than added to them.
_EXTRA_DARK = {"SUCCESS_HOT": "#16a34a",     # Confirm, pressed
               "DANGER_HOT":  "#c62828",     # Confirm Rejection, pressed
               "DANGER_SOFT": "#ef9a9a"}     # the reason field's focus ring
_EXTRA_LIGHT = {"SUCCESS_HOT": "#166534",
                "DANGER_HOT":  "#7f1d1d",
                "DANGER_SOFT": "#991b1b"}

THEME = ui_kit.Theme(globals(), _EXTRA_DARK, _EXTRA_LIGHT,
                     restyle=lambda _root: _style_notifier())

# The fourteen shared names and this app's own three are bound into this
# module by the THEME above, out of ui_kit.DARK merged with the extras it
# was handed - this file writes no second copy of that table. MONO is this
# app's identifiers, always monospace; FAINT its provenance, row counts
# and deadlines.

# Under the THEME rather than under the import, because bind() takes the
# palette as well as the module: notifier_remote's windows are drawn out
# of these same names, and there is only one set of them to draw out of.
notifier_remote.bind(sys.modules[__name__])


def _style_notifier():
    """The Dashboard's ttk block, in a function so a theme change can re-run it.

    A ttk widget reads its colours from a style rather than taking them as
    construction arguments, so it is invisible to the retint walk - there is no
    `bg` option on a Treeview to read back and remap.
    """
    s = ttk.Style()
    s.theme_use("clam")
    # bordercolor/lightcolor/darkcolor are the clam bevel; left at their
    # defaults they draw a pale 3-D box round every widget.
    s.configure("DB.Treeview", background=CARD, foreground=TEXT,
                fieldbackground=CARD, rowheight=30, borderwidth=0,
                font=font("body"))
    s.configure("DB.Treeview.Heading", background=CARD2, foreground=SUBTEXT,
                relief="flat", borderwidth=0, padding=(6, 8),
                font=font("emph"))
    s.map("DB.Treeview", background=[("selected", ACCENT)],
          foreground=[("selected", "white")])
    s.map("DB.Treeview.Heading", background=[("active", CARD2)])
    s.configure("Vertical.TScrollbar", background=CARD2, troughcolor=BG,
                bordercolor=BG, lightcolor=CARD2, darkcolor=CARD2,
                arrowcolor=SUBTEXT, relief="flat", borderwidth=0,
                arrowsize=12, width=11)
    s.map("Vertical.TScrollbar", background=[("active", LINE)])


def _tag_status(tree):
    """The Treeview's status colours, and the hook that re-applies them.

    A tag colour is not a widget option either, so the walk cannot see it and
    a switch would otherwise leave Confirmed rows green on white at 1.8:1.
    """
    tree.tag_configure("confirmed", foreground=SUCCESS)
    tree.tag_configure("rejected", foreground=DANGER)
    tree.tag_configure("pending", foreground=WARNING)
    # A Treeview row cannot span columns, so a day group is a tagged row with a
    # short label in the first cell.
    tree.tag_configure("day", foreground=FAINT, background=CARD2,
                       font=font("emph"))
    tree._retint_hook = lambda _rev, _new: _tag_status(tree)
    return tree


#: What each command is called when somebody is being asked to confirm it.
#: Worded here rather than taken from the server: `COMMAND_LABELS` lives in
#: `server.py` and no client carries a copy of a server list (rule 8's
#: argument, one table over) - what this is, is the question this window asks
#: about an act, which is this window's own sentence and not a name for the
#: command. The server is still the only thing that decides what `COMMANDS`
#: holds, and refuses anything else in its own words.
COMMAND_ASKS = {
    "logoff": "Log off %s?",
    "reset_identity": "Reset the identity of %s?",
    "update_now": "Apply the published update on %s?",
}


def _tag_clients(tree):
    """The Connected Clients colours, both sets, for `_tag_status`' reason.

    A tag colour is not a widget option, so the retint walk cannot see it and
    a theme switch would leave a stale row red on white. Six tags on one
    function rather than two functions of three: the list and the command
    list below it are one panel and are repainted together, and what each
    colour means is the same question - how long ago, and did it happen.

    The ages are the console's own thresholds (#174): green inside a quarter
    of an hour, amber inside a day, red past that, because a Notifier that is
    not running is an engineer who is not being asked to confirm anything.
    """
    tree.tag_configure("fresh", foreground=SUCCESS)
    tree.tag_configure("today", foreground=WARNING)
    tree.tag_configure("stale", foreground=DANGER)
    tree.tag_configure("queued", foreground=WARNING)
    tree.tag_configure("collected", foreground=SUCCESS)
    tree.tag_configure("expired", foreground=DANGER)
    tree._retint_hook = lambda _rev, _new: _tag_clients(tree)
    return tree


#: `Pill` used to be a tk.Canvas subclass here, byte-identical to the
#: Storekeeper's. It is now one class in ui_kit that both clients and the Server
#: GUI share - which is what a third copy was always going to cost - and it can
#: redraw at a width and a palette it was not born with. Both halves of this
#: change need that one property.
_round_rect = ui_kit.round_rect
Pill = ui_kit.Pill



def _ident(t):
    """Asset No. and Serial No. are the only identifiers - project rule 3."""
    bits = []
    if t.get('asset_number'):
        bits.append(str(t['asset_number']))
    if t.get('serial_number'):
        bits.append(str(t['serial_number']))
    return "   ".join(bits) if bits else "no identifier"


def _ago(t):
    """How long this has been sitting on the engineer. That matters more to
    them than the wall-clock time, because of the 24h auto-accept."""
    try:
        d = datetime.now() - datetime.fromisoformat(t.get('timestamp', ''))
    except (ValueError, TypeError):
        return ""
    m = int(d.total_seconds() // 60)
    if m < 1:
        return "just now"
    if m < 60:
        return "%dm ago" % m
    if m < 48 * 60:
        return "%dh ago" % (m // 60)
    return "%dd ago" % (m // 1440)


def _hours_left(t):
    """Hours before the server's 24h auto-accept confirms this without them."""
    try:
        d = datetime.now() - datetime.fromisoformat(t.get('timestamp', ''))
    except (ValueError, TypeError):
        return 24.0
    return 24 - d.total_seconds() / 3600.0


def _status_of(t):
    if t.get('rejected'):
        return "rejected"
    if t.get('confirmed'):
        return "confirmed"
    return "pending"


#: The name a Transaction is attributed to when its own column is empty. One
#: of the four places this product writes that name down - the cascade table in
#: `CLAUDE.md` has the others - and one place in this file rather than a
#: literal at each site that needs it.
STOREKEEPER_FALLBACK = "Storekeeper User"


def _when(t, fmt="%d %b %Y  %H:%M"):
    """This Transaction's own timestamp, or "" where there is not one.

    A Transaction written by an older build, or one whose column was never
    filled, has a timestamp that will not parse; every caller here draws the
    answer into a label, so the empty string is what they can all draw.
    """
    try:
        return datetime.fromisoformat(t.get('timestamp', '')).strftime(fmt)
    except (ValueError, TypeError):
        return ""


def _day_of(t):
    try:
        d = datetime.fromisoformat(t.get('timestamp', '')).date()
    except (ValueError, TypeError):
        return "Earlier"
    today = datetime.now().date()
    if d == today:
        return "Today"
    if (today - d).days == 1:
        return "Yesterday"
    # Short label on purpose: the group sits in a 90px column, and
    # "SATURDAY 05 SEPTEMBER" was truncated mid-word.
    return d.strftime("%a %d %b")


def _dir_bits(t):
    """Direction as a colour and the one word a row carries it in.

    Direction is the one thing that must not be misread: an asset going out
    becomes the engineer's responsibility, one coming back stops being it.

    The colour is WARNING for an outgoing asset rather than DANGER, which is
    the Storekeeper's answer to the same question (#179): a movement out of
    the store is the ordinary thing this store does all day, and DANGER is
    reserved for a Transaction somebody refused. It is the only colour on the
    popup either way.

    "Out" and "In" stay exactly these two words: the Server console's feed row
    says them, the History table's Direction column says them, and both gates
    find a row by them. They were derived inline in `_row_values` while this
    function answered "Taken out"/"Returned" beside an ALL-CAPS
    "OUT OF STORE" - three wordings of one fact, two of which every caller
    discarded. One is left.
    """
    out = t.get('direction') == "Out Store"
    return (WARNING if out else SUCCESS, "Out" if out else "In")


def _deadline_words(t):
    """What a Pending row says about the 24h Auto-Accept, and in what colour.

    On the row rather than in the pane beside it, because it is the half of a
    Pending Transaction that changes while nobody is looking at it: the server
    confirms this without the engineer a day after the store logged it, and a
    queue that does not say which of its rows is closest to that is a queue
    read in whatever order the eye lands.

    Past the deadline is DANGER and says so in one word rather than counting
    hours backwards - the Auto-Accept has either happened or is about to, and
    "-3h left" is a number nobody can act on differently from "overdue".
    """
    left = _hours_left(t)
    if left <= 0:
        return "overdue", DANGER
    return "%dh left" % left, (WARNING if left <= 4 else FAINT)


def _dir_words(t):
    """The direction as the two things an engineer reads, in plain words.

    `_dir_bits`' phrase is one ALL-CAPS string and was drawn at 9pt as an
    eyebrow over the identifier, which is the wrong way round: the direction is
    the second largest thing on the popup after the number, and "OUT OF STORE"
    set small says less than "OUT" set large with "of the store" beside it.
    Two values rather than one so the word can carry the colour and the size
    while the sentence around it stays quiet.
    """
    out = t.get('direction') == "Out Store"
    return ("OUT", "of the store") if out else ("IN", "to the store")

# ─── Tray icon ────────────────────────────────────────────────────────────────

def make_icon(pending=False):
    """The product icon, at the size a Windows tray asks for.

    The artwork is `ui_kit`'s: this file and `server.py` each held a
    byte-identical copy of a crude one drawn here, which is what rule 10 is
    about. What the badge *means* stays here - it is this app that knows a
    transaction is waiting on this engineer, and the tray icon is the only
    thing saying so while the popup is behind another window.
    """
    return ui_kit.app_icon(64, badge=pending)

# ─── Rejection Reason Dialog ──────────────────────────────────────────────────

class RejectReasonDialog:
    """Asks for a reason before sending reject to server.

    It has two exits and they mean the same thing, so both go through
    `on_cancel` here rather than being wired separately by whoever opened it.
    They were: Cancel called `win.destroy` straight, while the caller reached
    in and put its own handler on `WM_DELETE_WINDOW` - which a window manager
    raises for the X and a programmatic `destroy()` never does. So the X
    brought the popup back and the button labelled Cancel dismissed the dialog
    and nothing else, leaving the popup withdrawn, unresolved and unreachable,
    and `_show_next_popup` refusing to show anything behind it for the life of
    the process. Which dialog was dismissed is this class's own fact; that it
    was the caller's is how one of the two exits came to be missed.
    """

    def __init__(self, root, transaction, on_reject, on_cancel=None):
        self.on_reject = on_reject
        self.on_cancel = on_cancel
        self._answered = False
        t = transaction

        win = tk.Toplevel(root)
        win.title("Rejection Reason")
        win.configure(bg=BG)
        # This keeps its `-topmost`, and it is the one deliberate exception to
        # #193's sweep - stated here rather than left to be rediscovered. The
        # popup **withdraws itself** while this dialog is up, so the two are
        # one window as far as the engineer is concerned: a dialog that went
        # behind another application would read as the Transaction having
        # vanished, with nothing on screen to say otherwise and the 24h
        # Auto-Accept resolving it a day later. That is exactly the failure
        # the popup's own topmost exists to prevent, and it has to reach the
        # window the popup handed the question to. Everything else in these
        # four apps drops it.
        win.attributes("-topmost", True)
        win.grab_set()
        win.protocol("WM_DELETE_WINDOW", self._cancel)
        ui_kit.escape_closes(win, self._cancel)

        hdr = tk.Frame(win, bg=DANGER, height=40)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="✘  Reject Asset Transaction",
                 bg=DANGER, fg="white",
                 font=font("heading")).pack(side="left", padx=14, pady=10)

        # The footer before the body, and from the bottom: written at 400x240
        # against a 300x242 form, the bottom 2px of both pills was clipped, and
        # the height cannot be dragged. See ui_kit.fit.
        btn_f = tk.Frame(win, bg=CARD2, padx=18, pady=10)
        btn_f.pack(side="bottom", fill="x")

        body = tk.Frame(win, bg=BG, padx=18, pady=12)
        body.pack(fill="x")

        # Show which asset
        id_parts = []
        if t.get('asset_number'):  id_parts.append(f"Asset# {t['asset_number']}")
        if t.get('serial_number'): id_parts.append(f"S/N {t['serial_number']}")
        id_str = "  /  ".join(id_parts) if id_parts else "—"

        tk.Label(body, text=f"{t['asset_type']}   {id_str}",
                 bg=BG, fg=TEXT,
                 font=font("title")).pack(anchor="w")
        tk.Label(body, text="Please state the reason for rejection:",
                 bg=BG, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(8, 4))

        self.reason_var = tk.StringVar()
        reason_e = tk.Entry(body, textvariable=self.reason_var,
                            bg=INPUT_BG, fg=TEXT, relief="flat",
                            font=font("value"), insertbackground=TEXT,
                            highlightthickness=1,
                            highlightbackground=DANGER,
                            highlightcolor=DANGER_SOFT)
        reason_e.pack(fill="x", ipady=8)
        reason_e.focus_set()
        reason_e.bind("<Return>", lambda _: self._confirm())

        tk.Label(body, text="(optional — press Enter or click Reject)",
                 bg=BG, fg=SUBTEXT,
                 font=font("micro")).pack(anchor="w", pady=(3, 0))

        # The one row in this app with a width question to answer. Two buttons
        # in equal columns, at short labels if the full ones stop fitting, and
        # the window's minsize is the width below which they would have to be
        # truncated rather than a flat refusal to be resized at all.
        box, self.foot = ui_kit.row_of(
            btn_f,
            [("✘  Confirm Rejection", "✘  Reject",
              (CARD2, DANGER, DANGER_HOT, "white"), self._confirm),
             ("Cancel", None, (CARD2, CARD2, LINE, SUBTEXT), self._cancel)],
            kind="footer")
        box.pack(fill="x")
        win.resizable(True, False)
        win.minsize(self.foot.min_width() + 36, 240)
        ui_kit.fit(win, 400)

        self.win = win

    def _confirm(self):
        if self._answered:
            return
        self._answered = True
        reason = self.reason_var.get().strip()
        self.on_reject(reason)
        self.win.destroy()

    def _cancel(self):
        """Both exits, once. The popup behind this is waiting to be told."""
        if self._answered:
            return
        self._answered = True
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.on_cancel:
            self.on_cancel()

# ─── Notification Popup ───────────────────────────────────────────────────────

class NotificationPopup:
    """Variant E: one transaction, bottom-right, 430x214.

    Still borderless, still always-on-top, still no close button and still no
    Escape binding - it stays until the engineer confirms, rejects or puts it
    away on purpose, which is a product rule and not a style choice, and
    Confirm and Reject are the same size in the same place they have always
    been. Dismiss (#201) is the third control and is deliberately the quietest
    thing on the row: it answers nothing and it is not a way out, it is the
    auto-hide asked for by hand, so the Transaction comes back on the same gap
    and the engineer is still asked.

    What variant E changes is what the window is *about*. The identifier is the
    hero and is drawn in the code face at display size, because it is read a
    character at a time against a label on a machine; the direction is the next
    largest thing and is the only colour on the window, set as the word an
    engineer actually says - OUT - with "of the store" beside it in plain
    words rather than as an ALL-CAPS eyebrow. Everything else is quiet: the
    asset, who it is against, who recorded it and how long ago.

    And the chrome is a **groove**. A 1px line says where the surface ends
    for nothing, which on the one window that opens once per Transaction in
    the queue is the whole argument.
    """

    W, H = 430, 214

    # The gutter carries the direction as a block rather than a spine down the
    # whole card: 3px, the width the Storekeeper's custody strip uses, in the
    # one colour on this window.
    GUTTER = 3

    def __init__(self, root, transaction, on_confirm, on_reject_with_reason,
                 on_done=None, queued=0, hide_after=0, on_hide=None):
        self.root        = root
        self.trans       = transaction
        self.on_confirm  = on_confirm
        self.on_reject_r = on_reject_with_reason
        self.on_done     = on_done
        self.queued      = queued
        self._closed     = False
        # #194. `hide_after` is seconds and `0` is never, which is what this
        # window did before and is still the default. `on_hide` is handed the
        # Transaction back rather than called bare, because what the app does
        # with it is put it back in the queue and it must not have to remember
        # which one was on screen.
        # `on_hide` carries whether the engineer asked for it (#201) rather
        # than a second callback beside it: Dismiss and the timer take one
        # path through this class and one path through the app, so there is
        # no second way for a popup to come back and no second clock to keep
        # in step with the first. What the flag decides is one thing, and it
        # is the app's: whether a `transaction.dismissed` is written.
        self.hide_after  = int(hide_after or 0)
        self.on_hide     = on_hide
        self._hide_job   = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BG)

        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry("%dx%d+%d+%d"
                          % (self.W, self.H, sw - self.W - 18, sh - self.H - 52))

        t      = self.trans
        colour, _short = _dir_bits(t)
        word, whither = _dir_words(t)

        # A 1px border instead of a title bar: the popup has no chrome of its
        # own, so this is the only thing separating it from whatever window
        # happens to be underneath.
        edge = tk.Frame(self.win, bg=LINE, padx=1, pady=1)
        edge.pack(fill="both", expand=True)
        body = tk.Frame(edge, bg=CARD)
        body.pack(fill="both", expand=True)

        # Footer before the body: a widget packed after an expanding sibling is
        # the first thing to get clipped, and the buttons are the point.
        #
        # CARD2 and a groove above it rather than a rounded edge: the 1px
        # line is what says the row is a footer.
        foot = tk.Frame(body, bg=CARD2)
        foot.pack(fill="x", side="bottom")
        tk.Frame(body, bg=LINE, height=1).pack(fill="x", side="bottom")

        # The write action is the one inverted block on the window - the
        # Storekeeper's Submit, one window over (#179) - and Reject is quiet
        # beside it. Equal widths, deliberately: they were 118 and 104, and
        # two controls that must not be misread for each other are told apart
        # by their weight rather than by being different sizes.
        self.btn_confirm = Pill(foot, "Confirm", CARD2, TEXT, MONO, fg=BG,
                                w=114, h=36, radius=0, size=11,
                                short="OK", command=self._confirm)
        self.btn_confirm.pack(side="left", anchor="n", padx=(15, 0), pady=8)
        self.btn_reject = Pill(foot, "Reject", CARD2, CARD, LINE, fg=TEXT,
                               w=114, h=36, radius=0, size=11,
                               command=self._reject)
        self.btn_reject.pack(side="left", anchor="n", padx=8, pady=8)

        # Dismiss is a deferral and is drawn as one (#201). Its face is the
        # footer's own colour, so there is no block at all - a word on the row
        # that lights on hover - in SUBTEXT and not bold. Confirm and Reject
        # are the same width precisely so they cannot be misread for each
        # other, and a third control of that weight would join that pair; this
        # one has to read as the quietest thing here, because it is the only
        # control on the window that answers nothing.
        self.btn_dismiss = Pill(foot, "Dismiss", CARD2, CARD2, CARD,
                                fg=SUBTEXT, w=70, h=36, radius=0, size=9,
                                bold=False, command=self._dismiss)
        self.btn_dismiss.pack(side="left", anchor="n", padx=(4, 0), pady=8)

        # The queue count stays and the idle caption goes, which is what pays
        # for the control beside it: this row is 430px wide, and "awaiting
        # your response" is 123px of it saying what a window that is always on
        # top, has no close button and now carries a Dismiss already says
        # three times over. "N more waiting" is not that - it is the one fact
        # on the window nothing else carries, and it is what makes Dismiss
        # legible as a deferral rather than as a way out.
        self.note = tk.Label(
            foot,
            text=("%d more waiting" % self.queued) if self.queued else "",
            bg=CARD2, fg=WARNING if self.queued else SUBTEXT,
            font=font("strong") if self.queued else font("body"))
        self.note.pack(side="right", pady=(17, 0), padx=(0, 15))

        top = tk.Frame(body, bg=CARD)
        top.pack(fill="both", expand=True)
        # The direction block keeps its own colour: it is the one thing on this
        # window that says which way the asset moved, said twice - here and in
        # the word below - because it is the fact that must not be misread.
        tk.Frame(top, bg=colour, width=self.GUTTER).pack(side="left", fill="y")
        pad = tk.Frame(top, bg=CARD)
        pad.pack(side="left", fill="both", expand=True, padx=(15, 15),
                 pady=(11, 8))
        inner = self.W - 2 - self.GUTTER - 30

        # The identifier, in the code face at display size. Rule 3's two
        # numbers and nothing else, which is what somebody standing at a
        # machine is comparing against a label.
        tk.Label(pad, text=_ident(t), bg=CARD, fg=TEXT,
                 font=font("ident", size=20)).pack(anchor="w")

        # The direction, second largest and the only colour.
        drow = tk.Frame(pad, bg=CARD)
        drow.pack(fill="x", pady=(2, 0))
        # OUT / IN is data rather than prose - it is the one fact on this
        # window carrying a colour - so it takes the code face beside the
        # identifier above it rather than the prose one (Variant E).
        tk.Label(drow, text=word, bg=CARD, fg=colour,
                 font=font("figure", size=15)).pack(side="left")
        tk.Label(drow, text=whither, bg=CARD, fg=SUBTEXT,
                 font=font("label")).pack(side="left", padx=(7, 0),
                                          pady=(6, 0))

        tk.Frame(pad, bg=LINE, height=1).pack(fill="x", pady=(7, 6))

        # What it is, and who it is about. Sentence case, commas rather than
        # middle dots, and the engineer's own name - this popup is the one
        # place the Transaction is put in front of the person it was recorded
        # against, and saying so is what makes a mis-scan visible.
        tk.Label(pad, text="%s, %s" % (t.get('asset_type', '') or "Asset",
                                       t.get('asset_model') or "no model"),
                 bg=CARD, fg=TEXT, font=font("value"),
                 anchor="w", justify="left",
                 wraplength=inner).pack(anchor="w")
        tk.Label(pad, text="Against %s, recorded by %s, %s"
                          % (t.get('team_member', '') or "you",
                             t.get('storekeeper') or STOREKEEPER_FALLBACK,
                             _ago(t)),
                 bg=CARD, fg=FAINT, font=font("micro"),
                 anchor="w", justify="left",
                 wraplength=inner).pack(anchor="w", pady=(4, 0))

        # Last, after the window is built: a timer armed before it is on
        # screen would be counting down time the engineer could not have been
        # looking at it for.
        self._arm_hide()

    # ── auto-hide (#194) ──────────────────────────────────────────────────
    #
    # The popup owns the timer because it owns the window, and the app owns
    # the *returning* because it owns the queue. What crosses between them is
    # `on_hide`, and nothing else: this class never re-shows itself, never
    # decides how long the gap is, and above all never answers the question -
    # a hide confirms nothing and rejects nothing, so `on_done` is deliberately
    # not called on this path and the Transaction is exactly as unresolved as
    # it was. Dismiss (#201) joins that path rather than opening a second one:
    # what it adds is a flag saying a person asked for it, which the app turns
    # into one `transaction.dismissed`, and an entry that nobody was asked is
    # not an answer to the question either.

    def _arm_hide(self):
        """Start (or restart) the countdown, if there is one to start."""
        self._cancel_hide()
        if self.hide_after > 0 and not self._closed:
            try:
                self._hide_job = self.win.after(self.hide_after * 1000,
                                                self._hide)
            except Exception:
                self._hide_job = None

    def _cancel_hide(self):
        """Stop the countdown. Called wherever the window stops being the
        thing in front of the engineer without being answered - which is two
        places. `_reject`, since the reason dialog withdraws this window and a
        timer left running there would destroy the popup out from under the
        dialog that is still asking about it; and `_dismiss` (#201), which is
        that same timer being asked for by hand, so leaving it armed would
        leave an `after` pointing at a window that is already gone."""
        if self._hide_job is not None:
            try:
                self.win.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def _hide(self, deliberate=False):
        """Take the window away without answering it (#194, #201).

        `deliberate` is the engineer having clicked Dismiss rather than the
        timer having run out. Nothing in this class does anything different
        about it - the window goes the same way and the Transaction is put
        back the same way - it is carried across so the app can write the one
        entry that says a person did this.

        It is a `destroy` rather than a `withdraw`, so the popup that comes
        back is built fresh: the "N more waiting" count and the how-long-ago
        line are both stale by then, and a queue of withdrawn windows is a
        whole window per Transaction held alive for as long as nobody
        answers. `_closed` is set, so a `close()` racing this -
        the Dashboard resolving the same id in the same moment - is the no-op
        it already was.
        """
        self._hide_job = None
        if self._closed:
            return
        self._closed = True
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.on_hide:
            self.on_hide(self.trans, deliberate)

    def _dismiss(self):
        """Put this away and be asked again on #194's gap (#201).

        The same path the auto-hide takes, deliberately: the app puts the
        Transaction back at the **front** of the queue and arms the one timer
        there is, so Dismiss brings no clock of its own and there is no second
        way for a popup to come back. A Dismiss that hid the window for good
        would be the failure this whole window exists to prevent with a button
        on it - an engineer who was never asked, and a Transaction the 24h
        Auto-Accept resolves a day later with nobody having looked.

        It is **not** an answer, which is why it goes through `_hide` and
        never through `close()`: nothing is confirmed, nothing is rejected,
        nothing is sent to the server and nothing is held in
        `pending_answers.json`. And it is offered whatever the auto-hide is
        set to, including the default of never - the return interval is its
        own setting with a floor of 1 minute and no off value, so there is no
        configuration in which Dismiss returns never.
        """
        self._cancel_hide()
        self._hide(deliberate=True)

    def _tick(self):
        # Stay open until the engineer responds; keep the popup on top.
        try:
            self.win.attributes("-topmost", True)
            self.win.lift()
        except Exception:
            return
        self.win.after(2000, self._tick)

    def close(self):
        # The one way out of this popup, whoever resolved the transaction: the
        # engineer's buttons here, or the Dashboard resolving the same id. It
        # is called at most once, because on_done is what re-arms the queue and
        # a second call would race the popup that had just been shown.
        if self._closed:
            return
        self._closed = True
        self._cancel_hide()
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.on_done:
            self.on_done()

    def _confirm(self):
        self.on_confirm(self.trans['id'])
        self.close()

    def _reject(self):
        # Hide popup first, show reason dialog
        self.win.withdraw()
        # And stop the auto-hide clock with it (#194): this window is withdrawn
        # rather than answered, and a timer that fired here would destroy the
        # popup while the dialog asking about that same Transaction is still
        # on screen - leaving a reason typed against a Transaction the app has
        # already put back in the queue.
        self._cancel_hide()

        def on_reason(reason):
            self.on_reject_r(self.trans['id'], reason)
            self.close()

        def on_cancel():
            # Reason dialog cancelled — restore popup
            try:
                self.win.deiconify()
            except Exception:
                pass
            # Back in front of the engineer, so the clock starts again.
            self._arm_hide()

        RejectReasonDialog(self.root, self.trans, on_reason,
                           on_cancel=on_cancel)

# ─── Dashboard ────────────────────────────────────────────────────────────────

class DashboardWindow:
    """The Split shape (079): Pending and History as two sections of one window.

    **Confirming a movement is a decision**, and the decision wants the model,
    the engineer, what that same asset did before now and the deadline - which
    does not fit on a row, and is why this app has a popup at all. So the
    Pending section is the list with the detail beside it, and Confirm and
    Reject sit **in the detail, beside the evidence** rather than pinned to the
    bottom of the window: what the button acts on is the thing being read.

    It replaces a scrolled column of cards, where the two buttons were on the
    card and everything the decision wanted was not - the model and the
    storekeeper were nowhere, and what that asset did last meant reading the
    History table with the queue off the screen.

    The History section is unchanged and stays a `ttk.Treeview`. It sorts by
    column, it is searched, and it is genuinely a table - which is the half of
    076's list decision that says a table stays one.

    **The tray popup stays.** It is what happens when this window is closed,
    and `notifier_pending.waiting` decides what the list holds and in what
    order, beside the `PopupQueue` that decides the tray's - two orders, on
    purpose, written down together so neither drifts into a second answer.

    Confirm and Reject go through the same callbacks the popup uses, so there
    is one code path to the server and the tray count updates either way.
    """

    def _cycle_theme(self):
        """The next of `ui_kit.MODES`, and round again - the Storekeeper's."""
        modes = ui_kit.MODES
        self.on_theme(modes[(modes.index(THEME.mode) + 1) % len(modes)])
        self._paint_theme_btn()

    def _paint_theme_btn(self):
        """The icon is the theme in force, the caption the setting behind it."""
        icon = "\u2600" if THEME.active == "light" else "\u263e"
        self.theme_btn.set_text(icon + "  " + ui_kit.MODE_LABELS[THEME.mode])
        self.theme_btn.fit_text()

    def __init__(self, root, server_url, current_user,
                 on_confirm=None, on_reject=None, on_theme=None):
        # An engineer on a custom profile with view_all_history sees the whole
        # store's history; everyone else sees only their own records.
        self.see_all = "view_all_history" in fetch_permissions(server_url,
                                                               current_user)
        self.root         = root
        self.server_url   = server_url
        self.current_user = current_user
        self.on_confirm   = on_confirm
        self.on_reject    = on_reject
        # Where a theme chosen on this window is saved; the app's
        # `_set_theme`. Without one the pill still switches the palette.
        self.on_theme     = on_theme or THEME.set
        self.rows         = []
        self._queue_by_id = {}      # what the list is currently holding, so a
                                    # click on a row finds the row
        self._busy        = set()   # ids already acted on, so a double-click
                                    # cannot send two confirmations

        win = tk.Toplevel(root)
        ui_kit.single(win, "dashboard")
        self.win = win
        win.title("Asset History — all engineers" if self.see_all
                  else "My Asset History — %s" % current_user)
        # One size, not `1140 if see_all else 1080`: a size conditional on what
        # is in the window is wrong in at least one branch by construction and
        # no sweep for geometry literals sees it (ui_kit.fit says why). Asking
        # the children is the other answer and is the wrong one here - a
        # Treeview's request does not include the width of its own columns, so
        # it would come back at 449px - so this takes the wider of the two
        # branches and leaves both axes draggable.
        win.geometry("1140x740")
        ui_kit.escape_closes(win)
        win.minsize(980, 620)
        win.configure(bg=BG)

        _style_notifier()

        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=24, pady=(18, 0))
        _mark(head, BG, ACCENT).pack(side="left")
        tk.Label(head, text="Asset Manager", bg=BG, fg=TEXT,
                 font=font("display", size=14)).pack(side="left",
                                                     padx=(11, 7))
        # Sentence case and no middle dot (#180): a `·` join is chrome, and
        # what this says is one plain thing about whose window it is.
        tk.Label(head, text="%s%s" % (current_user,
                                      ", every engineer" if self.see_all
                                      else ""),
                 bg=BG, fg=SUBTEXT,
                 font=font("label")).pack(side="left", pady=(3, 0))

        # Dark, light or whatever Windows is set to, cycled in place - the
        # Storekeeper's control in the Storekeeper's place (090). It was a
        # submenu on the tray; it is about this window, so it is on it.
        self.theme_btn = Pill(head, "", BG, CARD2, LINE, fg=TEXT, w=158,
                              h=30, bold=False, command=self._cycle_theme)
        self.theme_btn.pack(side="right", padx=(16, 0))
        self._paint_theme_btn()
        # A "Follow Windows" swap arrives from the app's tick, not from this
        # pill, and the icon is not a colour the retint walk can work out.
        THEME.watch(lambda: win.winfo_exists() and self._paint_theme_btn())

        pill = tk.Frame(head, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)
        pill.pack(side="right")
        self.status_dot = tk.Label(pill, text="●", bg=CARD, fg=SUBTEXT,
                                   font=font("value"))
        self.status_dot.pack(side="left", padx=(10, 5), pady=5)
        self.status_lbl = tk.Label(pill, text="Checking…", bg=CARD, fg=TEXT,
                                   font=font("emph", size=9))
        self.status_lbl.pack(side="left", padx=(0, 11))

        # The app's whole navigation, and the three-figure strip is gone with
        # the tabs it stood over. The pending figure is the list's own header
        # count, beside the rows it counts; the confirmed and rejected ones
        # describe the History table and have moved onto its search row, which
        # is what they were always about - the comment in `_load` said so
        # while they sat above both sections saying it about neither.
        self.sections = ui_kit.SectionBar(win, ("Pending", "History"),
                                          BG, CARD, TEXT, SUBTEXT, LINE,
                                          command=self.show)
        self.sections.pack(fill="x", pady=(14, 0))

        foot = tk.Frame(win, bg=BG)
        foot.pack(fill="x", side="bottom", padx=24, pady=(0, 18))
        self.note = tk.Label(foot, text="", bg=BG, fg=FAINT,
                             font=font("body"), anchor="w")
        self.note.pack(side="left")
        Pill(foot, "↻  Refresh", BG, CARD2, LINE, fg=TEXT, w=110, h=32,
             bold=False, command=self._load).pack(side="right", anchor="n")

        # CARD rather than BG: the selected section cell is PANEL against the
        # SHELL the strip stands on, so the pane under it continues that cell
        # rather than stepping back down a level a hairline below it.
        body = tk.Frame(win, bg=CARD)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 6))

        # Each section is built once and shown with pack/pack_forget.
        # Rebuilding on every switch would mean a section change could destroy
        # a table mid-write.
        self._panes = {}

        # -- Pending: the list, and the detail beside it ----------------------
        self._panes["Pending"] = tk.Frame(body, bg=CARD)
        qh = tk.Frame(self._panes["Pending"], bg=CARD)
        qh.pack(fill="x", pady=(12, 7))
        tk.Label(qh, text="Waiting on you", bg=CARD, fg=TEXT,
                 font=font("emph", size=11)).pack(side="left")
        # The count the "Pending  (2)" tab label used to carry, drawn as a
        # count is drawn everywhere in this build. It is here rather than on
        # the section cell because `SectionBar` paints by name and a label that
        # changes is a name that changes.
        self.queue_count = tk.Label(qh, text="", bg=CARD, fg=WARNING,
                                    font=font("figure", size=13))
        self.queue_count.pack(side="right")
        tk.Frame(self._panes["Pending"], bg=LINE, height=1).pack(fill="x")

        self.split = tk.Frame(self._panes["Pending"], bg=CARD)
        self.listing = ui_kit.ListPane(self.split, CARD, INPUT_BG, TEXT,
                                       SUBTEXT, LINE,
                                       command=self._paint_detail)
        self.listing.pack(side="left", fill="y")
        tk.Frame(self.split, bg=LINE, width=1).pack(side="left", fill="y")
        self.detail = ui_kit.DetailPane(self.split, CARD, INPUT_BG, TEXT,
                                        SUBTEXT, FAINT, LINE, hot=CARD2,
                                        ink=BG)
        self.detail.pack(side="left", fill="both", expand=True)

        # The empty state replaces the whole split rather than writing a line
        # into the pane: with nothing pending there is no list, and a detail
        # pane standing beside no list is an empty half of a window. It stops
        # describing the tray as the place this happens and says what will land
        # here, the tray being the thing that points at it.
        self.empty = tk.Frame(self._panes["Pending"], bg=CARD)
        tk.Label(self.empty, text="Nothing to confirm", bg=CARD, fg=TEXT,
                 font=font("hero")).pack(anchor="w", pady=(26, 7))
        tk.Label(self.empty,
                 text="When the store logs a movement against you it lands "
                      "here, and the tray icon pops it up.",
                 bg=CARD, fg=SUBTEXT, font=font("label")).pack(anchor="w")

        # -- History: the table, unchanged ------------------------------------
        self._panes["History"] = tk.Frame(body, bg=CARD)
        srow = tk.Frame(self._panes["History"], bg=CARD)
        srow.pack(fill="x", pady=(12, 8))
        tk.Label(srow, text="Search", bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(side="left", padx=(0, 8))
        self.search_e = tk.Entry(srow, bg=INPUT_BG, fg=TEXT, relief="flat",
                                 insertbackground=TEXT, font=font("value"))
        self.search_e.pack(side="left", fill="x", expand=True, ipady=5)
        self.search_e.bind("<KeyRelease>", lambda _e: self._paint_table())
        self.count_lbl = tk.Label(srow, text="", bg=CARD, fg=FAINT,
                                  font=font("body"))
        self.count_lbl.pack(side="left", padx=(10, 0))
        # What the two remaining figures were always describing. Packed after
        # the count so they read as three facts about the same table.
        self.stat_lbls = {}
        for key, label, colour in (("confirmed", "confirmed", SUCCESS),
                                   ("rejected", "rejected", DANGER)):
            cell = tk.Frame(srow, bg=CARD)
            cell.pack(side="left", padx=(14, 0))
            v = tk.Label(cell, text="—", bg=CARD, fg=colour,
                         font=font("figure", size=13))
            v.pack(side="left")
            tk.Label(cell, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("body")).pack(side="left", padx=(5, 0),
                                             pady=(4, 0))
            self.stat_lbls[key] = v

        # Asset No. and Serial No. are the first data columns - project rule 4.
        cols = ("Asset No.", "Serial No.", "Model", "Type",
                "Direction", "Status", "Rejection Reason", "Logged At")
        if self.see_all:
            # Without this the rows of four engineers are indistinguishable.
            cols = cols + ("Engineer",)
        widths = [90, 125, 165, 85, 80, 105, 160, 105, 130]
        # A ring and the padding inside it: the rows themselves are a ttk
        # Treeview drawn out of its own style.
        wrap = tk.Frame(self._panes["History"], bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)   # the ring is the table's
                                                    # edge, CARD on CARD
        wrap.pack(fill="both", expand=True, pady=(0, 4))
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 style="DB.Treeview")
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w", stretch=(c == "Model"))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        _tag_status(self.tree)

        self.show("Pending")
        self._load()

    # -- sections --------------------------------------------------------
    def show(self, name):
        """Put one section in the body, and paint the bar to match.

        Called both by the bar - which does not paint itself from `command` -
        and from `__init__`, which is the one path where the two differ:
        `SectionBar.select` deliberately does not fire `command`, so a window
        restoring the section it was left on cannot rebuild what it restores.
        """
        for pane in self._panes.values():
            pane.pack_forget()
        self._panes[name].pack(fill="both", expand=True)
        self.sections.select(name)

    # -- data ------------------------------------------------------------
    def _load(self):
        """Fetch once and paint both tabs from the same rows. Runs on the Tk
        thread: the window is opened from the tray menu, not from the poller,
        and the fetch is a single call with a timeout."""
        try:
            resp = api("get", "%s/transactions" % self.server_url,
                       params=None if self.see_all
                       else {"member": self.current_user}, timeout=8)
            self.rows = resp.json() if resp.ok else []
            online = resp.ok
        except Exception:
            self.rows = []
            online = False
        self.rows.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        self.status_dot.config(fg=SUCCESS if online else DANGER)
        self.status_lbl.config(text="Online" if online else "Server unreachable")
        # The list's header count is a count of what the list actually
        # offers, so it counts the queue's own rows and not the widened set - a
        # figure reading 9 over a queue of 2 is the same defect one level up.
        # The confirmed and rejected figures describe the History table, which
        # view_all_history does widen, and sit on that table's own row.
        self.stat_lbls["confirmed"].config(
            text=str(sum(1 for r in self.rows if _status_of(r) == "confirmed")))
        self.stat_lbls["rejected"].config(
            text=str(sum(1 for r in self.rows if _status_of(r) == "rejected")))
        self._paint_queue()
        self._paint_table()
        self.note.config(
            text="Nothing could be loaded — the server did not answer."
            if not online else
            "Confirm and Reject here do the same as the popup.")

    def _queue_rows(self):
        """The rows the Pending section offers Confirm and Reject on.

        `notifier_pending.waiting` decides it - which rows and in what order -
        beside the `PopupQueue` that decides the tray's. The scope is the part
        that has to hold: a row belonging to somebody else, offered here, is an
        engineer resolving a Transaction nobody asked them about, and the
        server accepts that deliberately and permanently (ADR-0002). The
        reasoning is with the function.
        """
        return notifier_pending.waiting(self.rows, self.current_user,
                                        self._busy)

    def _previously(self, row):
        """What this same asset did before this movement, out of the rows this
        window already holds.

        Read off what was fetched rather than asked of the database: this
        window makes one call and a query per selection is a query per click.
        The cost is stated rather than hidden - **without `view_all_history`
        the fetch is this engineer's own rows**, so a movement of this asset by
        somebody else is not listed here, and the Server console's Manage
        Transaction History is the window that has all of them.
        """
        key = (row.get("asset_number"), row.get("serial_number"))
        out = []
        for other in self.rows:
            if other.get("id") == row.get("id"):
                continue
            if (other.get("asset_number"),
                    other.get("serial_number")) != key:
                continue
            if str(other.get("timestamp") or "") >= str(row.get("timestamp")
                                                        or ""):
                continue
            out.append("%s, %s, %s" % (other.get("direction", ""),
                                       other.get("team_member", ""),
                                       _when(other, "%d %b")))
            if len(out) == 4:
                break
        return out

    def _paint_queue(self):
        """The list, and whichever row the detail is standing beside."""
        mine = self._queue_rows()
        self.queue_count.config(text=str(len(mine)))
        self._queue_by_id = {r["id"]: r for r in mine}
        if not mine:
            self.listing.clear()
            self.detail.clear()
            self.split.pack_forget()
            self.empty.pack(fill="both", expand=True)
            return
        self.empty.pack_forget()
        self.split.pack(fill="both", expand=True)
        # Which row was selected, read back before the list is emptied: a
        # repaint is the queue having moved and not the engineer having changed
        # their mind, so a selection that still exists survives one.
        was = self.listing.selected
        self.listing.clear()
        for r in mine:
            colour, word = _dir_bits(r)
            state, state_fg = _deadline_words(r)
            self.listing.add(str(r.get("asset_number") or "\u2014"),
                             sub=str(r.get("serial_number") or "\u2014"),
                             word=word, word_fg=colour,
                             state=state, state_fg=state_fg,
                             gutter=colour, key=r["id"])
        pick = was if was in self._queue_by_id else mine[0]["id"]
        self.listing.select(pick)
        self._paint_detail(pick)

    def _paint_detail(self, tid):
        """The pane beside the list: one movement, and the two answers to it.

        Confirm and Reject are **here**, beside the model, the engineer, the
        storekeeper, the deadline and what this asset did last - which is 079's
        whole argument. On the card they were beside three of those facts and
        none of the others; pinned to the bottom of the window they would be
        beside none of them.
        """
        row = self._queue_by_id.get(tid)
        if row is None:
            self.detail.clear("Select a movement on the left to answer it.")
            return
        colour, word = _dir_bits(row)
        state, state_fg = _deadline_words(row)
        self.detail.show(
            str(row.get("asset_number") or "no asset number"),
            sub=str(row.get("serial_number") or ""),
            word="%s store" % word, word_fg=colour,
            state=state, state_fg=state_fg, gutter=colour,
            # No Engineer row would be wrong here even though the queue is this
            # engineer's own: this is the pane a decision is made off, and the
            # name the store logged it against is part of what is being agreed
            # to.
            fields=(("Asset type", row.get("asset_type") or "\u2014"),
                    ("Model", row.get("asset_model") or "\u2014"),
                    ("Engineer", row.get("team_member") or "\u2014"),
                    ("Storekeeper", row.get("storekeeper")
                     or STOREKEEPER_FALLBACK),
                    ("Logged", "%s  (%s)" % (_when(row), _ago(row)))),
            history=self._previously(row),
            # The write action inverted, the refusal quiet beside it, in the
            # order the popup says them (#180).
            actions=(("Confirm", True, lambda r=row: self._do_confirm(r)),
                     ("Reject", False, lambda r=row: self._do_reject(r))))

    def _paint_table(self):
        q = self.search_e.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        shown = 0
        day = None
        for r in self.rows:
            vals = self._row_values(r)
            if q and not any(q in str(v).lower() for v in vals):
                continue
            # Day groups only make sense in timestamp order, which is the only
            # order this table has.
            d = _day_of(r)
            if not q and d != day:
                day = d
                # Sentence case (#180): `_day_of` already says "Today" and
                # "Sat 05 Sep", and shouting it was the eyebrow treatment
                # variant E takes off every label in these windows.
                self.tree.insert("", "end",
                                 values=(d,) + ("",) * (len(vals) - 1),
                                 tags=("day",))
            self.tree.insert("", "end", values=vals, tags=(_status_of(r),))
            shown += 1
        self.count_lbl.config(text=("%d of %d" % (shown, len(self.rows))) if q
                              else "%d records" % len(self.rows))

    def _row_values(self, r):
        st = _status_of(r)
        glyph = {"pending": "● Pending", "confirmed": "✓ Confirmed",
                 "rejected": "✕ Rejected"}[st]
        if st != "pending":
            glyph += origin_suffix(r)
        ts = _when(r, "%d/%m/%y %H:%M")
        vals = (r.get('asset_number', ''), r.get('serial_number', ''),
                r.get('asset_model', '') or "—", r.get('asset_type', ''),
                _dir_bits(r)[1],
                glyph, r.get('rejection_reason', '') or '', ts)
        if self.see_all:
            vals = vals + (r.get('team_member', ''),)
        return vals

    # -- actions ---------------------------------------------------------
    def _do_confirm(self, row):
        if row["id"] in self._busy:
            return
        self._busy.add(row["id"])
        if self.on_confirm:
            self.on_confirm(row["id"])
        self.note.config(text="Confirmed %s." % _ident(row))
        self._load()

    def _do_reject(self, row):
        if row["id"] in self._busy:
            return

        def on_reason(reason):
            self._busy.add(row["id"])
            if self.on_reject:
                self.on_reject(row["id"], reason)
            self.note.config(text="Rejected %s." % _ident(row))
            self._load()

        RejectReasonDialog(self.win, row, on_reason)

# ─── Admin Auth (for Notifier settings) ──────────────────────────────────────

# ─── Own Password ────────────────────────────────────────────────────────────

class OwnPasswordWindow:
    """Where an Engineer chooses their own Own Password.

    Two ways in and one form. The tray menu opens it whenever an engineer wants
    to change a password they already have, and the logon window opens it with
    `forced` set when the server has just said the password they logged on
    with is a temporary one an admin set - then it is what has to happen
    before they carry on.

    **Nothing here can stop a Transaction being confirmed.** It is a Toplevel
    the engineer can close, the poll loop and the popup queue never consult it,
    it takes no grab, and a server that cannot be reached ends as a line on
    this window and nothing else. An engineer who stops being asked to confirm
    anything is the one failure this app exists to prevent, so a password
    replacement is never allowed to become that.

    The current password is pre-filled on the forced path because the engineer
    typed it a second ago, into the dialog that sent them here - and left
    editable, since an admin standing beside them may want to type the admin
    password instead, which the endpoint also accepts. That leaves the new
    password Temporary as well, and the engineer is asked once more: the server
    cannot tell an admin at this keyboard from one on the far side of the
    network, so it marks what an admin-proved password leaves behind either way
    (ADR-0009). The way to finish is for the engineer to type their own. Refusals are shown in
    the server's own words: it is the server that knows whether this engineer
    has an Own Password at all.
    """

    def __init__(self, root, server_url, name, current="", forced=False,
                 on_done=None):
        self.server_url = server_url.rstrip("/")
        self.name       = name
        self.on_done    = on_done

        win = tk.Toplevel(root)
        ui_kit.single(win, "own_password")
        win.title("Change My Password")
        win.configure(bg=BG)
        # Width only, the way every other window here does it. The height is
        # never written down - ui_kit.fit takes it from what the children ask
        # for once they are all packed. The minsize is the other half of that
        # rule: a draggable width with no floor drags to nothing, and the two
        # password fields and their captions are what 380 is.
        win.resizable(True, False)
        win.minsize(380, 320)
        # No `-topmost` (#193). Only the confirm/reject popup is always on
        # top in this product, and that is what makes it mean something:
        # a window somebody opened is already in front of them, and one
        # pinned over every other app is one they cannot put down to go
        # and read what it is asking about.

        hdr = tk.Frame(win, bg=ACCENT, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🔑  Change My Password", bg=ACCENT, fg="white",
                 font=font("title")).pack(side="left", padx=16,
                                                     pady=12)

        # Before the form and from the bottom, so the button that submits is
        # the first child served rather than the last: pack gives a shortfall
        # to whatever went in last, and the height cannot be dragged. See
        # ui_kit.fit.
        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x")

        # rewrap: the width drags and 380 was the answer at the width fit gives
        # it, so it stays the floor and anything wider comes from the window.
        # 40 is the padx below, on both sides.
        ui_kit.rewrap(tk.Label(
            win,
            text=("Your password was set for you and has to be replaced "
                  "before Settings will open."
                  if forced else
                  "Your Own Password opens your own Settings. It is not "
                  "the admin password and it opens nothing of anybody "
                  "else's."),
            bg=BG, fg=SUBTEXT, font=font("body"), wraplength=380,
            justify="left"), 40).pack(anchor="w", padx=20, pady=(12, 0))

        frm = tk.Frame(win, bg=CARD2, padx=20, pady=14)
        frm.pack(fill="x", padx=20, pady=12)

        def pw_field(label, value=""):
            tk.Label(frm, text=label, bg=CARD2, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 3))
            e = tk.Entry(frm, show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
            e.insert(0, value)
            e.pack(fill="x", ipady=7)
            ui_kit.reveal(e)
            return e

        self.cur_e = pw_field("Current Password  ·  or the admin password",
                              current)
        self.new_e = pw_field("New Password")
        self.cnf_e = pw_field("Confirm New Password")
        self.cnf_e.bind("<Return>", lambda _: self._submit())

        self.err = tk.Label(win, text="", bg=BG, fg=DANGER,
                            font=font("body"), wraplength=380,
                            justify="left")
        self.err.pack(anchor="w", padx=20, pady=(2, 0))
        ui_kit.rewrap(self.err, 40)

        tk.Button(foot, text="Change Password", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat",
                  cursor="hand2", pady=9, command=self._submit,
                  activebackground=ACCENT2).pack(fill="x", padx=20,
                                                 pady=(4, 12))

        ui_kit.fit(win, 420)
        ui_kit.escape_closes(win)

        self.win = win
        (self.new_e if current else self.cur_e).focus_set()

    def _submit(self):
        new = self.new_e.get()
        if new != self.cnf_e.get():
            self.err.config(text="✗  New password and confirmation do not "
                                 "match.", fg=DANGER)
            return
        try:
            r = api("post", "%s/auth/change_password" % self.server_url,
                    json={"name": self.name,
                          "current_password": self.cur_e.get(),
                          "new_password": new})
        except Exception:
            # The one case that must not turn into a lockout: the engineer is
            # told the check could not be made and everything else keeps
            # working, popups included.
            self.err.config(text="⚠  Cannot reach the server. Your password is "
                                 "unchanged - confirming and rejecting are "
                                 "unaffected.", fg=WARNING)
            return
        if not r.ok:
            # The server's own words: only it knows whether this engineer has
            # an Own Password to change at all.
            try:
                say = (r.json() or {}).get("error", "Refused.")
            except Exception:
                say = "Refused."
            self.err.config(text="✗  " + say, fg=DANGER)
            return
        self.win.destroy()
        messagebox.showinfo("Password Changed",
                            "✓  Your password has been changed.")
        if self.on_done:
            self.on_done()


# ─── Main Notifier App ────────────────────────────────────────────────────────

class NotifierApp:
    def __init__(self):
        self.cfg          = load_config()
        # Before any widget exists, so the first window is born in the right
        # palette rather than being repainted a moment after it appears.
        THEME.set(ui_kit.read_mode(self.cfg))
        self.server_url   = self.cfg["server_url"]
        self.current_user = self.cfg["current_user"]
        self.poll_secs    = poll_secs(self.cfg)
        # How long a popup stays up and how long it waits before coming back
        # (#194), both read through the clamping readers rather than off the
        # dict, `config.json` being a file on the engineer's own machine.
        self.popup_hide_secs = dismiss_secs(self.cfg)
        # The queue, the ids already offered and the gap a deferred popup waits
        # out - one invariant rather than three fields, which is why they moved
        # together into notifier_pending.PopupQueue (#208). What stays here is
        # the window on screen and the Tk timer, neither of which that module
        # is allowed to know about.
        self.popups = notifier_pending.PopupQueue(
            repeat_mins(self.cfg) * 60 * 1000)
        self._current_popup  = None   # only one popup on screen at a time
        self._hold_job = None
        self.running      = True
        self.tray_icon    = None
        # The maintenance hold the flush last reported, so a restore that runs
        # for ten minutes is one line in the log rather than one every tick.
        self._held_said   = ""    # the server's words, last time it held
        self._cmd_queue      = []     # collected by the poller, obeyed on Tk

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Asset Notifier")
        # `True`, so the popup, the dashboard and every dialog here inherit it:
        # they are all Toplevels of this one root. No badge - a window that is
        # already open is not what the badge is for.
        ui_kit.set_window_icon(self.root)
        # One Tk is enough for the whole app: every popup and dialog here is a
        # Toplevel of it, and the retint walk reaches a window's children.
        THEME.register(self.root)
        self._theme_ticks = 0

        # Asked from the poll thread, drawn on this one. Registered before
        # either worker starts, since the first poll is what runs into a
        # missing certificate.
        common.set_cert_confirm(self._confirm_cert)

        # To this machine's own client.log, and queued for the server. The
        # poll loop below is what ships it - there is no resolved server here
        # yet, and a laptop that never reaches one still has the file.
        log_event("app.started",
                  "NotifierApp %s  ·  %s" % (APP_VERSION,
                                             self.current_user or "(nobody)"))

        # And what the last update did, if this start is the one after one.
        # It is `common.py`'s because the file, the three event names and the
        # wording are one fact both clients state (rule 10); what is this
        # app's is that it is asked here, immediately after `app.started`, so
        # the two entries that bracket the update sit together on the Admin's
        # timeline. It answers "" on every ordinary start.
        report_update_result()

        # Seeded here rather than from run(): after() on the main thread is
        # legal before mainloop and simply queues, and this way the drain exists
        # from the moment the poller can put something in the list.
        self.root.after(1200, self._drain_commands)
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._check_update, daemon=True).start()

    def _confirm_cert(self, fingerprint, server_url):
        """Ask the engineer to accept the server's certificate on first contact.

        Every request here is made from the poll thread, so the question is
        marshalled onto the Tk thread and that worker waits for the answer -
        common.confirm_on_tk_thread refuses rather than pins where there is
        nobody to ask. Cancel is the default button: this is the one dialog in
        this app where the safe answer is to do nothing.
        """
        title, body = common.cert_prompt_text(fingerprint, server_url)
        return common.confirm_on_tk_thread(
            self.root,
            lambda: messagebox.askokcancel(title, body, icon="warning",
                                           default="cancel"))

    # One update at a time. The tray's Check for Updates can be clicked again
    # while a download is running, and two appliers waiting on the same pid
    # would both extract over the same directory.
    _updating = False

    def _check_update(self):
        res = check_for_update(self.server_url)
        if res:
            latest, url, has_pkg = res
            self.root.after(0, lambda: self._prompt_update(latest, url, has_pkg))

    def _manual_update_check(self, icon=None, item=None):
        """User-initiated check from the tray menu."""
        def work():
            try:
                r = api("get", f"{self.server_url}/version", timeout=6)
                if r.ok:
                    d = r.json(); latest = d.get("latest", "")
                    if latest and _ver_tuple(latest) > _ver_tuple(APP_VERSION):
                        dl = d.get("download_path", ""); url = f"{self.server_url}{dl}" if dl else ""
                        pkg = _has_client_package(d, UPDATE_APP_KEY)
                        self.root.after(0, lambda: self._prompt_update(latest, url, pkg, manual=True))
                        return
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Up to Date", f"You're on the latest version (v{APP_VERSION})."))
                    return
            except Exception:
                pass
            self.root.after(0, lambda: messagebox.showwarning(
                "Check for Updates", "Couldn't reach the server to check for updates."))
        threading.Thread(target=work, daemon=True).start()

    def _prompt_update(self, latest, url, has_pkg=False, manual=False):
        st = _load_update_state()
        count = st.get("count", 0) if st.get("version") == latest else 0

        # A server whose APP_VERSION is ahead of anything it actually holds
        # has nothing to offer, and the branch further down is the dead end
        # that says so. On a launch check that is a dialog nobody in front of
        # it can do anything about, shown again on every launch for as long as
        # the bundles are missing - and an update.offered beside it recording
        # an offer that was not one. So a launch check says nothing and writes
        # nothing, and an installation that is behind stays visible to the
        # Admin exactly where it already was, in Connected Clients. A manual
        # check is a question somebody asked, and is answered.
        if not (url or has_pkg) and not manual:
            return

        # Every offer, including the forced one below and the one this server
        # holds no package for: what the Admin is owed is that this
        # installation was told about the version, which is the fact the three
        # branches under here all share. Written once, above them, rather than
        # once per branch.
        log_event("update.offered",
                  "%s published; this install is on %s"
                  % (latest, APP_VERSION))

        if count >= MAX_LATER and (url or has_pkg):
            self._forced_update(latest, url, has_pkg)
            return

        if not (url or has_pkg):
            messagebox.showinfo("Update Available",
                f"A newer version (v{latest}) is available — you have v{APP_VERSION}.\n\n"
                "Please contact your admin to update.")
            return

        remaining = MAX_LATER - count
        # Two different answers behind one Yes. Where the server holds the
        # source zip this installs it in place and the notifier closes and
        # reopens by itself; where it does not, the old browser download of
        # AssetManager_Setup.exe is still what an engineer gets. The question
        # says which, because the two cost the person in front of it very
        # different amounts of attention.
        how = ("Yes = update now; the notifier will close and reopen"
               if has_pkg else "Yes = download • No = remind me later")
        if messagebox.askyesno("Update Available",
                f"A newer version of Asset Notifier is available "
                f"(v{latest} — you have v{APP_VERSION}).\n\n"
                f"You can postpone {remaining} more time(s) before the update is required.\n\n"
                f"Update now?  ({how})"):
            if has_pkg:
                self._apply_source_update(latest)
                return
            try:
                webbrowser.open(url)
            except Exception:
                pass
        else:
            log_event("update.declined",
                      "%s postponed (%d of %d)"
                      % (latest, count + 1, MAX_LATER))
            _save_update_state({"version": latest, "count": count + 1})

    def _apply_source_update(self, latest):
        """Download the published zip, then hand over to the applier and quit.

        On a worker, because the download is megabytes over a link that may be
        slow and the poll loop behind this window has to go on asking about
        Transactions until the moment the process actually ends. Nothing is
        stopped until client_update.update_now returns, and it returns only
        with a verified package staged - rule 13's Python check included - so
        every refusal costs a message box and leaves the notifier running.

        An engineer who is not being asked to confirm anything is the one
        failure this app exists to prevent, which is the whole shape of this."""
        if self._updating:
            return
        self._updating = True

        def work():
            try:
                client_update.update_now(UPDATE_APP_KEY, self.server_url,
                                         APP_VERSION)
            except client_update.UpdateRefused as exc:
                self._updating = False
                msg = str(exc)
                # The refusals `update_now` raises are one sentence and then a
                # paragraph for the person reading it; the first line is the
                # reason, which is what the System Log is for.
                log_event("update.verify_refused",
                          "%s: %s" % (latest, msg.split("\n")[0]),
                          level="warn")
                self.root.after(0, lambda: messagebox.showwarning("Update", msg))
                return
            except Exception:
                self._updating = False
                log_event("update.download_failed", latest, level="warn")
                self.root.after(0, lambda: messagebox.showwarning(
                    "Update", "The update could not be downloaded."))
                return
            # The postpone counter goes with the version it was counting.
            _save_update_state({})
            # `app.update` until #148, which is the same act under the name the
            # rest of the lifecycle is written in: this is the last thing this
            # process says, the applier takes over from here, and what became
            # of it is `update.applied`, `update.failed` or
            # `update.rolled_back` on the start after next.
            log_event("update.staged",
                      "%s verified and staged; restarting to apply" % latest)
            self.root.after(0, self._quit)

        threading.Thread(target=work, daemon=True).start()

    def _forced_update(self, latest, url, has_pkg=False):
        """Final, non-dismissable prompt after the postpone limit. Updating then
        stops the notifier so the old version can't keep running."""
        win = tk.Toplevel(self.root)
        win.title("Update Required")
        win.configure(bg=BG)
        win.grab_set()
        win.transient(self.root)
        # No `-topmost` (#193). What holds this window in front of the app it
        # belongs to is the `transient` above and the grab beside it, which is
        # a modal dialog rather than a window pinned over every other
        # application on the machine - and the two are routinely confused
        # because one was written here as well as the other.
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        tk.Label(win, text="⚠  Update Required", bg=DANGER, fg="white",
                 font=font("section")).pack(fill="x", ipady=10)
        # The control is packed before the form, which is what every other
        # dialog in this product does and what this one never did: `pack`
        # serves its children in the order they went in and gives the shortfall
        # to whichever was last, so the one button this window exists to be
        # pressed must not be that child (#192).
        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x")
        tell = ("Click below to install it. The notifier will close and\n"
                "reopen by itself when the update is in place."
                if has_pkg else
                "Click below to download it. The notifier will close so you can\n"
                "run AssetManager_Setup.exe and finish updating.")
        tk.Label(win, text=(f"You've postponed this update {MAX_LATER} times.\n\n"
                            f"Version v{latest} is now required (you have v{APP_VERSION}).\n\n"
                            + tell),
                 bg=BG, fg=TEXT, font=font("body"), justify="left",
                 wraplength=400).pack(padx=18, pady=14)

        def go():
            if has_pkg:
                win.destroy()
                self._apply_source_update(latest)
                return
            try:
                webbrowser.open(url)
            except Exception:
                pass
            _save_update_state({"version": latest, "count": MAX_LATER})
            # Through _quit, like every other way out of this app. It stopped
            # the loop and the tray icon here and ended at root.destroy, which
            # does both of the things this branch is for and neither of the
            # two _quit does before them: app.stopped is never written and
            # whatever client.log still holds is never shipped. There is
            # nothing after mainloop() here to catch that the way the
            # Storekeeper's entry point catches its own destroy() - and this
            # is the exit most worth recording, since the engineer is about to
            # run an installer over this install and the last thing the log
            # would otherwise say is that the Notifier was still running.
            self._quit()

        tk.Button(foot, text=("⬇  Install Now" if has_pkg
                             else "⬇  Download & Install Now"),
                  bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=go, activebackground=ACCENT2).pack(fill="x", padx=18, pady=(0, 12))
        # A written size is the copy that goes stale the next time a line is
        # added to the paragraph above, and this window states no `minsize` at
        # all - so it can be dragged below its own form on either axis, with
        # the button going first. `fit` answers both from the children: the
        # height from what they ask for and a floor derived from it (#192).
        ui_kit.fit(win, 440)

    def _poll_loop(self):
        self._poll_once()
        while self.running:
            time.sleep(self.poll_secs)
            self._poll_once()

    def _poll_once(self):
        # Logged off (090): no engineer, so nothing to ask about and no name
        # to check in under. The logon window is what puts one back.
        if not self.current_user:
            return
        # Follow the server if an admin changed the comms port. This also records
        # next_port while the old listener is still reachable, which is what
        # makes the switch survive the server restart.
        url, _health = resolve_server_url(self.cfg, save_config)
        if url:
            self.server_url = url
            sync_server_cert(self.server_url)
        # Before the check-in, deliberately: a logoff collected there ends
        # this process, and entries already written should have had their
        # chance to reach the server first. Unshipped ones stay in client.log.
        ship_log(self.server_url, self.cfg, save_config, "Notifier")
        # The tick that already follows the server is also where this
        # installation says it exists and collects whatever the Admin queued for
        # it. Handed to _drain_commands rather than obeyed here: this method
        # runs on the poll worker (and on a fresh thread after a settings
        # save), both handlers touch widgets, and root.after from a worker thread
        # raises RuntimeError while the main loop is not yet running - which the
        # very first poll, started from __init__, can easily beat. A command
        # dropped that way is gone: the server marked it collected as it handed
        # it over.
        self._cmd_queue.extend(checkin(self.server_url, self.cfg, save_config,
                                       "Notifier", APP_VERSION,
                                       self.current_user,
                                       member_key="current_user"))
        # An Engineer's name can be corrected at the Server GUI, and the
        # check-in above is where this installation is told - it sends the id
        # it has learnt and is answered with whatever that Engineer is called
        # now (`common._adopt_member` writes it into the config). What is read
        # back here is the in-memory copy: `self.current_user` is what the poll
        # below asks about and what every window here is captioned with, so a
        # name left until the next start would be a Notifier polling for
        # somebody who no longer exists, which is an Engineer who stops being
        # asked to confirm anything.
        adopted = str(self.cfg.get("current_user") or "").strip()
        if adopted and adopted != self.current_user:
            log_event("member.renamed",
                      "%s is now %s" % (self.current_user, adopted),
                      level="warn", actor=adopted)
            self.current_user = adopted
        # Before the pending read, deliberately: an answer this engineer has
        # already given must be delivered before the server is asked what is
        # still outstanding, or a Transaction they confirmed an hour ago comes
        # back as pending and is put in front of them a second time.
        self._flush_answers()
        try:
            r = api("get", f"{self.server_url}/pending/{self.current_user}")
            if r.ok:
                pending = r.json()
                if self.tray_icon:
                    has_p = len(pending) > 0
                    self.tray_icon.icon  = make_icon(has_p)
                    self.tray_icon.title = (
                        f"Asset Notifier  ({len(pending)} pending)"
                        if has_p else "Asset Notifier"
                    )
                # Before `arrived`: what left Pending stops being offered, and
                # an open popup for it closes (#284).
                shown = self._current_popup
                gone = self.popups.departed(
                    pending, shown.trans.get("id") if shown else None)
                for tid in gone:
                    self.root.after(0, self._dismiss, tid)
                new = self.popups.arrived(pending)
                if new:
                    self.root.after(0, self._show_next_popup)
                for tid in gone:
                    self._say_answered_elsewhere(tid)
        except Exception: pass

    def _say_answered_elsewhere(self, tid):
        """One request per dropped Transaction: read its row from the history
        and say where it was answered (#284). Runs on the poll worker; the
        notice itself is drawn on the Tk thread."""
        row = None
        try:
            r = api("get", "%s/transactions" % self.server_url,
                    params={"member": self.current_user}, timeout=8)
            if r.ok:
                row = next((t for t in r.json() if t.get("id") == tid), None)
        except Exception:
            pass
        text = notifier_pending.left_pending(row)
        self.root.after(0, self._show_notice, "#%s  %s" % (tid, text))

    def _show_notice(self, text):
        """A short non-modal notice, bottom right, gone after six seconds.
        Not topmost: the popup is the one window that is (#193)."""
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.configure(bg=LINE)
        ui_kit.escape_closes(win)
        tk.Label(win, text=text, bg=CARD, fg=TEXT, font=("Segoe UI", 10),
                 padx=16, pady=10).pack(padx=1, pady=1)
        win.update_idletasks()
        win.geometry("+%d+%d" % (win.winfo_screenwidth() - win.winfo_width() - 18,
                                 win.winfo_screenheight() - win.winfo_height() - 52))
        win.after(6000, win.destroy)

    def _show_next_popup(self):
        # Show one popup at a time; the next appears only after the current is
        # confirmed/rejected — so a bulk scan doesn't flood the screen with
        # stacked, flashing windows. *Which* one that is, and whether now is
        # the moment, is notifier_pending.PopupQueue's; what is left here is
        # the window and the timer.
        if self._current_popup is not None:
            return
        nxt = self.popups.next()
        if nxt.kind == notifier_pending.WAIT:
            # The gap has not elapsed yet, so come back when it has rather than
            # returning for good - what returning would cost is written down in
            # PopupQueue.next(). One pending re-arm at a time, since
            # `_popup_finished` and the poll tick call this as well and each
            # would otherwise leave a timer of its own.
            if self._hold_job is None:
                self._hold_job = self.root.after(nxt.wait_ms,
                                                 self._hold_elapsed)
            return
        if nxt.kind != notifier_pending.SHOW:
            return
        self._current_popup = NotificationPopup(
            self.root, nxt.tx,
            on_confirm=self._confirm,
            on_reject_with_reason=self._reject,
            on_done=self._popup_finished,
            queued=nxt.queued,
            hide_after=self.popup_hide_secs,
            on_hide=self._popup_hidden,
        )

    def _hold_elapsed(self):
        """The gap armed above has run out; offer the Transaction again."""
        self._hold_job = None
        self._show_next_popup()

    def _popup_finished(self):
        self._current_popup = None
        self.root.after(300, self._show_next_popup)

    def _popup_hidden(self, tx, deliberate=False):
        """A popup left the screen without being answered (#194, #201).

        Where it goes back to and how long the gap is are
        `notifier_pending.PopupQueue.deferred`'s. Deliberately **not**
        `_popup_finished` here:
        nothing was confirmed, nothing was rejected and nothing was sent to
        the server, so the 300ms advance that follows an answer would be this
        popup reappearing instantly, which is the flashing window the
        one-at-a-time queue exists to remove.

        `deliberate` is the engineer having clicked Dismiss (#201) rather than
        the timer having run out. It changes nothing about the queue - the
        same front of the same queue, the same gap, the same one timer - and
        decides one thing only, which is whether an entry is written saying a
        person put this Transaction off.
        """
        if deliberate:
            # The engineer clicked Dismiss (#201). Nothing is sent anywhere and
            # nothing is held, so this entry is the only record that they put
            # this Transaction off - which is what an Admin needs when a
            # Transaction sat unanswered for an hour on a machine somebody was
            # sitting at, and the honest thing to write down about a window
            # that was in front of them and was put away. `info`: nothing
            # failed, nothing is at risk and the popup is coming back.
            log_event("transaction.dismissed", "#%s" % tx.get("id"),
                      actor=self.current_user)
        self._current_popup = None
        wait_ms = self.popups.deferred(tx)
        if self._hold_job is not None:
            try:
                self.root.after_cancel(self._hold_job)
            except Exception:
                pass
        self._hold_job = self.root.after(wait_ms, self._hold_elapsed)

    def _dismiss(self, tid):
        # A Transaction resolved anywhere stops being asked about everywhere:
        # the Dashboard's Confirm/Reject reach _answer too, and without this
        # the popup for that id stayed on screen to be answered a second time
        # and a queued one still appeared later. Leaving the queue and leaving
        # notified_ids are one act and PopupQueue.resolved's. Closing goes
        # through the popup's own close(), so the queue is advanced by
        # _popup_finished exactly as the engineer's own buttons advance it.
        # Tk thread only - both callers are button callbacks, never the poller.
        self.popups.resolved(tid)
        popup = self._current_popup
        if popup is not None and popup.trans.get('id') == tid:
            popup.close()

    # ── The engineer's answers, when the server would not take them ──────────

    def _answers_load(self):
        try:
            if os.path.exists(ANSWER_BUFFER_PATH):
                with open(ANSWER_BUFFER_PATH, encoding="utf-8") as f:
                    got = json.load(f)
                return got if isinstance(got, list) else []
        except Exception:
            pass
        return []

    def _answers_save(self, items):
        try:
            with open(ANSWER_BUFFER_PATH, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2)
        except Exception:
            pass

    def _answers_add(self, entry):
        """Hold one answer until the server will take it.

        Written down here rather than by each caller, the way the Storekeeper's
        `_buffer_add` owns its own entry: the thing that must never be true is
        that an answer disappeared with nothing saying so. Which entries
        survive the merge - one per Transaction - is
        `notifier_pending.merge`'s.
        """
        self._answers_save(notifier_pending.merge(self._answers_load(), entry))
        log_event("answer.buffered",
                  "#%s  %s  held: %s" % (entry.get("id"),
                                         entry.get("action"),
                                         entry.get("why") or "the server "
                                         "could not be reached"),
                  level="warn", actor=self.current_user)

    def _send_answer(self, entry):
        """Try one held answer. "sent", "hold" or "refused".

        The performing half of `notifier_pending.request` and `.classify` -
        what each of those three words means, and why 409 is one of them, is
        written down there. A request that raised is handed on as `None`, a
        server that is not there being an answer about the server rather than
        an error this method has anything to do.
        """
        path, payload = notifier_pending.request(entry)
        url = "%s%s" % (self.server_url, path)
        try:
            r = (api("post", url, json=payload) if payload is not None
                 else api("post", url))
        except Exception:
            return notifier_pending.classify(None)
        return notifier_pending.classify(r)

    def _flush_answers(self):
        """Send what this engineer already answered, at the next chance.

        The run is `notifier_pending.Flush` - one hold ends it, a refusal
        leaves the queue, and both reasons are written down there. What is left
        here is performing each attempt and saying what it came to: this loop
        is on the poll worker, where each attempt is a timeout the next poll
        waits for.
        """
        items = self._answers_load()
        if not items:
            return
        run = notifier_pending.Flush(items)
        entry = run.next()
        while entry is not None:
            run.took(*self._send_answer(entry))
            entry = run.next()
        for entry, why in run.refused:
            log_event("answer.refused",
                      "#%s  %s  %s" % (entry.get("id"),
                                       entry.get("action"), why),
                      level="warn", actor=self.current_user)
        remaining = run.remaining()
        self._answers_save(remaining)
        if run.held and run.held != self._held_said:
            self._held_said = run.held
            log_event("answer.buffered",
                      "%d held  %s" % (len(remaining), run.held),
                      level="warn", actor=self.current_user)
        elif not run.held:
            self._held_said = ""

    def _answer(self, entry, event, level="info"):
        """Perform what `notifier_pending` decided about one answer.

        Held rather than lost where the server would not take it, the cost of
        losing one being written down in `notifier_pending.held`. Logged
        whether or not the call got through: the server records its own side,
        and what this file writes down is what the engineer did at this machine
        - which is the question asked when the two disagree. Then the
        Transaction stops being asked about anywhere, and a poll follows so the
        Dashboard behind the popup catches up.
        """
        hold = notifier_pending.held(entry, *self._send_answer(entry))
        if hold is not None:
            self._answers_add(hold)
        log_event(event, notifier_pending.note(entry), level=level,
                  actor=self.current_user)
        self._dismiss(entry["id"])
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _confirm(self, tid):
        """Confirmed, from the popup or from the Dashboard."""
        self._answer(notifier_pending.confirm(tid), "transaction.confirmed")

    def _reject(self, tid, reason=""):
        """Rejected. `warn` where a Confirm is not: a Reject that is lost is
        Auto-Accepted into the opposite of what the engineer said."""
        self._answer(notifier_pending.reject(tid, reason),
                     "transaction.rejected", level="warn")

    def _build_tray(self):
        if not HAS_TRAY: return
        items = [
            (lambda _i: "Asset Notifier  —  %s"
                        % (self.current_user or "nobody logged on"), None),
            (f"Version {APP_VERSION}", None),
            None,
            ("📋  View My History",  self._open_dashboard),
            ("⬆  Check for Updates",  self._manual_update_check),
            None,
            ("🔑  Change My Password", self._change_password),
            ("⚙  Settings",          self._open_settings),
            ("🛡  Remote Admin",      self._remote_admin),
            ("🚪  Log off",           self._log_off),
            ("❌  Exit",              self._quit),
        ]
        ui_kit.run_tray_icon(self.root, "AssetNotifier", "Asset Notifier",
                              make_icon(), items,
                              on_ready=lambda icon: setattr(self, "tray_icon", icon))

    def _set_theme(self, mode):
        """Chosen on the Dashboard's pill, on the Tk thread - the tray submenu
        that needed marshalling is gone (090)."""
        THEME.set(mode)
        self.cfg["theme"] = mode
        save_config(self.cfg)

    def _open_dashboard(self, *_):
        # Same callbacks the popup uses, so there is one path to the server and
        # the tray count updates whichever surface the engineer answered from.
        def open_it():
            # The guard is here rather than in DashboardWindow.__init__: the
            # decision has to be made before the window is built, and an
            # __init__ cannot abort cleanly (#191).
            if ui_kit.raise_open("dashboard") is not None:
                return
            DashboardWindow(
                self.root, self.server_url, self.current_user,
                on_confirm=self._confirm, on_reject=self._reject,
                on_theme=self._set_theme)
        self.root.after(0, open_it)

    def _change_password(self, *_):
        """The ordinary change, whenever the server is reachable.

        No password is asked for here first: the form's own Current Password
        field is the check, and it is the server that decides. Marshalled onto
        the Tk thread because the tray runs on its own, the same way a theme
        choice and a collected command are.
        """
        def open_it():
            if ui_kit.raise_open("own_password") is not None:
                return
            OwnPasswordWindow(self.root, self.server_url, self.current_user)
        self.root.after(0, open_it)

    def _remote_admin(self, *_):
        """R2's window, opened from the tray like every other one here.

        No password is asked for out here and none is held by this app: the
        window's own field is the check, what it opens is the server's
        decision, and the credential lives no longer than that window.
        Marshalled onto the Tk thread because the tray runs on its own, the
        same way a theme choice and a collected command are.
        """
        def open_it():
            if ui_kit.raise_open("remote_admin") is not None:
                return
            notifier_remote.RemoteAdminWindow(self.root, self.server_url)
        self.root.after(0, open_it)

    def _open_settings(self, *_):
        """Settings, with no password in front of it (090).

        It held the Assigned User, which is why it had a door: that field
        decided whose Transactions this laptop is asked about. Who this is
        is the logon's question now, asked with that engineer's own password,
        so what is left - the Server URL, the poll and the popup timings -
        is this machine's plumbing and nobody else's.
        """
        def do_open():
            if ui_kit.raise_open("settings") is not None:
                return
            notifier_remote.SettingsWindow(self.root, self.cfg,
                                           self.server_url, self._apply_cfg)
        self.root.after(0, do_open)

    def _log_off(self, *_):
        """Nobody is this laptop's engineer until somebody logs on (090).

        Clears the name and `setup_complete`, saves, and puts the logon
        window up at once. The popup on screen and every window open go
        first - the Dashboard, Remote Admin, their own password: all of them
        are the engineer who just left, and the next one to sit here is not
        owed their Transactions. The poll does nothing until the
        logon saves a name (`_poll_once`).
        """
        def do():
            who = self.current_user
            log_event("user.logged_off", who, actor=who)
            if self._current_popup is not None:
                self._current_popup.win.destroy()
                self._current_popup = None
            self.popups.forget()
            for w in self.root.winfo_children():
                if isinstance(w, tk.Toplevel):
                    w.destroy()
            self.current_user = ""
            self.cfg["current_user"] = ""
            self.cfg["setup_complete"] = False
            save_config(self.cfg)
            self._show_setup_wizard()
        self.root.after(0, do)

    def _apply_cfg(self, new_cfg):
        self.cfg          = new_cfg
        self.server_url   = new_cfg["server_url"]
        self.current_user = new_cfg["current_user"]
        self.poll_secs    = poll_secs(new_cfg)
        self.popup_hide_secs = dismiss_secs(new_cfg)
        self.popups.repeat_ms = repeat_mins(new_cfg) * 60 * 1000
        self.popups.forget()
        if self.tray_icon:
            self.tray_icon.title = f"Asset Notifier  —  {self.current_user}"
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _drain_commands(self):
        """Obey whatever the poller collected. Tk thread, once a second.

        A second of delay costs nothing - these are a log-off and a reset, not
        an interaction - and it buys the poller a way to hand work to the main
        thread that cannot raise on it.

        Drained as one batch, not one command at a time: obey() puts a logoff
        last so a reset_identity that arrived with it is applied first, and
        obeying them singly would hand that ordering back to arrival order and
        take the process down with the reset undone.
        """
        try:
            batch = self._cmd_queue[:]
            if batch:
                del self._cmd_queue[:len(batch)]
                obey(batch, self._commands())
            # Windows raises no event when the user switches Light and Dark
            # mode, so following it has to be a poll, and this is the tick that
            # already exists on the Tk thread. Every fifth turn: a registry read
            # is cheap but not free, and nobody flips their theme twice a
            # second. `follow` is a no-op unless the setting is "system".
            self._theme_ticks += 1
            if self._theme_ticks % 5 == 0:
                THEME.follow()
        finally:
            if self.running:
                self.root.after(1000, self._drain_commands)

    def _commands(self):
        """What each Client command means here. Called on the Tk thread.

        `logoff` is the tray menu's own Exit, so the icon goes down with the
        process instead of being left behind as a dead tray entry.

        `reset_identity` clears the identifier and reopens the logon window,
        which asks for an engineer's own password (or the admin one) before it
        will save anything - the reset does not hand this machine to whoever
        is sitting at it. The configured engineer is deliberately left in place until that
        wizard saves a new one: clearing it here would leave a Notifier polling
        for nobody the moment someone closed the wizard, and an engineer who
        stops being asked to confirm anything is the one failure this app exists
        to prevent.

        `trust_cert` is `common.trust_next_cert` and nothing of this app's: the
        fetch, the idempotent append and every refusal are transport and are
        written once for the three clients (rule 10). What is this app's is the
        line it writes down, which is the same split every other command here
        keeps. Nothing is shown to the engineer - a certificate the server has
        bound nothing to is not a thing to interrupt somebody about, and the
        one popup this app opens is the one asking about a Transaction.
        """
        def reset():
            log_event("command.obeyed", "reset_identity", level="warn")
            forget_client_id(self.cfg, save_config)
            self.cfg["setup_complete"] = False
            save_config(self.cfg)
            self._show_setup_wizard()

        def trust():
            fp = trust_next_cert(self.server_url)
            # "" is every answer but an append - nothing staged, a body that
            # was not a certificate, one this client already holds - and none
            # of those is a change worth a line claiming one was made.
            if fp:
                log_event("cert.trusted", fp, level="warn")

        def update():
            """`update_now`, obeyed. #177.

            The Admin's end of the update path, and deliberately nothing but a
            call into the one this app's own Check for Updates uses: the
            package, the pinned download, the SHA-256 and manifest checks made
            before anything is stopped, the applier, the rollback and the
            `update.applied` / `update.failed` / `update.rolled_back` that comes
            back on the start after (#148) are all that path's and none of them
            are re-decided here. What a push changes is who asked, which is why
            the postpone counter is not touched and no question is put on
            screen - an offer that cannot be declined is not an offer, and this
            one was accepted at the console.

            `check_for_update` answers None for a server advertising nothing
            newer, which is the ordinary state on a machine that has already
            updated itself since the Admin queued this - so that is a line and
            not a failure. The version that is checked is the live one rather
            than anything carried on the command: `_queue_command` refuses a
            push this server holds no package for, but a week may pass before
            the machine collects it, and the answer to what is published now is
            the server's to give now.
            """
            found = check_for_update(self.server_url)
            if not found:
                log_event("command.obeyed",
                          "update_now: nothing newer than %s is published"
                          % APP_VERSION)
                return
            latest, _url, has_pkg = found
            if not has_pkg:
                # The queue refused this case at issue time; reaching it means
                # the package stopped being there in between, and sending an
                # engineer who asked for nothing to a browser is not a push.
                log_event("command.obeyed",
                          "update_now: %s is published but this server holds "
                          "no package for it" % latest, level="warn")
                return
            log_event("command.obeyed", "update_now: applying %s" % latest,
                      level="warn")
            self._apply_source_update(latest)

        return {"logoff": self._quit, "reset_identity": reset,
                "trust_cert": trust, "update_now": update}

    def _quit(self, *_):
        # Written and shipped before the loop is stopped, since the poll worker
        # that would otherwise ship it is about to end. client.log has it even
        # when the ship does not get through.
        log_event("app.stopped",
                  "NotifierApp %s  ·  %s" % (APP_VERSION,
                                             self.current_user or "(nobody)"))
        ship_log(self.server_url, self.cfg, save_config, "Notifier",
                 timeout=2)
        self.running = False
        if self.tray_icon: self.tray_icon.stop()
        self.root.after(0, self.root.quit)

    def _check_first_run(self):
        """Show setup wizard on first run (when no user is configured yet)."""
        is_first = self.cfg.get("setup_complete") != True
        if is_first:
            self.root.after(400, self._show_setup_wizard)

    def _show_setup_wizard(self):
        """The logon window: first run, after Log off, after a reset.

        An engineer picks their name and types **their own password** (090);
        `verify_password` asks `/auth/verify`, which accepts that password for
        that name only, and the admin password for any. It used to take the
        admin password alone, because an own password opening it would have
        let one engineer point a laptop at another's name - a name-bound
        password is what closes that, since it proves the name typed.
        """
        if ui_kit.raise_open("setup_wizard") is not None:
            return
        win = tk.Toplevel(self.root)
        ui_kit.single(win, "setup_wizard")
        win.title("Asset Notifier — Log on")
        win.configure(bg=BG)
        win.resizable(True, False)
        win.minsize(380, 400)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        # Before the form and from the bottom: written at 420x400 against a
        # 326x426 form, Complete Setup was drawn 27px of the 53 it asks for,
        # and the height cannot be dragged. This is the window an engineer
        # sees first. See ui_kit.fit.
        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x")

        # Header
        hdr = tk.Frame(win, bg=ACCENT, height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📦  Asset Notifier — Log on",
                 bg=ACCENT, fg="white",
                 font=font("section")).pack(side="left", padx=16, pady=14)

        tk.Label(win,
                 text="Pick your name and type your own password.",
                 bg=BG, fg=SUBTEXT,
                 font=font("body")).pack(pady=(14, 0), padx=20, anchor="w")

        frm = tk.Frame(win, bg=CARD2, padx=20, pady=16)
        frm.pack(fill="x", padx=20, pady=10)

        def lbl(text):
            tk.Label(frm, text=text, bg=CARD2, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(8, 3))

        lbl("Server URL")
        url_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
        url_e.insert(0, self.cfg.get("server_url")
                     or "https://asset-server:8081")
        url_e.pack(fill="x", ipady=8)

        lbl("Engineer")
        member_row = tk.Frame(frm, bg=CARD2)
        member_row.pack(fill="x")
        _initial = fetch_members(url_e.get().strip())
        member_cb = ttk.Combobox(member_row, values=_initial,
                                 state="readonly", font=font("value"))
        member_cb.set(_initial[0])
        member_cb.pack(side="left", fill="x", expand=True, ipady=4)
        def _reload_members():
            vals = fetch_members(url_e.get().strip())
            member_cb["values"] = vals
            if member_cb.get() not in vals:
                member_cb.set(vals[0])
        tk.Button(member_row, text="↻", bg=ACCENT, fg="white", relief="flat",
                  cursor="hand2", font=font("heading"), width=3,
                  command=_reload_members).pack(side="left", padx=(6, 0))

        lbl("Your password")
        pw_e = tk.Entry(frm, show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                        font=font("value"), insertbackground=TEXT)
        pw_e.pack(fill="x", ipady=8)
        ui_kit.reveal(pw_e)
        pw_e.focus_set()

        err_lbl = tk.Label(win, text="", bg=BG, fg=DANGER, font=font("body"))
        err_lbl.pack(pady=(0, 4))

        def finish():
            server = url_e.get().strip().rstrip("/")
            member = member_cb.get()
            pw     = pw_e.get()
            if not server or not member or not pw:
                err_lbl.config(text="All fields are required.")
                return
            err_lbl.config(text="Verifying…", fg=SUBTEXT)
            win.update()
            try:
                d = verify_password(server, member, pw)
            except Exception:
                err_lbl.config(text="⚠  Cannot reach server. Check the URL.", fg=DANGER)
                return
            if not d.get("valid"):
                err_lbl.config(text="❌  Wrong password.", fg=DANGER)
                return
            # Over the config that is here rather than a fresh dict: a log
            # off keeps this installation's client_id, theme and timings.
            new_cfg = dict(self.cfg)
            new_cfg.update(server_url=server, current_user=member,
                           setup_complete=True)
            save_config(new_cfg)
            self._apply_cfg(new_cfg)
            win.destroy()
            # A temporary Own Password is replaced before anything else, on
            # the engineer's own path only - an admin who typed the admin
            # password is not the person who has to replace it.
            if d.get("must_change_password") and not d.get("admin"):
                OwnPasswordWindow(self.root, server, member, current=pw,
                                  forced=True)
                return
            messagebox.showinfo(
                "Logged on",
                f"✓  Logged on as  {member}\n\n"
                "The notifier is now running in the system tray.")

        tk.Button(foot, text="✔  Log on",
                  bg=ACCENT, fg="white",
                  font=font("title"),
                  relief="flat", cursor="hand2", pady=10,
                  command=finish,
                  activebackground=ACCENT2).pack(fill="x", padx=20, pady=6)
        ui_kit.fit(win, 420)
        ui_kit.escape_closes(win)

    def run(self):
        self._check_first_run()
        if HAS_TRAY:
            threading.Thread(target=self._build_tray, daemon=True).start()
        else:
            self.root.deiconify()
            self.root.configure(bg=BG)
            tk.Label(self.root,
                     text="Asset Notifier is running.\nKeep this window open.",
                     bg=BG, fg=TEXT, font=font("label")).pack(pady=30, padx=30)
        self.root.mainloop()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = NotifierApp()
    app.run()
