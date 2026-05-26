"""
Asset Manager — Notifier App
System tray poller with confirmation popups.
Settings protected by admin password (verified against server).
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading, time, requests, json, os, sys, ssl
from requests.adapters import HTTPAdapter
from datetime import datetime

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# ─── Config ───────────────────────────────────────────────────────────────────

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

TEAM_MEMBERS = [
    "Engineer 1",
    "Engineer 2",
    "Engineer 3",
    "Engineer 4",
]

DEFAULT_CFG = {
    "server_url":    "https://asset-server:8081",
    "current_user":  "Engineer 1",
    "poll_interval": 30,
}

def load_config():
    cfg = DEFAULT_CFG.copy()
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    return cfg

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

# ─── Shared API helper ────────────────────────────────────────────────────────

_SSL_CERT_PATH = os.path.join(BASE_DIR, "ssl_cert.pem")

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
                # Server is running HTTP — fall back transparently
                return getattr(requests, method)(url.replace("https://", "http://", 1), **kw)
            raise
    return getattr(requests, method)(url, **kw)

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

# ─── Tray icon ────────────────────────────────────────────────────────────────

def make_icon(pending=False):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    c   = (240, 165, 0) if pending else (0, 120, 212)
    d.rectangle([8, 24, 56, 56], fill=c)
    d.rectangle([20, 12, 44, 28], fill=c)
    d.line([(32, 12), (32, 56)], fill=(255, 255, 255, 180), width=2)
    d.line([(8, 36), (56, 36)],  fill=(255, 255, 255, 180), width=2)
    if pending:
        d.ellipse([42, 0, 62, 20], fill=(244, 67, 54))
        d.text((49, 2), "!", fill="white")
    return img

# ─── Rejection Reason Dialog ──────────────────────────────────────────────────

class RejectReasonDialog:
    """Asks for a reason before sending reject to server."""

    def __init__(self, root, transaction, on_reject):
        self.on_reject = on_reject
        t = transaction

        win = tk.Toplevel(root)
        win.title("Rejection Reason")
        win.geometry("400x240")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.grab_set()

        hdr = tk.Frame(win, bg=DANGER, height=40)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="✘  Reject Asset Transaction",
                 bg=DANGER, fg="white",
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=14, pady=10)

        body = tk.Frame(win, bg=BG, padx=18, pady=12)
        body.pack(fill="x")

        # Show which asset
        id_parts = []
        if t.get('asset_number'):  id_parts.append(f"Asset# {t['asset_number']}")
        if t.get('serial_number'): id_parts.append(f"S/N {t['serial_number']}")
        id_str = "  /  ".join(id_parts) if id_parts else "—"

        tk.Label(body, text=f"{t['asset_type']}   {id_str}",
                 bg=BG, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(body, text="Please state the reason for rejection:",
                 bg=BG, fg=SUBTEXT,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 4))

        self.reason_var = tk.StringVar()
        reason_e = tk.Entry(body, textvariable=self.reason_var,
                            bg=INPUT_BG, fg=TEXT, relief="flat",
                            font=("Segoe UI", 10), insertbackground=TEXT,
                            highlightthickness=1,
                            highlightbackground=DANGER,
                            highlightcolor="#ef9a9a")
        reason_e.pack(fill="x", ipady=8)
        reason_e.focus_set()
        reason_e.bind("<Return>", lambda _: self._confirm())

        tk.Label(body, text="(optional — press Enter or click Reject)",
                 bg=BG, fg=SUBTEXT,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))

        btn_f = tk.Frame(win, bg=CARD2, padx=18, pady=10)
        btn_f.pack(fill="x")

        tk.Button(btn_f, text="✘  Confirm Rejection",
                  bg=DANGER, fg="white",
                  font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2", padx=16, pady=7,
                  command=self._confirm,
                  activebackground="#c62828").pack(side="left", padx=(0, 10))

        tk.Button(btn_f, text="Cancel",
                  bg=CARD2, fg=SUBTEXT,
                  font=("Segoe UI", 9),
                  relief="flat", cursor="hand2", padx=12, pady=7,
                  command=win.destroy,
                  activebackground=INPUT_BG).pack(side="left")

        self.win = win

    def _confirm(self):
        reason = self.reason_var.get().strip()
        self.on_reject(reason)
        self.win.destroy()

# ─── Notification Popup ───────────────────────────────────────────────────────

class NotificationPopup:
    def __init__(self, root, transaction, on_confirm, on_reject_with_reason):
        self.root        = root
        self.trans       = transaction
        self.on_confirm  = on_confirm
        self.on_reject_r = on_reject_with_reason
        self.countdown   = 60

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BG)

        W, H = 420, 200
        sw   = self.win.winfo_screenwidth()
        sh   = self.win.winfo_screenheight()
        self.win.geometry(f"{W}x{H}+{sw - W - 18}+{sh - H - 52}")

        outer = tk.Frame(self.win, bg=ACCENT, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill="both", expand=True)

        hdr = tk.Frame(inner, bg=ACCENT, height=36)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📦  Asset Manager — Action Required",
                 bg=ACCENT, fg="white",
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=10, pady=8)
        tk.Button(hdr, text="✕", bg=ACCENT, fg="#cce4ff",
                  relief="flat", font=("Segoe UI", 9), cursor="hand2",
                  command=self.win.destroy,
                  activebackground=ACCENT).pack(side="right", padx=6)

        body = tk.Frame(inner, bg=BG, padx=14, pady=10)
        body.pack(fill="both", expand=True)

        t      = self.trans
        is_out = (t['direction'] == "Out Store")
        dir_c  = DANGER  if is_out else SUCCESS
        dir_t  = "🔴  Taken OUT of store" if is_out else "🟢  Returned INTO store"

        # Asset ID — primary display (large)
        id_parts = []
        if t.get('asset_number'):  id_parts.append(f"Asset#  {t['asset_number']}")
        if t.get('serial_number'): id_parts.append(f"S/N  {t['serial_number']}")
        id_str = "     ".join(id_parts) if id_parts else "No ID"

        tk.Label(body, text=id_str,
                 bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        type_model = t.get('asset_type', '')
        if t.get('asset_model'):
            type_model = f"{type_model}  ·  {t['asset_model']}"
        tk.Label(body, text=type_model,
                 bg=BG, fg=SUBTEXT,
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(body, text=dir_t,
                 bg=BG, fg=dir_c,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 1))

        ts = t.get('timestamp', '')
        try: ts = datetime.fromisoformat(ts).strftime("%d/%m/%Y  %H:%M")
        except: pass
        tk.Label(body,
                 text=f"Logged by {t.get('storekeeper', 'Storekeeper User')}  ·  {ts}",
                 bg=BG, fg=SUBTEXT, font=("Segoe UI", 8)).pack(anchor="w")

        btn_f = tk.Frame(inner, bg=CARD2, padx=14, pady=8)
        btn_f.pack(fill="x")

        tk.Button(btn_f, text="✔  Confirm",
                  bg=SUCCESS, fg="white",
                  font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2",
                  padx=16, pady=6,
                  command=self._confirm,
                  activebackground="#388e3c").pack(side="left", padx=(0, 8))

        tk.Button(btn_f, text="✘  Reject",
                  bg=DANGER, fg="white",
                  font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2",
                  padx=16, pady=6,
                  command=self._reject,
                  activebackground="#c62828").pack(side="left")

        self.timer_lbl = tk.Label(btn_f,
                                  text=f"closes in {self.countdown}s",
                                  bg=CARD2, fg=SUBTEXT, font=("Segoe UI", 8))
        self.timer_lbl.pack(side="right")

        self._tick()

    def _tick(self):
        if self.countdown > 0:
            self.countdown -= 1
            self.timer_lbl.config(text=f"closes in {self.countdown}s")
            self.win.after(1000, self._tick)
        else:
            self.win.destroy()

    def _confirm(self):
        self.on_confirm(self.trans['id'])
        self.win.destroy()

    def _reject(self):
        # Hide popup first, show reason dialog
        self.win.withdraw()
        def on_reason(reason):
            self.on_reject_r(self.trans['id'], reason)
            try: self.win.destroy()
            except: pass

        def on_cancel():
            # Reason dialog cancelled — restore popup
            try: self.win.deiconify()
            except: pass

        dlg = RejectReasonDialog(self.root, self.trans, on_reason)
        # Intercept cancel
        dlg.win.protocol("WM_DELETE_WINDOW", lambda: (dlg.win.destroy(), on_cancel()))

# ─── Dashboard ────────────────────────────────────────────────────────────────

class DashboardWindow:
    def __init__(self, root, server_url, current_user):
        win = tk.Toplevel(root)
        win.title(f"My Asset History — {current_user}")
        win.geometry("880x530")
        win.configure(bg=BG)

        hdr = tk.Frame(win, bg=ACCENT, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📦  My Asset History",
                 bg=ACCENT, fg="white",
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=18, pady=12)
        tk.Label(hdr, text=current_user,
                 bg=ACCENT, fg="#cce4ff",
                 font=("Segoe UI", 9)).pack(side="right", padx=18)

        summary = tk.Frame(win, bg=CARD2, pady=8)
        summary.pack(fill="x", padx=16, pady=(10, 4))
        stat_labels = {}
        for key, label, color in [
            ("pending",   "Pending",   WARNING),
            ("confirmed", "Confirmed", SUCCESS),
            ("rejected",  "Rejected",  DANGER),
        ]:
            f = tk.Frame(summary, bg=CARD2, padx=18)
            f.pack(side="left", padx=8)
            v = tk.Label(f, text="—", bg=CARD2, fg=color,
                         font=("Segoe UI", 20, "bold"))
            v.pack()
            tk.Label(f, text=label, bg=CARD2, fg=SUBTEXT,
                     font=("Segoe UI", 8)).pack(pady=(0, 4))
            stat_labels[key] = v

        s = ttk.Style()
        s.configure("DB.Treeview",
                    background=INPUT_BG, foreground=TEXT,
                    fieldbackground=INPUT_BG, rowheight=28,
                    font=("Segoe UI", 9))
        s.configure("DB.Treeview.Heading",
                    background=ACCENT, foreground="white",
                    font=("Segoe UI", 9, "bold"))
        s.map("DB.Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", "white")])

        cols = ("Asset No.", "Serial No.", "Model", "Type",
                "Direction", "Status", "Rejection Reason", "Logged At")
        frm = tk.Frame(win, bg=BG)
        frm.pack(fill="both", expand=True, padx=16, pady=(4, 16))

        tree = ttk.Treeview(frm, columns=cols, show="headings", style="DB.Treeview")
        for c, w in zip(cols, [90, 90, 130, 80, 80, 110, 180, 130]):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="center")

        sb = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        tree.tag_configure("confirmed", foreground=SUCCESS)
        tree.tag_configure("rejected",  foreground=DANGER)
        tree.tag_configure("pending",   foreground=WARNING)

        p = c2 = r2 = 0
        try:
            resp = api("get", f"{server_url}/transactions",
                       params={"member": current_user})
            if resp.ok:
                for t in resp.json():
                    if   t['confirmed']: status, tag = "✅ Confirmed", "confirmed"; c2 += 1
                    elif t['rejected']:  status, tag = "❌ Rejected",  "rejected";  r2 += 1
                    else:                status, tag = "⏳ Pending",   "pending";   p  += 1

                    def fmt(v):
                        try: return datetime.fromisoformat(v).strftime("%d/%m/%y %H:%M")
                        except: return ""

                    tree.insert("", "end", values=(
                        t.get('asset_number',     ''),
                        t.get('serial_number',    ''),
                        t.get('asset_model',      ''),
                        t.get('asset_type',       ''),
                        "🔴 Out" if t['direction'] == "Out Store" else "🟢 In",
                        status,
                        t.get('rejection_reason', '') or '',
                        fmt(t.get('timestamp', '')),
                    ), tags=(tag,))
        except:
            tk.Label(win, text="⚠  Could not reach server.",
                     bg=BG, fg=DANGER, font=("Segoe UI", 10)).pack(pady=10)

        stat_labels["pending"].config(text=str(p))
        stat_labels["confirmed"].config(text=str(c2))
        stat_labels["rejected"].config(text=str(r2))

# ─── Admin Auth (for Notifier settings) ──────────────────────────────────────

class AdminAuthNotifier:
    def __init__(self, root, server_url, on_success):
        self.server_url = server_url
        self.on_success = on_success

        win = tk.Toplevel(root)
        win.title("Admin Login")
        win.geometry("360x210")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.grab_set()
        win.attributes("-topmost", True)

        tk.Label(win, text="🔐  Admin Authentication",
                 bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(pady=(18, 4), padx=20, anchor="w")
        tk.Label(win, text="Only an admin can change notifier settings.",
                 bg=BG, fg=SUBTEXT,
                 font=("Segoe UI", 9)).pack(padx=20, anchor="w")

        frm = tk.Frame(win, bg=CARD2, padx=20, pady=14)
        frm.pack(fill="x", padx=20, pady=12)
        tk.Label(frm, text="Password", bg=CARD2, fg=SUBTEXT,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 4))
        self.pw_var = tk.StringVar()
        pw_e = tk.Entry(frm, textvariable=self.pw_var,
                        show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                        font=("Segoe UI", 11), insertbackground=TEXT)
        pw_e.pack(fill="x", ipady=8)
        pw_e.focus_set()
        pw_e.bind("<Return>", lambda _: self._verify())

        self.err = tk.Label(win, text="", bg=BG, fg=DANGER, font=("Segoe UI", 9))
        self.err.pack(pady=(0, 4))

        tk.Button(win, text="Login",
                  bg=ACCENT, fg="white",
                  font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2", pady=9,
                  command=self._verify,
                  activebackground=ACCENT2).pack(fill="x", padx=20)

        self.win = win

    def _verify(self):
        try:
            r = api("post", f"{self.server_url}/admin/verify",
                    json={"password": self.pw_var.get()})
            if r.ok and r.json().get("valid"):
                self.win.destroy()
                self.on_success()
            else:
                self.err.config(text="❌  Wrong password.")
        except:
            self.err.config(text="⚠  Cannot reach server.")

# ─── Settings Window (Admin only) ────────────────────────────────────────────

class SettingsWindow:
    def __init__(self, root, cfg, server_url, on_save):
        win = tk.Toplevel(root)
        win.title("Notifier Settings")
        win.geometry("430x380")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.grab_set()

        hdr = tk.Frame(win, bg=ACCENT, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⚙  Notifier Settings  (Admin)",
                 bg=ACCENT, fg="white",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=16, pady=12)

        frm = tk.Frame(win, bg=CARD2, padx=20, pady=16)
        frm.pack(fill="x", padx=20, pady=12)

        def lbl(text):
            tk.Label(frm, text=text, bg=CARD2, fg=SUBTEXT,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 3))

        lbl("Server URL")
        url_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=("Segoe UI", 10), insertbackground=TEXT)
        url_e.insert(0, cfg.get("server_url", ""))
        url_e.pack(fill="x", ipady=8)

        lbl("Assigned User  (this device belongs to)")
        member_cb = ttk.Combobox(frm, values=TEAM_MEMBERS, font=("Segoe UI", 10))
        member_cb.set(cfg.get("current_user", "Engineer 1"))
        member_cb.pack(fill="x", ipady=4)

        lbl("Poll Interval (seconds)")
        poll_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                          font=("Segoe UI", 10), insertbackground=TEXT)
        poll_e.insert(0, str(cfg.get("poll_interval", 30)))
        poll_e.pack(fill="x", ipady=8)

        def save():
            new = {
                "server_url":    url_e.get().strip().rstrip("/"),
                "current_user":  member_cb.get(),
                "poll_interval": int(poll_e.get().strip() or 30),
            }
            save_config(new)
            on_save(new)
            win.destroy()

        tk.Button(win, text="Save",
                  bg=ACCENT, fg="white",
                  font=("Segoe UI", 11, "bold"),
                  relief="flat", cursor="hand2",
                  command=save, pady=10).pack(fill="x", padx=20, pady=8)


# ─── Main Notifier App ────────────────────────────────────────────────────────

class NotifierApp:
    def __init__(self):
        self.cfg          = load_config()
        self.server_url   = self.cfg["server_url"]
        self.current_user = self.cfg["current_user"]
        self.poll_secs    = int(self.cfg.get("poll_interval", 30))
        self.notified_ids = set()
        self.running      = True
        self.tray_icon    = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Asset Notifier")

        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _poll_loop(self):
        self._poll_once()
        while self.running:
            time.sleep(self.poll_secs)
            self._poll_once()

    def _poll_once(self):
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
                for t in pending:
                    if t['id'] not in self.notified_ids:
                        self.notified_ids.add(t['id'])
                        self.root.after(0, lambda tx=t: self._show_popup(tx))
        except: pass

    def _show_popup(self, transaction):
        NotificationPopup(
            self.root, transaction,
            on_confirm=self._confirm,
            on_reject_with_reason=self._reject
        )

    def _confirm(self, tid):
        try: api("post", f"{self.server_url}/confirm/{tid}")
        except: pass
        self.notified_ids.discard(tid)
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _reject(self, tid, reason=""):
        try: api("post", f"{self.server_url}/reject/{tid}",
                 json={"reason": reason})
        except: pass
        self.notified_ids.discard(tid)
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _build_tray(self):
        if not HAS_TRAY: return
        menu = pystray.Menu(
            pystray.MenuItem(f"Asset Notifier  —  {self.current_user}",
                             None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("📋  View My History",  self._open_dashboard),
            pystray.MenuItem("🔔  Check Now",         self._check_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙  Settings (Admin)",  self._open_settings),
            pystray.MenuItem("❌  Exit",              self._quit),
        )
        icon = pystray.Icon("AssetNotifier", make_icon(), "Asset Notifier", menu)
        self.tray_icon = icon
        icon.run()

    def _open_dashboard(self, *_):
        self.root.after(0, lambda: DashboardWindow(
            self.root, self.server_url, self.current_user))

    def _open_settings(self, *_):
        def do_open():
            AdminAuthNotifier(self.root, self.server_url, lambda: SettingsWindow(
                self.root, self.cfg, self.server_url, self._apply_cfg))
        self.root.after(0, do_open)

    def _apply_cfg(self, new_cfg):
        self.cfg          = new_cfg
        self.server_url   = new_cfg["server_url"]
        self.current_user = new_cfg["current_user"]
        self.poll_secs    = int(new_cfg.get("poll_interval", 30))
        self.notified_ids.clear()
        if self.tray_icon:
            self.tray_icon.title = f"Asset Notifier  —  {self.current_user}"
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _check_now(self, *_):
        self.notified_ids.clear()
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _quit(self, *_):
        self.running = False
        if self.tray_icon: self.tray_icon.stop()
        self.root.after(0, self.root.quit)

    def _check_first_run(self):
        """Show setup wizard on first run (when no user is configured yet)."""
        is_first = self.cfg.get("setup_complete") != True
        if is_first:
            self.root.after(400, self._show_setup_wizard)

    def _show_setup_wizard(self):
        """First-run wizard: admin authenticates and picks engineer for this PC."""
        win = tk.Toplevel(self.root)
        win.title("Asset Notifier — First Time Setup")
        win.geometry("420x400")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        # Header
        hdr = tk.Frame(win, bg=ACCENT, height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📦  Asset Notifier — Setup",
                 bg=ACCENT, fg="white",
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=16, pady=14)

        tk.Label(win,
                 text="This is a one-time setup. An admin must complete it.",
                 bg=BG, fg=SUBTEXT,
                 font=("Segoe UI", 9)).pack(pady=(14, 0), padx=20, anchor="w")

        frm = tk.Frame(win, bg=CARD2, padx=20, pady=16)
        frm.pack(fill="x", padx=20, pady=10)

        def lbl(text):
            tk.Label(frm, text=text, bg=CARD2, fg=SUBTEXT,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 3))

        lbl("Server URL")
        url_e = tk.Entry(frm, bg=INPUT_BG, fg=TEXT, relief="flat",
                         font=("Segoe UI", 10), insertbackground=TEXT)
        url_e.insert(0, "https://asset-server:8081")
        url_e.pack(fill="x", ipady=8)

        lbl("Assign this PC to")
        member_cb = ttk.Combobox(frm, values=TEAM_MEMBERS,
                                 state="readonly", font=("Segoe UI", 10))
        member_cb.set(TEAM_MEMBERS[0])
        member_cb.pack(fill="x", ipady=4)

        lbl("Admin Password")
        pw_e = tk.Entry(frm, show="●", bg=INPUT_BG, fg=TEXT, relief="flat",
                        font=("Segoe UI", 10), insertbackground=TEXT)
        pw_e.pack(fill="x", ipady=8)
        pw_e.focus_set()

        err_lbl = tk.Label(win, text="", bg=BG, fg=DANGER, font=("Segoe UI", 9))
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
                r = api("post", f"{server}/admin/verify", json={"password": pw})
                if r.ok and r.json().get("valid"):
                    new_cfg = {
                        "server_url":    server,
                        "current_user":  member,
                        "poll_interval": 30,
                        "setup_complete": True,
                    }
                    save_config(new_cfg)
                    self._apply_cfg(new_cfg)
                    win.destroy()
                    # Show confirmation briefly
                    messagebox.showinfo(
                        "Setup Complete",
                        f"✓  Configured for  {member}\n\n"
                        "The notifier is now running in the system tray."
                    )
                else:
                    err_lbl.config(text="❌  Wrong admin password.", fg=DANGER)
            except Exception:
                err_lbl.config(text="⚠  Cannot reach server. Check the URL.", fg=DANGER)

        tk.Button(win, text="✔  Complete Setup",
                  bg=ACCENT, fg="white",
                  font=("Segoe UI", 11, "bold"),
                  relief="flat", cursor="hand2", pady=10,
                  command=finish,
                  activebackground=ACCENT2).pack(fill="x", padx=20, pady=6)

    def _register_autostart(self):
        if not getattr(sys, 'frozen', False):
            return
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "AssetManagerNotifier", 0, winreg.REG_SZ, sys.executable)
            winreg.CloseKey(key)
        except Exception:
            pass

    def run(self):
        self._register_autostart()
        self._check_first_run()
        if HAS_TRAY:
            threading.Thread(target=self._build_tray, daemon=True).start()
        else:
            self.root.deiconify()
            self.root.configure(bg=BG)
            tk.Label(self.root,
                     text="Asset Notifier is running.\nKeep this window open.",
                     bg=BG, fg=TEXT, font=("Segoe UI", 11)).pack(pady=30, padx=30)
        self.root.mainloop()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = NotifierApp()
    app.run()
