"""The Storekeeper's Bulk submit window - one engineer, one direction, many
assets, and nothing sent until Submit.

Lifted out of storekeeper_app.py by #236 (061): the seven methods behind the
Bulk submit link on the form, and ``_bulk_tags`` beside them, which existed for
nothing else. The move is verbatim apart from where a name is read from - the
window has the same layout, the same wording, and logs and buffers exactly what
it did the line before this file existed.

It cannot ``import storekeeper_app`` for the reason storekeeper_export.py gives
(source mode runs that file as ``__main__``), so it takes the same ``bind()``:
the palette seeded off the app's ``THEME`` and re-seeded after every swap, and
``S`` the running module, read for the two names that belong to it rather than
to an import - ``_sk_name``, which a heartbeat rebinds, and ``sk_actor``.

``BulkWindow`` takes the app itself. The block reached seven of its attributes
- ``root``, ``_members``, ``v_member``, ``v_direction``, ``server_url``,
``_buffer_add`` and ``_refresh_transactions`` - and reads them as
``self.app.<name>`` rather than having them handed in, because four of them
move under the window: ``server_url`` on a settings save, ``_members`` on a
refresh, and the form's two variables whenever the Storekeeper touches them. A
constructor that took them would take a snapshot. What the window builds, and
the queue, are its own; the app makes one ``BulkWindow`` at start-up and keeps
it, because the rows survive the window being closed and reopened.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import requests, threading
import ui_kit
from common import api, log_event, lookup_asset
# The faces never move with a theme - storekeeper_export.py's reason.
from ui_kit import font

Pill = ui_kit.Pill

S = None


def bind(storekeeper_module):
    """Give this module the running storekeeper_app.py, and the palette with it.

    Called once, at import, from storekeeper_app.py under its ``THEME`` - the
    same call, and for the same reasons, as ``storekeeper_export.bind``.
    """
    global S
    S = storekeeper_module
    _bind_palette()
    S.THEME.watch(_bind_palette)


def _bind_palette():
    """This module's colour names, out of the palette that is live."""
    g = globals()
    for name, colour in S.THEME.palette().items():
        g[name] = colour


def _bulk_tags(tree):
    """The Bulk submit list's two colours, and their hook - same reason as
    _tag_status: a tag is not a widget option."""
    tree.tag_configure("known", foreground=TEXT)
    tree.tag_configure("unknown", foreground=WARNING)
    # Re-seeded first: the retint walk runs this hook before THEME's
    # watchers, so without it TEXT would still be the colour being left.
    tree._retint_hook = lambda _rev, _new: (_bind_palette(),
                                            _bulk_tags(tree))
    return tree


# ─── Bulk submit ──────────────────────────────────────────────────────────────

