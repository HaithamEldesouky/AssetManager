"""Server Settings - host, port, and the certificate clients pin.

Lifted out of server_gui.py by #235 (060). One subject in one window: the
address this server answers on and the certificate it answers with, the
staging and cut-over behind it being ``server_cert.py``'s (ADR-0020).

The seam back to ``server_gui.py`` - ``S`` read at call time, the
palette seeded by ``_bind_palette`` - is described once, in that module's own
docstring, under "The nine window modules".
"""

import os
import socket
import sys
import threading

import ui_kit
from ui_kit import Pill, font
from server_cert import (CERT_ERROR_DAYS, CERT_WARN_DAYS, _cert_expiry,
                         _cert_fingerprint, _cert_to_pem,
                         _clients_behind_staged, _cut_over_cert,
                         _export_public_cert, _stage_new_cert)

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


def _port_locked():
    """Is the process actually bound to the port unable to move it?

    This window runs in the console's own process - interactive GUI mode,
    one of `server.py`'s three, and not the one HttpPlatformHandler starts
    (#267). `S._is_iis_served()` would answer for *this* process's
    environment, which never carries HTTP_PLATFORM_PORT, so it always says
    no even when the process actually listening on `S.PORT` cannot move it.
    This asks that process instead, over the loopback GET /health already
    carries `port_locked` for - the same probe `refresh_stats` in
    server_gui.py already makes of /stats, for the same reason: a
    self-signed certificate proves nothing to a client that phones home to
    itself.

    Unreachable answers False - saving then meets whatever /admin's own
    refusal says, the pre-#267 outcome, rather than blocking a save this
    window failed to ask about.
    """
    import ssl as _ssl
    from server_gui import _loopback_get
    try:
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        try:
            body = _loopback_get("/health", ctx)
        except Exception:
            body = _loopback_get("/health")
        if body is not None:
            return bool(body.get("port_locked"))
    except Exception:
        pass
    return False


