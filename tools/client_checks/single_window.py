r"""A client window opened twice is one window (#191), and the pair of
calls that guards it.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
from client_checks.stage import (NT, SK, SRC, bad, close, eq, head, ok, opened,
                                 quiesce, tk_or_skip, widgets)


def _opened_again(tk, root, opener):
    """Open it a second time and hand back whatever that built.

    `opened` above reports an opener that built nothing as a failure, which is
    exactly the answer wanted here, so this is the same walk with no verdict
    attached to it.
    """
    before = {str(w) for w in widgets(root) if isinstance(w, tk.Toplevel)}
    opener()
    root.update_idletasks()
    root.update()
    return [w for w in widgets(root)
            if isinstance(w, tk.Toplevel) and str(w) not in before]


def _one_window(tk, ui_kit, root, label, key, opener):
    """Three questions about one opener, in the order they can be asked."""
    first = opened(tk, root, label, opener)
    if len(first) != 1:
        bad("%s opened %d windows the first time" % (label, len(first)))
        close(root, first)
        return
    win = first[0]
    again = _opened_again(tk, root, opener)
    if again:
        bad("%s opened a second window over the first - there are now %d of it"
            % (label, len(again) + 1))
    elif ui_kit._OPEN_WINDOWS.get(key) is not win:
        bad("%s is not the window registered under %r" % (label, key))
    else:
        ok("%s asked for twice is one window, raised rather than rebuilt"
           % label)
    close(root, [win] + again)
    third = opened(tk, root, label, opener)
    if len(third) != 1:
        bad("%s did not open again after it was closed - the key outlived the "
            "window" % label)
    else:
        ok("%s opens again once it has been closed" % label)
    close(root, third)


def check_a_client_window_opened_twice_is_one_window():
    """Every window these two apps open is one window (#191).

    Nothing stopped a second copy. The Storekeeper's toolbar and both tables
    stay clickable behind every dialog it opens, and the Notifier is a tray
    menu, which is reachable whatever is already on screen - so Change My
    Password twice is two forms, and the tray's Settings is a second Admin
    Login over the first. What that costs is two windows editing one
    `config.json` with the last save winning, and two Export dialogs asking
    one server for the same workbook.

    Bulk Scan is the one window in these apps that already had this rule
    written out by hand, which is what the guard replaces (rule 10).

    Three things per opener, and the third is the one a guard gets wrong: it
    has to open again once it has been closed. A key left behind by a window
    that is gone is a control that works once per process.

    Driven rather than read, because what is asserted is that the second
    request produced no widget and that the window standing under the key is
    the one already open: a source read sees the call and not the answer. The
    source half is the group below, for the openers this file cannot press.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("a client window opened twice is one window")
    tk = tk_or_skip()
    if tk is None:
        return
    import ui_kit

    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = SK.StorekeeperApp(root)
    root.update_idletasks()
    root.update()
    for label, key, opener in [
            ("Export to Excel", "export", app._open_export),
            ("Add Engineer", "add_engineer", app._add_engineer_dialog),
            ("Add New Asset", "propose_asset", app._propose._propose_dialog),
            # Opened past its file picker, the way the measurement group
            # opens it: the window is handed the rows a delivery note holds.
            ("Import Asset List", "import_asset_list",
             lambda: app._propose._import_proposals_window(
                 "delivery.csv",
                 ["Asset No", "Serial Number", "Type", "Model"],
                 [["F-1", "FS-1", "Laptop", "T14"]])),
            ("Bulk Scan", "bulk_scan", app._bulk.open),
            ("Admin Login", "settings_auth", app._open_settings),
            ("Server Settings", "settings", app._show_settings_window)]:
        _one_window(tk, ui_kit, root, label, key, opener)
    quiesce(root)

    # The Notifier's are tray entries, and each marshals onto the Tk thread
    # with after(0) - so the window is built inside the update() `opened`
    # already does rather than inside the call itself.
    NT.fetch_permissions = lambda *a, **k: []
    napp = NT.NotifierApp()
    nroot = napp.root
    nroot.deiconify()
    nroot.geometry("320x140+0+0")
    nroot.update_idletasks()
    nroot.update()
    for label, key, opener in [
            ("the Dashboard", "dashboard", napp._open_dashboard),
            ("Change My Password", "own_password", napp._change_password),
            ("Remote Admin", "remote_admin", napp._remote_admin),
            ("Notifier Settings", "settings", napp._open_settings),
            ("the logon window", "setup_wizard", napp._show_setup_wizard)]:
        _one_window(tk, ui_kit, nroot, label, key, opener)
    quiesce(nroot)


def check_every_guarded_client_window_takes_the_pair():
    """The guard is a pair, and both halves are in the app that opens it.

    Source, because what is asserted is that no key is half-guarded: a
    `single` with no `raise_open` in front of it registers a window nothing
    ever asks about, and a `raise_open` with no `single` behind it answers
    None for ever - both of which look exactly like a guarded window from
    outside, the second until somebody opens it twice.

    The two halves are not always in one function, and deliberately: the
    decision has to be made before `tk.Toplevel` is called and an `__init__`
    cannot abort cleanly, so a class-based window takes the `raise_open` at
    its construction site and keeps the registration inside itself. So this
    matches them by **key** across the file rather than by function, and
    counts them, so a key added with one half cannot pass by looking like
    another key's.

    The Storekeeper's Cancel Transaction is keyed on the row it retracts
    rather than on a literal - a second row is a second window, which is what
    keying on what a window is about buys - so its two halves are matched on
    the expression they share.

    "The app that opens it" is an app and not a file. Since #218 the
    Notifier is two and since #219 the Storekeeper is, and the split runs
    straight through this pair in both: the tray menu kept the `raise_open`
    and `RemoteAdminWindow` took the `single` inside itself into
    notifier_remote.py, and `_open_export` kept the `raise_open` while
    `ExportDialog` took the `single` into storekeeper_export.py. Matching by
    key within one file would report *both* halves of remote_admin and of
    export missing while the guard is intact, so an app is read as the text
    of its files together. Since #236 the Storekeeper is three, and there
    both halves of bulk_scan went to storekeeper_bulk.py together; since
    #237 it is four, and propose_asset and import_asset_list went to
    storekeeper_propose.py the same way.
    """
    head("every guarded client window takes the raise_open/single pair")
    per_row = 'cancel_transaction:%s" % t.get("id")'
    for names, keys in (
            (("storekeeper_app.py", "storekeeper_export.py",
              "storekeeper_bulk.py", "storekeeper_propose.py"),
             ["export", "add_engineer", "propose_asset", "import_asset_list",
              "bulk_scan", "settings_auth", "settings"]),
            (("notifier_app.py", "notifier_remote.py"),
             ["dashboard", "own_password", "remote_admin",
              "remote_notify_rules", "settings", "setup_wizard"])):
        name = " + ".join(names)
        src = "\n".join(SRC[n] for n in names)
        for key in keys + ([per_row] if name.startswith("store") else []):
            asked = 'ui_kit.raise_open("%s' % key in src
            kept = 'ui_kit.single(' in src and ', "%s' % key in src
            if not asked:
                bad("%s: nothing asks whether %s is already open" % (name, key))
            elif not kept:
                bad("%s: nothing registers the window opened under %s"
                    % (name, key))
            else:
                ok("%s: %s asks before it builds and registers what it built"
                   % (name, key))
        eq("%s pairs every raise_open with a single" % name,
           src.count("ui_kit.raise_open("), src.count("ui_kit.single("))