class BulkWindow:
    """The Bulk submit window and the queue behind it, for one app."""

    def __init__(self, app):
        self.app = app
        self._bulk_queue = []     # rows scanned in the Bulk submit window

    def open(self):
        """Its own window, not a mode the main form switches into. The batch
        shares one engineer and one direction, which is the only reason it
        deserves a separate surface at all."""
        if ui_kit.raise_open("bulk_scan") is not None:
            # The one window in these apps that already had this rule written
            # out by hand, which is what #191 replaces (rule 10: a copy per
            # window is what that rule exists to prevent). What is kept is the
            # focus - the entry is where the next barcode goes.
            self._bulk_entry.focus_set()
            return
        win = tk.Toplevel(self.app.root, bg=BG)
        ui_kit.single(win, "bulk_scan")
        self._bulk_win = win
        win.title("Bulk submit")
        win.transient(self.app.root)
        w, h = 820, 620
        self.app.root.update_idletasks()
        win.geometry("%dx%d+%d+%d" % (
            w, h,
            max(0, self.app.root.winfo_rootx() + (self.app.root.winfo_width() - w) // 2),
            max(0, self.app.root.winfo_rooty() + (self.app.root.winfo_height() - h) // 3)))
        ui_kit.escape_closes(win)
        win.minsize(720, 540)

        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=24, pady=(20, 0))
        tk.Label(head, text="Bulk submit", bg=BG, fg=TEXT,
                 font=font("emph", size=15)).pack(anchor="w")
        tk.Label(head, text="One engineer, one direction, many assets. Nothing "
                            "is sent until Submit.",
                 bg=BG, fg=SUBTEXT, font=font("body")
                 ).pack(anchor="w", pady=(3, 0))

        card = tk.Frame(win, bg=CARD, highlightbackground=LINE,
                        highlightthickness=1)
        card.pack(fill="x", padx=24, pady=(16, 0))
        batch = tk.Frame(card, bg=CARD)
        batch.pack(fill="x", padx=16, pady=(14, 0))
        for label, values, width, attr, default in (
                ("ENGINEER", self.app._members, 20, "_bulk_member",
                 self.app.v_member.get() or (self.app._members[0] if self.app._members
                                         else "")),
                ("DIRECTION", ["Out Store", "In Store"], 12, "_bulk_direction",
                 self.app.v_direction.get())):
            col = tk.Frame(batch, bg=CARD)
            col.pack(side="left", anchor="n", padx=(0, 14))
            tk.Label(col, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("emph")).pack(anchor="w")
            cb = ttk.Combobox(col, values=values, state="readonly", width=width,
                              font=font("value"))
            cb.set(default)
            cb.pack(anchor="w", pady=(7, 0))
            setattr(self, attr, cb)
        tk.Label(batch, text="applies to every row below", bg=CARD, fg=FAINT,
                 font=font("body")).pack(side="left", anchor="n",
                                            pady=(26, 0))

        tk.Frame(card, bg=LINE, height=1).pack(fill="x", padx=16, pady=(14, 0))

        scan = tk.Frame(card, bg=CARD)
        scan.pack(fill="x", padx=16, pady=(14, 0))
        col = tk.Frame(scan, bg=CARD)
        col.pack(side="left", anchor="n")
        tk.Label(col, text="SCAN", bg=CARD, fg=SUBTEXT,
                 font=font("emph")).pack(anchor="w")
        self._bulk_entry = tk.Entry(col, bg=INPUT_BG, fg=MONO, width=26,
                                    font=font("code_lg", size=15), relief="flat", bd=0,
                                    insertbackground=ACCENT,
                                    highlightthickness=1,
                                    highlightbackground=LINE,
                                    highlightcolor=ACCENT)
        self._bulk_entry.pack(anchor="w", ipady=8, pady=(6, 0))
        self._bulk_entry.bind("<Return>", lambda _e: self._bulk_add_from_entry())
        Pill(scan, "Add  \u21b5", CARD, CARD2, LINE, fg=TEXT, w=96, h=44,
             bold=False, command=self._bulk_add_from_entry
             ).pack(side="left", anchor="n", padx=(12, 0), pady=(20, 0))
        self._bulk_scan_status = tk.Label(
            card, bg=CARD, fg=SUBTEXT, anchor="w", font=font("body"),
            text="Asset No. or Serial No. Enter adds it and clears the field.")
        self._bulk_scan_status.pack(fill="x", padx=17, pady=(11, 14))

        # The footer carries the primary action, so it reserves its space with
        # side="bottom" before the list expands into what is left. Packed after
        # the list, it fell off the bottom of the window.
        foot = tk.Frame(win, bg=BG)
        foot.pack(side="bottom", fill="x", padx=24, pady=(14, 20))
        # Grid rather than pack: the count is whatever width its text is and the
        # buttons want every pixel that leaves, which is a two-column layout
        # with the weight on the right - pack can only give the whole row to one
        # of them.
        foot.grid_columnconfigure(1, weight=1)
        left = tk.Frame(foot, bg=BG)
        left.grid(row=0, column=0, sticky="w")
        self._bulk_count_lbl = tk.Label(left, text="", bg=BG, fg=SUBTEXT,
                                        font=font("body"))
        self._bulk_count_lbl.pack(side="left")
        clear = tk.Label(left, text="Clear all", bg=BG, fg=SUBTEXT,
                         font=font("body"), cursor="hand2")
        clear.pack(side="left", padx=(14, 0))
        clear.bind("<Button-1>", lambda _e: self._bulk_clear_queue())
        box, self._bulk_foot = ui_kit.row_of(
            foot,
            [("Remove selected", "Remove", (BG, CARD2, LINE, SUBTEXT),
              self._bulk_remove_selected),
             ("Close", None, (BG, CARD2, LINE, SUBTEXT), win.destroy),
             ("Submit", None, (BG, ACCENT, ACCENT2, "white"),
              self._bulk_submit_all)],
            kind="footer", h=40)
        box.grid(row=0, column=1, sticky="ew", padx=(18, 0))
        self._btn_submit_all = self._bulk_foot.pills[-1]

        listwrap = tk.Frame(win, bg=CARD, highlightbackground=LINE,
                            highlightthickness=1)
        listwrap.pack(fill="both", expand=True, padx=24, pady=(16, 0))
        cols = (("Asset No.", 100), ("Serial No.", 150), ("Model", 190),
                ("Type", 100), ("Lookup", 140))
        self._bulk_tree = ttk.Treeview(listwrap, columns=[c for c, _ in cols],
                                       show="headings")
        for c, cw in cols:
            self._bulk_tree.heading(c, text=c, anchor="w")
            self._bulk_tree.column(c, width=cw, anchor="w", minwidth=50)
        _bulk_tags(self._bulk_tree)
        sb = ttk.Scrollbar(listwrap, orient="vertical",
                           command=self._bulk_tree.yview)
        self._bulk_tree.configure(yscrollcommand=sb.set)
        self._bulk_tree.pack(side="left", fill="both", expand=True,
                             padx=(1, 0), pady=1)
        sb.pack(side="right", fill="y")
        self._bulk_tree.bind("<Delete>", lambda _e: self._bulk_remove_selected())

        # Rows survive the window being closed and reopened - closing it is not
        # the same as discarding a batch half-way through scanning it.
        self._bulk_paint()
        self._bulk_entry.focus_set()

    def _bulk_add_from_entry(self):
        val = self._bulk_entry.get().strip()
        if not val:
            return
        self._bulk_entry.delete(0, "end")
        self._bulk_scan_status.config(text=f"\u2026 looking up {val}", fg=SUBTEXT)
        self._bulk_entry.focus_set()

        def fetch():
            try:
                r = lookup_asset(self.app.server_url, val, timeout=4)
                data = r.json() if r.ok else {"found": False}
            except Exception:
                data = {"found": False, "offline": True}
            self.app.root.after(0, lambda: self._bulk_got_lookup(val, data))
        threading.Thread(target=fetch, daemon=True).start()

    def _bulk_got_lookup(self, scanned, data):
        """Add the row either way. An asset the sheet does not know is kept and
        flagged rather than dropped at the door: the storekeeper can see what
        the scanner actually picked up, and _bulk_submit_all sends the known
        ones and reports the rest."""
        if data.get("found"):
            item = {"asset_number":  data.get("asset_number", "") or scanned,
                    "serial_number": data.get("serial_number", ""),
                    "asset_type":    data.get("asset_type", ""),
                    "asset_model":   data.get("asset_model", ""),
                    "scanned":       scanned,
                    "known":         True}
        else:
            item = {"asset_number": scanned, "serial_number": "",
                    "asset_type": "", "asset_model": "",
                    "scanned": scanned, "known": False}

        key = (item["asset_number"].lower(), item["serial_number"].lower())
        if any((q["asset_number"].lower(), q["serial_number"].lower()) == key
               for q in self._bulk_queue):
            self._bulk_scan_status.config(
                text=f"\u26a0  {scanned} is already in the list \u2014 skipped",
                fg=WARNING)
            return

        self._bulk_queue.append(item)
        if item["known"]:
            self._bulk_scan_status.config(
                text=f"\u2713  {scanned}  \u00b7  "
                     f"{item['asset_model'] or 'no model'}  \u00b7  "
                     f"{item['asset_type']}", fg=SUCCESS)
        elif data.get("offline"):
            self._bulk_scan_status.config(
                text=f"!  {scanned} could not be checked \u2014 the server is "
                     f"unreachable", fg=WARNING)
        else:
            self._bulk_scan_status.config(
                text=f"!  {scanned} is not in the lookup sheet \u2014 it will "
                     f"be reported, not submitted", fg=WARNING)
        self._bulk_paint()

    def _bulk_remove_selected(self):
        sel = self._bulk_tree.selection()
        if not sel:
            return
        # Highest index first: deleting from the front shifts every index after
        # it, and the tree row order is the queue order.
        for idx in sorted((self._bulk_tree.index(i) for i in sel), reverse=True):
            del self._bulk_queue[idx]
        self._bulk_paint()

    def _bulk_clear_queue(self):
        self._bulk_queue.clear()
        self._bulk_paint()

    def _bulk_paint(self):
        self._bulk_tree.delete(*self._bulk_tree.get_children())
        for it in self._bulk_queue:
            self._bulk_tree.insert(
                "", "end", tags=("known" if it["known"] else "unknown",),
                values=(it["asset_number"], it["serial_number"] or "\u2014",
                        it["asset_model"] or "\u2014",
                        it["asset_type"] or "\u2014",
                        "\u2713 in sheet" if it["known"] else "! not in sheet"))
        n = len(self._bulk_queue)
        unknown = sum(1 for it in self._bulk_queue if not it["known"])
        self._bulk_count_lbl.config(
            fg=SUBTEXT,
            text="nothing scanned yet" if not n else
                 f"{n} scanned" + (f", {unknown} not in the lookup sheet and "
                                   f"will be reported" if unknown else ""))
        # The count on the button is what will actually be sent, not the length
        # of the list - the unknown rows are not going anywhere.
        self._btn_submit_all.set_text("Submit" if n == unknown
                                      else f"Submit {n - unknown}")

    def _bulk_submit_all(self):
        """Send the rows the lookup sheet knows and report the rest. Anything
        not sent stays in the list, so the storekeeper can act on it.

        Each answer is written to the System Log as the **Transaction's** own
        entry, in `_submit`'s wording and at its levels, because that is what
        the entry is about: `_create_transaction` writes a row per asset and
        there is no batch in the `transactions` table to attribute a summary
        line to. This loop wrote none at all until #100 - so twenty assets
        scanned in one sitting were twenty rows on the server and nothing in
        either half of this installation's log, and the path that carries the
        volume was the invisible one. The refusals are the half that cost an
        Admin something: a bulk row the server turned down is a message box
        that is dismissed and gone, and `transaction.refused` is the only
        durable record that it was ever attempted.

        A row the server never answered goes into `pending_buffer.json`, the
        same answer `_submit` gives the same situation and for the same reason:
        the movement already happened and the record is owed. It was kept in
        `self._bulk_queue` alone until #95 - a plain list on this object that
        nothing ever writes anywhere - so forty assets scanned against a server
        that is not there were forty movements held in RAM, reported as "still
        in the list", and gone the moment the app was closed, with no file to
        flush and nothing to say they had ever been owed. The row leaves the
        queue with them, so a second click cannot send it twice.

        **This is not the proposals' answer and must not be confused with it.**
        A proposal is refused rather than queued because it is a question, and a
        queued question is one the storekeeper believes was asked (ADR-0012).

        The exception class is deliberately left at `ConnectionError`: widening
        it to `Timeout` is the question #94 scoped out of the submit leg and it
        is the same question here, a `ReadTimeout` on a POST leaving the write's
        outcome unknown where the duplicate-pending guard only absorbs a resend
        while the row is still pending.
        """
        if not self._bulk_queue:
            self._bulk_count_lbl.config(text="nothing scanned yet", fg=WARNING)
            return
        member = self._bulk_member.get()
        direc  = self._bulk_direction.get()
        if not member:
            messagebox.showerror("Missing", "Select an engineer first.",
                                 parent=self._bulk_win)
            return

        sent, keep, dupes, failed, offline = [], [], [], [], []
        for item in self._bulk_queue:
            label = item["asset_number"] or item["serial_number"]
            if not item["known"]:
                keep.append(item)
                continue
            payload = {
                "asset_number":  item["asset_number"],
                "serial_number": item["serial_number"],
                "asset_type":    item["asset_type"],
                "asset_model":   item.get("asset_model", ""),
                "team_member":   member,
                "direction":     direc,
                "notes":         "",
                "storekeeper":   S._sk_name,
            }
            try:
                r = api("post", f"{self.app.server_url}/transactions", json=payload)
                if r.status_code == 201:
                    log_event("transaction.submitted",
                              "%s  %s  %s" % (label, member, direc),
                              actor=S.sk_actor())
                    sent.append(label)
                    continue
                try:
                    body = r.json() or {}
                except Exception:
                    body = {}
                code = body.get("code")
                if r.status_code == 409:
                    # Deliberately not logged, because _submit does not log one
                    # either: a 409 says this movement is already recorded, and
                    # the offline buffer's flush treats that answer as done for
                    # the same reason. An entry here would be a shape the form's
                    # own path never writes.
                    dupes.append(label)
                else:
                    # Every other answer is a refusal the server made, which is
                    # what _submit's else branch writes and at the same level.
                    log_event("transaction.refused",
                              "%s  %s" % (label,
                                          body.get("error", r.status_code)),
                              level="warn", actor=S.sk_actor())
                    if r.status_code == 400 and code == "not_in_lookup":
                        # The sheet can be replaced between the scan and the
                        # submit, and the server is what enforces the rule
                        # (project rule 6). Flip the flag so the row reads
                        # honestly on the way back.
                        item["known"] = False
                        item["asset_type"] = item["asset_model"] = ""
                    else:
                        failed.append(f"{label} ({r.status_code})")
            except requests.exceptions.ConnectionError:
                # Owed, so it is written down rather than held in a list this
                # app never saves. _buffer_add writes the System Log entry, for
                # this caller as for the other one. The row does not go back in
                # the queue: it is queued somewhere that survives the app now,
                # and a second click must not send it twice.
                self.app._buffer_add(payload)
                offline.append(label)
                continue
            except Exception as e:
                failed.append(f"{label} ({type(e).__name__})")
            keep.append(item)

        self._bulk_queue = keep
        self._bulk_paint()

        unknown = [i["scanned"] for i in keep if not i["known"]]
        icon  = "\U0001f534" if direc == "Out Store" else "\U0001f7e2"
        lines = [f"{icon}  {len(sent)} submitted to {member.split()[0]} "
                 f"({direc})." if sent
                 else "Nothing was submitted."]

        def block(title, items):
            if not items:
                return
            shown = ", ".join(items[:8])
            more  = f"  (+{len(items) - 8} more)" if len(items) > 8 else ""
            lines.append(f"\n{title} ({len(items)}):\n{shown}{more}")

        block("Not in the lookup sheet \u2014 still in the list", unknown)
        block("Already had a pending transaction", dupes)
        block("Server unreachable \u2014 saved offline, will be sent when it "
              "is back", offline)
        block("Failed", failed)

        leftover = unknown or dupes or offline or failed
        show = messagebox.showwarning if leftover else messagebox.showinfo
        show("Bulk submit", "\n".join(lines), parent=self._bulk_win)
        self.app._refresh_transactions()