def server_settings(root):
    """Host, port and the certificate clients pin - one subject, one window.

    `change_host_port` and `upload_ssl_cert` were two entries on a row
    measured at six full labels, asking about the same question: how
    this server is reached (#125). Merged into one window rather than
    left as neighbours - host and port above, the certificate below -
    the way Server Administration folded four passworded actions into
    one door. Both halves keep everything they carried apart: the IIS
    branch says that saving a new port moves the site binding and how
    (069, ADR-0021) - it warned that the save was only what this window
    probes for and sent the Admin to run tools\\install-iis.ps1 by hand
    until there was an elevated half to spawn - and the certificate
    half still reads ssl_cert.pem beside
    the server rather than whatever IIS has bound - those stop being the
    same file the moment a binding moves on, and the question the
    fingerprint answers is what a Client would be handed.

    Top-level, like `manage_records` beside it, rather than nested in
    `run_gui`: `upload_ssl_cert` always was, and `_cert_fingerprint`'s
    only callers are this window and the two actions nested inside it -
    a fact `server-checks.py` holds by walking every enclosing function,
    which would otherwise also name `run_gui` for every dialog it
    encloses.

    Behind the admin password at the door: the Server Settings entry
    asks `_admin_again` on every open (096), Backup / Restore's shape,
    and nothing in here - Cut Over included - asks again. It took a
    password of its own, and accepted a capability password for it,
    until the console became one door with the admin password on it
    (ADR-0015).
    """
    from server_gui import S

    import tkinter as tk
    import tkinter.messagebox as mb
    import tkinter.filedialog as fd
    _iis = S._iis_host()
    if ui_kit.raise_open("server_settings") is not None:
        return
    dlg = tk.Toplevel(root)
    ui_kit.single(dlg, "server_settings")
    dlg.title("Server Settings")
    dlg.configure(bg=BG)
    dlg.resizable(False, False)
    dlg.grab_set()
    ui_kit.escape_closes(dlg)
    dlg.transient(root)

    hdr2 = tk.Frame(dlg, bg=ACCENT, height=44)
    hdr2.pack(fill="x")
    hdr2.pack_propagate(False)
    tk.Label(hdr2, text="🌐  Server Settings",
             bg=ACCENT, fg="white",
             font=font("title")).pack(side="left", padx=14, pady=12)

    # Packed before the form so pack serves it first: a shortfall goes to
    # whichever child was packed last, and these two certificate buttons are
    # what the bottom of this window is for - the same rule the other twelve
    # dialogs in this file keep.
    btn_frm = tk.Frame(dlg, bg=BG)
    btn_frm.pack(side="bottom", fill="x", padx=18, pady=(6, 12))

    # The form scrolls (095): at 943px it is taller than the 688px a 768px
    # screen leaves once `fit` has clamped it, and pack gives the shortfall to
    # whatever it served last. The footer above is outside the region and was
    # packed before it, so it stays on the screen however short that is.
    scroll = ui_kit.ScrollRegion(dlg, BG)
    body = scroll.body
    scroll.pack(padx=0, pady=0)

    # ── Host / Port ──
    frm2 = tk.Frame(body, bg=CARD, padx=20, pady=14)
    frm2.pack(fill="x", padx=18, pady=(14, 0))

    def cfg_field(label, default_val):
        tk.Label(frm2, text=label, bg=CARD, fg=SUBTEXT,
                 font=font("body")).pack(anchor="w", pady=(6, 2))
        e = tk.Entry(frm2, bg=INPUT_BG, fg=TEXT, relief="flat",
                     font=font("value"), insertbackground=TEXT)
        e.insert(0, str(default_val))
        e.pack(fill="x", ipady=7)
        return e

    host_e = cfg_field("Bind Host  (0.0.0.0 = all interfaces)", S.HOST)
    port_e = cfg_field("Port", S.PORT)
    # Under IIS the port served is the site binding, so a restart applies
    # nothing: what Save does there is write the number down and then ask
    # Windows to elevate the half that can move the binding (069). Still a
    # warning rather than a caption, because the move takes the old port
    # away at the end of a grace window, and a client switched off through
    # that window has to be corrected by hand.
    #
    # This is three wrapped lines where the other branch is one, and the
    # window no longer carries a written size to lose them against - it
    # asks ui_kit.fit for its size instead, at the bottom of this
    # function, once the certificate form below has been packed too.
    # server-checks.py opens this window both ways.
    tk.Label(body,
             text=("⚠  IIS serves the port: it is the site binding. "
                   "Saving a new one asks Windows to elevate "
                   "tools\\bind-port.ps1, which binds it beside the old "
                   "port, waits while every online client records it, "
                   "then takes the old one away." if _iis is not None else
                   "⚠  Restart the server after saving for changes "
                   "to take effect."),
             bg=BG, fg=WARNING, font=font("micro"),
             wraplength=360).pack(pady=(6, 2))
    err2 = tk.Label(body, text="", bg=BG, fg=DANGER, font=font("body"))
    err2.pack()

    def do_save_cfg():
        h = host_e.get().strip()
        p = port_e.get().strip()
        if not h:
            err2.config(text="✗  Host cannot be empty.")
            return
        p_int, perr = S._validate_port(p)
        if perr:
            err2.config(text="✗  " + perr)
            return
        old_port = S.PORT
        if p_int != old_port and _port_locked():
            err2.config(text="✗  The port cannot be changed: IIS is serving "
                             "this process through HttpPlatformHandler but "
                             "install-iis.ps1 never ran, so no site is on "
                             "record to move. Run install-iis.ps1, or change "
                             "the binding directly in IIS Manager.")
            return
        S._save_server_cfg(host=h, port=p_int,
                         _actor="Admin (Server GUI)")
        dlg.destroy()
        if _iis is None:
            mb.showinfo("Saved", "✓  Server config saved.\nRestart the server to apply.")
            return
        if p_int == old_port:
            mb.showinfo("Saved",
                        "✓  Server config saved.\n\n"
                        "The port is unchanged, so there is no binding to "
                        "move. IIS serves the port, so restarting this "
                        "process applies nothing.")
            return
        # Written **before** the spawn, for the reason _cut_over_cert's
        # docstring gives about its own entry: what follows is an app pool
        # restart, and an entry written after one goes missing. It names
        # both ports because months later the question asked of this row is
        # which port this install was on and what it moved to.
        S._log_event("server.port_moved", "%d  ->  %d" % (old_port, p_int),
                     actor="Admin (Server GUI)", level="warn",
                     data={"from": old_port, "to": p_int,
                           "site": _iis.get("site") or ""})
        # Spawned rather than run in process, the way the certificate
        # cutover spawns: under IIS this process is the app pool identity
        # and cannot touch a binding, a firewall rule or an app pool.
        # `runas` is what raises the UAC prompt, and a refusal is an
        # ordinary answer here rather than a failure - the number is
        # already saved, so what is owed is the exact command rather than
        # an apology. It is the command _bind_port_command built, so what
        # is printed and what would have run are one string.
        cmd = S._bind_port_command(p_int)
        try:
            import ctypes
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", cmd[0],
                " ".join('"%s"' % a for a in cmd[1:]), None, 1)
            if rc <= 32:
                raise OSError("elevation was refused (%d)" % rc)
            moved = ("Windows is being asked to elevate the script that "
                     "moves the binding from %d to %d. It binds the new "
                     "port beside the old one, waits while every online "
                     "client records it, and only then takes the old one "
                     "away." % (old_port, p_int))
        except Exception as ex:
            moved = ("The binding has NOT moved (%s), so this server is "
                     "still served on %d. Run this elevated:\n\n%s"
                     % (ex, old_port, " ".join(cmd)))
        mb.showinfo("Saved", "✓  Server config saved.\n\n" + moved)

    # "restart to apply" is not true under IIS, where what this button does
    # is move the site binding (069). The caption says which of the two it
    # is and the label above it says what that costs - a caption is not the
    # place for the grace window.
    tk.Button(body, text="Save  (moves the IIS binding)" if _iis is not None
                        else "Save  (restart to apply)",
              bg=ACCENT, fg="white", font=font("heading"),
              relief="flat", cursor="hand2", pady=9,
              command=do_save_cfg,
              activebackground=ACCENT2).pack(fill="x", padx=18, pady=(4, 0))

    tk.Frame(body, bg=LINE, height=1).pack(fill="x", padx=18, pady=(14, 0))

    # ── SSL Certificate ──
    tk.Label(body, text="🔒  SSL Certificate", bg=BG, fg=TEXT,
             font=font("heading")).pack(anchor="w", padx=18,
                                                 pady=(12, 0))

    # Who is terminating TLS - _ssl_active in run_gui, for its reason: under
    # IIS nothing writes ssl_enabled, and under -PfxPath or -CertThumbprint
    # ssl_cert.pem may rightly not be on the machine (#280). Off IIS the
    # expression is exactly what it was.
    _cert_ok = os.path.exists(S.SSL_CERT_PATH)
    if _iis is not None:
        _ssl_on = bool(S._iis_tls_bound())
    else:
        _ssl_on = bool(S._SERVER_CFG.get('ssl_enabled', False) and _cert_ok)
    _status  = "Active (HTTPS)" if _ssl_on else "Inactive (HTTP)"
    _s_color = SUCCESS if _ssl_on else DANGER

    sf = tk.Frame(body, bg=CARD, padx=16, pady=10)
    sf.pack(fill="x", padx=18, pady=(6, 0))
    tk.Label(sf, text=f"Status:  {_status}", bg=CARD, fg=_s_color,
             font=font("heading")).pack(anchor="w")
    if _cert_ok:
        tk.Label(sf, text=S.SSL_CERT_PATH, bg=CARD, fg=SUBTEXT,
                 font=font("micro"), wraplength=380).pack(anchor="w", pady=(2, 0))
        # What a Client is handed, in the form it can be checked in.
        # Nothing else in this product answers "is the certificate this
        # Client pinned the one I am serving?". It asks for no password
        # for the reason Display Settings does not: this is a console
        # display of a file that GET /cert already serves to anybody who
        # asks.
        fpf = tk.Frame(sf, bg=CARD)
        fpf.pack(fill="x", pady=(9, 0))
        fphd = tk.Frame(fpf, bg=CARD)
        fphd.pack(fill="x")
        tk.Label(fphd, text="SHA-256 fingerprint", bg=CARD, fg=SUBTEXT,
                 font=font("emph")).pack(side="left")
        fp_said = tk.Label(fphd, text="", bg=CARD, fg=SUCCESS,
                           font=font("micro"))
        fp_said.pack(side="left", padx=(8, 0))
        _fp = _cert_fingerprint()
        if _fp:
            def copy_fingerprint():
                dlg.clipboard_clear()
                dlg.clipboard_append(_fp)
                fp_said.config(text="✓  Copied")

            # Four rows of eight pairs rather than one 95-character line:
            # it is read aloud at least as often as it is copied. The
            # clipboard gets the single canonical line, which is what a
            # comparison is actually made against.
            _pairs = _fp.split(":")
            tk.Label(fpf, text="\n".join(
                         ":".join(_pairs[i:i + 8])
                         for i in range(0, len(_pairs), 8)),
                     bg=CARD, fg=MONO, font=font("code"),
                     justify="left").pack(side="left", anchor="w", pady=(3, 0))
            def export_cert():
                # The public half, for carrying to a client: dropped beside
                # AssetManager_Setup.exe, where installer.py already looks, or
                # beside an installed client to answer an ADR-0010 prompt
                # before it is asked. A control rather than a sentence telling
                # somebody to copy a file, because the file to copy sits next
                # to ssl_key.pem with a name one character different.
                dest = fd.asksaveasfilename(
                    parent=dlg, title="Export Certificate",
                    defaultextension=".pem",
                    initialfile="ssl_cert.pem",
                    filetypes=[("PEM certificate", "*.pem"),
                               ("All files", "*.*")])
                if not dest:
                    return
                try:
                    written = _export_public_cert(dest)
                except (ValueError, OSError) as ex:
                    # In the exporter's own words: a file holding a key and a
                    # file with no certificate in it need different things
                    # done about them, and "failed" names neither.
                    mb.showerror("Export Certificate", str(ex), parent=dlg)
                    return
                # No password came near this and the certificate is public,
                # so there is nothing here _log_event refuses - and the
                # fingerprint is the point of the entry: it is the record of
                # which certificate left this machine, which is the question
                # asked afterwards when a client will not connect.
                S._log_event("cert.exported", "%s  ->  %s" % (written, dest),
                           actor="Admin (Server GUI)")
                fp_said.config(text="✓  Exported")
                mb.showinfo("Export Certificate",
                            "✓  The public certificate was written to:\n\n%s"
                            "\n\nSHA-256 fingerprint:\n%s\n\nThe private "
                            "key was not exported and never travels."
                            % (dest, written), parent=dlg)

            Pill(fpf, "Copy", CARD, ACCENT, ACCENT2, w=76, h=28, bold=False,
                 command=copy_fingerprint).pack(side="right", anchor="s")
            Pill(fpf, "Export", CARD, CARD2, LINE, w=84, h=28, bold=False,
                 command=export_cert).pack(side="right", anchor="s",
                                           padx=(0, 6))

            # Expiry (#273): the same live file the fingerprint above reads,
            # coloured by the daily background check's own thresholds so the
            # console says nothing the System Log has not already said.
            _days_left, _expires = _cert_expiry()
            if _days_left is not None:
                if _days_left <= CERT_ERROR_DAYS:
                    _exp_color = DANGER
                elif _days_left <= CERT_WARN_DAYS:
                    _exp_color = WARNING
                else:
                    _exp_color = SUBTEXT
                tk.Label(sf, text="Expires %s (%d day%s)"
                              % (_expires.date().isoformat(), _days_left,
                                 "" if _days_left == 1 else "s"),
                         bg=CARD, fg=_exp_color,
                         font=font("micro")).pack(anchor="w", pady=(3, 0))
        else:
            tk.Label(fpf, text="unreadable — no certificate in the file",
                     bg=CARD, fg=DANGER,
                     font=font("micro")).pack(anchor="w", pady=(3, 0))

    # ── Next certificate (C1, ADR-0020) ──
    # Generated here and bound to nothing. The two fingerprints sit one above
    # the other because the only question an Admin has at this point is
    # whether the thing they just made is the thing the fleet is still
    # pinning, and it must read as two certificates rather than one changing.
    rot = tk.Frame(body, bg=CARD, padx=16, pady=10)
    rot.pack(fill="x", padx=18, pady=(8, 0))
    tk.Label(rot, text="Next certificate", bg=CARD, fg=SUBTEXT,
             font=font("emph")).pack(anchor="w")
    staged_var = tk.StringVar()
    tk.Label(rot, textvariable=staged_var, bg=CARD, fg=MONO,
             font=font("mono"), justify="left",
             wraplength=380).pack(anchor="w", pady=(3, 0))
    # Said on the window rather than left to be inferred from the word
    # staged: a rotation that begins by binding strands every client at once
    # (rule 1), so what makes this safe is exactly that nothing has happened
    # yet, and an Admin who thinks it has will not go on to the step that
    # pushes it.
    tk.Label(rot, text="Staged beside the server and bound to nothing: this "
                       "server goes on serving the certificate above, and no "
                       "client can reach this one yet.",
             bg=CARD, fg=SUBTEXT, font=font("micro"),
             wraplength=380, justify="left").pack(anchor="w", pady=(4, 0))

    def show_staged():
        _next = _cert_fingerprint(S.SSL_CERT_NEXT_PATH)
        staged_var.set(_next or "none staged")

    def generate_cert():
        # Generating twice replaces the staged pair, which is a question
        # rather than a refusal - the reason to do it is a name that was
        # missing from the first one - and the answer says which fingerprint
        # is staged afterwards, since a staged certificate nobody can name is
        # one nobody can compare against what a client reports.
        if os.path.exists(S.SSL_CERT_NEXT_PATH) and not mb.askyesno(
                "Next Certificate",
                "A certificate is already staged:\n\n%s\n\nGenerate "
                "another? The staged pair is replaced. Nothing that is being "
                "served changes either way."
                % (_cert_fingerprint(S.SSL_CERT_NEXT_PATH) or "(unreadable)"),
                parent=dlg, icon="warning"):
            return
        try:
            _fp_next = _stage_new_cert()
        except (RuntimeError, ValueError, OSError) as ex:
            # In the generator's own words: a missing library and a path that
            # would have overwritten the live certificate need different
            # things done about them, and "failed" names neither.
            mb.showerror("Next Certificate", str(ex), parent=dlg)
            return
        # No password comes near this and the certificate is public, so there
        # is nothing in it _log_event refuses - and the fingerprint is the
        # point of the entry, being what the later phases are checked against.
        # At `info`, not `warn`: nothing is bound and nothing is stranded.
        S._log_event("cert.generated", _fp_next or "(unreadable)",
                   actor="Admin (Server GUI)")
        show_staged()
        mb.showinfo("Next Certificate",
                    "A new certificate was generated and staged.\n\n"
                    "SHA-256 fingerprint:\n%s\n\nNothing is bound and "
                    "nothing is served: this server still presents the "
                    "certificate it had, and every client goes on working. "
                    "Its private key stays on this machine."
                    % (_fp_next or "(unreadable)"), parent=dlg)

    def cut_over():
        """Phase three: make the staged certificate the one being served (C4).

        The confirmation is the feature. Every other control in this window
        either changes nothing that is served or replaces a certificate an
        Admin went and found, where this one is a deliberate act with a known
        cost: the machines that never collected `trust_cert` fail closed the
        moment the binding moves, the hourly refresh included, and there is
        nothing this server can do for them afterwards. So the count is put in
        front of the Admin **before** the password field rather than reported
        after the fact, and it is the **queue's** count rather than the
        Certificate column's, that column being unable to see an append (C3).

        What is refused is refused by `_cut_over_cert` and shown in its words:
        nothing staged, no key beside it, and a staged certificate that is
        already the one being served are three different things to do
        something about, and "failed" names none of them.
        """
        fp_next = _cert_fingerprint(S.SSL_CERT_NEXT_PATH)
        if not fp_next:
            mb.showinfo("Cut Over",
                        "Nothing is staged on this server.\n\nGenerate a "
                        "certificate above first, then push it to the Clients "
                        "from Connected Clients, and only then cut over.",
                        parent=dlg)
            return
        behind, total = _clients_behind_staged()
        iis = S._iis_host()
        script = os.path.join("tools", "bind-cert.ps1")
        d = tk.Toplevel(dlg)
        d.title("Cut Over")
        d.configure(bg=BG)
        d.transient(dlg)
        d.grab_set()
        ui_kit.escape_closes(d)
        tk.Label(d, text="Serve the staged certificate", bg=BG, fg=TEXT,
                 font=font("title")).pack(anchor="w", padx=18,
                                                     pady=(16, 2))
        tk.Label(d, text=fp_next, bg=BG, fg=MONO,
                 font=font("code")).pack(anchor="w", padx=18)
        # The sentence an Admin decides on, worded as a proportion rather than
        # as a bare number: 0 of 12 and 0 of 0 are different situations and
        # only the first of them is a fleet that is ready.
        if behind:
            warn = ("%d of %d installation(s) have not collected the staged "
                    "certificate yet, and each of them fails closed the "
                    "moment the binding moves - the hourly refresh included. "
                    "Nothing this server can do reaches them afterwards: "
                    "somebody has to delete ssl_cert.pem at that machine and "
                    "confirm the new fingerprint." % (behind, total))
        elif total:
            warn = ("All %d installation(s) that have checked in collected "
                    "the staged certificate, so each already accepts both "
                    "and none of them is stranded by this." % (total,))
        else:
            warn = ("No Client has ever checked in, so there is nobody here "
                    "to strand - and nobody who has been told about this "
                    "certificate either.")
        ui_kit.rewrap(tk.Label(d, text=warn, bg=BG,
                               fg=DANGER if behind else SUBTEXT,
                               font=font("body"), justify="left",
                               wraplength=420), 36).pack(
                                   anchor="w", padx=18, pady=(10, 0))
        if iis:
            after = ("The binding is IIS's, so this replaces the files and "
                     "then asks Windows to elevate %s, which moves site %s "
                     "onto them. Refuse the elevation and the files are in "
                     "place and the binding is not - the command to run is "
                     "printed rather than left to be guessed."
                     % (script, iis.get("site") or "this install"))
        else:
            after = ("Nothing binds here: this process serves the files "
                     "directly, so the new pair is picked up when the server "
                     "is restarted. Until then it goes on presenting the "
                     "certificate it has.")
        ui_kit.rewrap(tk.Label(d, text=after, bg=BG, fg=SUBTEXT,
                               font=font("body"), justify="left",
                               wraplength=420), 36).pack(
                                   anchor="w", padx=18, pady=(8, 0))

        def send():
            payload, status = _cut_over_cert(
                authorised_as="Admin (Server GUI)")
            if status >= 400:
                mb.showerror("Cut Over", payload.get("error", "Refused"),
                             parent=d)
                return
            d.destroy()
            show_staged()
            tail = ("\n\nThe pair that was live is in %s, which keeps one "
                     "generation.\n\n%d of %d installation(s) had not "
                     "collected it." % (payload["aside"], payload["behind"],
                                        payload["clients"]))
            if payload["iis"]:
                # Spawned rather than run in process: under IIS this process
                # is the app pool identity and cannot bind anything. `runas`
                # is what raises the UAC prompt, and a refusal is an ordinary
                # answer here rather than a failure - the files are already
                # swapped, so what is owed is the exact command rather than an
                # apology. It is the command `_bind_cert_command` built, so
                # what is printed and what would have run are one string.
                cmd = payload["command"]
                try:
                    import ctypes
                    rc = ctypes.windll.shell32.ShellExecuteW(
                        None, "runas", cmd[0],
                        " ".join('"%s"' % a for a in cmd[1:]), None, 1)
                    if rc <= 32:
                        raise OSError("elevation was refused (%d)" % rc)
                    moved = ("The IIS binding has not moved yet - Windows is "
                             "being asked to elevate the script that moves "
                             "it.\n\n")
                except Exception as ex:
                    moved = ("The binding has NOT moved (%s). Run this "
                             "elevated:\n\n%s\n\n"
                             % (ex, " ".join(cmd)))
                mb.showinfo(
                    "Cut Over",
                    "The files are in place. %sNow serving:\n%s%s"
                    % (moved, payload["to"], tail), parent=dlg)
                return
            # No IIS in front of this process: `_cut_over_cert` has already
            # turned `ssl_enabled` on for the reason Install turns it on
            # (#266) - a standalone server that was on HTTP stays on HTTP
            # otherwise, `_run_flask` builds a TLS context only when that
            # flag is set. What is left is the same restart Install does,
            # which is where the new pair is actually picked up.
            done = ("Now serving:\nhttps://%s:%d%s"
                    % (socket.gethostname(), S.PORT, tail))
            _restart_server(done)

        bf = tk.Frame(d, bg=BG)
        bf.pack(fill="x", padx=18, pady=(16, 14))
        cbox, crow2 = ui_kit.row_of(
            bf,
            [("Cut Over", "Cut", (BG, DANGER_BG, DANGER_HOT, "white"), send),
             ("Cancel", None, (BG, CARD2, LINE, SUBTEXT), d.destroy)],
            kind="footer")
        cbox.pack(fill="x")
        ui_kit.fit(d, max(460, crow2.min_width() + 36))

    # Two pills rather than one, and Cut over is the secondary of the pair:
    # Generate writes a file nothing is served from, where this one replaces
    # what every client verifies against, so the accent goes on the harmless
    # one and the dialog behind this carries the warning.
    crow = tk.Frame(rot, bg=CARD)
    crow.pack(anchor="e", pady=(6, 0))
    Pill(crow, "Cut over", CARD, CARD2, LINE, fg=SUBTEXT, w=96, h=28,
         bold=False, command=cut_over).pack(side="left", padx=(0, 6))
    Pill(crow, "Generate", CARD, ACCENT, ACCENT2, w=96, h=28, bold=False,
         command=generate_cert).pack(side="left")
    show_staged()

    frm = tk.Frame(body, bg=BG, padx=18)
    frm.pack(fill="x", pady=(6, 0))

    CERT_TYPES = [
        ("Certificate files", "*.pfx *.p12 *.crt *.cer *.pem"),
        ("PFX / PKCS#12",    "*.pfx *.p12"),
        ("CRT / CER",        "*.crt *.cer"),
        ("PEM",              "*.pem"),
        ("All files",        "*.*"),
    ]
    KEY_TYPES = [
        ("Key files", "*.pem *.key"),
        ("All files", "*.*"),
    ]

    # ── Cert row ──
    tk.Label(frm, text="Certificate file  (.pfx  .crt  .cer  .pem)",
             bg=BG, fg=SUBTEXT, font=font("body")).pack(anchor="w", pady=(8, 2))
    cert_row = tk.Frame(frm, bg=BG)
    cert_row.pack(fill="x")
    cert_var = tk.StringVar()
    cert_e = tk.Entry(cert_row, textvariable=cert_var, bg=INPUT_BG, fg=TEXT,
                      relief="flat", font=font("body"), insertbackground=TEXT)
    cert_e.pack(side="left", fill="x", expand=True, ipady=6)

    # ── Key row (hidden for PFX) ──
    key_lbl_var = tk.StringVar(value="Private key file  (.pem  .key)")
    key_lbl = tk.Label(frm, textvariable=key_lbl_var,
                       bg=BG, fg=SUBTEXT, font=font("body"))
    key_lbl.pack(anchor="w", pady=(8, 2))
    key_row = tk.Frame(frm, bg=BG)
    key_row.pack(fill="x")
    key_var = tk.StringVar(value=S.SSL_KEY_PATH if os.path.exists(S.SSL_KEY_PATH) else "")
    key_e = tk.Entry(key_row, textvariable=key_var, bg=INPUT_BG, fg=TEXT,
                     relief="flat", font=font("body"), insertbackground=TEXT)
    key_e.pack(side="left", fill="x", expand=True, ipady=6)
    key_btn = tk.Button(key_row, text="Browse", bg=CARD2, fg="white",
                        relief="flat", cursor="hand2", font=font("body"),
                        command=lambda: key_var.set(
                            fd.askopenfilename(title="Select Key File",
                                               filetypes=KEY_TYPES) or key_var.get()))
    key_btn.pack(side="left", padx=(4, 0), ipadx=8, ipady=6)

    # ── PFX password row (shown only for PFX) ──
    pfx_lbl = tk.Label(frm, text="PFX Password  (leave blank if none)",
                       bg=BG, fg=SUBTEXT, font=font("body"))
    pfx_pwd_var = tk.StringVar()
    pfx_e = tk.Entry(frm, textvariable=pfx_pwd_var, show="●",
                     bg=INPUT_BG, fg=TEXT, relief="flat",
                     font=font("body"), insertbackground=TEXT)
    # Before this field is in the form at all: `_on_cert_change` grids it when
    # a `.pfx` is picked and forgets it again otherwise. The toggle is placed
    # inside the entry (#202), so it travels with the widget and needs to know
    # nothing about which row it ends up on, or whether it ends up on one.
    ui_kit.reveal(pfx_e)

    def _on_cert_change(*_):
        path = cert_var.get().strip()
        ext  = os.path.splitext(path)[1].lower()
        is_pfx = ext in ('.pfx', '.p12')
        # Toggle key row
        state = tk.DISABLED if is_pfx else tk.NORMAL
        key_e.config(state=state, bg=BG if is_pfx else INPUT_BG)
        key_btn.config(state=state)
        key_lbl_var.set("Private key file  (not needed for PFX)"
                        if is_pfx else "Private key file  (.pem  .key)")
        # Toggle PFX password row
        if is_pfx:
            pfx_lbl.pack(anchor="w", pady=(8, 2))
            pfx_e.pack(fill="x", ipady=6)
        else:
            pfx_lbl.pack_forget()
            pfx_e.pack_forget()

    cert_var.trace_add("write", _on_cert_change)
    tk.Button(cert_row, text="Browse", bg=CARD2, fg="white",
              relief="flat", cursor="hand2", font=font("body"),
              command=lambda: cert_var.set(
                  fd.askopenfilename(title="Select Certificate File",
                                     filetypes=CERT_TYPES) or cert_var.get())
              ).pack(side="left", padx=(4, 0), ipadx=8, ipady=6)

    err_lbl = tk.Label(body, text="", bg=BG, fg=DANGER, font=font("body"))
    err_lbl.pack(pady=(6, 0))

    def _elevate(cmd):
        """Ask Windows to run `cmd` elevated, or raise saying it would not.

        Under IIS this process is the app pool identity and is not an
        administrator: it cannot touch a binding, a firewall rule or a pool,
        so what it does instead is spawn something that can. `runas` is what
        raises the UAC prompt, and a refusal is an ordinary answer here rather
        than a failure - whatever this follows has already been written to
        disk, so what is owed is the exact command rather than an apology.

        One spelling for the two callers below, which is `_bind_cert_command`'s
        own argument one level up: what is printed on a refusal has to be what
        would have run.
        """
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", cmd[0],
            " ".join('"%s"' % a for a in cmd[1:]), None, 1)
        if rc <= 32:
            raise OSError("elevation was refused (%d)" % rc)

    def _restart_server(action_done):
        """Restart Flask to apply the new SSL config.
        - Under IIS -> recycle the app pool, elevated. Never os.execv.
        - If Windows Service is running -> stop + start the service.
        - If plain GUI mode -> restart this process (os.execv).
        """
        import subprocess as _sp

        iis = S._iis_host()
        if iis is not None:
            # The branch this had none of. `sc query` finds the service
            # stopped, because under IIS it is disabled (ADR-0001), and the
            # fall-through then os.execv'd the **GUI process** - a monitor
            # window restarting while the site goes on serving out of a pool
            # that has read nothing since it started, under a popup saying the
            # change had been applied. What has to restart is the pool, and
            # this identity is exactly the one that cannot restart it.
            cmd = S._recycle_pool_command()
            if not cmd:
                mb.showinfo("Done",
                            "%s\n\nIIS serves this install and iis.json "
                            "records no app pool, so there is no name here to "
                            "recycle. Restart the pool in IIS Manager for "
                            "this to take effect." % action_done)
                return
            try:
                _elevate(cmd)
                note = ("Windows is being asked to elevate the app pool "
                        "restart, which is what applies this.")
            except Exception as ex:
                note = ("The app pool has NOT been recycled (%s), so this is "
                        "not in effect yet. Run this elevated:\n\n%s"
                        % (ex, " ".join(cmd)))
            mb.showinfo("Done", "%s\n\n%s" % (action_done, note))
            return

        svc_running = False
        if S.HAS_WIN32SVC:
            try:
                r = _sp.run(["sc", "query", "AssetManagerServer"],
                            capture_output=True, timeout=5)
                svc_running = "RUNNING" in r.stdout.decode(errors="replace")
            except Exception:
                pass

        if svc_running:
            mb.showinfo("Done", f"{action_done}\n\n"
                        "Restarting Windows Service to apply changes…\n"
                        "(Stats will refresh in a few seconds.)")
            def _do():
                try:
                    _sp.run(["net", "stop", "AssetManagerServer"],
                            capture_output=True, timeout=30)
                    _sp.Popen(["net", "start", "AssetManagerServer"],
                              stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                except Exception:
                    pass
            threading.Thread(target=_do, daemon=True).start()
        else:
            mb.showinfo("Done", f"{action_done}\n\n"
                        "Restarting server now to apply changes…")
            # Restart the process — new instance picks up new SSL config
            try:
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception:
                mb.showinfo("Restart Required",
                            "Please close and reopen AssetServer.exe to apply changes.")

    def do_install():
        c   = cert_var.get().strip()
        k   = key_var.get().strip()
        pwd = pfx_pwd_var.get()
        if not c:
            err_lbl.config(text="✗  Certificate file is required.")
            return
        if not os.path.exists(c):
            err_lbl.config(text="✗  Certificate file not found.")
            return
        # Read before the write, because afterwards there is nothing left
        # to read it from. One digest on its own answers nothing here -
        # the question being asked is which certificate the Clients on
        # this network pinned - which is why tools/update.ps1 names both
        # sides of the same mismatch rather than only the incoming one.
        outgoing = _cert_fingerprint()
        try:
            cert_pem, key_pem = _cert_to_pem(c, k or None, pwd or None)
            with open(S.SSL_CERT_PATH, 'wb') as f:
                f.write(cert_pem)
            with open(S.SSL_KEY_PATH, 'wb') as f:
                f.write(key_pem)
            S._save_server_cfg(ssl_enabled=True,
                             _actor="Admin (Server GUI)")
            # The largest blast radius this console has, and it left no
            # entry at all. Every Client loads this file as its own trust
            # anchor and fails closed against anything else (rule 1), so
            # replacing it strands each one - the hourly GET /cert
            # refresh included, that going over the connection the
            # outgoing certificate verified - until somebody at that
            # machine confirms the new fingerprint (ADR-0010). The
            # `ssl_enabled=True` _save_server_cfg writes above is not
            # this fact: it reads identically whether HTTPS was switched
            # on for the first time or a certificate was swapped
            # underneath a fleet that had already pinned one. Sharper
            # because this action is delegable (ADR-0006). The
            # certificate is public and no password comes near this, so
            # there is nothing in it _log_event refuses.
            incoming = _cert_fingerprint()
            S._log_event("cert.installed",
                       "was %s  ->  now %s"
                       % (outgoing or "(none)", incoming or "(unreadable)"),
                       actor="Admin (Server GUI)", level="warn",
                       data={"was": outgoing or "(none)",
                             "now": incoming or "(unreadable)"})
            dlg.destroy()
            done = ("✓  Certificate installed.\n\nClients connect to:\n"
                    "https://%s:%d" % (socket.gethostname(), S.PORT))
            iis = S._iis_host()
            if iis is None:
                _restart_server(done)
                return
            # Install is the cutover one step earlier - the same two files
            # replaced, with no staging in front of it - so it takes the
            # cutover's elevated half rather than a restart. Restarting moves
            # no binding: the site goes on presenting the certificate it was
            # bound to, while the popup says the clients connect over the new
            # one. It is the command `_bind_cert_command` built, so what is
            # printed on a refusal and what would have run are one string.
            cmd = S._bind_cert_command()
            try:
                _elevate(cmd)
                moved = ("The IIS binding has not moved yet - Windows is "
                         "being asked to elevate %s, which moves site %s onto "
                         "this pair and recycles the pool."
                         % (os.path.join("tools", "bind-cert.ps1"),
                            iis.get("site") or "this install"))
            except Exception as ex:
                moved = ("The binding has NOT moved (%s), so the site is "
                         "still presenting the certificate it had. Run this "
                         "elevated:\n\n%s" % (ex, " ".join(cmd)))
            mb.showinfo("Done", "%s\n\n%s" % (moved, done))
        except Exception as ex:
            err_lbl.config(text=f"✗  {ex}")

    def do_remove():
        # Refused before the confirmation rather than after it, because there
        # is nothing here to confirm: under IIS the site terminates TLS
        # (ADR-0001) and deleting these two files turns nothing off. It leaves
        # an https site with no `GET /cert` behind it and every pinned Client
        # stranded with no channel left to hand it anything (rule 1) - the
        # exact outage ADR-0020 exists to prevent, reached by the one button
        # that sounds like the safe way out of it.
        _iis_now = S._iis_host()
        if _iis_now is not None:
            mb.showerror(
                "Remove SSL",
                "IIS terminates TLS in front of this server, so removing "
                "these files does not turn https off. Site %s would go on "
                "presenting the certificate it is bound to, GET /cert would "
                "start answering 404, and every Client that pinned this file "
                "would be stranded with no way left to reach this server.\n\n"
                "Nothing has been deleted.\n\n"
                "What the site serves is changed by tools\\install-iis.ps1, "
                "and by nothing in this window."
                % (_iis_now.get("site") or "this install"), parent=dlg)
            return
        if not mb.askyesno("Remove SSL",
                           "Remove the SSL certificate and revert to HTTP?",
                           icon="warning"):
            return
        # Read before the files go, for the reason do_install reads
        # before the write: this is the last moment the outgoing
        # certificate can be named.
        outgoing = _cert_fingerprint()
        try:
            for p in [S.SSL_CERT_PATH, S.SSL_KEY_PATH]:
                if os.path.exists(p):
                    os.remove(p)
            S._save_server_cfg(ssl_enabled=False,
                             _actor="Admin (Server GUI)")
            # Reverting to HTTP strands every pinned Client exactly as a
            # swap does - their https:// requests stop having a server
            # to verify - so it is the same entry, carrying what was
            # taken away.
            S._log_event("cert.removed", outgoing or "(none)",
                       actor="Admin (Server GUI)", level="warn",
                       data={"was": outgoing or "(none)"})
            dlg.destroy()
            _restart_server("✓  Certificate removed.")
        except Exception as ex:
            err_lbl.config(text=f"✗  {ex}")

    tk.Button(btn_frm, text="🔒  Install Certificate",
              bg=SUCCESS_BG, fg="white", font=font("heading"),
              relief="flat", cursor="hand2", pady=9,
              command=do_install,
              activebackground=SUCCESS_HOT).pack(fill="x", pady=(0, 4))
    if _cert_ok:
        tk.Button(btn_frm, text="Remove SSL",
                  bg=CARD2, fg="white", font=font("body"),
                  relief="flat", cursor="hand2", pady=7,
                  command=do_remove,
                  activebackground=LINE).pack(fill="x")
    # No written size: this form has grown twice over, and the PFX
    # password row is packed into it at runtime, after this has run -
    # ui_kit.fit is what keeps either from losing a button.
    scroll.size()
    ui_kit.fit(dlg, scroll.width(440))
    host_e.focus_set()
