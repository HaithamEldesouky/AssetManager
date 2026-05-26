"""
Asset Manager — Unified Installer
Bundles AssetServer.exe, StorekeeperApp.exe, NotifierApp.exe.
User picks which component to install; installer writes config.json
and copies the right exe to a chosen directory.
Notifier install verifies the admin password live against the server.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os, sys, json, shutil, threading, hashlib, requests, textwrap, ssl
from requests.adapters import HTTPAdapter

# ─── Bundled exe names (must match build.bat output names) ────────────────────
BUNDLED_EXES = {
    "server":      "AssetServer.exe",
    "storekeeper": "StorekeeperApp.exe",
    "notifier":    "NotifierApp.exe",
}

TEAM_MEMBERS = [
    "Engineer 1",
    "Engineer 2",
    "Engineer 3",
    "Engineer 4",
]

DEFAULT_SERVER_URL = "https://asset-server:8081"


# ─── Colours ──────────────────────────────────────────────────────────────────
BG       = "#1a2332"
CARD     = "#1e2d3d"
CARD2    = "#243447"
ACCENT   = "#0078d4"
ACCENT2  = "#106ebe"
TEXT     = "#e8edf2"
SUBTEXT  = "#7a8fa3"
SUCCESS  = "#4caf50"
WARNING  = "#f0a500"
DANGER   = "#f44336"
INPUT_BG = "#2a3f55"

# ─── Helpers ──────────────────────────────────────────────────────────────────

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

if getattr(sys, 'frozen', False):
    _INSTALLER_DIR = os.path.dirname(sys.executable)
else:
    _INSTALLER_DIR = os.path.dirname(os.path.abspath(__file__))

_SSL_CERT_PATH = os.path.join(_INSTALLER_DIR, "ssl_cert.pem")
_SSL_KEY_PATH  = os.path.join(_INSTALLER_DIR, "ssl_key.pem")

class _SelfSignedAdapter(HTTPAdapter):
    """Trust a specific self-signed cert; skip hostname check (internal network)."""
    def __init__(self, cert_path, **kw):
        self._cert_path = cert_path
        super().__init__(**kw)
    def _make_ctx(self):
        if os.path.exists(self._cert_path):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.load_verify_locations(self._cert_path)
        else:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
        return ctx
    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = self._make_ctx()
        return super().init_poolmanager(*args, **kwargs)
    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs['ssl_context'] = self._make_ctx()
        return super().proxy_manager_for(proxy, **proxy_kwargs)

def api(method, url, **kw):
    kw.setdefault("timeout", 7)
    if url.startswith("https"):
        try:
            s = requests.Session()
            s.mount("https://", _SelfSignedAdapter(_SSL_CERT_PATH))
            return getattr(s, method)(url, **kw)
        except requests.exceptions.SSLError as _e:
            if "WRONG_VERSION_NUMBER" in str(_e) or "wrong version number" in str(_e).lower():
                return getattr(requests, method)(url.replace("https://", "http://", 1), **kw)
            raise
    return getattr(requests, method)(url, **kw)

def _bundled_path(name):
    """Return path to a bundled exe.
    When running as AssetManager_Setup.exe (frozen), PyInstaller extracts
    bundled files to sys._MEIPASS. When running as script, look next to installer.py.
    """
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, BUNDLED_EXES[name])

# ─── Main Installer Window ────────────────────────────────────────────────────

class InstallerApp:
    def __init__(self, root):
        self.root = root
        root.title("Asset Manager — Setup")
        root.geometry("560x700")
        root.minsize(560, 600)
        root.configure(bg=BG)
        root.resizable(False, True)

        self._build_ui()

    def _build_ui(self):
        # Fixed header (not scrollable)
        hdr = tk.Frame(self.root, bg=ACCENT, height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="\U0001f4e6  Asset Manager \u2014 Setup",
                 bg=ACCENT, fg="white",
                 font=("Segoe UI", 15, "bold")).pack(side="left", padx=20, pady=14)

        # Scrollable body
        canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(self.root, orient="vertical",
                                 command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=BG)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(body_window, width=e.width)
        body.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # All content goes into `body` from here
        tk.Label(body,
                 text="Choose which component to install on this computer.",
                 bg=BG, fg=SUBTEXT,
                 font=("Segoe UI", 10)).pack(pady=(14, 4), padx=24, anchor="w")

        # ── Component selector ─────────────────────────────────────────────────
        self.v_component = tk.StringVar(value="notifier")

        cards = [
            ("server",      "🖥  Server",
             "Run on asset-server only.\nHosts the database and REST API on port 8081."),
            ("storekeeper", "📋  Storekeeper App",
             "Install on Storekeeper User's computer.\nUsed to log asset transactions."),
            ("notifier",    "🔔  Notifier",
             "Install on each engineer's laptop.\nShows confirmation popups for asset movements."),
        ]

        self.card_frames = {}
        for key, title, desc in cards:
            f = tk.Frame(body, bg=CARD2, padx=14, pady=8,
                         cursor="hand2", highlightthickness=2,
                         highlightbackground=CARD2)
            f.pack(fill="x", padx=24, pady=4)
            rb = tk.Radiobutton(f, text=title, variable=self.v_component, value=key,
                                bg=CARD2, fg=TEXT, selectcolor=INPUT_BG,
                                activebackground=CARD2, activeforeground=TEXT,
                                font=("Segoe UI", 11, "bold"),
                                command=self._on_component_change)
            rb.pack(anchor="w")
            tk.Label(f, text=desc, bg=CARD2, fg=SUBTEXT,
                     font=("Segoe UI", 9), justify="left").pack(anchor="w", padx=26)
            # Click anywhere on card to select
            for w in (f,):
                w.bind("<Button-1>", lambda e, k=key: (
                    self.v_component.set(k), self._on_component_change()))
            self.card_frames[key] = f

        # ── Dynamic section (changes per component) ────────────────────────────
        self.dynamic = tk.Frame(body, bg=BG)
        self.dynamic.pack(fill="x", padx=24, pady=(8, 0))

        # ── Install dir picker ─────────────────────────────────────────────────
        dir_row = tk.Frame(body, bg=BG)
        dir_row.pack(fill="x", padx=24, pady=(10, 0))
        tk.Label(dir_row, text="Install directory:",
                 bg=BG, fg=SUBTEXT, font=("Segoe UI", 9)).pack(anchor="w")
        pick_row = tk.Frame(dir_row, bg=BG)
        pick_row.pack(fill="x", pady=4)
        self.v_dir = tk.StringVar(
            value=os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"),
                               "AssetManager"))
        dir_e = tk.Entry(pick_row, textvariable=self.v_dir,
                         bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=("Segoe UI", 9), insertbackground=TEXT)
        dir_e.pack(side="left", fill="x", expand=True, ipady=7)
        tk.Button(pick_row, text="Browse…",
                  bg=CARD2, fg=SUBTEXT, font=("Segoe UI", 9),
                  relief="flat", cursor="hand2", padx=8, pady=6,
                  command=self._pick_dir,
                  activebackground=INPUT_BG).pack(side="left", padx=(6, 0))

        # Status / error label
        self.err_lbl = tk.Label(body, text="", bg=BG, fg=DANGER,
                                font=("Segoe UI", 9))
        self.err_lbl.pack(pady=(6, 0))

        # Install button
        tk.Button(body, text="  \u27a4  Install",
                  bg=ACCENT, fg="white", font=("Segoe UI", 12, "bold"),
                  relief="flat", cursor="hand2", pady=12,
                  command=self._install,
                  activebackground=ACCENT2).pack(fill="x", padx=24, pady=(8, 4))

        tk.Label(body,
                 text="Asset Manager  \u2014  For SD department internal use only.",
                 bg=BG, fg="#3d5470",
                 font=("Segoe UI", 8)).pack(pady=(4, 12))

        self._on_component_change()

    def _highlight_card(self, selected_key):
        for key, frame in self.card_frames.items():
            if key == selected_key:
                frame.config(highlightbackground=ACCENT, bg=CARD)
                for w in frame.winfo_children():
                    try: w.config(bg=CARD)
                    except: pass
            else:
                frame.config(highlightbackground=CARD2, bg=CARD2)
                for w in frame.winfo_children():
                    try: w.config(bg=CARD2)
                    except: pass

    def _on_component_change(self):
        for w in self.dynamic.winfo_children():
            w.destroy()
        key = self.v_component.get()
        self._highlight_card(key)

        if key == "server":
            tk.Label(self.dynamic,
                     text="ℹ  Runs on asset-server only. Uses port 8081.",
                     bg=BG, fg=SUBTEXT, font=("Segoe UI", 9)).pack(anchor="w")
            tk.Label(self.dynamic, text="Set Admin Password:",
                     bg=BG, fg=SUBTEXT, font=("Segoe UI", 9)).pack(anchor="w", pady=(10, 2))
            if not hasattr(self, 'v_admin_pw'):
                self.v_admin_pw  = tk.StringVar()
                self.v_admin_pw2 = tk.StringVar()
            tk.Entry(self.dynamic, textvariable=self.v_admin_pw, show="●",
                     bg=INPUT_BG, fg=TEXT, relief="flat",
                     font=("Segoe UI", 10), insertbackground=TEXT).pack(fill="x", ipady=8)
            tk.Label(self.dynamic, text="Confirm Password:",
                     bg=BG, fg=SUBTEXT, font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 2))
            tk.Entry(self.dynamic, textvariable=self.v_admin_pw2, show="●",
                     bg=INPUT_BG, fg=TEXT, relief="flat",
                     font=("Segoe UI", 10), insertbackground=TEXT).pack(fill="x", ipady=8)
            # Update suggested dir
            self.v_dir.set(os.path.join(
                os.environ.get("PROGRAMFILES", "C:\\Program Files"),
                "AssetManager", "Server"))

        elif key == "storekeeper":
            self._build_url_field(self.dynamic)
            self.v_dir.set(os.path.join(
                os.environ.get("PROGRAMFILES", "C:\\Program Files"),
                "AssetManager", "Storekeeper"))

        elif key == "notifier":
            self._build_url_field(self.dynamic)
            tk.Label(self.dynamic, text="Assign this PC to:",
                     bg=BG, fg=SUBTEXT, font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 2))
            self.v_member = ttk.Combobox(self.dynamic, values=TEAM_MEMBERS,
                                          state="readonly", font=("Segoe UI", 10))
            self.v_member.set(TEAM_MEMBERS[0])
            self.v_member.pack(fill="x", ipady=4)

            tk.Label(self.dynamic,
                     text="Admin Password  (verified against server — required):",
                     bg=BG, fg=SUBTEXT, font=("Segoe UI", 9)).pack(anchor="w", pady=(10, 2))
            self.v_notifier_pw = tk.StringVar()
            tk.Entry(self.dynamic, textvariable=self.v_notifier_pw,
                     show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                     font=("Segoe UI", 11), insertbackground=TEXT,
                     highlightthickness=1,
                     highlightbackground=DANGER,
                     highlightcolor="#ef9a9a").pack(fill="x", ipady=8)
            tk.Label(self.dynamic,
                     text="⚠  Without the correct admin password, installation is blocked.",
                     bg=BG, fg=WARNING, font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))

            self.v_dir.set(os.path.join(
                os.environ.get("APPDATA", os.path.expanduser("~")),
                "AssetManager", "Notifier"))

    def _build_url_field(self, parent):
        tk.Label(parent, text="Server URL:",
                 bg=BG, fg=SUBTEXT, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 2))
        if not hasattr(self, 'v_url'):
            self.v_url = tk.StringVar(value=DEFAULT_SERVER_URL)
        url_e = tk.Entry(parent, textvariable=self.v_url,
                         bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=("Segoe UI", 10), insertbackground=TEXT)
        url_e.pack(fill="x", ipady=7)

    def _pick_dir(self):
        d = filedialog.askdirectory(title="Choose Install Directory")
        if d:
            self.v_dir.set(d)

    # ── Install logic ──────────────────────────────────────────────────────────

    def _install(self):
        self.err_lbl.config(text="", fg=DANGER)
        key      = self.v_component.get()
        dest_dir = self.v_dir.get().strip()

        if not dest_dir:
            self.err_lbl.config(text="Choose an install directory.")
            return

        exe_src = _bundled_path(key)
        if not os.path.exists(exe_src):
            self.err_lbl.config(
                text=f"Bundled exe not found: {BUNDLED_EXES[key]}\n"
                     "Make sure you're running AssetManager_Setup.exe")
            return

        if key == "notifier":
            self._install_notifier(exe_src, dest_dir)
        elif key == "server":
            self._install_server(exe_src, dest_dir)
        elif key == "storekeeper":
            self._install_storekeeper(exe_src, dest_dir)


    def _install_notifier(self, exe_src, dest_dir):
        member     = getattr(self, "v_member",
                             type("", (), {"get": lambda _: TEAM_MEMBERS[0]})).get()
        server_url = getattr(self, "v_url",
                             tk.StringVar(value=DEFAULT_SERVER_URL)).get().strip().rstrip("/")
        pw         = getattr(self, "v_notifier_pw", tk.StringVar()).get().strip()

        if not member:
            self.err_lbl.config(text="\u274c  Select the engineer for this PC.", fg=DANGER)
            return
        if not pw:
            self.err_lbl.config(text="\u274c  Enter the admin password.", fg=DANGER)
            return

        # Verify admin password against the server — blocks unauthorised installs
        self.err_lbl.config(text="Verifying admin password...", fg=SUBTEXT)
        self.root.update()
        try:
            r = api("post", f"{server_url}/admin/verify",
                    json={"password": pw})
            if not (r.ok and r.json().get("valid")):
                self.err_lbl.config(
                    text="\u274c  Wrong admin password. Installation blocked.", fg=DANGER)
                return
        except Exception as _ve:
            _hint = ("\n(For HTTPS: copy ssl_cert.pem next to the installer.)"
                     if server_url.startswith("https") and
                        not os.path.exists(_SSL_CERT_PATH) else "")
            self.err_lbl.config(
                text="\u26a0  Cannot reach server at the URL above.\n"
                     "Make sure the server is running before installing the Notifier."
                     + _hint,
                fg=DANGER)
            return

        try:
            os.makedirs(dest_dir, exist_ok=True)
            dst = os.path.join(dest_dir, BUNDLED_EXES["notifier"])
            shutil.copy2(exe_src, dst)
            if os.path.exists(_SSL_CERT_PATH):
                shutil.copy2(_SSL_CERT_PATH, os.path.join(dest_dir, "ssl_cert.pem"))
            cfg = {
                "server_url":     server_url,
                "current_user":   member,
                "poll_interval":  30,
                "setup_complete": True,
            }
            with open(os.path.join(dest_dir, "config.json"), "w") as f:
                json.dump(cfg, f, indent=2)

            _create_shortcut(dst, f"Asset Notifier \u2014 {member.split()[0]}")

            messagebox.showinfo(
                "Installation Complete \u2714",
                f"\u2705  Notifier installed successfully for  {member}\n\n"
                f"Location: {dst}\n\n"
                "A Desktop shortcut has been created.\n"
                "The app will start automatically with Windows."
            )
            self.root.destroy()
        except Exception as e:
            self.err_lbl.config(text=f"Install failed: {e}", fg=DANGER)

    def _install_server(self, exe_src, dest_dir):
        pw  = getattr(self, "v_admin_pw",  tk.StringVar()).get()
        pw2 = getattr(self, "v_admin_pw2", tk.StringVar()).get()
        if not pw:
            self.err_lbl.config(text="✗  Enter an admin password.", fg=DANGER)
            return
        if len(pw) < 4:
            self.err_lbl.config(text="✗  Password must be at least 4 characters.", fg=DANGER)
            return
        if pw != pw2:
            self.err_lbl.config(text="✗  Passwords do not match.", fg=DANGER)
            return
        try:
            import subprocess
            os.makedirs(dest_dir, exist_ok=True)
            dst = os.path.join(dest_dir, BUNDLED_EXES["server"])
            shutil.copy2(exe_src, dst)
            cert_copied = False
            key_copied  = False
            if os.path.exists(_SSL_CERT_PATH):
                shutil.copy2(_SSL_CERT_PATH, os.path.join(dest_dir, "ssl_cert.pem"))
                cert_copied = True
            if os.path.exists(_SSL_KEY_PATH):
                shutil.copy2(_SSL_KEY_PATH, os.path.join(dest_dir, "ssl_key.pem"))
                key_copied = True

            # Write admin_config.json with hashed password
            admin_cfg = {
                "password_hash": hashlib.sha256(pw.encode()).hexdigest(),
                "first_run": False,
            }
            with open(os.path.join(dest_dir, "admin_config.json"), "w") as f:
                json.dump(admin_cfg, f, indent=2)

            # Preserve or create server_config.json
            srv_cfg_path = os.path.join(dest_dir, "server_config.json")
            if os.path.exists(srv_cfg_path):
                # Reinstall — keep existing config (host, port, ssl_enabled, etc.)
                pass
            else:
                # Fresh install — enable SSL only when BOTH cert and key were bundled
                srv_cfg = {"host": "0.0.0.0", "port": 8081}
                if cert_copied and key_copied:
                    srv_cfg["ssl_enabled"] = True
                with open(srv_cfg_path, "w") as f:
                    json.dump(srv_cfg, f, indent=2)

            # Register the Windows Service then start it in background
            # (onefile EXE extraction takes time; we don't block the installer)
            svc_note = ""
            try:
                subprocess.run([dst, "install"], check=True,
                               capture_output=True, timeout=60)
                # Fire-and-forget — service starts in background, no timeout risk
                subprocess.Popen(["net", "start", "AssetManagerServer"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                svc_note = "\n\n✅  Windows Service registered and starting in background."
            except subprocess.CalledProcessError as svc_err:
                svc_note = (
                    "\n\n⚠️  Service registration failed (run installer as Administrator).\n"
                    f"    Error: {svc_err.stderr.decode(errors='replace').strip() or svc_err}\n\n"
                    "    To register manually (as Administrator):\n"
                    f'    "{dst}" install\n'
                    '    net start AssetManagerServer'
                )
            except Exception as svc_err:
                svc_note = (
                    f"\n\n⚠️  Service registration failed: {svc_err}\n\n"
                    "    To register manually (as Administrator):\n"
                    f'    "{dst}" install\n'
                    '    net start AssetManagerServer'
                )

            _create_shortcut(dst, "Asset Manager Server")
            messagebox.showinfo(
                "Installation Complete ✔",
                f"✅  Server installed successfully!\n\n"
                f"Location: {dst}\n"
                f"{svc_note}\n\n"
                "IMPORTANT: Open port 8081 in Windows Firewall:\n"
                "netsh advfirewall firewall add rule name=\"Asset Manager\" "
                "dir=in action=allow protocol=TCP localport=8081"
            )
            self.root.destroy()
        except Exception as e:
            self.err_lbl.config(text=f"Install failed: {e}", fg=DANGER)

    def _install_storekeeper(self, exe_src, dest_dir):
        server_url = getattr(self, 'v_url',
                             tk.StringVar(value=DEFAULT_SERVER_URL)).get().strip().rstrip("/")
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dst = os.path.join(dest_dir, BUNDLED_EXES["storekeeper"])
            shutil.copy2(exe_src, dst)
            if os.path.exists(_SSL_CERT_PATH):
                shutil.copy2(_SSL_CERT_PATH, os.path.join(dest_dir, "ssl_cert.pem"))
            cfg = {"server_url": server_url}
            with open(os.path.join(dest_dir, "config.json"), "w") as f:
                json.dump(cfg, f, indent=2)
            _create_shortcut(dst, "Asset Manager — Storekeeper")
            messagebox.showinfo(
                "Installation Complete ✔",
                f"✅  Storekeeper App installed successfully!\n\n"
                f"Location: {dst}\n\n"
                "A Desktop shortcut has been created."
            )
            self.root.destroy()
        except Exception as e:
            self.err_lbl.config(text=f"Install failed: {e}", fg=DANGER)


# ─── Shortcut helper (Windows VBScript) ──────────────────────────────────────

def _create_shortcut(target_path, name):
    """Create a Desktop shortcut using a temporary VBScript (Windows only)."""
    try:
        import tempfile, subprocess
        desktop = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")),
                               "Desktop")
        lnk     = os.path.join(desktop, f"{name}.lnk")
        vbs     = textwrap.dedent(f"""\
            Set WshShell = WScript.CreateObject("WScript.Shell")
            Set oShortcut = WshShell.CreateShortcut("{lnk}")
            oShortcut.TargetPath = "{target_path}"
            oShortcut.WorkingDirectory = "{os.path.dirname(target_path)}"
            oShortcut.Save
        """)
        tmp = tempfile.NamedTemporaryFile(suffix=".vbs", delete=False, mode='w')
        tmp.write(vbs)
        tmp.close()
        subprocess.run(["cscript", "//Nologo", tmp.name],
                       capture_output=True, timeout=10)
        os.unlink(tmp.name)
    except Exception:
        pass  # Non-fatal — shortcut creation is a convenience, not critical


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()
