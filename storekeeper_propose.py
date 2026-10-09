"""The Storekeeper's Propose and Import dialogs - an asset the lookup sheet
does not hold, raised as a proposal one at a time or from a file.

Lifted out of storekeeper_app.py by #237 (062): the four methods behind the
form's "Add new asset" link and the Assets tab's Add New Asset and Import Asset
List buttons - ``_propose_dialog``, ``_read_import_file``,
``_import_proposals_dialog`` and ``_import_proposals_window``. The move is
verbatim apart from where a name is read from - the dialogs have the same
layout, the same wording, and send and log exactly what they did the line
before this file existed.

It cannot ``import storekeeper_app`` for the reason storekeeper_export.py gives
(source mode runs that file as ``__main__``), so it takes the same ``bind()``:
the palette seeded off the app's ``THEME`` and re-seeded after every swap, and
``S`` the running module, read for ``sk_actor`` and ``save_config``.

``ProposeDialogs`` takes the app itself, storekeeper_bulk.py's seam and for its
reason. The block reached five of the app's attributes - ``root``,
``server_url``, ``cfg``, ``asset_types`` and ``_show_propose`` - and reads them
as ``self.app.<name>`` rather than having them handed in, because
``server_url`` moves on a settings save and ``asset_types`` on a refresh: a
constructor that took them would take a snapshot.
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import common
import ui_kit
from common import api, log_event
# The faces never move with a theme - storekeeper_export.py's reason.
from ui_kit import font

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


class ProposeDialogs:
    """The Propose dialog and the Import window, for one app."""

    def __init__(self, app):
        self.app = app

    def _propose_dialog(self, asset_no="", serial=""):
        """Record an asset the lookup sheet does not hold, for the admin.

        It asks for exactly what an asset is - the two identifiers, a type and
        an optional model - because that is what the admin has to approve, and
        anything else asked here would be a field nobody reads. The type is
        editable rather than a closed list: new hardware arrives in a category
        this department has never bought before, and what stops a typo becoming
        an Asset Type every client offers is that an admin approves it (rule 2)
        rather than that this form would not let it be typed.

        **The offline path is a refusal, not a buffer.** A Transaction is
        buffered because the movement already happened and the record is owed;
        a proposal is a question, and a question nobody can answer yet is
        better asked when the server is back than queued to be asked in a state
        this app cannot see.
        """
        if ui_kit.raise_open("propose_asset") is not None:
            return
        dlg = tk.Toplevel(self.app.root)
        ui_kit.single(dlg, "propose_asset")
        dlg.title("Add New Asset")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(self.app.root)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        ui_kit.set_window_icon(dlg)

        hdr = tk.Frame(dlg, bg=ACCENT, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="\u2795  Add New Asset", bg=ACCENT, fg="white",
                 font=font("title")).pack(side="left", padx=14,
                                                     pady=12)
        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")

        frm = tk.Frame(dlg, bg=CARD, padx=18, pady=14)
        frm.pack(fill="both", expand=True, padx=16, pady=(12, 8))
        tk.Label(frm, text="This asset is not in the lookup sheet, so it "
                           "cannot be transacted yet. The admin sees this and "
                           "either adds it or says why not - either way the "
                           "answer comes back here.",
                 bg=CARD, fg=FAINT, font=font("micro"), wraplength=380,
                 justify="left").pack(anchor="w", pady=(0, 8))

        def field(label, value=""):
            tk.Label(frm, text=label, bg=CARD, fg=SUBTEXT,
                     font=font("body")).pack(anchor="w", pady=(6, 2))
            e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=font("value"), insertbackground=ACCENT)
            e.pack(fill="x", ipady=6)
            if value:
                e.insert(0, value)
            return e

        # Asset Number and Serial Number first, as they are everywhere here
        # (rule 4), prefilled with whatever the form was already asking about.
        an_e = field("Asset Number", asset_no)
        sn_e = field("Serial Number", serial)
        tk.Label(frm, text="Asset Type", bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(6, 2))
        at_v = tk.StringVar()
        at_cb = ttk.Combobox(frm, textvariable=at_v,
                             values=list(self.app.asset_types),
                             font=font("value"))
        at_cb.pack(fill="x")

        # Asset Model is the same widget as Asset Type, which is 026's answer
        # at the console reaching the door that is actually used by the person
        # holding the hardware. It was a bare Entry, which is how one laptop
        # came to be held as `ThinkPad T14`, `Thinkpad T14` and `T14`.
        #
        # **Editable**, for the reason Type is: a model nobody has bought
        # before has to be typeable somewhere, and what stops a typo becoming
        # a permanent model is that an Admin approves the proposal (ADR-0012),
        # not that the form would not let it be typed. It is **not** confirmed
        # with a question the way a new Type is - a Type changes what rule 2
        # serves every client, a model is filled into a Transaction that sent
        # none and reaches nothing else, so asking would be ceremony.
        tk.Label(frm, text="Asset Model", bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(6, 2))
        am_v = tk.StringVar()
        am_cb = ttk.Combobox(frm, textvariable=am_v, font=font("value"))
        am_cb.pack(fill="x")

        def refresh_models(live):
            """Offer the models this register holds for the Type now picked.

            `live` asks the server; otherwise the on-disk cache answers with
            no call at all. Synchronous when it does ask, with `common`'s 4s
            timeout, which is this app's existing idiom - the debounced
            lookup on the form behind this window is a blocking `GET` on the
            Tk thread too - and it is asked only on the two deliberate moments
            below rather than on every keystroke, because a call per keystroke
            in a window somebody is typing into is a frozen window.

            A Type with no model recorded against it offers **nothing** rather
            than everything, matching what the console does: a list narrowed
            to a Type is the whole point, and falling back to every model in
            the department would put Screens in front of somebody adding a
            Laptop.
            """
            want = at_v.get().strip()
            if live:
                models = common.fetch_asset_models(self.app.server_url, want)
            else:
                models = common.cached_asset_models(want)
            am_cb.config(values=list(models))

        # Two deliberate moments: the window opening, and a Type actually
        # being picked off the list. A Type somebody types by hand is either
        # one the cache already answers for or a new one this register has no
        # model for, which is the empty answer either way.
        at_cb.bind("<<ComboboxSelected>>", lambda _e: refresh_models(True))
        at_v.trace_add("write", lambda *_a: refresh_models(False))
        refresh_models(True)

        say = tk.Label(frm, text="", bg=CARD, fg=DANGER, font=font("body"),
                       wraplength=380, justify="left")
        say.pack(anchor="w", pady=(8, 0))

        def refuse(text):
            # The window was fitted with this label empty and cannot be
            # resized, so a refusal longer than a line was clipped to its first
            # (103). Fitted again to what it now says.
            say.config(text=text, fg=DANGER)
            ui_kit.fit(dlg, 430)

        def send():
            # No checks of its own: what an asset must carry is the server's to
            # say (rule 6, 103), and its sentence is what `refuse` shows.
            an, sn = an_e.get().strip(), sn_e.get().strip()
            at, am = at_v.get().strip(), am_v.get().strip()
            try:
                r = api("post", f"{self.app.server_url}/assets/propose",
                        json={"client_id": common.client_id(self.app.cfg,
                                                            S.save_config),
                              "asset_number": an, "serial_number": sn,
                              "asset_type": at, "asset_model": am,
                              "proposed_by": S.sk_actor()}, timeout=6)
            except Exception:
                # Refused, not buffered: see this method's docstring.
                refuse("\u2717  The server cannot be reached, so nothing was "
                       "proposed. A proposal is a question rather than a "
                       "record of something that happened, so it is not "
                       "queued - ask again when the server is back.")
                log_event("asset.propose_failed", f"{an or sn} - no server",
                          actor=S.sk_actor(), level="warn")
                return
            if not r.ok:
                # The server's own words. `duplicate_identifier` is the useful
                # refusal: that asset is in the sheet already and can be
                # transacted right now, which is what was actually wanted.
                body = {}
                try:
                    body = r.json() or {}
                except Exception:
                    pass
                refuse("\u2717  %s" % (body.get("error")
                                        or "The proposal was refused."))
                log_event("asset.propose_refused",
                          f"{an or sn} - {body.get('code') or r.status_code}",
                          actor=S.sk_actor(), level="warn")
                return
            pid = (r.json() or {}).get("proposal_id")
            log_event("asset.proposed", f"{an or sn} as {at} (proposal #{pid})",
                      actor=S.sk_actor(), level="warn")
            self.app._show_propose(False)
            dlg.destroy()
            messagebox.showinfo(
                "Proposed",
                f"\u2713  {an or sn} is waiting for the admin.\n\n"
                f"It is not an asset yet and still cannot be transacted. The "
                f"answer appears here when the admin has made it.",
                parent=self.app.root)

        tk.Button(foot, text="Send to the admin", bg=ACCENT, fg="white",
                  font=font("heading"), relief="flat", cursor="hand2",
                  pady=9, command=send,
                  activebackground=ACCENT2).pack(fill="x", padx=16,
                                                 pady=(6, 12))
        ui_kit.fit(dlg, 430)
        (an_e if not asset_no else sn_e).focus_set()

    def _read_import_file(self, path):
        """(headers, rows) out of an .xlsx or a .csv. Every cell a string.

        The one part of an import this app carries: it has the file and the
        server does not, and posting somebody else's workbook to an
        unauthenticated endpoint to be parsed is a worse thing to offer the
        network than a list of strings. It is a **mechanism** and not a rule -
        openpyxl, which this app already carries for its Excel export, and the
        stdlib `csv`. Every rule stays on the server, where 027's importer
        reads the same one: which column is which (`_map_import_columns`),
        whether a mapping can describe an asset (`_check_import_mapping`) and
        what each row would become (`_validate_import_rows`). A client carrying
        a copy of those is what rule 10 exists to prevent - it would drift into
        a file this door accepts and the admin's refuses.
        """
        if path.lower().endswith(".csv"):
            import csv
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = [r for r in csv.reader(f)]
        else:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            wb.close()
        rows = [[("" if c is None else str(c)).strip() for c in r]
                for r in rows]
        while rows and not any(c for c in rows[0]):
            rows.pop(0)
        if not rows:
            return [], []
        return rows[0], [r for r in rows[1:] if any(c for c in r)]

    def _import_proposals_dialog(self):
        """Pick a delivery's spreadsheet and propose every asset on it."""
        path = filedialog.askopenfilename(
            parent=self.app.root, title="Import Asset List",
            filetypes=[("Excel workbook or CSV", "*.xlsx *.csv"),
                       ("Excel workbook", "*.xlsx"),
                       ("CSV file", "*.csv")])
        if not path:
            return
        name = os.path.basename(path)
        try:
            headers, rows = self._read_import_file(path)
        except Exception as ex:
            messagebox.showerror("Import Asset List",
                                 f"{name} could not be read:\n\n{ex}",
                                 parent=self.app.root)
            return
        if not rows:
            messagebox.showerror("Import Asset List",
                                 f"{name} has no rows under its header row.",
                                 parent=self.app.root)
            return
        self._import_proposals_window(name, headers, rows)

    def _import_proposals_window(self, name, headers, rows):
        """Map the columns, see what each row would become, then send the lot.

        The same three stages the admin's Import Assets has, and deliberately
        the same order, because it is the same file arriving at a different
        door: **nothing is proposed until all three have passed.** What differs
        is what the last one writes - proposals rather than assets - and that
        every judgement in the first two is the server's. This app has the file
        and no way to judge it: the guess, the mapping check and the row
        verdicts all come back from `POST /assets/import/preview`, which writes
        nothing.

        **The batch is all or nothing**, which is `POST /assets/propose`'s
        rule and not this window's: a delivery half recorded is worse than one
        refused, because nothing says which half. So the refused rows are shown
        beside the good ones and the send is offered only while there are none.

        With no server the window still opens and says so, and **nothing is
        queued** - a proposal is a question (ADR-0012), and twenty questions
        queued into a state this app cannot see is twenty the storekeeper
        believes were asked.
        """
        NOT_HERE = "\u2014  not in this file  \u2014"
        choices  = [NOT_HERE] + ["%d \u00b7 %s" % (i + 1, h or "(unnamed column)")
                                 for i, h in enumerate(headers)]

        if ui_kit.raise_open("import_asset_list") is not None:
            return
        dlg = tk.Toplevel(self.app.root)
        ui_kit.single(dlg, "import_asset_list")
        dlg.title("Import Asset List")
        dlg.configure(bg=BG)
        dlg.transient(self.app.root)
        dlg.grab_set()
        ui_kit.escape_closes(dlg)
        ui_kit.set_window_icon(dlg)

        hdr = tk.Frame(dlg, bg=ACCENT, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="\U0001f4e5  Import Asset List  \u00b7  %s" % name,
                 bg=ACCENT, fg="white",
                 font=font("title")).pack(side="left", padx=14,
                                                     pady=12)
        foot = tk.Frame(dlg, bg=BG)
        foot.pack(side="bottom", fill="x")
        say = tk.Label(dlg, text="", bg=BG, fg=DANGER, font=font("body"),
                       wraplength=620, justify="left")
        say.pack(side="bottom", anchor="w", padx=18, pady=(0, 6))
        stage = tk.Frame(dlg, bg=BG)
        stage.pack(fill="both", expand=True)

        def clear():
            for w in list(stage.winfo_children()) + list(foot.winfo_children()):
                w.destroy()
            say.config(text="", fg=DANGER)

        def offline():
            # Refused, never buffered: see this method's docstring.
            say.config(text="\u2717  The server cannot be reached, so nothing "
                            "was proposed. A proposal is a question rather "
                            "than a record of something that happened, so it "
                            "is not queued - try again when the server is "
                            "back.", fg=DANGER)
            log_event("asset.propose_failed", f"{name} - no server",
                      actor=S.sk_actor(), level="warn")

        def preview(body):
            """Ask the server what this file is. None where nothing answered."""
            try:
                r = api("post", f"{self.app.server_url}/assets/import/preview",
                        json=body, timeout=10)
            except Exception:
                offline()
                return None
            try:
                answer = r.json() or {}
            except Exception:
                answer = {}
            if not r.ok:
                say.config(text="\u2717  %s" % (answer.get("error")
                                                or "The file was refused."),
                           fg=DANGER)
                return None
            return answer

        def map_stage(guess=None):
            """Which column is which, with the server's guess shown not used."""
            clear()
            if guess is None:
                answer = preview({"headers": headers})
                guess  = (answer or {}).get("mapping") or {}
            tk.Label(stage, text="%d row%s under %d column%s. Say which column "
                                 "is which - a guess is shown where the server "
                                 "could make one. An Asset Type and at least "
                                 "one identifier are what an asset needs, so "
                                 "those cannot be left unmapped."
                                 % (len(rows), "" if len(rows) == 1 else "s",
                                    len(headers),
                                    "" if len(headers) == 1 else "s"),
                     bg=BG, fg=FAINT, font=font("micro"), wraplength=620,
                     justify="left").pack(anchor="w", padx=18, pady=(10, 8))
            card = tk.Frame(stage, bg=CARD, padx=16, pady=12)
            card.pack(fill="x", padx=18)
            pick = {}
            for f, label in (("asset_number", "Asset Number"),
                             ("serial_number", "Serial Number"),
                             ("asset_type", "Asset Type"),
                             ("asset_model", "Asset Model")):
                i = guess.get(f)
                i = i if isinstance(i, int) and 0 <= i < len(headers) else None
                tk.Label(card, text=label + ("" if i is None
                                             else "   \u00b7 guessed"),
                         bg=CARD, fg=SUBTEXT,
                         font=font("body")).pack(anchor="w", pady=(6, 2))
                v = tk.StringVar(value=NOT_HERE if i is None
                                 else choices[i + 1])
                ttk.Combobox(card, textvariable=v, values=choices,
                             state="readonly",
                             font=font("value")).pack(fill="x")
                pick[f] = v

            def go():
                mapping = {}
                for f in pick:
                    chosen = pick[f].get()
                    mapping[f] = (None if chosen == NOT_HERE
                                  else choices.index(chosen) - 1)
                # The mapping is checked on the server, by the same function
                # the admin's importer calls - one file at two doors has to be
                # called one thing.
                answer = preview({"headers": headers, "rows": rows,
                                  "mapping": mapping})
                if answer is None:
                    return
                validate_stage(mapping, answer.get("verdicts") or [],
                               answer.get("warning") or "")

            tk.Button(foot, text="Check the rows  \u2192", bg=ACCENT,
                      fg="white", font=font("heading"), relief="flat",
                      cursor="hand2", pady=9, command=go,
                      activebackground=ACCENT2).pack(fill="x", padx=18,
                                                     pady=(10, 6))
            tk.Button(foot, text="Cancel", bg=CARD2, fg=SUBTEXT,
                      font=font("body"), relief="flat", cursor="hand2",
                      pady=6, command=dlg.destroy).pack(fill="x", padx=18,
                                                        pady=(0, 12))
            ui_kit.fit(dlg, 640)

        def validate_stage(mapping, verdicts, warning=""):
            """The server's whole answer, before anything is proposed."""
            clear()
            good = [v for v in verdicts if not v.get("error")]
            bad  = [v for v in verdicts if v.get("error")]
            tk.Label(stage, text="%d of %d row%s can be proposed.%s"
                                 % (len(good), len(verdicts),
                                    "" if len(verdicts) == 1 else "s",
                                    "" if not bad else
                                    "  A file is proposed whole or not at all, "
                                    "so the %d refused row%s have to be "
                                    "corrected first - half a delivery "
                                    "recorded is worse than none, because "
                                    "nothing says which half."
                                    % (len(bad),
                                       "" if len(bad) == 1 else "s")),
                     bg=BG, fg=FAINT, font=font("micro"), wraplength=620,
                     justify="left").pack(anchor="w", padx=18, pady=(10, 8))
            # A warning, not a refusal (#269): the server thinks the Asset
            # Number and Serial Number columns are swapped, from what their
            # values match in the register - shown, not blocking the propose.
            if warning:
                tk.Label(stage, text="⚠  " + warning, bg=BG, fg=WARNING,
                         font=font("micro"), wraplength=620,
                         justify="left").pack(anchor="w", padx=18,
                                              pady=(0, 8))
            vcols = ("line", "asset", "type", "verdict")
            vhead = {"line": "Row", "asset": "Asset", "type": "Asset Type",
                     "verdict": "What would happen"}
            vwide = {"line": 55, "asset": 190, "type": 110, "verdict": 430}
            vbody = tk.Frame(stage, bg=BG)
            vbody.pack(fill="both", expand=True, padx=18)
            vt = ttk.Treeview(vbody, columns=vcols, show="headings",
                              selectmode="browse", height=12)
            for c in vcols:
                vt.heading(c, text=vhead[c])
                vt.column(c, width=vwide[c], anchor="w")
            vsb = ttk.Scrollbar(vbody, orient="vertical", command=vt.yview)
            vt.configure(yscrollcommand=vsb.set)
            vt.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")
            vt.tag_configure("bad", foreground=DANGER)
            for v in verdicts:
                ident = " \u00b7 ".join(x for x in (v.get("asset_number"),
                                                    v.get("serial_number"))
                                        if x)
                vt.insert("", "end", values=(
                    v.get("line"), ident or "no identifier",
                    v.get("asset_type"),
                    v.get("error") or ("proposed as %s"
                                       % (v.get("asset_model")
                                          or "no model"))),
                    tags=("bad",) if v.get("error") else ())

            def send():
                if bad or not good:
                    say.config(text="\u2717  This file cannot be proposed as "
                                    "it stands. Correct the rows above and "
                                    "open it again.", fg=DANGER)
                    return
                try:
                    r = api("post", f"{self.app.server_url}/assets/propose",
                            json={"client_id": common.client_id(self.app.cfg,
                                                                S.save_config),
                                  "proposed_by": S.sk_actor(), "source": name,
                                  "rows": [{k: v.get(k, "") for k in
                                            ("asset_number", "serial_number",
                                             "asset_type", "asset_model")}
                                           for v in good]}, timeout=20)
                except Exception:
                    offline()
                    return
                body = {}
                try:
                    body = r.json() or {}
                except Exception:
                    pass
                if not r.ok:
                    # The server's own words, and where it refused the file row
                    # by row, the lines it named - this window showed the same
                    # rows a moment ago, so what changed is the register.
                    lines = body.get("refusals") or []
                    say.config(text="\u2717  %s%s"
                                    % (body.get("error")
                                       or "The file was refused.",
                                       "".join("\n   \u00b7 row %s: %s"
                                               % (x.get("line"), x.get("error"))
                                               for x in lines[:5])),
                               fg=DANGER)
                    log_event("asset.propose_refused",
                              f"{name} - {body.get('code') or r.status_code}",
                              actor=S.sk_actor(), level="warn")
                    return
                n = body.get("proposed") or len(good)
                log_event("asset.proposed",
                          f"{n} asset(s) from {name} (one batch)",
                          actor=S.sk_actor(), level="warn")
                dlg.destroy()
                messagebox.showinfo(
                    "Proposed",
                    f"\u2713  {n} asset{'' if n == 1 else 's'} from {name} "
                    f"{'is' if n == 1 else 'are'} waiting for the admin, as "
                    f"one delivery.\n\n"
                    f"{'It is' if n == 1 else 'They are'} not "
                    f"{'an asset' if n == 1 else 'assets'} yet and still "
                    f"cannot be transacted. The answer appears here when the "
                    f"admin has made it.",
                    parent=self.app.root)

            tk.Button(foot, text="Propose %d asset%s"
                             % (len(good), "" if len(good) == 1 else "s"),
                      bg=ACCENT if good and not bad else CARD2,
                      fg="white" if good and not bad else SUBTEXT,
                      font=font("heading"), relief="flat",
                      cursor="hand2", pady=9, command=send,
                      activebackground=ACCENT2).pack(fill="x", padx=18,
                                                     pady=(10, 6))
            tk.Button(foot, text="\u2190  Back to the columns", bg=CARD2,
                      fg=SUBTEXT, font=font("body"), relief="flat",
                      cursor="hand2", pady=6,
                      command=lambda: map_stage(mapping)).pack(fill="x",
                                                               padx=18,
                                                               pady=(0, 12))
            ui_kit.fit(dlg, 840)

        map_stage()
        return dlg

    # \u2500\u2500 the answers to what this installation proposed \u2500\u2500
