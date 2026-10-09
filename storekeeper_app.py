"""
Asset Manager — Storekeeper App

Whose name this installation records Transactions under is a setting, not a
literal: the Admin sets it in the Server GUI's Manage Users window and it
arrives on /health. "Storekeeper User" is only the default, which is what every
Transaction recorded before the setting existed carries.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import requests, json, os, sys, threading, webbrowser
import client_update
from datetime import datetime, date, timedelta

# Wire layer shared with the Notifier and the installer - see common.py.
import common
# The Export window and the workbook it writes, lifted out by #219 - reached
# below as storekeeper_export.ExportDialog. It reaches back through bind().
import storekeeper_export
# The Bulk submit window, lifted out by #236 the same way - reached below as
# self._bulk, a storekeeper_bulk.BulkWindow. It reaches back through bind().
import storekeeper_bulk
# The Propose and Import dialogs (#237) are self._propose, a
# storekeeper_propose.ProposeDialogs. It reaches back through bind().
import storekeeper_propose
from common import (api, resolve_server_url, sync_server_cert, MAX_LATER,
                    TEAM_MEMBERS, _ver_tuple, _load_update_state,
                    _save_update_state, checkin, forget_client_id, obey,
                    trust_next_cert, verify_admin_password, log_event,
                    ship_log, cached_asset_types, fetch_asset_types,
                    lookup_asset, report_update_result, _has_client_package,
                    _mark, origin_suffix)
# The window kit shared with the Notifier and the Server GUI: the two palette
# tables, the live retint, and the button row that lays itself out against the
# width it actually has. See ui_kit.py.
import ui_kit

APP_VERSION = "2.10.1"   # compared against the server's /version to offer updates

# What this app is called on the wire, to /version's client_packages and to
# /download/client/<key>. The same word names the zip tools/bundle-client.ps1
# builds (-App storekeeper) and the key server.py resolves it under.
UPDATE_APP_KEY = "storekeeper"


# ─── Config ───────────────────────────────────────────────────────────────────

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
BUFFER_PATH = os.path.join(BASE_DIR, "pending_buffer.json")
SEEN_REJECTIONS_PATH = os.path.join(BASE_DIR, "seen_rejections.json")
# The same shape as the file above and for the same reason: an answer to a
# proposal arrives whenever the Admin gets to it, which is routinely after
# this app has been closed and reopened, and a decision shown twice is as
# bad as one never shown.
SEEN_PROPOSALS_PATH = os.path.join(BASE_DIR, "seen_proposals.json")

DEFAULT_CFG = {
    "server_url": "https://asset-server:8081",
    # system / dark / light. Not admin-gated, unlike Asset Server Settings beside it:
    # this changes what this screen looks like, not what this installation is
    # configured to do.
    "theme": "system",
    # Who this installation records Transactions as. Not set here and not
    # editable here - the Admin sets it in the Server GUI's Manage Users window
    # and it arrives on /health, the same tick that already carries the Cancel
    # switch. It is written back to this file so the two entries that bracket a
    # run, app.started and app.stopped, can be attributed before the first
    # heartbeat has been answered; the default is the storekeeper column's own
    # default, so a machine that has never reached the server says what every
    # Transaction recorded before this existed says.
    "storekeeper_name": "Storekeeper User",
}

# The name the entries below are attributed to. Module scope rather than an
# attribute of the app, because app.started is written inside __init__ and
# app.stopped after mainloop has returned - either side of the object that
# would otherwise hold it.
_sk_name = DEFAULT_CFG["storekeeper_name"]


def _show_window(root):
    """Bring the main window back from the tray (#272). Forcing it in front
    is what #193 forbids everywhere else in this file; here the Storekeeper
    asked for it from the tray menu, so it is the one place allowed."""
    root.deiconify()
    root.lift()
    root.focus_force()


def sk_actor():
    """Who this installation's System Log entries are attributed to.

    The role in brackets is a log label and never the `storekeeper` field of a
    Transaction: that field carries the name alone, and the server appends the
    same suffix for a caller that sends none. What it buys is an entry that
    reads as an act by the person who holds the store rather than as a bare
    name beside an Engineer's.
    """
    return "%s (Storekeeper)" % _sk_name

def load_config():
    """This app's config.json, read over DEFAULT_CFG - see common.load_config.

    The order matters for `storekeeper_name`: `__init__`'s fallback is
    `DEFAULT_CFG["storekeeper_name"]`, which only stays right if a stale file
    is merged onto a fresh copy of the defaults rather than the other way
    round - a name of spaces once got the wrong order and left every System
    Log entry of the run attributed to " (Storekeeper)". common.load_config's
    docstring carries that lesson now; this is only the path and the defaults.
    """
    return common.load_config(CONFIG_PATH, DEFAULT_CFG)

def save_config(cfg):
    common.save_config(CONFIG_PATH, cfg)

# ---- Colours, and the theme --------------------------------------------------
# Variant C's palette. The names are the ones the rest of this file and every
# dialog in it already use, so re-pointing them here restyles the export dialog,
# the engineer dialogs and the settings windows too.
#
# What changed is that they are no longer constants. ui_kit holds the same
# fourteen names in a light table as well; THEME rebinds them, so a widget built
# after a switch is born the right colour, and ui_kit.retint repaints the ones
# built before it. Rebuilding the window instead would be simpler and is the
# wrong answer here: it would take the history filters, the search text and the
# table selection with it, which is state the storekeeper typed.

#: Three colours that are this app's own rather than the product's. They were
#: inline hex literals before ui_kit existed and still belong here, so they are
#: merged into the shared tables rather than added to them.
_EXTRA_DARK = {"SUCCESS_HOT": "#16a34a",     # Export, pressed
               "DANGER_BG":   "#c0392b",     # Cancel Transaction
               "DANGER_HOT":  "#922b21"}     # ...the same two, pressed
_EXTRA_LIGHT = {"SUCCESS_HOT": "#166534",
                "DANGER_BG":   "#a52017",
                "DANGER_HOT":  "#7f1d1d"}

THEME = ui_kit.Theme(globals(), _EXTRA_DARK, _EXTRA_LIGHT)

# The fourteen shared names and this app's own three are bound into this
# module by the THEME above, out of ui_kit.DARK merged with the extras it
# was handed - this file writes no second copy of that table. MONO is this
# app's identifiers, always monospace; FAINT its provenance and row counts.

# The Export window and the workbook writer, which were here until #219 and
# are storekeeper_export.py now, the Bulk submit window, which was here
# until #236 and is storekeeper_bulk.py, and the Propose and Import dialogs,
# which were here until #237 and are storekeeper_propose.py. Under the THEME rather than beside the
# imports at the top of the file, because bind() takes the palette as well as
# the module and there is no palette to take until the line above has run.
storekeeper_export.bind(sys.modules[__name__])
storekeeper_bulk.bind(sys.modules[__name__])
storekeeper_propose.bind(sys.modules[__name__])


def _tag_status(tree, group=True):
    """A table's row colours, and the hook that re-applies them.

    A tag colour is not a widget option, so the retint walk cannot read it back
    - a switch would otherwise leave Confirmed rows in the dark green, which
    measures 1.8:1 against a white table.

    **One set since 078**, where there were two (#179). History is searched,
    so a row there is coloured by its *state* - what somebody filtering a
    quarter is looking for - and RECENT was coloured by its **direction**,
    which is what the eye scans a receipt for. One Treeview row cannot carry
    both: it colours a row and never a cell, so the axis had to be chosen per
    table. RECENT is not a Treeview any more - it is the list-and-detail shape,
    where the direction is a 3px gutter and the state is a word beside it, so
    that row carries both and nothing has to be chosen. History is the one
    table left in this window and it is coloured by state.
    """
    tree.tag_configure("confirmed", foreground=SUCCESS)
    tree.tag_configure("rejected", foreground=DANGER)
    tree.tag_configure("pending", foreground=WARNING)
    if group:
        # A Treeview has no group header, so a tagged row plays one. Only used
        # while the table is in timestamp order - see _apply_filters.
        tree.tag_configure("group", background=CARD2, foreground=SUBTEXT,
                           font=font("emph"))
    tree._retint_hook = lambda _rev, _new: _tag_status(tree, group)
    return tree


#: `Pill` used to be a tk.Canvas subclass here, byte-identical to the Notifier's
#: and near enough to the Server GUI's. All three are now one class in ui_kit -
#: which the Notifier's copy already said a third copy should cost - and it
#: redraws at a width and a palette it was not born with. Both halves of this
#: change need that one property.
_round_rect = ui_kit.round_rect
Pill = ui_kit.Pill


#: Which of this module's palette names each `ui_kit` pane attribute is drawn
#: out of. `SectionBar`, `ListPane` and `DetailPane` are handed their colours
#: once and keep them as Python attributes as well as on their widgets, so a
#: theme switch is only half done by the retint walk: the widgets on screen are
#: repainted by it, and the next `select()` or `show()` would paint a row out
#: of the palette the window is no longer in.
_PANE_COLOURS = {"shell": "BG", "panel": "CARD", "well": "INPUT_BG",
                 "hot": "CARD2", "ink": "BG", "text": "TEXT",
                 "mute": "SUBTEXT", "faint": "FAINT", "line": "LINE"}


def _follows_theme(pane, widget):
    """Re-point `pane`'s stored colours after a swap - `_tag_status`'s reason.

    Hung on a widget rather than on the pane, because the retint walk sees
    widgets: `_retint_hook` is the one door this module has into it. Only the
    attributes the pane actually has are written, the three classes carrying
    different subsets of the nine.
    """
    def _repoint(_rev=None, _new=None):
        for attr, token in _PANE_COLOURS.items():
            if hasattr(pane, attr):
                setattr(pane, attr, globals()[token])
    widget._retint_hook = _repoint
    return pane



# ─── Main App ─────────────────────────────────────────────────────────────────

class StorekeeperApp:
    def __init__(self, root):
        global _sk_name
        self.root       = root
        self.cfg        = load_config()
        self.server_url = self.cfg.get("server_url", "https://asset-server:8081")
        # Before app.started below, so the first entry of a run is attributed
        # to the name this installation last heard rather than to the default
        # it would take until the first heartbeat answered.
        _sk_name        = ((self.cfg.get("storekeeper_name") or "").strip()
                           or DEFAULT_CFG["storekeeper_name"])
        self._all_rows  = []
        self._sort_col  = None
        self._sort_rev       = False
        self._lookup_after_id = None   # pending debounce call id
        self._bulk            = storekeeper_bulk.BulkWindow(self)  # and its queue
        self._propose         = storekeeper_propose.ProposeDialogs(self)
        self._resolved_model  = ""     # asset_model from the lookup, submitted as-is
        self._tab             = "Submit"
        self._server_check_timer = None  # track after() timer to prevent leaks
        # The maintenance hold the flush last reported, so a restore that takes
        # ten minutes is one line in the log rather than one every fifteen
        # seconds. Cleared the moment the server takes a write again.
        self._held_said       = ""    # the server's words, last time it held
        self._members         = list(TEAM_MEMBERS)  # populated from server
        self.asset_types      = cached_asset_types()  # last real answer, or the fallback
        self._seen_rejected   = set()  # rejection ids already shown to storekeeper
        self._seen_decided    = set()  # proposal ids whose answer has been shown
        # Absent from /health means allowed - that is the behaviour from before
        # the switch existed, and a server built then must not have the offer
        # taken away. True until the first heartbeat says otherwise.
        self._can_cancel      = True
        # Absent means allowed, the answer the switch beside it gives, so a
        # server that predates the key leaves the offer standing (ADR-0017).
        self._can_add_member  = True
        # And absent means **zero** here, deliberately the other answer from
        # the two above (#198): a switch nobody has written down means the
        # freedom that was there before it existed, where a duration nobody has
        # written down is no window at all. A server that predates the key is
        # one that refuses a Confirmed cancel without the admin password, which
        # is what 0 asks for.
        self._cancel_window_mins = 0

        # Before any widget exists, so the window is born in the right palette
        # rather than being repainted a moment after it appears. The ttk block
        # is this window's own, so the theme is handed it rather than carrying
        # a copy.
        THEME.restyle = lambda _root: self._setup_styles()
        THEME.set(ui_kit.read_mode(self.cfg))
        THEME.register(self.root)

        self.root.title(f"Asset Manager — Storekeeper   (v{APP_VERSION})")
        # `True`, so the six dialogs this window opens inherit it.
        ui_kit.set_window_icon(self.root)
        self.root.geometry("1360x830")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(1180, 700)

        # Before the first worker starts: _check_server is what runs into a
        # missing certificate, and it runs on a thread.
        common.set_cert_confirm(self._confirm_cert)

        self._setup_styles()
        self._build_ui()
        # Written to this machine's own client.log and queued for the server.
        # The queue is shipped on the background tick - not from here, where no
        # server has been resolved yet.
        log_event("app.started", "StorekeeperApp %s" % APP_VERSION,
                  actor=sk_actor())

        # And what the last update did, if this start is the one after one.
        # It is `common.py`'s because the file, the three event names and the
        # wording are one fact both clients state (rule 10); what is this
        # app's is that it is asked here, immediately after `app.started`, so
        # the two entries that bracket the update sit together on the Admin's
        # timeline. It answers "" on every ordinary start.
        report_update_result(actor=sk_actor())
        # Deferred rather than called straight through: both start a worker
        # thread, and any Tk call from a worker before root.mainloop() is
        # running raises RuntimeError("main thread is not in main loop").
        # _check_server died on it outright; _refresh_transactions swallowed
        # it and silently lost its first refresh. after() is called here on
        # the main thread, so the first tick of each lands once the loop is up.
        self.root.after(0, self._check_server)
        self.root.after(0, self._refresh_transactions)
        self._load_members()
        self._load_asset_types()
        self._init_seen_rejected()
        self._init_seen_decided()
        self.root.after(3000, self._tick_background)
        threading.Thread(target=self._check_update, daemon=True).start()
        # Closing the window hides it to the tray, and only the tray's Exit
        # quits (#272). With no tray to come back from, a hidden window would
        # be unreachable, so there closing still quits.
        self.tray_icon = None
        if ui_kit.HAS_TRAY:
            self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)
            threading.Thread(target=self._build_tray, daemon=True).start()

    def _tray_items(self):
        """The tray menu, top to bottom, in `ui_kit.run_tray_icon`'s shape."""
        return [
            (lambda _i: "Storekeeper - %s" % _sk_name, None),
            (f"Version {APP_VERSION}", None),
            None,
            ("Show console",      self._show_console),
            ("Check for updates", self._manual_update_check),
            None,
            ("Exit",              self._quit),
        ]

    def _build_tray(self):
        ui_kit.run_tray_icon(self.root, "AssetStorekeeper",
                             "Asset Manager - Storekeeper",
                             ui_kit.app_icon(64), self._tray_items(),
                             on_ready=lambda icon: setattr(self, "tray_icon", icon))

    def _show_console(self):
        _show_window(self.root)

    def _quit(self):
        """The tray's Exit: stop the icon and end the loop. What quitting
        always did - app.stopped and the last ship - runs after mainloop."""
        if self.tray_icon is not None:
            self.tray_icon.stop()
        self.root.destroy()

    def _confirm_cert(self, fingerprint, server_url):
        """Ask before pinning the server's certificate on first contact.

        The background tick and the server check both run on worker threads, so
        the question is marshalled onto the Tk thread and the worker waits -
        common.confirm_on_tk_thread refuses rather than pins where there is
        nobody to ask. Cancel is the default button.
        """
        title, body = common.cert_prompt_text(fingerprint, server_url)
        return common.confirm_on_tk_thread(
            self.root,
            lambda: messagebox.askokcancel(title, body, icon="warning",
                                           default="cancel"))

    # One update at a time. The history header's Check for Updates can be
    # clicked again while a download is running, and two appliers waiting on
    # the same pid would both extract over the same directory.
    _updating = False

    def _check_update(self):
        """Check the server's /version; if a newer build is published, offer to
        apply it. Where the server holds this app's source zip the update is
        installed in place by client_update; where it does not, the old
        browser download of the installer stands. Defender-safe either way:
        no executable of ours is fetched, and nothing runs unattended - the
        user answers a question first."""
        try:
            r = api("get", f"{self.server_url}/version", timeout=5)
            if not r.ok:
                return
            data   = r.json()
            latest = data.get("latest", "")
            if not latest or _ver_tuple(latest) <= _ver_tuple(APP_VERSION):
                return
            dl  = data.get("download_path", "")
            url = f"{self.server_url}{dl}" if dl else ""
            pkg = _has_client_package(data, UPDATE_APP_KEY)
            self.root.after(0, lambda: self._prompt_update(latest, url, pkg))
        except Exception:
            pass

    def _manual_update_check(self):
        """User-initiated check (button). Reports up-to-date / behind / unreachable."""
        def work():
            try:
                r = api("get", f"{self.server_url}/version", timeout=6)
                if not r.ok:
                    self.root.after(0, lambda: messagebox.showwarning(
                        "Check for Updates", f"Server returned {r.status_code}."))
                    return
                d = r.json(); latest = d.get("latest", "")
                if latest and _ver_tuple(latest) > _ver_tuple(APP_VERSION):
                    dl = d.get("download_path", ""); url = f"{self.server_url}{dl}" if dl else ""
                    pkg = _has_client_package(d, UPDATE_APP_KEY)
                    self.root.after(0, lambda: self._prompt_update(latest, url, pkg, manual=True))
                else:
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Up to Date", f"You're on the latest version (v{APP_VERSION})."))
            except Exception:
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
                  % (latest, APP_VERSION), actor=sk_actor())

        # After MAX_LATER postpones, the update is forced (only if there is
        # something to apply - a source zip on the server, or an installer).
        if count >= MAX_LATER and (url or has_pkg):
            self._forced_update(latest, url, has_pkg)
            return

        if not (url or has_pkg):
            messagebox.showinfo("Update Available",
                f"A newer version (v{latest}) is available — you have v{APP_VERSION}.\n\n"
                "Please contact your admin to update.")
            return

        remaining = MAX_LATER - count
        # Two different answers behind one Yes, and the question says which:
        # an in-place update closes and reopens this window by itself, while
        # the browser download leaves somebody to run the installer.
        how = ("Yes = update now; the app will close and reopen"
               if has_pkg else "Yes = download • No = remind me later")
        if messagebox.askyesno("Update Available",
                f"A newer version of the Storekeeper app is available "
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
                      % (latest, count + 1, MAX_LATER), actor=sk_actor())
            _save_update_state({"version": latest, "count": count + 1})

    def _apply_source_update(self, latest):
        """Download the published zip, then hand over to the applier and close.

        On a worker, because the download is megabytes over a link that may be
        slow and this window has a 15s tick behind it that has to go on
        flushing the offline buffer until the moment the process ends.
        Nothing is closed until client_update.update_now returns, and it
        returns only with a verified package staged - rule 13's Python check
        included - so every refusal costs a message box and leaves the app
        running with whatever is still in the buffer.

        Closing is what releases the applier: it is waiting on this process
        id, because lib\\ holds .pyd files that are open while we run."""
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
                          level="warn", actor=sk_actor())
                self.root.after(0, lambda: messagebox.showwarning("Update", msg))
                return
            except Exception:
                self._updating = False
                log_event("update.download_failed", latest, level="warn",
                          actor=sk_actor())
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
                      "%s verified and staged; restarting to apply" % latest,
                      actor=sk_actor())
            self.root.after(0, self.root.destroy)

        threading.Thread(target=work, daemon=True).start()

    def _forced_update(self, latest, url, has_pkg=False):
        """Final, non-dismissable prompt after the postpone limit is reached.
        Updating then closes the app so the old version can't keep being used."""
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
        win.protocol("WM_DELETE_WINDOW", lambda: None)   # cannot be closed
        tk.Label(win, text="⚠  Update Required", bg=DANGER, fg="white",
                 font=font("section")).pack(fill="x", ipady=10)
        # The control is packed before the form, which is what every other
        # dialog in this product does and what this one never did: `pack`
        # serves its children in the order they went in and gives the shortfall
        # to whichever was last, so the one button this window exists to be
        # pressed must not be that child (#192).
        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x")
        tell = ("Click below to install it. The app will close and reopen\n"
                "by itself when the update is in place."
                if has_pkg else
                "Click below to download it. The app will close so you can run\n"
                "AssetManager_Setup.exe and finish updating.")
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
            self.root.after(400, self.root.destroy)

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

    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Treeview", background=CARD, foreground=TEXT,
                    fieldbackground=CARD, rowheight=31, borderwidth=0,
                    font=font("body"))
        s.configure("Treeview.Heading", background=CARD2, foreground=SUBTEXT,
                    relief="flat", borderwidth=0, padding=(6, 8),
                    font=font("emph"))
        s.map("Treeview", background=[("selected", ACCENT)],
              foreground=[("selected", "white")])
        s.map("Treeview.Heading", background=[("active", CARD2)])
        # bordercolor/lightcolor/darkcolor are the clam bevel. Left at their
        # defaults they draw a pale 3-D box round every combobox and give the
        # arrow its own raised button, which was most of what dated the window.
        s.configure("TCombobox", fieldbackground=INPUT_BG, background=INPUT_BG,
                    foreground=TEXT, arrowcolor=SUBTEXT, bordercolor=LINE,
                    lightcolor=INPUT_BG, darkcolor=INPUT_BG, borderwidth=1,
                    relief="flat", padding=(9, 6), arrowsize=13)
        s.map("TCombobox",
              fieldbackground=[("readonly", INPUT_BG)],
              background=[("readonly", INPUT_BG)],
              foreground=[("readonly", TEXT), ("disabled", SUBTEXT)],
              bordercolor=[("focus", ACCENT), ("hover", ACCENT)],
              arrowcolor=[("active", ACCENT)],
              selectbackground=[("readonly", INPUT_BG)],
              selectforeground=[("readonly", TEXT)])
        # The dropdown list is neither a ttk style nor a child of the combobox,
        # so it is the kit's job in both directions - the options a popdown is
        # born with, and a repaint of the ones already built.
        ui_kit.combo_popdown(self.root, THEME.palette())
        s.configure("Vertical.TScrollbar", background=INPUT_BG, troughcolor=BG,
                    bordercolor=BG, lightcolor=INPUT_BG, darkcolor=INPUT_BG,
                    arrowcolor=SUBTEXT, relief="flat", borderwidth=0,
                    arrowsize=12, width=11)
        s.map("Vertical.TScrollbar", background=[("active", LINE)])

    # -- Chrome ----------------------------------------------------------------

    TABS = ("Submit", "History", "Tools")

    def _build_ui(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=26, pady=(18, 0))

        _mark(bar, BG, ACCENT).pack(side="left")
        tk.Label(bar, text="Asset Manager", bg=BG, fg=TEXT,
                 font=font("emph", size=14)).pack(side="left", padx=(11, 7))
        self.sk_lbl = tk.Label(bar, text="", bg=BG, fg=SUBTEXT,
                               font=font("body"))
        self.sk_lbl.pack(side="left", pady=(3, 0))
        self._paint_sk_name()

        # Dark, light or whatever Windows is set to, cycled in place. It lives
        # here rather than in a Tools card because it is the one control on
        # this window that is about the window itself, and it asks for no
        # password for the same reason it never did: it changes what this
        # screen looks like and nothing else.
        self.theme_btn = Pill(bar, "", BG, CARD2, LINE, fg=TEXT, w=158, h=30,
                              bold=False, command=self._cycle_theme)
        self.theme_btn.pack(side="right", padx=(16, 0))
        self._paint_theme_btn()

        # The dot and the text are written separately by _check_server, so the
        # colour of one never decides the wording of the other.
        pill = tk.Frame(bar, bg=CARD, highlightthickness=1,
                        highlightbackground=LINE)
        pill.pack(side="right")
        self.status_dot = tk.Label(pill, text="\u25cf", bg=CARD, fg=WARNING,
                                   font=font("value"))
        self.status_dot.pack(side="left", padx=(10, 5), pady=5)
        self.status_lbl = tk.Label(pill, text="Connecting\u2026", bg=CARD,
                                   fg=TEXT, font=font("emph", size=9))
        self.status_lbl.pack(side="left", padx=(0, 11))
        # The four counts used to be four more numerals on this row (166).
        # They are over the RECENT table now, which is the surface they are
        # about: this band is the app's name, who is recording and whether the
        # server is answering, and six facts plus a mode toggle on one line is
        # a stat strip doing a title bar's job. Nothing left the product - see
        # `_build_submit_tab`, which builds them and keeps `stat_lbls`.

        # **The sections are the bar from 076** (078). Submit, History and
        # Tools were this window's own three labels with a 2px rule under the
        # selected one, which is `ui_kit.SectionBar` written a second time and
        # slightly differently: the bar's selected cell is `CARD` against the
        # `BG` it stands on with the mark on its bottom edge, and the hairline
        # under the strip is part of the widget rather than a rule this window
        # remembers to draw. Packed full width for that hairline - it is what
        # says where the strip ends and the pane under it starts, and an inset
        # one would stop 26px short of both edges of the window.
        #
        # No version badge here (166). It was drawn into the same strip the
        # tabs are packed into and overlapped them at the widths this window
        # opens at, which is what two homes for one fact produces: the version
        # is in the window title, set in `__init__` and read wherever Windows
        # lists this app, so this was the second copy rather than the first.
        self.sections = ui_kit.SectionBar(self.root, self.TABS, BG, CARD, TEXT,
                                          SUBTEXT, LINE,
                                          command=self._show_tab,
                                          current="Submit")
        # The bar keeps the four colours it paints a cell with, so the switch
        # that repaints the strip has to re-point them too: without this the
        # next `select` after a swap draws the selected cell and its mark out
        # of the palette the window has just left, which is a dark cell in a
        # light window and was exactly that until it was driven.
        _follows_theme(self.sections, self.sections.box)
        self.sections.pack(fill="x", pady=(14, 0))

        # Where a notification lands (#193). It is empty almost always and an
        # empty `Frame` asks for no height at all, so this costs nothing until
        # something is put in it - which is the whole reason a notice can live
        # on the window rather than having to be a window of its own. Packed
        # here, under the tabs and above the tab bodies, because what it
        # carries is about this installation rather than about whichever tab
        # happens to be showing: a rejection arriving while somebody is in
        # Tools is still theirs to read.
        self.notices = tk.Frame(self.root, bg=BG)
        self.notices.pack(fill="x")
        # Each tab is built once and shown with pack/pack_forget rather than
        # rebuilt on every switch: the 15s background tick writes into the
        # history table, and a table destroyed by a tab change would take the
        # tick down with it.
        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill="both", expand=True)
        self._panes = {}
        for name, build in (("Submit", self._build_submit_tab),
                            ("History", self._build_history_tab),
                            ("Tools", self._build_tools_tab)):
            pane = tk.Frame(self.body, bg=BG)
            build(pane)
            self._panes[name] = pane
        self._show_tab("Submit")

    def _show_tab(self, name):
        """Show one section's pane. **The bar paints itself** (078).

        Reached from the bar's own `command`, and from anywhere in this window
        that moves somebody to another section - which has to say so on the bar
        as well, `SectionBar.select` deliberately not firing the callback that
        would rebuild what it is restoring.
        """
        if name not in self._panes:
            return
        self._tab = name
        if self.sections.current != name:
            self.sections.select(name)
        for n, pane in self._panes.items():
            if n == name:
                pane.pack(fill="both", expand=True)
            else:
                pane.pack_forget()
        if name == "Tools":
            # Built once, so the server URL in it would otherwise still be the
            # one from startup after a change in Asset Server Settings.
            self.lbl_server_info.config(
                text=f"Connected to {self.server_url}  \u00b7  this app is "
                     f"v{APP_VERSION}.")

    # -- Submit tab ------------------------------------------------------------

    HINT = ("Scan a label, or type either number. Enter looks it up, "
            "transaction. A whole batch goes through Bulk submit.")

    #: The form column's width. Written down once, because the hero
    #: identifiers, the Submit block and the verdict line's `wraplength` are
    #: all measured against it and a second copy is the one that drifts.
    FORM_W = 430
    FORM_PAD = 22

    #: RECENT's list column. Narrower than `ui_kit.LIST_W`, which is the width
    #: a list gets in a window that is nothing but the list - the Server
    #: console's feed and the Notifier's queue. Here the form already holds
    #: `FORM_W` and the detail pane takes what is left of a 1180px minimum, so
    #: this is the proportion `prototypes/pass3_ui.py`'s `draw_storekeeper`
    #: settled for this window - 358 beside a 452 form - rather than the
    #: full-window figure, which would leave the detail 260px to put a 26pt
    #: identifier in.
    RECENT_W = 358

    def _groove(self, parent, pady=(12, 12), colour=None):
        """A 1px rule, which is what this window separates things with (#179).

        Not a shadow and not a ring: a seam here is one pixel of LINE, which
        is a colour the widget either side of it can be read against.
        """
        g = tk.Frame(parent, bg=colour or LINE, height=1)
        g.pack(fill="x", pady=pady)
        return g

    @staticmethod
    def _dir_colour(direction):
        """Out is WARNING, In is SUCCESS - the one colour on this window.

        The palette's saturated entries are reserved for what a Transaction is
        doing, and on this form what it is doing is a direction.
        """
        return WARNING if str(direction).startswith("Out") else SUCCESS

    def _build_submit_tab(self, parent):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True, padx=26, pady=(18, 20))

        # Two columns, and the seam is a groove rather than a gap: the form is
        # one task with a fixed width and RECENT is a list that takes whatever
        # is left. The form is flat CARD throughout.
        form = tk.Frame(wrap, bg=CARD, width=self.FORM_W)
        form.pack(side="left", fill="y")
        form.pack_propagate(False)
        tk.Frame(wrap, bg=LINE, width=1).pack(side="left", fill="y")
        right = tk.Frame(wrap, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(18, 0))

        body = tk.Frame(form, bg=CARD)
        body.pack(fill="both", expand=True, padx=self.FORM_PAD,
                  pady=(18, 18))
        inner = self.FORM_W - 2 * self.FORM_PAD

        # **The primary control is packed first and from the bottom.** `pack`
        # serves its children in the order they went in and gives the
        # shortfall to whatever went in last, so at the 1180x700 minimum the
        # part that gets squeezed has to be the custody strip below and never
        # this - the same rule every dialog in this product keeps about the
        # button that saves it.
        self.btn_submit = Pill(body, "Submit", CARD, TEXT, MONO, fg=BG,
                               w=inner, h=46, radius=0, size=11,
                               command=self._submit)
        self.btn_submit.pack(side="bottom", fill="x")
        # The one inverted block on the window, which is what makes it the
        # write action: everything else here is drawn out of the shell.
        # Bulk submit is not down here any more (090): it is a button beside
        # the Serial no. field, where a scan starts.
        tk.Frame(body, bg=CARD, height=12).pack(side="bottom")

        tk.Label(body, text="Record a movement", bg=CARD, fg=TEXT,
                 font=font("section")).pack(anchor="w")
        tk.Label(body, text="Scan a label, or type either number.", bg=CARD,
                 fg=SUBTEXT, font=font("body")).pack(anchor="w", pady=(3, 0))
        self._groove(body, pady=(14, 14))

        # **The identifier is the hero.** It is the largest type in the
        # window, in the mono face, because it is read a character at a time
        # off a label by somebody holding a laptop and comparing it against
        # this screen. Asset No. and Serial No. stay the first two fields -
        # project rule 4.
        ids = tk.Frame(body, bg=CARD)
        ids.pack(fill="x")
        for attr, label, width in (("v_asset_no", "Asset no.", 10),
                                   ("v_serial", "Serial no.", 13)):
            col = tk.Frame(ids, bg=CARD)
            col.pack(side="left", anchor="n", padx=(0, 16))
            tk.Label(col, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("micro")).pack(anchor="w")
            # INPUT_BG rather than CARD: a groove says where a surface ends,
            # and a field is the one thing on this column somebody types into,
            # so it is the one thing that states itself with a fill.
            e = tk.Entry(col, bg=INPUT_BG, fg=TEXT, width=width,
                         font=font("code_lg", size=15), relief="flat", bd=0,
                         insertbackground=TEXT, highlightthickness=1,
                         highlightbackground=LINE, highlightcolor=ACCENT)
            e.pack(anchor="w", ipady=8, pady=(4, 0))
            e.bind("<KeyRelease>", lambda _e, a=attr: self._schedule_lookup(a))
            e.bind("<Return>", lambda _e: self._on_scan_enter())
            setattr(self, attr, e)
        # Beside the identifiers rather than under the form (090): a batch
        # starts where one scan does, and a button says it is a control where
        # a line of grey text said it was a caption. Bottom-aligned, so it
        # sits level with the two fields rather than with their captions.
        self.btn_bulk = Pill(ids, "Bulk submit", CARD, CARD2, LINE, fg=TEXT,
                             w=96, h=44, radius=0, bold=False, short="Bulk",
                             command=self._bulk.open)
        self.btn_bulk.pack(side="left", anchor="s")

        # What the sheet said about it, in a block of its own rather than in a
        # field: the type is not a choice (rule 2) and the model is not a
        # field at all, so neither belongs in something that looks typeable.
        # Still `v_type`, still a get()/set() pair, so `_submit` and the
        # offline buffer read the type exactly as they did.
        #
        # **INPUT_BG rather than CARD2** (078): a block on this form is a
        # recess, and CARD2 is one step *lighter* than the card it sits on,
        # which is the tile this pass exists to remove. It is the fill the two
        # identifier fields above it already carry, so the form reads as one
        # surface with three holes in it rather than two materials.
        self.v_type = tk.StringVar()
        res = tk.Frame(body, bg=INPUT_BG)
        res.pack(fill="x", pady=(14, 0))
        tk.Label(res, text="resolved", bg=INPUT_BG, fg=FAINT,
                 font=font("micro")).pack(anchor="w", padx=12, pady=(8, 0))
        self.lbl_resolved = tk.Label(res, text="\u2014", bg=INPUT_BG,
                                     fg=SUBTEXT,
                                     anchor="w", justify="left",
                                     font=font("body"))
        self.lbl_resolved.pack(anchor="w", fill="x", padx=12, pady=(1, 9))
        self.v_type.trace_add("write", lambda *_: self._paint_resolved())
        self.v_type.set("")

        tk.Label(body, text="Engineer", bg=CARD, fg=SUBTEXT,
                 font=font("micro")).pack(anchor="w", pady=(14, 0))
        self.v_member = ttk.Combobox(body, values=self._members,
                                     state="readonly", font=font("value"))
        self.v_member.pack(fill="x", pady=(4, 0))

        tk.Label(body, text="Direction", bg=CARD, fg=SUBTEXT,
                 font=font("micro")).pack(anchor="w", pady=(12, 0))
        drow = tk.Frame(body, bg=CARD)
        drow.pack(fill="x", pady=(4, 0))
        # The colour is the direction and nothing else on this form carries
        # one, which is what makes a glance at the block an answer.
        self.dir_block = tk.Frame(drow, bg=WARNING, width=3)
        self.dir_block.pack(side="left", fill="y")
        # Still a StringVar so `_submit`, `_clear_form` and the bulk window
        # keep reading and writing the direction the same way.
        self.v_direction = tk.StringVar(value="Out Store")
        self.v_direction.trace_add("write", lambda *_: self._paint_dir_block())
        ttk.Combobox(drow, values=["Out Store", "In Store"], state="readonly",
                     textvariable=self.v_direction, font=font("value")
                     ).pack(side="left", fill="x", expand=True, padx=(10, 0))

        tk.Label(body, text="Notes", bg=CARD, fg=SUBTEXT,
                 font=font("micro")).pack(anchor="w", pady=(12, 0))
        self.v_notes = tk.Entry(body, bg=INPUT_BG, fg=TEXT,
                                font=font("value"),
                                relief="flat", bd=0, insertbackground=TEXT,
                                highlightthickness=1,
                                highlightbackground=LINE,
                                highlightcolor=ACCENT)
        self.v_notes.pack(fill="x", ipady=8, pady=(4, 0))

        # The lookup verdict gets its own line, so the column keeps one shape
        # whether or not an asset has been matched.
        verdict = tk.Frame(body, bg=CARD)
        verdict.pack(fill="x", pady=(12, 0))
        self.lbl_resolve = tk.Label(verdict, text=self.HINT, bg=CARD,
                                    fg=SUBTEXT, anchor="w", justify="left",
                                    wraplength=inner, font=font("body"))
        self.lbl_resolve.pack(anchor="w")
        actions = tk.Frame(body, bg=CARD)
        actions.pack(fill="x", pady=(8, 0))
        # A button of control height rather than a word (090): it empties
        # the whole form, and a target that small was missed for the field
        # next to it.
        self.btn_clear = Pill(actions, "Clear", CARD, CARD2, LINE, fg=TEXT,
                              w=110, h=36, radius=0, bold=False,
                              command=self._clear_form)
        self.btn_clear.pack(side="left")
        # Offered on the line that has just said the server will refuse this
        # asset, and nowhere else on this form: that sentence is the moment
        # somebody wants a way past rule 6, and this is the way there is. It is
        # packed only while that is what the line says - a standing offer to
        # propose an asset, next to a form for an asset that resolved perfectly
        # well, is an invitation to propose a duplicate.
        self.lbl_propose = tk.Label(actions, text="Add new asset", bg=CARD,
                                    fg=TEXT, font=font("strong"),
                                    cursor="hand2")
        self.lbl_propose.bind("<Button-1>",
                              lambda _e: self._propose._propose_dialog(
                                  self.v_asset_no.get().strip(),
                                  self.v_serial.get().strip()))

        # **This asset, before now.** It fetches nothing: `self._all_rows` is
        # the whole transactions list the 15s tick already keeps current, so
        # the answer to "has this one been out since Tuesday" costs no request
        # and is there by the time the identifier has resolved.
        self._groove(body, pady=(16, 12))
        tk.Label(body, text="This asset, before now", bg=CARD, fg=SUBTEXT,
                 font=font("strong")).pack(anchor="w")
        self.custody = tk.Frame(body, bg=CARD)
        self.custody.pack(fill="x", pady=(8, 0))
        self._paint_custody("")

        rhead = tk.Frame(right, bg=BG)
        rhead.pack(fill="x", pady=(0, 10))
        tk.Label(rhead, text="Recent", bg=BG, fg=TEXT,
                 font=font("section")).pack(side="left")

        # The store's four counts, over the table they are counts of (166).
        # They were four more numerals on the header band, which is the row
        # that says what this app is and who is recording; here they sit on the
        # heading of the rows they describe, at no cost in height - this line
        # was a label and a rule and nothing else. Inline numerals rather than
        # cards for the reason they always were: four tiles cost over a hundred
        # pixels to show four integers, and that height is worth more as rows.
        # `out_now` is the server's count of what an engineer is holding right
        # now, which is why it is read from /stats rather than off this table.
        #
        # Packed before the rule, because the rule is the child that expands:
        # `pack` serves its children in order and one that fills takes whatever
        # is left, so a right-hand child packed after it has nothing to sit in.
        self.stat_lbls = {}
        chips = tk.Frame(rhead, bg=BG)
        chips.pack(side="right")
        for key, label, colour in (("total", "total", SUBTEXT),
                                   ("pending", "pending", WARNING),
                                   ("confirmed", "confirmed", SUCCESS),
                                   ("out_now", "out now", SUBTEXT)):
            c = tk.Frame(chips, bg=BG)
            c.pack(side="left", padx=(16, 0))
            v = tk.Label(c, text="\u2013", bg=BG, fg=TEXT,
                         font=font("emph", size=13))
            v.pack(side="left")
            tk.Label(c, text=label, bg=BG, fg=colour,
                     font=font("micro")).pack(side="left", padx=(5, 0),
                                                pady=(4, 0))
            self.stat_lbls[key] = v

        tk.Frame(rhead, bg=LINE, height=1).pack(side="left", fill="x",
                                                expand=True, padx=14, pady=8)

        # **The list, and the detail beside it** (078). RECENT was a Treeview
        # of seven columns, so every fact about a movement past those seven -
        # the Asset Type the sheet corrected it to, the model, the note that
        # was typed, the reason a rejection gave - meant leaving this tab and
        # reading History. It is `ui_kit.ListPane` and `ui_kit.DetailPane` now,
        # the shape 076 added and the Server console's feed proved: the row
        # selects and the pane beside it answers, so a row is inspected where
        # it was submitted.
        #
        # A groove for the seam rather than a ring around either half: a border
        # is a thing this window states with one pixel.
        split = tk.Frame(right, bg=CARD)
        split.pack(fill="both", expand=True)
        self.recent = ui_kit.ListPane(split, CARD, INPUT_BG, TEXT, SUBTEXT,
                                      LINE, width=self.RECENT_W,
                                      command=self._paint_recent_detail)
        self.recent.pack(side="left", fill="y")
        tk.Frame(split, bg=LINE, width=1).pack(side="left", fill="y")
        self.recent_detail = ui_kit.DetailPane(split, CARD, INPUT_BG, TEXT,
                                               SUBTEXT, FAINT, LINE,
                                               hot=CARD2, ink=BG)
        self.recent_detail.pack(side="left", fill="both", expand=True)
        _follows_theme(self.recent, self.recent.frame)
        _follows_theme(self.recent_detail, self.recent_detail.frame)
        self._recent_rows = {}
        self._paint_recent_detail(None)

    # -- RECENT, the list and the pane beside it --------------------------------

    @staticmethod
    def _stamp(ts, fmt="%d %b %Y  %H:%M"):
        """A timestamp as this window words one, or whatever came back."""
        try:
            return datetime.fromisoformat(str(ts)).strftime(fmt)
        except (TypeError, ValueError):
            return str(ts or "")

    @staticmethod
    def _recent_state(t):
        """A row's state and the colour it is said in - History's three, since
        a movement this window lists is pending, confirmed or rejected."""
        if t.get('confirmed'):
            return "Confirmed" + origin_suffix(t), SUCCESS
        if t.get('rejected'):
            return "Rejected" + origin_suffix(t), DANGER
        return "Pending", WARNING

    def _fill_recent(self, rows):
        """Draw RECENT's list, and keep the pane beside it on the same row.

        **The selection survives a repaint where it can.** This list is redrawn
        on every 15s tick, and a pane that emptied itself four times a minute
        while somebody was reading it would be worse than the History trip it
        replaced. A row that has left the list takes the pane with it, there
        being nothing left to show.
        """
        keep = self.recent.selected
        self.recent.clear()
        self._recent_rows = {}
        for t in rows:
            tid = t.get('id')
            if tid is None:
                continue
            self._recent_rows[tid] = t
            out = str(t.get('direction', '')).startswith("Out")
            state, state_fg = self._recent_state(t)
            self.recent.add(
                str(t.get('asset_number') or "no asset number"),
                sub=str(t.get('serial_number') or ""),
                word="Out store" if out else "In store",
                word_fg=WARNING if out else SUCCESS,
                state=state, state_fg=state_fg,
                # A **rejected** row's gutter is DANGER rather than a
                # direction, `_tag_status`'s reason: nothing moved, so there is
                # no direction to state.
                gutter=(DANGER if t.get('rejected')
                        else self._dir_colour(t.get('direction', ''))),
                key=tid)
        if keep in self._recent_rows:
            self.recent.select(keep)
            self._paint_recent_detail(keep)
        else:
            self._paint_recent_detail(None)

    def _earlier_lines(self, t):
        """What this same asset did before this movement, already worded.

        Read off `self._all_rows` rather than asked of the server -
        `_paint_custody`'s reason: that list is the whole transactions table
        the 15s tick keeps current, and a request per click on a window that
        repaints on a timer is a request per click too many. A movement older
        than what the tick holds is not listed here, and History is the window
        that has all of them.
        """
        key = (str(t.get('asset_number') or "").lower(),
               str(t.get('serial_number') or "").lower())
        out = []
        for other in getattr(self, "_all_rows", []):
            if other.get('id') == t.get('id'):
                continue
            if (str(other.get('asset_number') or "").lower(),
                    str(other.get('serial_number') or "").lower()) != key:
                continue
            if str(other.get('timestamp', '')) >= str(t.get('timestamp', '')):
                continue
            out.append("%s, %s, %s" % (other.get('direction', ''),
                                       other.get('team_member', ''),
                                       self._stamp(other.get('timestamp'),
                                                   "%d %b")))
            if len(out) == 4:
                break
        return out

    def _paint_recent_detail(self, key):
        """The pane beside the list, for whichever row is selected.

        **The four facts RECENT's columns dropped are here** (166 dropped Asset
        Type, the Rejection Reason and Direction; the note was never on a
        table): the type is what the Lookup Sheet corrected the scan to, and
        reading it back is how a storekeeper finds out the sheet holds that
        asset as something else.
        """
        pane = getattr(self, "recent_detail", None)
        if pane is None:
            return
        t = getattr(self, "_recent_rows", {}).get(key)
        if t is None:
            pane.clear("Select a movement on the left to see what was "
                       "recorded.")
            return
        out = str(t.get('direction', '')).startswith("Out")
        state, state_fg = self._recent_state(t)
        fields = [("Asset type", t.get('asset_type') or "\u2014"),
                  ("Model", t.get('asset_model') or "\u2014"),
                  ("Engineer", t.get('team_member') or "\u2014"),
                  # The row's own column, not this installation's setting: a
                  # movement recorded before the Admin changed the name was
                  # recorded under the name it had.
                  ("Storekeeper", t.get('storekeeper') or "\u2014"),
                  ("Logged", self._stamp(t.get('timestamp')))]
        if t.get('notes'):
            fields.append(("Notes", t['notes']))
        if t.get('rejected') and t.get('rejection_reason'):
            fields.append(("Rejection reason", t['rejection_reason']))
        pane.show(
            str(t.get('asset_number') or "no asset number"),
            sub=str(t.get('serial_number') or ""),
            word="Out store" if out else "In store",
            word_fg=WARNING if out else SUCCESS,
            state=state, state_fg=state_fg,
            gutter=(DANGER if t.get('rejected')
                    else self._dir_colour(t.get('direction', ''))),
            fields=tuple(fields),
            history=self._earlier_lines(t),
            actions=(("Open in history", False,
                      lambda tid=t.get('id'): self._open_in_history(tid)),))

    def _open_in_history(self, tid):
        """The door RECENT's missing columns used to be.

        History is the table with all nine, sortable and searchable, and it is
        where a movement is cancelled - so the pane names that window rather
        than carrying a second copy of what it does. A row the filters
        currently hide is **not** selected and the section is still shown: what
        was asked for is that window, and a selection under a filter that
        excludes the row is a selection nothing displays.
        """
        self._show_tab("History")
        tree = getattr(self, "tree", None)
        if tree is None or tid is None:
            return
        iid = str(tid)
        if iid in tree.get_children():
            tree.selection_set(iid)
            tree.see(iid)

    # -- History tab -----------------------------------------------------------

    def _build_history_tab(self, parent):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True, padx=26, pady=(18, 20))

        bar = tk.Frame(wrap, bg=CARD, highlightbackground=LINE,
                       highlightthickness=1)
        bar.pack(fill="x")
        row = tk.Frame(bar, bg=CARD)
        row.pack(fill="x", padx=14, pady=11)

        def filt(label, values, width, attr):
            tk.Label(row, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("body")).pack(side="left", padx=(0, 6))
            cb = ttk.Combobox(row, values=values, state="readonly",
                              width=width, font=font("body"))
            cb.set("All")
            cb.pack(side="left", padx=(0, 16))
            cb.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())
            setattr(self, attr, cb)

        filt("Member", ["All"] + self._members, 14, "v_filter_member")
        filt("Status", ["All", "Pending", "Confirmed", "Rejected"], 11,
             "v_filter_status")
        filt("Direction", ["All", "Out Store", "In Store"], 10, "v_filter_dir")
        filt("Type", ["All"] + self.asset_types, 11, "v_filter_type")

        Pill(row, "\u21bb  Refresh", CARD, CARD2, LINE, fg=TEXT, w=94, h=30,
             bold=False, command=self._refresh_transactions
             ).pack(side="right", padx=(10, 0))
        # Held in a frame of its own so hiding the offer and bringing it back
        # cannot move it: a Pill re-packed straight into this row would land at
        # the wrong end of everything already packed to the right.
        self._cancel_holder = tk.Frame(row, bg=CARD)
        self._cancel_holder.pack(side="right", padx=(10, 0))
        self._cancel_pill = Pill(self._cancel_holder, "\u2298  Cancel", CARD,
                                 CARD2, LINE, fg=DANGER, w=104, h=30,
                                 bold=False, command=self._cancel_selected)
        self._paint_cancel_offer()
        self.v_search = tk.StringVar()
        self.v_search.trace_add("write", lambda *_: self._apply_filters())
        tk.Entry(row, textvariable=self.v_search, bg=INPUT_BG, fg=TEXT,
                 width=22, font=font("body"), relief="flat", bd=0,
                 insertbackground=ACCENT, highlightthickness=1,
                 highlightbackground=LINE, highlightcolor=ACCENT
                 ).pack(side="right", ipady=5)
        tk.Label(row, text="Search", bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(side="right", padx=(0, 8))
        clear = tk.Label(row, text="Clear all", bg=CARD, fg=SUBTEXT,
                         font=font("body"), cursor="hand2")
        clear.pack(side="right", padx=(0, 14))
        clear.bind("<Button-1>", lambda _e: self._clear_filters())

        tf = tk.Frame(wrap, bg=CARD, highlightbackground=LINE,
                      highlightthickness=1)
        tf.pack(fill="both", expand=True, pady=(12, 0))
        self.tree = self._make_table(tf)
        self.row_count_lbl = tk.Label(wrap, text="", bg=BG, fg=FAINT,
                                      font=font("micro"))
        self.row_count_lbl.pack(anchor="e", pady=(8, 0))

    # -- Tools tab -------------------------------------------------------------

    def _build_tools_tab(self, parent):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True, padx=26, pady=(18, 20))

        card = self._tool_card(wrap, "Export to Excel",
                               "Pick a date range and an engineer, and write a "
                               "formatted workbook with a summary sheet.")
        self._tool_row(card, [
            ("Choose range and export", "Export",
             (CARD, SUCCESS, SUCCESS_HOT, "white"), self._open_export)])

        card = self._tool_card(wrap, "Engineers",
                               "Add an engineer so they can be picked here. "
                               "Removing one, their password and their access "
                               "profile are the Server GUI's Manage Users "
                               "window.")
        # The outer frame, which is what is packed - `_tool_card` hands back
        # the padded inner one.
        self._eng_card = card.master
        self._tool_row(card, [
            ("\u2795  Add new engineer", "\u2795  Add",
             (CARD, ACCENT, ACCENT2, "white"), self._add_engineer_dialog)])

        card = self._tool_card(wrap, "Assets",
                               "Record an asset the lookup sheet does not "
                               "have yet - one at a time, or a delivery's "
                               "whole spreadsheet at once. It is not an asset "
                               "and cannot be transacted until the admin "
                               "approves it - this records what you are "
                               "holding so you do not have to go and find "
                               "somebody. The answer arrives here.")
        self._assets_card = card.master
        self._paint_add_engineer_offer()
        self._tool_row(card, [
            ("\u2795  Add New Asset", "\u2795  Add Asset",
             (CARD, ACCENT, ACCENT2, "white"), self._propose._propose_dialog),
            ("\U0001f4e5  Import Asset List", "\U0001f4e5  Import",
             (CARD, CARD2, LINE, TEXT), self._propose._import_proposals_dialog)])

        card = self._tool_card(wrap, "Server and updates", "")
        self.lbl_server_info = card.desc
        self._tool_row(card, [
            ("\u2699  Server settings", "\u2699  Server",
             (CARD, CARD2, LINE, TEXT), self._open_settings),
            ("\U0001f504  Check for updates", "\U0001f504  Updates",
             (CARD, CARD2, LINE, TEXT), self._manual_update_check)])

    def _tool_row(self, card, specs):
        """A card's buttons as a row that lays itself out against the card.

        Every one of these was a fixed `w=` chosen by measuring the label once.
        They now take the width they have: full labels while they fit, short
        ones below that, and a second line before anything is truncated.
        """
        box, row = ui_kit.row_of(card, specs, kind="toolbar", h=38)
        box.pack(fill="x")
        return row

    def _cycle_theme(self):
        """The next of the three modes, and round again.

        All three survive the move to one button: `system` is a real value in
        `config.json` that the Notifier and the Server GUI both offer, so
        dropping it here would leave one app's config disagreeing with the
        other two. `ui_kit.MODES` is the order, so there is no second list of
        them to fall out of step.
        """
        modes = ui_kit.MODES
        self._set_theme(modes[(modes.index(THEME.mode) + 1) % len(modes)])

    def _paint_theme_btn(self):
        """The icon is the theme in force, the caption the setting behind it.

        Both, because they are two facts: "Follow Windows" that has resolved to
        dark and a plain "Dark" are the same window, and the difference between
        them is what the caption carries now that the note under the old row
        has gone.

        Widened to whatever the caption measures rather than kept at the `w`
        this button was built with (165): the three modes are three different
        lengths, and each of them is `font.measure`d at the display scaling
        this machine is set to while that number was written at one. Left
        alone, the pill elides - and what it elides is the tail, which is the
        mode, which is the half that a sun over "Follow Windows" and a sun
        over "Light" are told apart by.
        """
        icon = "\u2600" if THEME.active == "light" else "\u263e"
        self.theme_btn.set_text(icon + "  " + ui_kit.MODE_LABELS[THEME.mode])
        self.theme_btn.fit_text()

    def _set_theme(self, mode):
        THEME.set(mode)
        self.cfg["theme"] = mode
        save_config(self.cfg)
        # After the retint, not before: that walk repaints the button in the
        # new palette, and which icon belongs on it is not a colour it can work
        # out.
        self._paint_theme_btn()

    def _tool_card(self, parent, title, desc):
        card = tk.Frame(parent, bg=CARD, highlightbackground=LINE,
                        highlightthickness=1)
        card.pack(fill="x", pady=(0, 14))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=20, pady=16)
        tk.Label(inner, text=title, bg=CARD, fg=TEXT,
                 font=font("emph", size=11)).pack(anchor="w")
        inner.desc = tk.Label(inner, text=desc, bg=CARD, fg=SUBTEXT,
                              font=font("body"), justify="left",
                              wraplength=820)
        inner.desc.pack(anchor="w", pady=(3, 11))
        # This window is the one that drags on both axes, and 820 was the
        # answer at the width it opens at. ui_kit.rewrap keeps it the floor and
        # takes the rest from the card.
        ui_kit.rewrap(inner.desc)
        return inner

    # -- Shared table ----------------------------------------------------------

    # Asset No. and Serial No. are the first two data columns - project rule 4,
    # and in whatever a second set would be.
    COLS = (("Asset No.", 90), ("Serial No.", 120), ("Model", 160),
            ("Type", 85), ("Member", 130), ("Direction", 80),
            ("Status", 100), ("Rejection Reason", 150), ("Time", 95))

    # **One set since 078**, where there were two. `RECENT_COLS` was `COLS`
    # without Asset Type, the Rejection Reason and Direction (166, #179): the
    # receipt for what was just submitted carried the same nine columns as the
    # window somebody opens to search a quarter, and at nine the identifiers
    # were squeezed by columns that are not identity. RECENT is not a table
    # any more - it is the list-and-detail shape, where the row carries the two
    # identifiers and the pane beside it carries everything those three
    # columns did and the note as well - so the set that existed to say less
    # has nothing left to say it about. History is the one table here and it
    # states all nine.

    def _make_table(self, parent):
        """History's table. The one Treeview left in this window.

        Sortable, searched and multi-selected, which is what
        `docs/CODING_STANDARDS.md` says a list stays a Treeview for; RECENT,
        which was glanced at rather than searched, is the list-and-detail shape
        instead. The `gutter` and `cols` arguments went with it - the margin
        gutter was a Treeview colouring a row and never a cell, and History
        never had one.
        """
        cols = self.COLS
        names = tuple(c for c, _ in cols)
        tree = ttk.Treeview(parent, columns=names, show="headings")
        # Kept on the widget rather than read back off `-columns`: Tcl hands a
        # list of names carrying spaces back as one brace-quoted string, and
        # `Asset No.` is two words. `_fill_table` asks this.
        tree.ui_cols = names
        for c, w in cols:
            tree.heading(c, text=c, anchor="w",
                         command=lambda col=c: self._sort_by(col))
            tree.column(c, width=w, anchor="w", minwidth=40)
        sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        sb.pack(side="right", fill="y")
        return _tag_status(tree)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _submit(self):
        asset_no = self.v_asset_no.get().strip()
        serial   = self.v_serial.get().strip()
        atype    = self.v_type.get()
        member   = self.v_member.get()
        direc    = self.v_direction.get()

        if not asset_no and not serial:
            messagebox.showerror("Missing ID",
                "Please enter at least the Asset Number or Serial Number.")
            return
        if not member:
            messagebox.showerror("Missing Field", "Please select an Engineer.")
            return

        # ── Validate & correct against lookup sheet ───────────────────────
        # Try asset_no first, then serial_no — accept whichever is found
        found_data = None
        tried = []
        for q in filter(None, [asset_no, serial]):
            if q in tried:
                continue
            tried.append(q)
            try:
                r = lookup_asset(self.server_url, q, timeout=4)
                if r.ok:
                    d = r.json()
                    if d.get("found"):
                        found_data = d
                        break
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout):
                # Could not be reached - queue the submission to send later.
                #
                # Timeout as well as ConnectionError, because ReadTimeout is
                # neither: requests makes ConnectTimeout a ConnectionError and
                # leaves ReadTimeout outside it, so the one server state this
                # system is built to survive - the socket accepted and the
                # reply never came - was the one that fell through to the
                # handler below and refused the Transaction. That state is why
                # _port_in_use probes with an exclusive bind rather than a
                # connect, which reads a wedged-but-listening server as free,
                # and why the server runs threaded at all. This is a GET that
                # writes nothing, so a timeout on it says only that the server
                # could not be reached, which is what every other path in this
                # file already calls offline: _check_server paints Offline off
                # a bare Exception and _flush_buffer keeps the payload off one.
                # The movement has already happened by the time anybody is
                # standing here, and the record is owed.
                self._buffer_offline_submit()
                return
            except Exception as e:
                messagebox.showerror("Error", f"Lookup failed: {e}")
                return

        if found_data is None:
            lines = ""
            if asset_no: lines += f"Asset No: {asset_no}\n"
            if serial:   lines += f"Serial No: {serial}\n"
            messagebox.showerror("Asset Not in Lookup",
                f"\u26a0  This asset was not found in the lookup sheet.\n\n"
                f"{lines}\n"
                "Only registered assets can be submitted.")
            return

        # Auto-correct both fields to the canonical values from the lookup sheet
        correct_an   = str(found_data.get("asset_number",  "") or asset_no).strip()
        correct_sn   = str(found_data.get("serial_number", "") or serial).strip()
        correct_type = found_data.get("asset_type", atype)
        asset_no = correct_an
        serial   = correct_sn
        atype    = correct_type if correct_type in self.asset_types else atype
        self.v_asset_no.delete(0, "end")
        self.v_asset_no.insert(0, asset_no)
        self.v_serial.delete(0, "end")
        self.v_serial.insert(0, serial)
        self.v_type.set(atype)

        payload = {
            "asset_number":  asset_no,
            "serial_number": serial,
            "asset_type":    atype,
            "asset_model":   self._resolved_model,
            "team_member":   member,
            "direction":     direc,
            "notes":         self.v_notes.get().strip(),
            "storekeeper":   _sk_name,
        }
        try:
            r = api("post", f"{self.server_url}/transactions", json=payload)
            if common.held_for_maintenance(r):
                # The server is up and is not taking writes (ADR-0018). The
                # movement has already happened and the record is owed, so this
                # is the offline buffer's situation rather than a refusal - the
                # only difference from a server that is down is that this one
                # said so, which is why the notice is the server's own words
                # rather than this app's sentence about being offline.
                self._buffer_add(payload)
                messagebox.showinfo("Saved For Later",
                    "%s  %s\n\nThis transaction was saved to a local buffer "
                    "and will be sent automatically when the server is taking "
                    "writes again." % ("⏸", common.maintenance_notice(r)))
                self._clear_form()
                self._refresh_transactions()
                return
            if r.status_code == 409:
                messagebox.showerror("Duplicate Pending",
                    r.json().get("error", "This asset already has a pending transaction."))
                return
            if r.status_code == 201:
                log_event("transaction.submitted",
                          "%s  %s  %s" % (asset_no or serial, member, direc),
                          actor=sk_actor())
                id_line = ""
                if asset_no: id_line += f"Asset No : {asset_no}\n"
                if serial:   id_line += f"Serial No: {serial}\n"
                icon = "🔴" if direc == "Out Store" else "🟢"
                messagebox.showinfo("Submitted ✓",
                    f"{icon}  Transaction recorded!\n\n"
                    f"{id_line}"
                    f"Type  : {atype}\n"
                    f"To    : {member}\n"
                    f"Status: {direc}\n\n"
                    f"⏳  Waiting for {member.split()[0]}'s confirmation…")
                self._clear_form()
                self._refresh_transactions()
            else:
                err = r.json().get("error", r.status_code)
                log_event("transaction.refused",
                          "%s  %s" % (asset_no or serial, err), level="warn",
                          actor=sk_actor())
                messagebox.showerror("Server Error", err)
        except requests.exceptions.ConnectionError:
            # Server went offline between lookup and submit - queue it.
            # _buffer_add writes the System Log entry, for both callers.
            self._buffer_add(payload)
            messagebox.showinfo("Saved Offline",
                "⚠  The server is offline.\n\nThis transaction was saved to a local buffer "
                "and will be sent automatically when the server is back online.")
            self._clear_form()
            self._refresh_transactions()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _clear_form(self):
        for w in (self.v_asset_no, self.v_serial, self.v_notes):
            w.delete(0, "end")
        self.v_member.set("")
        self.v_direction.set("Out Store")
        self._clear_lookup()

    # ── Dynamic engineers ─────────────────────────────────────────────────────
    def _load_members(self):
        """Fetch the engineer list from the server; fall back to the built-in list."""
        try:
            r = api("get", f"{self.server_url}/members", timeout=5)
            if r.ok:
                names = [m["name"] for m in r.json()]
                if names:
                    self._members = names
                    cur = self.v_member.get()
                    self.v_member["values"] = names
                    if cur in names:
                        self.v_member.set(cur)
                    if hasattr(self, "v_filter_member"):
                        fcur = self.v_filter_member.get()
                        self.v_filter_member["values"] = ["All"] + names
                        if fcur not in (["All"] + names):
                            self.v_filter_member.set("All")
        except Exception:
            pass

    def _load_asset_types(self):
        """Refresh the valid asset types for the history filter, through
        common.fetch_asset_types() - the request and the on-disk cache both
        live there now (rule 10), so a failed fetch still leaves the last real
        answer rather than the built-in list. New types added to the lookup
        appear here without a rebuild. The form's type is not picked from this
        list - it is whatever the lookup gave."""
        try:
            types = fetch_asset_types(self.server_url, timeout=5)
            self.asset_types = types
            if hasattr(self, "v_filter_type"):
                fcur = self.v_filter_type.get()
                self.v_filter_type["values"] = ["All"] + types
                if fcur not in (["All"] + types):
                    self.v_filter_type.set("All")
        except Exception:
            pass

    def _add_engineer_dialog(self):
        """A name, and whether anybody is ever asked to confirm for them.

        This app creates an Engineer and does nothing else with one (013). The
        Own Password field, the Access Profile choice and the per-permission
        checkboxes have gone to the Server GUI's Manage Users and Engineer
        Passwords windows: what a Permission gates is what an *Engineer's* own
        client shows them, and an Own Password is a credential somebody can
        then be that Engineer with - both the Admin's decisions, and neither
        settable here on the way in only, which is all this dialog could ever
        do. Delete Engineer went with them for the same reason: removing a row
        takes that Engineer's Own Password down with it.

        **Auto-Approve stays.** It is not a permission and not a credential -
        it says this Engineer has no Notifier, so nothing will ever be asked to
        confirm their Transactions - and it is the one fact the person adding
        the Engineer actually knows at that moment, here at the machine where
        those Transactions are recorded. `_save_member` has no _KEEP for it
        either, so the field is sent on every write regardless.

        **It asks for no password since S3** (ADR-0017). Creating an Engineer
        is delegated by default, gated by `storekeeper_can_add_engineer` on the
        server and hidden here while that is off. What it hands over is the
        ability to name somebody Transactions are then recorded against, which
        is small beside `POST /transactions` needing no credential at all
        (ADR-0002) and large enough that the row is created with no password of
        any kind - and that an Engineer who already exists is refused, an
        update being an edit and edits staying at the console.

        `POST /members` is untouched for an admin caller: an omitted
        `member_password` or `permissions` keeps whatever the row already had,
        so this narrower form and an older Storekeeper still mid-rollout mean
        the same thing. What is new is a body with no `password` key at all.
        """
        if ui_kit.raise_open("add_engineer") is not None:
            return
        dlg = tk.Toplevel(self.root)
        ui_kit.single(dlg, "add_engineer")
        dlg.title("Add Engineer")
        dlg.configure(bg=BG)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(self.root)
        tk.Label(dlg, text="➕  Add Engineer", bg=ACCENT, fg="white",
                 font=font("title")).pack(fill="x", ipady=10)
        # Before the form, and from the bottom: the form below expands, so a
        # button packed after it is the first thing squeezed. It still asks for
        # its size rather than carrying one - the form is shorter than it was,
        # and a written number would be the stale copy of that. See ui_kit.fit.
        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")
        frm = tk.Frame(dlg, bg=CARD2, padx=18, pady=12)
        frm.pack(fill="both", expand=True, padx=14, pady=12)

        def fld(text):
            tk.Label(frm, text=text, bg=CARD2, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(8, 2))

        fld("Engineer Name")
        name_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                          font=font("value"), insertbackground=TEXT)
        name_e.pack(fill="x", ipady=6)
        auto_var = tk.IntVar(value=0)
        tk.Checkbutton(frm, text="Auto-approve (no Notifier — transactions auto-confirmed)",
                       variable=auto_var, bg=CARD2, fg=TEXT, selectcolor=INPUT_BG,
                       activebackground=CARD2, activeforeground=TEXT,
                       font=font("micro"), wraplength=300, justify="left").pack(anchor="w", pady=(8, 0))

        tk.Label(frm, text="They start on the Default profile and with no own "
                           "password. Both are set in the Server GUI's Manage "
                           "Users window, which is also where an engineer who "
                           "is already on the list is changed.",
                 bg=CARD2, fg=SUBTEXT, font=font("micro"),
                 wraplength=320, justify="left").pack(anchor="w", pady=(8, 0))
        err = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=font("body"))
        err.pack()

        def do_add():
            nm = name_e.get().strip()
            if not nm:
                err.config(text="✗  Enter a name."); return
            try:
                # No `password` key at all, which is what the server reads as
                # this path - `password: ""` would be an attempt at the admin
                # one and is refused as wrong (ADR-0017).
                r = api("post", f"{self.server_url}/members",
                        json={"name": nm,
                              "auto_approve": bool(auto_var.get())}, timeout=6)
                if r.ok:
                    self._load_members()
                    self.v_member.set(nm)
                    dlg.destroy()
                    messagebox.showinfo("Engineer Added",
                        f"✓  {nm} added"
                        + ("  (auto-approve)" if auto_var.get() else "") + ".")
                else:
                    err.config(text="✗  " + str(r.json().get("error", r.status_code)))
            except Exception as e:
                err.config(text=f"✗  {e}")

        tk.Button(foot, text="✔  Add Engineer", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=do_add, activebackground=ACCENT2).pack(fill="x", padx=14, pady=(0, 12))
        ui_kit.fit(dlg, 400)
        name_e.focus_set()

    # ── Offline buffer (queue submits when the server is down) ────────────────
    def _buffer_load(self):
        try:
            if os.path.exists(BUFFER_PATH):
                with open(BUFFER_PATH, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _buffer_save(self, items):
        try:
            with open(BUFFER_PATH, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2)
        except Exception:
            pass

    def _buffer_add(self, payload):
        """Queue one Transaction for the next time the server answers.

        The System Log entry is written here rather than by whoever called,
        because this is the one place a Transaction is added to the buffer.
        It was the caller's, and only one of the two callers had it: the POST
        leg of `_submit` - the server falling over inside the few hundred
        milliseconds between the lookup and the submit - logged
        `transaction.buffered`, while the lookup leg, which is what happens
        every time the server is simply down, logged nothing at all. So the
        one entry that only ever exists when the server cannot be reached was
        missing from the path the offline buffer exists for, out of the
        rolling `client.log` this machine keeps about itself as well as out of
        the queue shipped to the server, and a Transaction that sat here for
        an hour was invisible in both.
        """
        log_event("transaction.buffered",
                  "%s  %s  %s  ·  server unreachable"
                  % (payload.get("asset_number")
                     or payload.get("serial_number") or "",
                     payload.get("team_member") or "",
                     payload.get("direction") or ""), level="warn",
                  actor=sk_actor())
        items = self._buffer_load()
        items.append(payload)
        self._buffer_save(items)

    def _buffer_offline_submit(self):
        """Queue the current form as a transaction to send when the server returns."""
        self._buffer_add({
            "asset_number":  self.v_asset_no.get().strip(),
            "serial_number": self.v_serial.get().strip(),
            "asset_type":    self.v_type.get(),
            "asset_model":   self._resolved_model,
            "team_member":   self.v_member.get(),
            "direction":     self.v_direction.get(),
            "notes":         self.v_notes.get().strip(),
            "storekeeper":   _sk_name,
        })
        messagebox.showinfo("Saved Offline",
            "⚠  The server is offline.\n\nThis transaction was saved to a local buffer "
            "and will be sent automatically when the server is back online.")
        self._clear_form()

    def _flush_buffer(self):
        """Send what was queued offline. Three answers, not two.

        201 is recorded and 409 is already recorded by somebody, so both are
        done with. A connection error, a timeout and a 5xx are the failures
        this buffer exists for, and stay queued.

        A **4xx is permanent**, and that is the case that used to sit here for
        ever: every answer but 201 and 409 went back into the buffer, so a
        payload the server will always refuse was re-POSTed every fifteen
        seconds for the life of the installation. The movement was never
        recorded, nothing said so, and the storekeeper had been told at submit
        time that it would be sent when the server came back.

        It is reached by an ordinary route rather than a strange one. The
        offline path buffers **before** any lookup check — correctly, since
        the Lookup Sheet is on the server and there is nothing to check against
        while it is down — so an asset the sheet does not hold is the one
        thing most likely to be queued and always refused, and that is rule 6's
        400, which is exactly the situation the Tools tab's Propose an asset
        exists for.

        So a permanent refusal leaves the buffer and is shown, in the server's
        own words: only the server knows why it said no, and the Cancel flow
        beside this one shows a refusal verbatim for the same reason. Dropping
        it is also what stops it being shown twice, which is the answer
        seen_rejections.json gives for a rejection.

        **One transport failure ends the run.** This loop is not on a worker -
        the whole tick is an after() callback and runs straight through on the
        Tk thread - so every second it spends is a second this window cannot
        repaint in. Against a server that accepts and never answers, twenty
        queued rows were twenty five-second timeouts: a hundred seconds of a
        frozen app per fifteen-second tick, and nineteen of those requests could
        not come back with anything the first had not already said, being the
        same request to the same host a moment later. The situation is also the
        one this buffer exists for and the one the rest of this system is built
        to survive - a wedged-but-listening server is why _port_in_use probes
        with an exclusive bind rather than a connect and why the server runs
        threaded - and a bulk scan is what puts twenty rows in here at once.
        So the rest are kept in the order they were queued and the flush stops.

        A server **answer** that is not 201/409 is not that and does not stop
        it: a refusal is about that one row, and the row behind it may well go
        through, so the 4xx and 5xx branches are untouched.

        **The one answer that does stop it is a maintenance hold** (G3,
        ADR-0018), which is the sentence above rather than an exception to it:
        an ordinary 5xx is the server failing at this one row, where a
        `maintenance` 503 is the server saying it is taking no writes at all,
        so it has already answered for every row behind this one exactly as a
        transport failure has. Left to the general 5xx branch, a restore would
        turn a forty-row buffer into forty POSTs on every fifteen-second tick,
        on the Tk thread - the frozen window #99 landed to remove, reached
        through a different door. The **code** is the discriminator and not the
        status: a 503 without it is somebody's proxy answering about this
        request rather than the server answering about itself.
        """
        items = self._buffer_load()
        if not items:
            return
        remaining, refused, sent = [], [], 0
        held = ""
        for i, payload in enumerate(items):
            try:
                r = api("post", f"{self.server_url}/transactions", json=payload, timeout=5)
            except Exception:
                # Still offline, and that is now known about every row behind
                # this one as well - so they are kept in the order they were
                # queued and the next tick asks again, rather than this one
                # spending a timeout per row on the thread that repaints the
                # window. See the docstring.
                remaining.extend(items[i:])
                break
            if common.held_for_maintenance(r):
                # An answer about the server rather than about this row, so it
                # has been given for every row behind it too. See the
                # docstring - this is the transport failure's rule, reached by
                # a server that is answering.
                remaining.extend(items[i:])
                held = common.maintenance_notice(r)
                break
            if r.status_code in (201, 409):
                sent += 1          # 409 = a matching pending already exists
            elif 400 <= r.status_code < 500:
                try:
                    why = r.json().get("error") or ""
                except Exception:
                    why = ""
                refused.append((payload, why or "The server refused it (%d)."
                                                % r.status_code))
            else:
                remaining.append(payload)   # a 5xx is the server, not the row
        self._buffer_save(remaining)
        if sent:
            self._refresh_transactions()
        # Reported after the buffer is written, so a refusal that somehow
        # raised while being shown cannot leave the row queued to be refused
        # again on the next tick.
        for payload, why in refused:
            self._notify_buffer_refused(payload, why)
        # Written once per hold rather than once per tick: the buffer is doing
        # exactly what it exists for and nothing has been lost, so what an
        # Admin reading the log needs is that this machine is holding rows and
        # why - which the fortieth copy of does not add to.
        if held and held != self._held_said:
            self._held_said = held
            log_event("transaction.buffered",
                      "%d queued  %s  %s" % (len(remaining), "·", held),
                      level="warn", actor=sk_actor())
        elif not held:
            self._held_said = ""

    def _notify_buffer_refused(self, payload, why):
        """Say that a queued Transaction will never be sent, and why.

        Forced forward the way _notify_rejection is, and for a sharper reason:
        this is said once, the row is already out of the buffer, and what it
        reports is a movement that happened in the store and now has no record
        of it anywhere.
        """
        aid = (payload.get("asset_number") or payload.get("serial_number")
               or "?")
        # The same event name the form's own refusal writes — it is the same
        # fact, the server saying no to this Transaction — with the detail
        # naming which door it came through, since nobody was watching when it
        # was queued.
        log_event("transaction.refused",
                  "%s  %s  %s  — from the offline buffer, not recorded: %s"
                  % (aid, payload.get("team_member", "?"),
                     payload.get("direction", "?"), why),
                  level="warn", actor=sk_actor())
        self._notice(
            "error",
            "Saved offline — not recorded",
            ["%s  ·  %s  ·  %s  ·  %s"
             % (aid, payload.get("asset_type", ""),
                payload.get("team_member", ""), payload.get("direction", "")),
             "The server said: %s" % why,
             "It has been taken out of the offline buffer, so it will not be "
             "retried. Fix what the server named and record it again."])

    # ── Rejection notifications to the storekeeper ────────────────────────────
    def _seen_load(self):
        """Return the persisted set of acknowledged rejection ids, or None if no file yet."""
        try:
            if os.path.exists(SEEN_REJECTIONS_PATH):
                with open(SEEN_REJECTIONS_PATH, encoding="utf-8") as f:
                    return set(json.load(f))
        except Exception:
            pass
        return None

    def _seen_save(self):
        try:
            with open(SEEN_REJECTIONS_PATH, "w", encoding="utf-8") as f:
                json.dump(sorted(self._seen_rejected), f)
        except Exception:
            pass

    def _init_seen_rejected(self):
        stored = self._seen_load()
        if stored is not None:
            # Resume from the persisted acknowledged set — rejections that occurred
            # while the app was closed (and not yet acknowledged) will pop on next poll.
            self._seen_rejected = stored
            return
        # First run (no file yet): mark all existing rejections as acknowledged so we
        # don't replay the whole history — only rejections from now on will notify.
        try:
            r = api("get", f"{self.server_url}/export", timeout=5)
            if r.ok:
                for t in r.json():
                    if t.get("rejected"):
                        self._seen_rejected.add(t["id"])
        except Exception:
            pass
        self._seen_save()

    def _poll_rejections(self):
        try:
            r = api("get", f"{self.server_url}/export", timeout=5)
            if not r.ok:
                return
            for t in r.json():
                if t.get("rejected") and t["id"] not in self._seen_rejected:
                    self._seen_rejected.add(t["id"])
                    self._seen_save()          # persist before showing, so it never re-nags
                    self._notify_rejection(t)
        except Exception:
            pass

    # At most this many notices are kept on the strip. A bound rather than a
    # scroll region: what is behind the fourth is something the storekeeper
    # has had three notifications' worth of time to read, and an unbounded
    # column of them would push the tab bodies off the window - which is the
    # popup-nobody-dismisses failure reached by a different door.
    NOTICE_MAX = 4

    def _notice(self, level, title, lines):
        """Say it on the window, and ask the taskbar for attention (#193).

        What this replaces is `deiconify()` + `lift()` + `-topmost` followed
        by a modal `messagebox`, which every notification in this app used to
        be. Two things were wrong with it and only one of them is the
        raising. A window forced in front of whatever the storekeeper was
        doing takes the screen rather than asking for it, and this machine is
        one somebody is scanning at - but dropping the lift on its own would
        have been **worse** than leaving it: a `messagebox` is modal and
        appears over its parent, so a parent behind another app is an app
        wedged behind a dialog nobody can see. The remedy is the pair, not
        half of it.

        So the notice is drawn here, on the window, where it waits however
        long it has to and is dismissed by the \u2715 on it; and
        `ui_kit.flash` asks the taskbar button to say that this app has
        something, which is the half that survives the window being behind
        something else. Nothing here grabs, nothing raises and nothing takes
        focus, so a Transaction being typed at the moment one arrives is
        untouched.
        """
        colour = {"error": DANGER, "warn": WARNING,
                  "good": SUCCESS}.get(level, ACCENT)
        row = tk.Frame(self.notices, bg=CARD2)
        row.pack(fill="x", padx=26, pady=(10, 0))
        tk.Frame(row, bg=colour, width=3).pack(side="left", fill="y")
        shut = tk.Label(row, text="\u2715", bg=CARD2, fg=SUBTEXT,
                        font=font("value"), cursor="hand2", padx=13)
        shut.pack(side="right", fill="y")
        shut.bind("<Button-1>", lambda _e: row.destroy())
        box = tk.Frame(row, bg=CARD2)
        box.pack(side="left", fill="x", expand=True, padx=(13, 0), pady=9)
        tk.Label(box, text=title, bg=CARD2, fg=colour,
                 font=font("emph", size=10), anchor="w").pack(fill="x")
        for ln in lines:
            if not ln:
                continue
            ui_kit.rewrap(tk.Label(box, text=ln, bg=CARD2, fg=TEXT,
                                   font=font("body"), wraplength=560,
                                   justify="left", anchor="w"), 90).pack(
                fill="x", pady=(2, 0))
        # Oldest first, the order they were packed in.
        kept = self.notices.winfo_children()
        for extra in kept[:max(0, len(kept) - self.NOTICE_MAX)]:
            extra.destroy()
        ui_kit.flash(self.root)
        return row

    def _notify_rejection(self, t):
        aid    = t.get("asset_number") or t.get("serial_number") or "?"
        reason = t.get("rejection_reason") or "(no reason given)"
        self._notice(
            "warn",
            "%s rejected a transaction" % t.get("team_member", "?"),
            ["%s  ·  %s  ·  %s" % (aid, t.get("asset_type", ""),
                                        t.get("direction", "")),
             "Reason: %s" % reason,
             "The row is in History, carrying the same state."])

    def _seen_decided_load(self):
        """The proposal ids whose answer has been shown, or None if no file."""
        try:
            if os.path.exists(SEEN_PROPOSALS_PATH):
                with open(SEEN_PROPOSALS_PATH, encoding="utf-8") as f:
                    return set(json.load(f))
        except Exception:
            pass
        return None

    def _seen_decided_save(self):
        try:
            with open(SEEN_PROPOSALS_PATH, "w", encoding="utf-8") as f:
                json.dump(sorted(self._seen_decided), f)
        except Exception:
            pass

    def _init_seen_decided(self):
        """First run acknowledges whatever was already decided.

        The same shape `_init_seen_rejected` has, and for the same reason: an
        installation standing up for the first time must not replay every
        answer the admin has ever given somebody else.
        """
        stored = self._seen_decided_load()
        if stored is not None:
            self._seen_decided = stored
            return
        try:
            r = api("get", f"{self.server_url}/assets/proposals", timeout=5)
            if r.ok:
                for p in r.json():
                    if p.get("status") != "pending":
                        self._seen_decided.add(p["id"])
        except Exception:
            pass
        self._seen_decided_save()

    def _poll_proposals(self):
        """Show the answer to anything this installation proposed.

        Scoped to this installation's own `client_id`: the admin's answer to
        another store's proposal is not this screen's business, and the
        Connected Clients registry is where an admin asks who proposed what.
        """
        mine = common.client_id(self.cfg, save_config)
        try:
            r = api("get", f"{self.server_url}/assets/proposals", timeout=5)
            if not r.ok:
                return
            for p in r.json():
                if p.get("status") == "pending" or p["id"] in self._seen_decided:
                    continue
                self._seen_decided.add(p["id"])
                self._seen_decided_save()   # before showing, so it never re-nags
                if p.get("client_id") == mine:
                    self._notify_decision(p)
        except Exception:
            pass

    def _notify_decision(self, p):
        ident = p.get("asset_number") or p.get("serial_number") or "?"
        if p.get("status") == "approved":
            self._notice(
                "good",
                "%s is in the lookup sheet now" % ident,
                ["Type: %s" % p.get("asset_type", ""),
                 "Approved by: %s" % (p.get("decided_by") or "the admin"),
                 "It can be transacted from here as any other asset."])
        else:
            self._notice(
                "warn",
                "%s was not added to the lookup sheet" % ident,
                ["Reason: %s" % (p.get("reason") or "(none given)"),
                 "It still cannot be transacted."])

    def _tick_background(self):
        """Periodic: refresh the history table (so confirm/reject status reflects
        without a manual refresh), flush the offline buffer, and check for new
        rejections. Filters/search are preserved by _refresh_transactions."""
        try:
            # Follow the server if an admin changed the comms port; see
            # resolve_server_url for why this runs before the refresh.
            url, health = resolve_server_url(self.cfg, save_config)
            if url:
                self.server_url = url
                sync_server_cert(self.server_url)
            # The switch rides on the heartbeat this call already made, so the
            # offer follows it within one tick and with no restart.
            self._note_health(health)
            self._refresh_transactions()
            self._flush_buffer()
            self._poll_rejections()
            # Beside the rejections above, and for the same reason: an answer
            # this app never shows is an answer nobody gets, the admin having
            # no way to reach this machine except the next time it asks.
            self._poll_proposals()
            # Before the check-in below, deliberately: a logoff collected there
            # closes the window, and entries this app has already written
            # should have had their chance to reach the server first. What is
            # left unshipped is still in client.log either way.
            ship_log(self.server_url, self.cfg, save_config, "Storekeeper")
            # Last in the tick, after the buffer has had its chance to flush: a
            # logoff arriving here must not be what stops a submission that was
            # waiting for the server to come back.
            #
            # Already on the Tk thread, since this whole tick is an after()
            # callback, so the handlers run straight through - unlike the
            # Notifier, whose tick is a worker thread. The logoff is deferred by
            # one callback rather than destroying the root from inside it: this
            # method re-arms itself immediately below, and `after` on a
            # destroyed root raises TclError into Tk's handler. There is no
            # setup wizard here, so reset_identity is the identifier alone.
            #
            # `trust_cert` is common.trust_next_cert and nothing of this app's
            # (rule 10): the fetch, the idempotent append and every refusal are
            # transport, and what is this app's is the line it writes down. It
            # answers "" for everything but an actual append - nothing staged,
            # a body that was not a certificate, one already held - so a second
            # push is not logged as a change that was not made.
            obey(checkin(self.server_url, self.cfg, save_config, "Storekeeper",
                         APP_VERSION),
                 {"logoff": lambda: (log_event("command.obeyed", "logoff",
                                               actor=sk_actor()),
                                     self.root.after(200, self.root.destroy)),
                  "reset_identity": lambda: (
                      log_event("command.obeyed", "reset_identity",
                                actor=sk_actor()),
                      forget_client_id(self.cfg, save_config)),
                  "trust_cert": lambda: self._trust_cert(),
                  "update_now": lambda: self._update_now()})
            # Windows raises no event when the user switches Light and Dark
            # mode, so following it is a poll, and this tick already exists.
            # `follow` is a no-op unless the setting is "system".
            if THEME.follow():
                self._paint_theme_btn()
        except Exception:
            pass
        self.root.after(15000, self._tick_background)

    def _trust_cert(self):
        """The `trust_cert` command, obeyed. C3, ADR-0020.

        A method rather than a lambda beside the other two only because it has
        a branch in it: `trust_next_cert` answers "" for everything that is not
        an append - nothing staged, a body that was not a certificate, one this
        installation already holds - and a line claiming a certificate was
        added is worth writing only where one was. Nothing is shown to the
        storekeeper: a certificate the server has bound nothing to is not a
        thing to interrupt somebody mid-scan about.
        """
        fp = trust_next_cert(self.server_url)
        if fp:
            log_event("cert.trusted", fp, level="warn", actor=sk_actor())

    def _update_now(self):
        """The `update_now` command, obeyed. #177.

        The Admin's end of the update path, and nothing but a call into the one
        this app's own Check for Updates uses: the package, the pinned
        download, the SHA-256 and manifest checks made before anything is
        closed, the applier, the rollback and the outcome reported on the start
        after (#148) are all that path's and none of them are re-decided here.
        What a push changes is who asked, so the postpone counter is not
        touched and no question is put on screen - an offer that cannot be
        declined is not an offer, and this one was accepted at the console.

        It is obeyed at the end of the background tick, where the logoff beside
        it already sits and for its reason: the offline buffer has had its
        chance to flush first, and an update must not be what strands a
        submission waiting for the server to come back. What the applier then
        waits on is this process going, and the buffer file it leaves behind is
        in no manifest, so whatever is still queued survives the update and is
        flushed by the run after it.

        The version is read here and now rather than taken off the command:
        `_queue_command` refuses a push this server holds no package for, but a
        week may pass before the machine collects it, and what is published now
        is the server's to say now. A server advertising nothing newer is the
        ordinary state on a machine that has already updated itself since the
        Admin queued this, so that is a line rather than a failure.

        The read is on the Tk thread, like the rest of this tick and like the
        buffer flush above it - one /version against a server that answered a
        check-in a moment ago, rather than a worker for a call that has already
        been shown to be answering. `_apply_source_update` puts the download
        itself on one.
        """
        try:
            r = api("get", f"{self.server_url}/version", timeout=5)
            data = r.json() if r.ok else {}
        except Exception:
            data = {}
        latest = (data or {}).get("latest", "")
        if not latest or _ver_tuple(latest) <= _ver_tuple(APP_VERSION):
            log_event("command.obeyed",
                      "update_now: nothing newer than %s is published"
                      % APP_VERSION, actor=sk_actor())
            return
        if not _has_client_package(data, UPDATE_APP_KEY):
            # The queue refused this case at issue time; reaching it means the
            # package stopped being there in between, and sending a storekeeper
            # who asked for nothing to a browser is not a push.
            log_event("command.obeyed",
                      "update_now: %s is published but this server holds no "
                      "package for it" % latest, level="warn",
                      actor=sk_actor())
            return
        log_event("command.obeyed", "update_now: applying %s" % latest,
                  level="warn", actor=sk_actor())
        self._apply_source_update(latest)

    # ── Asset Lookup (auto-fill) ──────────────────────────────────────────────

    def _schedule_lookup(self, source_field):
        """Cancel any pending lookup and schedule a new one in 400 ms."""
        if self._lookup_after_id:
            self.root.after_cancel(self._lookup_after_id)
        q = getattr(self, source_field).get().strip()
        if len(q) < 2:
            return
        self._lookup_after_id = self.root.after(
            400, lambda: self._do_lookup(q, source_field))

    def _do_lookup(self, q, source_field):
        """Hit /lookup and auto-fill sibling field + type combobox."""
        self._lookup_after_id = None
        def fetch():
            try:
                r = lookup_asset(self.server_url, q, timeout=4)
                if r.ok:
                    data = r.json()
                    self.root.after(0, lambda: self._apply_lookup(data, source_field))
            except Exception:
                pass  # server offline — silent, don't block the user
        threading.Thread(target=fetch, daemon=True).start()

    def _apply_lookup(self, data, source_field):
        """Called on the main thread after a lookup response."""
        q = self.v_asset_no.get().strip() or self.v_serial.get().strip()
        if not data.get('found'):
            # Say so rather than staying silent: the server refuses an asset
            # the sheet does not know (project rule 6), so the storekeeper is
            # better off learning it here than from an error on Submit.
            if q:
                self.lbl_resolve.config(
                    fg=WARNING,
                    text=f"!  {q} is not in the lookup sheet \u2014 the server "
                         f"will refuse this one")
                self._show_propose(True)
                self._paint_custody(q)
            return
        self._show_propose(False)
        atype  = data.get('asset_type', '')
        an     = data.get('asset_number', '')
        sn     = data.get('serial_number', '')
        amodel = data.get('asset_model', '')
        # Fill the sibling field only if it is currently empty
        if source_field == 'v_asset_no' and sn:
            if not self.v_serial.get().strip():
                self.v_serial.delete(0, 'end')
                self.v_serial.insert(0, sn)
        elif source_field == 'v_serial' and an:
            if not self.v_asset_no.get().strip():
                self.v_asset_no.delete(0, 'end')
                self.v_asset_no.insert(0, an)
        # The model is no longer a field. It is still submitted, so it is held
        # here and shown in the verdict line instead of sitting in a disabled
        # Entry the storekeeper could never type into anyway.
        self._resolved_model = amodel
        self.v_type.set(atype)
        # The block above states the model and the type, so this line says
        # only what happened - the verdict, not a second copy of the answer.
        self.lbl_resolve.config(fg=SUCCESS,
                                text="Found in the lookup sheet.")
        self._paint_custody(an or sn or q)

    def _paint_resolved(self):
        """The block under the identifiers: what the sheet said about this one.

        Derived from what the last lookup resolved rather than stored beside
        it, so it cannot disagree with what `_submit` is about to send.
        """
        lbl = getattr(self, "lbl_resolved", None)
        if lbl is None:
            return
        atype = self.v_type.get()
        if not atype:
            lbl.config(text="\u2014", fg=SUBTEXT)
            return
        model = getattr(self, "_resolved_model", "") or "no model recorded"
        lbl.config(text="%s\n%s" % (atype, model), fg=TEXT)

    def _paint_dir_block(self):
        """The 3px block beside the Direction picker."""
        block = getattr(self, "dir_block", None)
        if block is not None:
            block.config(bg=self._dir_colour(self.v_direction.get()))

    def _paint_custody(self, ident):
        """What this asset has done before now, out of `self._all_rows`.

        Fetches nothing: that list is the whole transactions table the 15s
        tick keeps current, so this is a read of something already in hand
        rather than a request made while somebody is typing.
        """
        frame = getattr(self, "custody", None)
        if frame is None:
            return
        for w in frame.winfo_children():
            w.destroy()

        def note(text):
            tk.Label(frame, text=text, bg=CARD, fg=FAINT,
                     font=font("body")).pack(anchor="w")

        key = (ident or "").strip().lower()
        if not key:
            note("Type an identifier to see its history.")
            return
        hits = [r for r in getattr(self, "_all_rows", [])
                if key in (str(r.get('asset_number', '')).lower(),
                           str(r.get('serial_number', '')).lower())]
        if not hits:
            note("Nothing recorded against it yet.")
            return
        shown = hits[:6]
        for r in shown:
            out = str(r.get('direction', '')).startswith("Out")
            line = tk.Frame(frame, bg=CARD)
            line.pack(fill="x", pady=(0, 5))
            tk.Frame(line, bg=self._dir_colour(r.get('direction', '')),
                     width=3).pack(side="left", fill="y")
            tk.Label(line, text="OUT" if out else "IN", bg=CARD,
                     fg=self._dir_colour(r.get('direction', '')), width=4,
                     anchor="w", font=font("code")).pack(side="left",
                                                         padx=(8, 0))
            tk.Label(line, text=r.get('team_member', '') or "\u2014", bg=CARD,
                     fg=TEXT, anchor="w", font=font("body")).pack(side="left")
            try:
                when = datetime.fromisoformat(
                    r.get('timestamp', '')).strftime("%d %b")
            except Exception:
                when = ""
            tk.Label(line, text=when, bg=CARD, fg=SUBTEXT, anchor="e",
                     font=font("body")).pack(side="right")
        if len(hits) > len(shown):
            note("%d more in History" % (len(hits) - len(shown)))

    def _clear_lookup(self):
        """Drop everything the last lookup resolved - the type, the model and
        the verdict line (Clear, and after every submit)."""
        if hasattr(self, 'v_type'):
            self.v_type.set("")
        self._resolved_model = ""
        if hasattr(self, 'lbl_resolve'):
            self.lbl_resolve.config(fg=SUBTEXT, text=self.HINT)
        self._show_propose(False)
        self._paint_resolved()
        self._paint_custody("")

    def _show_propose(self, offer):
        """Show or hide the offer to propose whatever is typed in."""
        lbl = getattr(self, "lbl_propose", None)
        if lbl is None:
            return
        if offer:
            lbl.pack(side="right")
        else:
            lbl.pack_forget()

    def _on_scan_enter(self):
        """A scanner sends Enter after a barcode: look the value up straight
        away instead of waiting out the 400ms debounce."""
        if self._lookup_after_id:
            self.root.after_cancel(self._lookup_after_id)
            self._lookup_after_id = None
        q = self.v_asset_no.get().strip() or self.v_serial.get().strip()
        if q:
            self._do_lookup(q, 'v_asset_no' if self.v_asset_no.get().strip()
                            else 'v_serial')

    def _paint_sk_name(self):
        """Say who this installation records Transactions as."""
        if hasattr(self, "sk_lbl"):
            self.sk_lbl.config(text="Storekeeper  \u00b7  %s" % _sk_name)

    def _note_health(self, health):
        """Take the Cancel switch and the Storekeeper's name off a heartbeat.
        Main thread only.

        A missing `storekeeper_can_cancel` - or a missing
        `storekeeper_can_add_engineer` (ADR-0017) - means allowed, so a server
        built before either switch existed keeps the offer. An unreachable server changes
        nothing: the last answer is better than a guess, and a click while it is
        down fails with a message of its own anyway.

        A missing or empty `storekeeper_name` is read the same way - as nothing
        said rather than as a name cleared - so a server that predates the key
        leaves this installation recording under the name it already had. The
        name is written back to config.json rather than only held here, because
        app.started is logged before the first heartbeat is answered, and an
        entry attributed to a name this machine has since been told is wrong is
        worse than one attributed a run late.
        """
        global _sk_name
        if not health:
            return
        can = bool(health.get("storekeeper_can_cancel", True))
        if can != self._can_cancel:
            self._can_cancel = can
            self._paint_cancel_offer()
        try:
            self._cancel_window_mins = max(0, int(
                health.get("storekeeper_cancel_window_mins", 0) or 0))
        except (TypeError, ValueError):
            self._cancel_window_mins = 0
        add = bool(health.get("storekeeper_can_add_engineer", True))
        if add != self._can_add_member:
            self._can_add_member = add
            self._paint_add_engineer_offer()
        name = (health.get("storekeeper_name") or "").strip()
        if name and name != _sk_name:
            _sk_name = name
            # Over the config that is already here rather than a fresh dict,
            # for the reason the Server URL save gives: this is about one key,
            # and a dict built from it would drop client_id and theme.
            self.cfg["storekeeper_name"] = name
            save_config(self.cfg)
            self._paint_sk_name()

    def _within_cancel_window(self, t):
        """Is this an auto-approved Transaction still inside the window? (#198)

        Both facts are read off the row the server sent: `auto_approved`, which
        says how it came to be Confirmed rather than what the engineer's flag
        says today, and `confirmed_at`, which for such a row is the moment it
        was recorded. A row from a server that predates the column carries
        neither and answers False, which is the closed answer.

        The clock is this machine's against a timestamp the server wrote, so a
        badly-set client clock can make this answer either way - which costs
        nothing, because the server asks the same question again with its own
        clock and refuses what it will not take. What is decided here is the
        form, never the outcome.
        """
        if not self._cancel_window_mins or not t.get("auto_approved"):
            return False
        try:
            made = datetime.fromisoformat(str(t.get("confirmed_at") or ""))
        except (TypeError, ValueError):
            return False
        return datetime.now() - made <= timedelta(
            minutes=self._cancel_window_mins)

    def _paint_cancel_offer(self):
        """Show or hide the Cancel offer.

        Hidden rather than greyed out: a disabled button invites a click and
        then explains itself, and the switch being off is not about the row that
        was selected and is not something the storekeeper can do anything about.
        The server enforces it either way - this only decides what is offered.
        """
        if not hasattr(self, "_cancel_pill"):
            return
        if self._can_cancel:
            self._cancel_pill.pack()
        else:
            self._cancel_pill.pack_forget()

    def _paint_add_engineer_offer(self):
        """Show or hide the Add Engineer card (ADR-0017).

        Hidden rather than greyed, for the reason the Cancel offer is: the
        switch is not about anything the storekeeper can do something about,
        and a disabled button invites a click and then explains itself. The
        whole card goes rather than the button alone - what is left would be a
        heading and a sentence about a control that is not there.

        The server enforces it either way; this only decides what is offered.
        """
        if not hasattr(self, "_eng_card"):
            return
        if not self._can_add_member:
            self._eng_card.pack_forget()
        elif not self._eng_card.winfo_manager():
            # Back in its own place rather than appended to the end: pack puts
            # a re-shown child last, and the Engineers card sits above Assets.
            self._eng_card.pack(fill="x", pady=(0, 14),
                                before=self._assets_card)

    def _selected_row(self):
        """The one selected Transaction, or None for a header or no selection."""
        sel = self.tree.selection() if hasattr(self, "tree") else ()
        if len(sel) != 1:
            return None
        try:
            tid = int(sel[0])
        except ValueError:
            return None
        return next((t for t in self._all_rows if t.get("id") == tid), None)

    def _cancel_selected(self):
        """Retract one Transaction whose movement never happened.

        One row at a time, like the Server GUI's Cancel: only the newest
        non-cancelled Transaction for an asset can be cancelled, so a bulk
        cancel would refuse most of what it was handed with no useful way to
        say which of them.

        A reason is always required and a password only when the endpoint would
        demand one, so the ordinary mis-scan is not slower than the scan that
        made it. The server is the enforcement point - `_cancel_transaction` is
        shared by the endpoint and the Server GUI - and everything this dialog
        decides ahead of it is a courtesy, not a check.
        """
        t = self._selected_row()
        if t is None:
            messagebox.showinfo(
                "Cancel Transaction",
                "Select one row in the table to cancel.\n\n"
                "Cancelling retracts a movement that never happened - a "
                "mis-scan. The record is kept and marked, not deleted.")
            return
        # Refused here as a courtesy, so the reason is not typed out first. The
        # server refuses it too, and that is the check.
        if t.get("rejected"):
            messagebox.showwarning(
                "Cannot Cancel",
                "The engineer has already rejected this transaction, and that "
                "answer is the record. A rejected transaction cannot be "
                "cancelled.")
            return

        # Confirmed is not one state where the password is concerned (#198):
        # an Auto-Approve engineer has no Notifier and was never asked, so that
        # row was Confirmed a millisecond after the scan, and inside the window
        # the server publishes it is retracted with no password at all. The
        # server decides it again in `_cancel_transaction` - what is decided
        # here is only whether to put a password field in front of somebody.
        confirmed = bool(t.get("confirmed")) and not self._within_cancel_window(t)
        ident = t.get("asset_number") or t.get("serial_number") or "\u2014"
        if ui_kit.raise_open("cancel_transaction:%s" % t.get("id")) is not None:
            return
        dlg = tk.Toplevel(self.root)
        ui_kit.single(dlg, "cancel_transaction:%s" % t.get("id"))
        dlg.title("Cancel Transaction")
        dlg.configure(bg=BG)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        dlg.transient(self.root)
        tk.Label(dlg, text="\u2298  Cancel Transaction", bg=DANGER_BG,
                 fg="white", font=font("title")).pack(fill="x",
                                                                 ipady=10)
        # Before the form and from the bottom, so the button that cancels is
        # the first child served. `confirmed` adds a field, which is exactly
        # the change a written height does not follow - it was
        # `350 if confirmed else 290` and short in both branches - so the size
        # is asked for instead. See ui_kit.fit.
        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")
        frm = tk.Frame(dlg, bg=CARD2, padx=18, pady=12)
        frm.pack(fill="both", expand=True, padx=14, pady=12)

        tk.Label(frm, text="%s  \u00b7  %s  \u00b7  %s"
                           % (ident, t.get("team_member", ""),
                              t.get("direction", "")),
                 bg=CARD2, fg=TEXT, font=font("emph", size=10),
                 wraplength=330, justify="left").pack(anchor="w")
        tk.Label(frm, text="The record is kept and marked cancelled, carrying "
                           "who cancelled it, when and why. It stops counting "
                           "towards Pending and Out Now.",
                 bg=CARD2, fg=SUBTEXT, font=font("micro"), wraplength=330,
                 justify="left").pack(anchor="w", pady=(4, 0))

        tk.Label(frm, text="Reason", bg=CARD2, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(10, 2))
        reason_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                            font=font("value"), insertbackground=TEXT)
        reason_e.pack(fill="x", ipady=6)
        reason_e.focus_set()

        pw_e = None
        if confirmed:
            # The caption says which of the two cases is asking. A Pending
            # Transaction while the switch is on needs no password at all, so
            # this field is not built for one - an empty password box would read
            # as a credential the storekeeper was expected to have.
            tk.Label(frm, text="Admin Password  \u00b7  this transaction is "
                               "already confirmed",
                     bg=CARD2, fg=SUBTEXT, font=font("body")
                     ).pack(anchor="w", pady=(10, 2))
            pw_e = tk.Entry(frm, show="\u25cf", bg=INPUT_BG, fg=TEXT,
                            relief="flat", font=font("value"),
                            insertbackground=TEXT)
            pw_e.pack(fill="x", ipady=6)
            ui_kit.reveal(pw_e)
        err = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=font("body"),
                       wraplength=370, justify="left")
        err.pack()

        def do_cancel():
            reason = reason_e.get().strip()
            if not reason:
                err.config(text="\u2717  A reason is required.")
                return
            body = {"id": t.get("id"), "reason": reason}
            if pw_e is not None:
                pw = pw_e.get()
                if not pw:
                    err.config(text="\u2717  Enter the admin password.")
                    return
                # Only ever sent when there is one. A `password` key holding an
                # empty string is an attempt at the admin path and is refused as
                # wrong, not treated as absent.
                body["password"] = pw
            try:
                r = api("post", f"{self.server_url}/transactions/cancel",
                        json=body, timeout=6)
                if r.ok:
                    dlg.destroy()
                    self._refresh_transactions()
                    messagebox.showinfo(
                        "Transaction Cancelled",
                        "\u2713  %s cancelled. The record is kept and marked."
                        % ident)
                    return
                out = r.json() if r.content else {}
                code = out.get("code", "")
                if code == "cancel_disabled":
                    # The switch went off between the last heartbeat and this
                    # click. Take the offer away now rather than waiting for the
                    # next tick to say the same thing.
                    self._can_cancel = False
                    self._paint_cancel_offer()
                # The server's own words: `not_newest` names the transaction to
                # cancel first, and a generic failure would throw that away.
                err.config(text="\u2717  " + str(out.get("error", r.status_code)))
            except Exception as e:
                err.config(text=f"\u2717  {e}")

        tk.Button(foot, text="\u2298  Cancel Transaction", bg=DANGER_BG,
                  fg="white", font=font("heading"), relief="flat",
                  cursor="hand2", pady=9, command=do_cancel,
                  activebackground=DANGER_HOT).pack(fill="x", padx=14,
                                                   pady=(0, 12))
        ui_kit.fit(dlg, 400)

    def _clear_filters(self):
        self.v_filter_member.set("All")
        self.v_filter_status.set("All")
        self.v_filter_dir.set("All")
        self.v_filter_type.set("All")
        self.v_search.set("")

    def _refresh_transactions(self):
        def fetch():
            try:
                r = api("get", f"{self.server_url}/transactions")
                if r.ok:
                    self._all_rows = r.json()
                    self.root.after(0, self._apply_filters)
            except Exception: pass
            try:
                r = api("get", f"{self.server_url}/stats", timeout=5)
                if r.ok:
                    stats = r.json()
                    self.root.after(0, lambda: self._set_stats(stats))
            except Exception: pass
        threading.Thread(target=fetch, daemon=True).start()

    def _set_stats(self, stats):
        """Header counts. out_now is the server's definition - the assets an
        engineer is holding right now, not a running total of Out Store rows -
        so it is read from /stats rather than recounted from the table."""
        for key, lbl in self.stat_lbls.items():
            v = stats.get(key)
            lbl.config(text="\u2013" if v is None else str(v))

    def _apply_filters(self):
        if not hasattr(self, "tree"):
            return
        rows = list(self._all_rows)

        member_f = self.v_filter_member.get() if hasattr(self, 'v_filter_member') else "All"
        status_f = self.v_filter_status.get() if hasattr(self, 'v_filter_status') else "All"
        dir_f    = self.v_filter_dir.get()    if hasattr(self, 'v_filter_dir')    else "All"
        type_f   = self.v_filter_type.get()   if hasattr(self, 'v_filter_type')   else "All"
        query    = self.v_search.get().strip().lower() if hasattr(self, 'v_search') else ""

        if member_f != "All":
            rows = [t for t in rows if t['team_member'] == member_f]
        if dir_f != "All":
            rows = [t for t in rows if t['direction'] == dir_f]
        if type_f != "All":
            rows = [t for t in rows if t.get('asset_type') == type_f]
        if status_f == "Pending":
            rows = [t for t in rows if not t['confirmed'] and not t['rejected']]
        elif status_f == "Confirmed":
            rows = [t for t in rows if t['confirmed']]
        elif status_f == "Rejected":
            rows = [t for t in rows if t['rejected']]
        if query:
            rows = [t for t in rows if any(
                query in str(t.get(f, "")).lower()
                for f in ('asset_number', 'serial_number', 'asset_type',
                          'team_member', 'notes', 'direction', 'rejection_reason')
            )]

        # Day groups only make sense while the table is in timestamp order. A
        # sort by any other column scatters the dates, and a group header over
        # scattered dates is a lie about what follows it.
        self._fill_table(self.tree, rows,
                         grouped=self._sort_col in (None, "Time"))

        # RECENT is deliberately unfiltered: it is a receipt for what was just
        # submitted, not a second history view. /transactions comes back newest
        # first, but _sort_by mutates _all_rows in place, so sort it here.
        if hasattr(self, "recent"):
            recent = sorted(self._all_rows,
                            key=lambda t: str(t.get("timestamp", "")),
                            reverse=True)[:40]
            self._fill_recent(recent)

        count = len(rows)
        total = len(self._all_rows)
        self.row_count_lbl.config(
            text=f"{count} record{'s' if count != 1 else ''}"
                 + (f"  (filtered from {total})" if count != total else "")
        )

    @staticmethod
    def _day_label(ts):
        try:
            d = datetime.fromisoformat(ts).date()
        except Exception:
            return "Earlier"
        today = date.today()
        if d == today:
            return "Today"
        if (today - d).days == 1:
            return "Yesterday"
        # Not "%A %d %B": "Saturday 05 September" does not fit an Asset No.
        # column, and a Treeview group row cannot span columns.
        # Sentence case, like every other label on this window since #179: an
        # ALL-CAPS band is an eyebrow, and what this one carries is a date.
        return d.strftime("%a %d %b")

    def _fill_table(self, tree, rows, grouped):
        tree.delete(*tree.get_children())
        day = None
        for t in rows:
            ts = t.get('timestamp', '')
            if grouped:
                d = self._day_label(ts)
                if d != day:
                    day = d
                    wide = len(tree.ui_cols)
                    # **A band says how many** (#179), counted over the rows
                    # being drawn rather than over `_all_rows`, so it agrees
                    # with what is under it on a filtered table - and derived
                    # here rather than carried, a per-day total being a fact
                    # these rows already hold.
                    n = sum(1 for r in rows
                            if self._day_label(r.get('timestamp', '')) == d)
                    band = "%s   %d" % (d, n)
                    tree.insert("", "end", tags=("group",),
                                values=(band,) + ("",) * (wide - 1))
            if   t['confirmed']: status, tag = "\u2713 Confirmed", "confirmed"
            elif t['rejected']:  status, tag = "\u2715 Rejected",  "rejected"
            else:                status, tag = "\u25cf Pending",   "pending"
            if tag != "pending":
                status += origin_suffix(t)
            try:
                # Grouped by day already, so the date would only repeat itself.
                fmt = "%H:%M" if grouped else "%d/%m/%y  %H:%M"
                ts = datetime.fromisoformat(ts).strftime(fmt)
            except Exception:
                pass
            # The row's own id as the item id, so a selection can be turned
            # back into a Transaction. Day-group headers keep a generated one,
            # which is how _selected_row tells a header from a row.
            tid = t.get('id')
            kw = {} if tid is None else {"iid": str(tid)}
            # Keyed on the heading rather than written out in order, since
            # 166. Two tables were filled from here then and they did not state
            # the same columns, so a positional tuple would have had to be
            # sliced by whichever set the tree was built with - the shape that
            # writes serial numbers into the Asset Number column the day a
            # column moves. One table is filled from here now and the tree is
            # still asked what it is showing: a positional tuple written back
            # would be the same defect waiting for the next column to move.
            cells = {
                "Asset No.":        t.get('asset_number',  ''),
                "Serial No.":       t.get('serial_number', ''),
                "Model":            t.get('asset_model',   '') or "\u2014",
                "Type":             t.get('asset_type',    ''),
                "Member":           t.get('team_member',   ''),
                "Direction":        t.get('direction',     ''),
                "Status":           status,
                "Rejection Reason": t.get('rejection_reason', '') or '',
                "Time":             ts,
            }
            tree.insert("", "end", tags=(tag,), **kw,
                        values=tuple(cells[c] for c in tree.ui_cols))

    def _sort_by(self, col):
        col_map = {
            "Asset No.": "asset_number", "Serial No.": "serial_number",
            "Model": "asset_model", "Type": "asset_type",
            "Member": "team_member", "Direction": "direction",
            "Status": "confirmed", "Rejection Reason": "rejection_reason",
            "Time": "timestamp"
        }
        key = col_map.get(col, col)
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = False
        self._all_rows.sort(
            key=lambda x: str(x.get(key, "")),
            reverse=self._sort_rev
        )
        self._apply_filters()

    def _open_export(self):
        # The guard is here rather than in ExportDialog.__init__: the
        # decision has to be made before the window is built, and an
        # __init__ cannot abort cleanly (#191).
        if ui_kit.raise_open("export") is not None:
            return
        storekeeper_export.ExportDialog(self.root, self.server_url,
                                        self._members)

    def _open_settings(self):
        """Open settings — requires admin password, or nobody to ask.

        `verify_admin_password` is a POST, and the setting behind this door is
        the Server URL - the one whose wrongness is why the server cannot be
        reached. So a door that only a reachable server can open is the one
        thing standing between the storekeeper and the field that would fix it.
        Where the check could not be *made*, the settings window opens with the
        Server URL alone and says on itself that no password was checked. A
        wrong password never gets there: that is an answer, and only an
        unanswered check opens anything. Same rule as the Notifier's Admin
        Login, and the same wording - see common.offline_url_notice.
        """
        if ui_kit.raise_open("settings_auth") is not None:
            return
        auth = tk.Toplevel(self.root)
        ui_kit.single(auth, "settings_auth")
        auth.title("Admin Login")
        auth.configure(bg=BG)
        auth.resizable(True, False)
        auth.minsize(320, 205)
        auth.grab_set()
        ui_kit.escape_closes(auth)
        # No `-topmost` (#193). Only the confirm/reject popup is always on
        # top in this product, and that is what makes it mean something:
        # a window somebody opened is already in front of them, and one
        # pinned over every other app is one they cannot put down to go
        # and read what it is asking about.

        # Before the form and from the bottom. Written at 360x205 against a
        # 285x252 form, this window's Login button was 1px tall and never
        # mapped, and the height cannot be dragged. See ui_kit.fit.
        foot = tk.Frame(auth, bg=BG)
        foot.pack(side="bottom", fill="x")

        tk.Label(auth, text="🔐  Admin Authentication",
                 bg=BG, fg=TEXT,
                 font=font("section")).pack(pady=(16, 4), padx=20, anchor="w")
        tk.Label(auth, text="Admin password required to change settings.",
                 bg=BG, fg=SUBTEXT,
                 font=font("body")).pack(padx=20, anchor="w")

        frm = tk.Frame(auth, bg=CARD2, padx=20, pady=14)
        frm.pack(fill="x", padx=20, pady=10)
        tk.Label(frm, text="Password", bg=CARD2, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(0, 4))
        pw_var = tk.StringVar()
        pw_e = tk.Entry(frm, textvariable=pw_var, show="●",
                        bg=INPUT_BG, fg=TEXT, relief="flat",
                        font=font("label"), insertbackground=TEXT)
        pw_e.pack(fill="x", ipady=8)
        ui_kit.reveal(pw_e)
        pw_e.focus_set()

        err = tk.Label(auth, text="", bg=BG, fg=DANGER, font=font("body"))
        err.pack(pady=(0, 4))

        def verify():
            try:
                # The admin password only, through the admin-only door: the
                # settings behind this decide which server the whole store
                # talks to.
                good = verify_admin_password(self.server_url, pw_var.get())
            except Exception:
                # Not a refusal - nobody was asked. Only the server can say
                # whether this password is right, and the Server URL is the
                # likeliest reason it cannot say, so the field that fixes that
                # is opened rather than a dialog that can never be satisfied.
                log_event("settings.opened_offline",
                          "no password could be checked  ·  %s" % self.server_url,
                          level="warn", actor=sk_actor())
                auth.destroy()
                self._show_settings_window(url_only=True)
                return
            if good:
                auth.destroy()
                self._show_settings_window()
            else:
                err.config(text="❌  Wrong password.")

        pw_e.bind("<Return>", lambda _: verify())
        tk.Button(foot, text="Login",
                  bg=ACCENT, fg="white", font=font("heading"),
                  relief="flat", cursor="hand2", pady=9,
                  command=verify,
                  activebackground=ACCENT2).pack(fill="x", padx=20)
        ui_kit.fit(auth, 360)

    def _show_settings_window(self, url_only=False):
        """Settings window shown after admin authentication - or without one.

        `url_only` is what _open_settings opens when no password could be
        checked. The Server URL is the only setting on this window, so there is
        nothing here to disable the way the Notifier disables its other two -
        what the flag changes is that the window says nothing was verified, and
        that saving it is logged as such.
        """
        if ui_kit.raise_open("settings") is not None:
            return
        win = tk.Toplevel(self.root)
        ui_kit.single(win, "settings")
        win.title("Asset Server Settings")
        win.configure(bg=BG)
        win.resizable(True, False)
        win.minsize(360, 180)
        # No grab on the offline one: it opens with nobody checked and the
        # server can start answering again at any moment, and a modal window
        # over a store that is still recording movements is how a submission
        # stops being answerable.
        if not url_only:
            win.grab_set()
        ui_kit.escape_closes(win)

        # Before the form and from the bottom: written at 400x180 against a
        # 224x215 form, Save was drawn 11px of the 46 it asks for. See
        # ui_kit.fit.
        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x")

        tk.Label(win, text=("⚙  Asset Server Settings  (Server URL only)"
                            if url_only else "⚙  Asset Server Settings"),
                 bg=BG, fg=TEXT,
                 font=font("section")).pack(pady=14, padx=20, anchor="w")

        if url_only:
            # Its own lines rather than a wraplength: this window's width
            # drags, and a written-down wrap stops being the answer the moment
            # somebody widens it. fit() takes the width from the label instead.
            tk.Label(win, text=common.offline_url_notice(self.server_url),
                     bg=BG, fg=WARNING, justify="left",
                     font=font("body")).pack(padx=20, pady=(0, 10),
                                                anchor="w")

        frm = tk.Frame(win, bg=CARD2, padx=20, pady=14)
        frm.pack(fill="x", padx=20)
        tk.Label(frm, text="Server URL", bg=CARD2, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(0, 4))
        url_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=TEXT)
        url_e.insert(0, self.server_url)
        url_e.pack(fill="x", ipady=8)

        def save():
            new_url = url_e.get().strip().rstrip("/")
            was = self.cfg.get("server_url", "")
            self.server_url = new_url
            # Over the config that is already here rather than a fresh dict:
            # this window is about the Server URL and nothing else, and a dict
            # built from its one field would drop every key it is not about -
            # client_id, theme.
            self.cfg["server_url"] = new_url
            save_config(self.cfg)
            if url_only:
                log_event("settings.url_changed",
                          "%s -> %s  ·  no password was checked"
                          % (was, new_url), level="warn", actor=sk_actor())
            win.destroy()
            self._check_server()

        tk.Button(foot, text="Save", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  command=save, pady=9).pack(fill="x", padx=20, pady=12)
        ui_kit.fit(win, 400)

    def _check_server(self):
        if self._server_check_timer:
            self.root.after_cancel(self._server_check_timer)
            self._server_check_timer = None
        def _do():
            # Bound before the try: an unreachable server leaves the
            # heartbeat empty, and _note_health reads an empty one as keeping
            # whatever the last answer was.
            health = {}
            try:
                r = api("get", f"{self.server_url}/health")
                if r.ok:
                    health = r.json()
                    total = health.get('total', 0)
                    text, colour = f"Online  ·  {total} records", SUCCESS
                else:
                    text, colour = f"Server error {r.status_code}", WARNING
            except Exception as _e:
                text, colour = f"Offline: {type(_e).__name__}", DANGER
            # Tk is not thread-safe: work out the label here, apply it on the
            # main thread. The .config() calls this replaces ran on the worker,
            # and the one in the except clause meant a Tk failure inside the try
            # re-raised from inside its own handler.
            # _note_health as well as the label: this is the first
            # heartbeat of the run, and waiting for the 3s tick would offer
            # Cancel for three seconds on a server that forbids it.
            self.root.after(0, lambda: (self.status_lbl.config(text=text),
                                        self.status_dot.config(fg=colour),
                                        self._note_health(health)))
        threading.Thread(target=_do, daemon=True).start()
        self._server_check_timer = self.root.after(20_000, self._check_server)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = StorekeeperApp(root)
    root.mainloop()
    # mainloop returning is this app stopping, however it was closed - the
    # window, a Log Off command, or the process being asked to go. One last
    # ship, so a stop recorded here is not stranded until the next launch;
    # client.log has it whether that reaches the server or not.
    log_event("app.stopped", "StorekeeperApp %s" % APP_VERSION,
              actor=sk_actor())
    ship_log(app.server_url, app.cfg, save_config, "Storekeeper")
