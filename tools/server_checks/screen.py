r"""The console's four windows taller than a 768px screen, and the recorder
that judges them (095).

`stage.py` wraps the staged `ui_kit.fit` and judges every window at the call:
one asking more than 688px that does not scroll is a failure there and then,
whichever group opened it. This group is what keeps that from quietly
stopping - it opens the four console windows that were over the line when
the recorder went in and asserts the recorder saw each of them by title. A
recorder that measured nothing would otherwise pass by finding nothing.
"""
from server_checks.console import open_section_entry
from server_checks.stage import (FIT_SEEN, GM, M, bad, eq, fresh_db, gui_root,
                                 head, ok, tk_or_skip, widgets)


def check_the_windows_taller_than_the_screen_are_measured():
    """Asset Sync, Server Settings, Mail Settings and Add Transaction, by title.

    Add Transaction is opened off the Transactions section the way a person
    opens it, being a function nested inside `run_gui`; the other three are
    module functions and are called - Server Settings off `server_gui`,
    which is the one of the three `server.py` does not re-export.
    """
    head("the windows taller than the screen are measured (095)")
    tk = tk_or_skip()
    if tk is None:
        return

    fresh_db()
    root = gui_root(tk)
    openers = [
        ("Asset Sync", lambda: M.asset_sync(root)),
        ("Server Settings", lambda: GM.server_settings(root)),
        ("Mail Settings", lambda: M.mail_settings(root)),
        ("Add Transaction", lambda: open_section_entry(
            tk, root, "Transactions", "Add Transaction")),
    ]
    for title, opener in openers:
        FIT_SEEN.pop(title, None)
        before = {str(w) for w in widgets(root) if isinstance(w, tk.Toplevel)}
        try:
            opener()
            root.update_idletasks()
            root.update()
        except Exception as e:
            bad("%s did not open: %s" % (title, e))
        eq("the recorder saw %s" % title, title in FIT_SEEN, True)
        for w in widgets(root):
            if isinstance(w, tk.Toplevel) and str(w) not in before:
                try:
                    w.destroy()
                except Exception:
                    pass
        root.update_idletasks()
    try:
        root.destroy()
    except Exception:
        pass
    ok("four windows opened against the recorder")
