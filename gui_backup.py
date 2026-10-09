"""Backup and Restore - a copy of this install, and putting one back.

Lifted out of server_gui.py by #235 (060). The smallest of the nine, and left
on its own rather than folded in beside Mail Settings: what it stands in
front of is ADR-0019, which is nothing the mail relay shares.

The seam back to ``server_gui.py`` - ``S`` read at call time, the
palette seeded by ``_bind_palette`` - is described once, in that module's own
docstring, under "The nine window modules".
"""

import ui_kit
from ui_kit import font

import server_gui


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


def backup_restore(root):
    """Take a backup of this install, or put one back (A13, ADR-0019).

    Reached from the System section, which asks for the admin password on
    every open (`_admin_again`, 090) rather than once a sitting: this window
    can replace the database, which is the largest blast
    radius on the console after Manage Transaction History, and neither is a
    window to open first and ask about afterwards. Not a capability either,
    for Mail Settings' reason - whoever can restore a backup can restore an
    `admin_config.json` carrying a password they chose.

    The work is `_take_backup` and `_restore_backup`, which take paths and
    touch no Tk, so every refusal here is reachable by a gate and this window
    is the part that asks and reports. **There is deliberately no endpoint**,
    the same call Add Transaction, Modify, the Client commands and the Lookup
    Sheet made.
    """
    from server_gui import S

    import tkinter as tk
    import tkinter.messagebox as mb
    from tkinter import filedialog

    if ui_kit.raise_open("backup_restore") is not None:
        return
    win = tk.Toplevel(root)
    ui_kit.single(win, "backup_restore")
    win.title("Backup / Restore")
    win.configure(bg=BG)
    win.resizable(False, False)
    win.transient(root)
    win.grab_set()

    hdr = tk.Frame(win, bg=ACCENT, height=44)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)
    tk.Label(hdr, text="💾  Backup / Restore", bg=ACCENT, fg="white",
             font=font("title")).pack(side="left", padx=14, pady=12)

    # Packed before the body and from the bottom, for the reason every dialog
    # here packs its buttons first.
    foot = tk.Frame(win, bg=BG)
    foot.pack(side="bottom", fill="x")

    tk.Label(win, text="A backup carries the database this server is "
                       "configured to open, its write-ahead files, the server "
                       "and admin configuration and the Lookup Sheet workbook, "
                       "with a digest of each. It is taken while the server "
                       "holds writes, which is what makes the copy worth "
                       "having; reads carry on, so nobody is stopped from "
                       "looking anything up while it runs.",
             bg=BG, fg=FAINT, font=font("micro"), wraplength=520,
             justify="left").pack(anchor="w", padx=18, pady=(10, 4))

    # Said on the window and not only in the manifest: the moment an Admin is
    # deciding whether this backup is enough to rebuild the machine from is
    # now, not after a restore that sends no mail.
    tk.Label(win, text="It does not carry the mail password or the Asset Sync "
                       "credential: both are encrypted to this machine and "
                       "cannot be decrypted on another, so they are set again "
                       "after a restore. Nor the server's private key, which "
                       "never leaves the machine it was made on.",
             bg=BG, fg=WARNING, font=font("micro"), wraplength=520,
             justify="left").pack(anchor="w", padx=18, pady=(0, 6))

    msg = tk.Label(win, text="", bg=BG, fg=SUBTEXT, font=font("body"),
                   wraplength=520, justify="left")
    msg.pack(anchor="w", padx=18, pady=(0, 8))

    def do_backup():
        where = filedialog.askdirectory(
            parent=win, title="Where should the backup be written?")
        if not where:
            return
        try:
            out, manifest = S._take_backup(where)
        except Exception as ex:
            msg.config(fg=DANGER, text="The backup was not taken: %s" % ex)
            return
        msg.config(fg=SUCCESS,
                   text="Backed up %d file(s) to %s"
                        % (len(manifest.get("files") or {}), out))

    def do_restore():
        where = filedialog.askdirectory(
            parent=win, title="Which backup should be restored?")
        if not where:
            return
        # Read and verified before the question is asked, so what an Admin is
        # asked to confirm is a restore that is actually going to happen - a
        # yes followed by "that backup is damaged" is a question that should
        # not have been put.
        try:
            manifest, checked = S._restore_preflight(where)
        except Exception as ex:
            msg.config(fg=DANGER, text="%s" % ex)
            return
        if not mb.askyesno(
                "Restore",
                "Replace this server's database and configuration with the "
                "backup taken on %s by %s?\n\n%d file(s) will be written. "
                "What they replace is copied into restore_aside\\ first.\n\n"
                "The mail password and the Asset Sync credential are not in a "
                "backup and will have to be set again."
                % (manifest.get("taken_at", "?"), manifest.get("taken_by", "?"),
                   len(checked)), parent=win):
            return
        try:
            aside, _m = S._restore_backup(where)
        except Exception as ex:
            msg.config(fg=DANGER, text="The restore did not finish: %s" % ex)
            return
        msg.config(fg=SUCCESS,
                   text="Restored %d file(s). What they replaced is in %s. "
                        "Restart the server so it opens the restored database."
                        % (len(checked), aside))
        mb.showinfo("Restore",
                    "Restart the Asset Server so it opens the restored "
                    "database, then set the mail password and the Asset Sync "
                    "credential again - neither travels in a backup.",
                    parent=win)

    ui_kit.escape_closes(win)
    bbox, _brow = ui_kit.row_of(
        foot,
        [("💾  Back up now", "💾  Back up", (BG, ACCENT, ACCENT2, "white"),
          do_backup),
         ("📥  Restore from a backup", "📥  Restore",
          (BG, CARD2, LINE, SUBTEXT), do_restore),
         ("Close", None, (BG, CARD2, LINE, SUBTEXT), win.destroy)],
        kind="footer")
    bbox.pack(fill="x", padx=18, pady=(0, 12))

    ui_kit.fit(win, 560)
    return win
