r"""Who terminates TLS, what the status card says, the tray it paints.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import json
import os
import re
import sys
import time

from server_checks.console import open_section_entry
from server_checks.stage import (GM, IIS_SRC, IM, M, SRC_ALL, SRC_ALL_IIS,
                                 _call_name, _code, bad, eq, fresh_db,
                                 gui_root, head, ok, skip, tk_or_skip,
                                 widgets)



# ── the status card names this machine ────────────────────

def check_the_server_url_names_the_machine_it_runs_on():
    """The Server GUI's server_url is built from the machine's own name.

    It was the literal "asset-server", so every install anywhere else showed
    a URL naming a machine that is not this one - and Copy URL put that on the
    clipboard for an operator to hand to clients. A source check because
    run_gui draws a window no harness opens far enough to read the string back
    off, and because what is asserted is the absence of a literal.

    `host` from server_config.json is not the answer either and never was: it
    is the bind address, 0.0.0.0 by default, which is not a name anything can
    be reached by. So a host literal and a read of that setting both fail here.
    """
    head("the server URL names the machine it runs on")
    tree = ast.parse(SRC_ALL)
    fns = {f.name: f for f in ast.walk(tree)
           if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}

    assigns = [n for n in ast.walk(fns["run_gui"]) if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "server_url"
                       for t in n.targets)]
    eq("run_gui builds server_url exactly once", len(assigns), 1)
    if not assigns:
        return
    src = ast.unparse(assigns[0].value)
    literals = [n.value for n in ast.walk(assigns[0].value)
                if isinstance(n, ast.Constant)]

    if "hostname" in src:
        ok("from hostname, which is this machine's own name")
    else:
        bad("server_url is not built from hostname: %s" % src)

    if any(isinstance(v, str) and "asset-server" in v for v in literals):
        bad("server_url carries a hardcoded server name: %s" % src)
    else:
        ok("and carries no hardcoded server name")

    if "host" in literals:
        bad("server_url reads the bind address, 0.0.0.0 by default: %s" % src)
    else:
        ok("and does not read the bind address")

    # What it is built from, asserted where that is set rather than taken on
    # trust: the Host chip beside the URL reads the same name, so the two
    # cannot come to disagree about which machine the card is describing.
    host = [n for n in ast.walk(fns["run_gui"]) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "hostname"
                    for t in n.targets)]
    eq("hostname is set once", len(host), 1)
    if host:
        eq("and it is the machine's own name",
           ast.unparse(host[0].value), "socket.gethostname()")



def check_the_gui_says_when_iis_owns_the_process():
    """Once IIS hosts the server, the window says so and stops offering to stop it.

    install-iis.ps1 stops and disables the AssetManagerServer service, because
    two listeners cannot share one port (ADR-0001). Nothing in the product said
    so, and three things in the Server GUI went on assuming this process was
    the server: the banner looked identical to a serving one, the tray's Quit
    offered to stop a server that would go on serving, and Server Settings
    reported a save that applies nothing - the port under IIS is the site
    binding.

    iis.json is the one signal, so the first half of this group is about what
    that helper does with a file it cannot read. The wrong answer it can give
    is "not IIS" on a machine IIS hosts, and the likeliest route to it is the
    BOM Windows PowerShell 5.1 writes - so both byte-for-byte files
    install-iis.ps1 has produced are cases: the no-BOM one it writes since
    054, and the BOM'd one every install before that keeps until somebody
    re-runs it.

    The second half opens the real window, because a dialog carrying a written
    size is exactly where added text would be lost: Server Settings carries no
    written size at all any more (#125), asking ui_kit.fit for it instead, and
    the branch this ticket added text to is one no other group here reaches -
    every other run of this file has no iis.json beside the staged server,
    which is also the regression worth proving, so the window is opened both
    ways.
    """
    head("the GUI says when IIS owns the process")

    path = M.IIS_STATE_PATH

    def answer(body):
        if body is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with io.open(path, "wb") as fh:
                fh.write(body)
        return M._iis_host()

    state = {"site": "AssetManager", "app_pool": "AssetManagerPool",
             "port": 8081, "cert_thumbprint": "AB12",
             "install_dir": "C:\\AssetManager", "configured_at": "2026-09-12"}
    body = json.dumps(state).encode("utf-8")
    try:
        eq("no iis.json is not IIS", answer(None), None)
        eq("an empty file is not IIS", answer(b""), None)
        eq("bytes that are not JSON are not IIS", answer(b"<not json>"), None)
        eq("JSON that is not an object is not IIS",
           answer(b'["AssetManagerPool"]'), None)
        eq("the no-BOM file install-iis.ps1 writes is IIS", answer(body), state)
        # Set-Content -Encoding UTF8 means UTF-8 *with* a BOM under Windows
        # PowerShell 5.1, and that is what install-iis.ps1 wrote this file
        # with until 054. Fixing the writer rewrites nothing already on disk,
        # so every install made before it keeps its BOM - and a plain open()
        # raises on that, which _iis_host would report as "not IIS" on every
        # one of those machines.
        eq("and so is the same file carrying the BOM an older install left",
           answer(b"\xef\xbb\xbf" + body), state)
    finally:
        answer(None)

    # One signal, read in one place. A second reader is a second answer to a
    # question that already has one, and the three surfaces below would then be
    # free to disagree about who is hosting. IIS_STATE_PATH and _iis_host are
    # server_iis.py's since #243 - server.py's own text carries only the
    # bind() call handing the path over, so the load count below is read off
    # IIS_SRC alone rather than off server.py.
    iis_tree = ast.parse(IIS_SRC)
    iis_fns = {f.name: f for f in ast.walk(iis_tree)
               if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    loads = [n for n in ast.walk(iis_tree) if isinstance(n, ast.Name)
             and n.id == "IIS_STATE_PATH" and isinstance(n.ctx, ast.Load)]
    eq("server_iis.py reads iis.json in exactly one place", len(loads), 1)
    if "_iis_host" not in iis_fns:
        bad("there is no _iis_host in server_iis.py")
        return
    inside = [n for n in ast.walk(iis_fns["_iis_host"])
              if isinstance(n, ast.Name) and n.id == "IIS_STATE_PATH"]
    eq("and that place is _iis_host", len(inside), 1)
    tree = ast.parse(SRC_ALL)
    fns = {f.name: f for f in ast.walk(tree)
           if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    asks = [n for n in ast.walk(fns["run_gui"]) if isinstance(n, ast.Call)
            and _call_name(n.func) == "_iis_host"]
    eq("run_gui asks it once, for all three surfaces", len(asks), 1)

    tk = tk_or_skip()
    if tk is None:
        return
    fresh_db()

    def banner_lines(root):
        return [str(w.cget("text")) for w in widgets(root)
                if w.winfo_class() == "Label"
                and "Hosted by IIS" in str(w.cget("text"))]

    def host_port(root):
        """Open Server Settings off the console's System section, and measure it.

        Off the action row until 077 deleted it. `open_section_entry` is
        `server_checks.console`'s, and it is imported rather than repeated
        because putting a section on the stage before clicking a row on it is
        the console's own idiom and not this group's subject.
        """
        before = {str(w) for w in widgets(root) if isinstance(w, tk.Toplevel)}
        if not open_section_entry(tk, root, "System", "Server Settings"):
            bad("no Server Settings entry on the console's System section")
            return
        new = [w for w in widgets(root)
               if isinstance(w, tk.Toplevel) and str(w) not in before]
        if not new:
            bad("Server Settings opened no window")
            return
        dlg = new[-1]
        dlg.update_idletasks()
        w, h = dlg.winfo_width(), dlg.winfo_height()
        rw, rh = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        if rh > h or rw > w:
            bad("Server Settings is %dx%d of its children's %dx%d - a "
                "button is what pack squeezes out"
                % (w, h, rw, rh))
        else:
            ok("Server Settings: %dx%d holds its children's %dx%d"
               % (w, h, rw, rh))
        try:
            dlg.destroy()
        except Exception:
            pass

    # A server with no iis.json has to look exactly as it did. This is the
    # regression the whole ticket is measured against, so it is asserted rather
    # than left to the rest of this file happening to run that way.
    root = gui_root(tk)
    try:
        eq("with no iis.json the banner says nothing about a host",
           banner_lines(root), [])
        host_port(root)
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    answer(body)
    try:
        root = gui_root(tk)
        try:
            lines = banner_lines(root)
            eq("with one, the banner says who is hosting", len(lines), 1)
            if lines:
                for want in ("Hosted by IIS", state["site"],
                             "Stop-WebAppPool", state["app_pool"]):
                    if want in lines[0]:
                        ok("and names %r" % want)
                    else:
                        bad("the banner line does not name %r: %r"
                            % (want, lines[0]))
            # The branch nothing else here reaches. The label it adds is three
            # wrapped lines where the old one was one, in a window ui_kit.fit
            # sizes rather than one carrying a written geometry.
            host_port(root)
        finally:
            try:
                root.destroy()
            except Exception:
                pass
    finally:
        answer(None)


def _tray_stub():
    """A pystray that records the icons it is asked to build.

    The same shape check_the_tray_says_what_the_banner_says uses - the real
    Icon.run blocks its thread, and run_gui starts it daemonised and never
    joins it.
    """
    made = []

    class _Icon(object):
        def __init__(self, name, image, title, menu=None):
            self.icon = image
            self.title = title
            made.append(self)

        def run(self):
            time.sleep(2)

        def stop(self):
            pass

    class _Menu(list):
        SEPARATOR = object()

        def __init__(self, *items):
            list.__init__(self, items)

    class _Stub(object):
        Icon = _Icon
        Menu = _Menu

        @staticmethod
        def MenuItem(*a, **kw):
            return (a, kw)

    return _Stub, made


def _probe_stub():
    """A `_loopback_get` that answers nothing and records what it was asked.

    The liveness probe inside refresh_stats hands `_loopback_get` a TLS
    context or none, so what it asks over is a fact only that call can
    report: the scheme is the banner's protocol decision made visible. It
    stubbed `requests` wholesale until #280, which is how a probe that could
    not complete a handshake against a self-signed certificate went on
    passing here - the transport is exercised for real by
    check_the_console_probes_answer_over_a_self_signed_listener below.
    """
    asked = []

    def _get(path, ctx=None):
        asked.append("%s://127.0.0.1:%d%s"
                     % ("https" if ctx is not None else "http", M.PORT, path))
        return None

    return _get, asked


def _health_fill(root):
    """The health mark's fill, found by the two colours only it takes.

    A ring around the banner until 077, which put the status on the
    app bar instead: a word and an 8px block, and the block is a
    canvas rectangle rather than a ringed frame. Matched on the
    value and on the item type, not on the 8px - every groove on
    this window is 1px and a pill is a canvas too, so the rectangle
    painted SUCCESS or DANGER is the one thing this can be.
    """
    for w in widgets(root):
        if w.winfo_class() != "Canvas":
            continue
        for item in w.find_all():
            if w.type(item) != "rectangle":
                continue
            fill = str(w.itemcget(item, "fill"))
            if fill in (str(GM.SUCCESS), str(GM.DANGER)):
                return fill
    return None


def check_the_banner_reads_who_terminates_tls():
    """Under IIS the window has to read the binding, not this install's files.

    `ssl_enabled` in server_config.json has exactly one writer - the Server
    GUI's own SSL Certificate install - and install-iis.ps1 is not it. So on
    the supported deployment (ADR-0001) that key is false while the site in
    front of this process is serving https, and under -PfxPath or
    -CertThumbprint there is no ssl_key.pem on the machine at all: the pair
    of files the banner was asking for correctly is not there.

    What that cost was both surfaces at once. The banner and the tray said
    HTTP over an HTTPS site, and the liveness probe beside them fired
    http://127.0.0.1:443/stats at a TLS listener, failed, and reported a
    healthy server as NOT RESPONDING - which is what a production console
    was showing. The server already answered this question correctly one
    function over, in _remote_tls_ok; the window simply did not ask it.

    Driven over the probe's own `_loopback_get`, because the scheme it asks
    over is the protocol decision made visible and nothing else reports it, and
    with the tray on, because the tooltip is where the word is readable on
    the offline branch. The production state is staged exactly: a thumbprint
    in iis.json, `ssl_enabled` false, ssl_cert.pem on disk and **no
    ssl_key.pem**.

    The fifth state is #185's, and is the one that record cannot describe: an
    IIS site that is serving TLS while iis.json names no thumbprint, which is
    every certificate bound by anything other than install-iis.ps1 - in IIS
    Manager, after that script ran, or on a site it never ran against. The
    port probe is stubbed rather than listened for, in every case and not only
    that one, so what each case asserts is the decision and never this
    machine's own port; that the probe is a handshake and is asked from one
    place is the source group below.
    """
    head("the banner reads who is terminating TLS")
    tk = tk_or_skip()
    if tk is None:
        return
    import ui_kit
    if not ui_kit.HAS_PIL:
        skip("pillow is not installed - there is no tray tooltip to read")
        return

    stub, made = _tray_stub()
    probe_get, asked = _probe_stub()

    bound = {"site": "AssetManager", "app_pool": "AssetManagerPool",
             "cert_thumbprint": "AB12"}
    unbound = {"site": "AssetManager", "app_pool": "AssetManagerPool"}

    was = (M.PORT, M.HAS_TRAY, getattr(M, "pystray", None), IM._iis_host,
           dict(M._SERVER_CFG), IM._port_serves_tls, GM._loopback_get)
    M.pystray = stub
    # A port nothing serves, for check_the_tray_says_what_the_banner_says'
    # reason: this gate runs on machines where the real server is up.
    M.PORT = 59999
    GM._loopback_get = probe_get
    fresh_db()

    def files(cert, key):
        for path, want in ((M.SSL_CERT_PATH, cert), (M.SSL_KEY_PATH, key)):
            if want:
                with io.open(path, "w", encoding="utf-8") as fh:
                    fh.write("not a certificate, and nothing reads it here")
            elif os.path.exists(path):
                os.remove(path)

    def case(label, iis, enabled, cert, key, scheme, word, probe=False):
        IM._iis_host = lambda: iis
        IM._port_serves_tls = lambda: probe
        M._SERVER_CFG["ssl_enabled"] = enabled
        files(cert, key)
        del asked[:]
        del made[:]
        root = None
        try:
            root = gui_root(tk, tray=True)
            # refresh_stats is scheduled 1.5s out and is both the probe and
            # what calls set_health. Pumped rather than slept through, the
            # probe running on this same thread.
            # The icon is constructed on a daemon thread, so `made` can be
            # filled before _tray_icon[0] is assigned and set_health then
            # has nothing to write to. What is waited for is the title
            # leaving CHECKING, which is the write itself. The deadline is
            # generous because that thread competes with this one for the
            # GIL on a machine running the rest of this suite: at 15s the
            # first case failed with no icon built at all, on a run that
            # passed on its own and passed again afterwards, which is a
            # gate reporting the load it was run under.
            def titled():
                return bool(asked and made
                            and "CHECKING" not in (made[0].title or ""))

            deadline = time.time() + 60
            while time.time() < deadline and not titled():
                root.update_idletasks()
                root.update()
                time.sleep(0.05)
            if not asked:
                bad("%s: the probe never ran - nothing below is a check"
                    % label)
                return
            if not made:
                bad("%s: no tray icon was built - the tooltip cannot be read"
                    % label)
                return
            eq("%s: the probe asks over %s" % (label, scheme),
               asked[0].split("://")[0], scheme)
            title = made[0].title or ""
            if "(%s)" % word in title:
                ok("%s: and the tray says %s" % (label, word))
            else:
                bad("%s: the tray says %r where it has to say (%s)"
                    % (label, title, word))
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    try:
        # The production state, and the one that was wrong both ways.
        case("an IIS site with a certificate bound", bound, False, True, False,
             "https", "HTTPS")
        # An iis.json naming no thumbprint and a port that answers nothing
        # is a site nothing was bound to, which is what that record used to
        # be taken to mean on its own.
        case("an IIS site with nothing bound", unbound, False, True, False,
             "http", "HTTP")
        # And #185: the same record over a port that does answer a handshake,
        # which is every certificate install-iis.ps1 did not bind. The record
        # is the only thing that changed here; what the site is doing did not.
        case("an IIS site serving TLS that iis.json has no thumbprint for",
             unbound, False, True, False, "https", "HTTPS", probe=True)
        # Off IIS the expression is exactly what it was, both ways: the
        # Service and the hand-started launcher bind their own listener, and
        # those two files are what says whether it is a TLS one.
        case("off IIS with ssl_enabled and both files", None, True, True, True,
             "https", "HTTPS")
        case("off IIS with neither", None, False, True, False, "http", "HTTP")
    finally:
        files(False, False)
        M.PORT, M.HAS_TRAY, M.pystray, IM._iis_host = was[:4]
        M._SERVER_CFG.clear()
        M._SERVER_CFG.update(was[4])
        IM._port_serves_tls = was[5]
        GM._loopback_get = was[6]


def check_the_protocol_is_decided_in_one_place():
    """One function answers the IIS half, and both callers ask it.

    A source check because what is claimed is an absence: no second spelling
    of "is this connection encrypted" anywhere in the window. The defect was
    rule 10's, with the wrong copy being the one an operator reads -
    _remote_tls_ok consulted iis.json and was right, while the banner, the
    tray and the liveness probe each consulted server_config.json and the
    pem files and were wrong together on the supported deployment.

    The probe is the sharpest half of it: it re-read those files every five
    seconds, so the scheme it asked over was free to differ from the scheme
    the banner it sets was reporting.
    """
    head("the protocol is decided in one place")
    tree = ast.parse(SRC_ALL_IIS)
    fns = {f.name: f for f in ast.walk(tree)
           if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("_iis_tls_bound", "_remote_tls_ok", "run_gui"):
        if name not in fns:
            bad("there is no %s in server.py" % name)
            return

    inside = [n for n in ast.walk(fns["_iis_tls_bound"])
              if isinstance(n, ast.Call)
              and getattr(n.func, "id", "") == "_iis_host"]
    eq("_iis_tls_bound is the one that reads the binding", len(inside), 1)

    # And since #185 the one that asks the machine, where that record says
    # nothing. Same rule as the line above and the sharper half of it: the
    # probe opens a socket, so a second caller is a second handshake against
    # this server's own port on a schedule nobody wrote down.
    if "_port_serves_tls" not in fns:
        bad("there is no _port_serves_tls in server.py - iis.json's "
            "cert_thumbprint has one writer and cannot be the whole answer")
    else:
        probes = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and getattr(n.func, "id", "") == "_port_serves_tls"]
        eq("_port_serves_tls is called from exactly one place",
           len(probes), 1)
        asked_in = [n for n in ast.walk(fns["_iis_tls_bound"])
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") == "_port_serves_tls"]
        eq("and that place is _iis_tls_bound", len(asked_in), 1)
        # A handshake and nothing else: the probe sends no request and reads
        # nothing back, which is what makes verifying nothing honest rather
        # than rule 1 turned off. A `requests` call here would be neither.
        inner_probe = _code(fns["_port_serves_tls"])
        for spelling in ("requests", "urllib", "/stats", "GET"):
            if spelling in inner_probe:
                bad("_port_serves_tls reaches for %r - it is a handshake, "
                    "not a request" % spelling)
            else:
                ok("the probe carries no %r" % spelling)

    for name in ("_remote_tls_ok", "run_gui"):
        asks = [n for n in ast.walk(fns[name]) if isinstance(n, ast.Call)
                and _call_name(n.func) == "_iis_tls_bound"]
        eq("%s asks it once" % name, len(asks), 1)

    body = _code(fns["run_gui"])
    eq("run_gui reads ssl_enabled once, where _ssl_active is worked out",
       body.count("ssl_enabled"), 1)

    probe = [f for f in ast.walk(fns["run_gui"])
             if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
             and f.name == "refresh_stats"]
    eq("the liveness probe is still there", len(probe), 1)
    if not probe:
        return
    inner = _code(probe[0])
    for spelling in ("ssl_enabled", "SSL_KEY_PATH", "_iis_tls_bound"):
        if spelling in inner:
            bad("refresh_stats decides the protocol for itself, on %r - it "
                "has to ask the banner's own _ssl_active" % spelling)
        else:
            ok("the probe carries no %r of its own" % spelling)
    if "_ssl_active" not in inner:
        bad("refresh_stats does not read _ssl_active at all")
    else:
        ok("and reads _ssl_active, which is what the banner says")

    # #186. Having got the scheme right, the probe then refused the
    # handshake: it pinned SSL_CERT_PATH as its own anchor under
    # CERT_REQUIRED, which is the certificate this process would have bound
    # and not the one an IIS site presents - and under -PfxPath that file is
    # not on the machine at all, leaving CERT_REQUIRED against an empty
    # store. Either way a healthy server was captioned NOT RESPONDING, which
    # is #176's defect one step further along. Both halves are asserted,
    # because the second is what the first rests on: it verifies nothing,
    # and nothing authenticated is asked over it.
    for spelling in ("CERT_REQUIRED", "load_verify_locations", "SSL_CERT_PATH"):
        if spelling in inner:
            bad("the liveness probe reaches for %r - it is a loopback "
                "liveness check and the certificate an IIS site presents is "
                "not this install's own file (#186)" % spelling)
        else:
            ok("the probe pins no certificate of its own (%s)" % spelling)
    if "CERT_NONE" not in inner:
        bad("the liveness probe does not say CERT_NONE - it has to state "
            "what it verifies rather than leave it to a default")
    else:
        ok("and says CERT_NONE outright")
    # The whole of why CERT_NONE is safe here. A credential over this
    # session would make it a client trusting a server, which is rule 1 and
    # is exactly what this is not.
    # And the transport both probes share since #280, which is where a
    # header would be added - and which must never hand `requests` a falsy
    # verify, in whatever spelling: capabilities.py's common.py check found
    # a setdefault the bare literal missed, so this is its pattern.
    helper = [f for f in ast.walk(tree)
              if isinstance(f, ast.FunctionDef) and f.name == "_loopback_get"]
    eq("the probes share one transport, _loopback_get", len(helper), 1)
    carried = _code(helper[0]) if helper else ""
    for where, text in (("the liveness probe", inner),
                        ("_loopback_get", carried)):
        for spelling in ("password", "auth=", "_authorise", "capability",
                         "headers"):
            if spelling in text:
                bad("%s carries %r - nothing authenticated may cross a "
                    "session that verifies nothing (#186)" % (where, spelling))
            else:
                ok("%s carries no %r" % (where, spelling))
        if re.search(r"verify\W{0,6}False", text):
            bad("%s hands requests a falsy verify - rule 1" % where)
        else:
            ok("%s hands requests no falsy verify" % where)


def check_the_tray_icon_is_rebuilt_only_when_the_answer_changed():
    """set_health redraws the tray icon when it has a different answer.

    The icon is drawn at 4x and resampled - app_icon(64) is composed at 256
    - and set_health runs on the Tk thread on every tick, so an icon rebuilt
    every five seconds is that work standing between the window and its own
    repaint for the life of the console. The answer it is drawn from changes
    perhaps twice a day.

    The first call is still a write, and has to be: that is what takes the
    tray off the CHECKING icon it was constructed with. What is measured
    here is the ticks after it.
    """
    head("the tray icon is rebuilt only when the answer changed")
    tk = tk_or_skip()
    if tk is None:
        return
    import ui_kit
    if not ui_kit.HAS_PIL:
        skip("pillow is not installed - there is no tray icon to rebuild")
        return

    stub, made = _tray_stub()
    calls = []
    ticks = []
    real_icon = M._make_server_tray_icon
    # The tick is counted at `_gui_snapshot` rather than at
    # `_client_rows` (#205): the CLIENTS box that called the second one
    # per tick went with the side panel, while the first is what
    # `refresh_feed` reads on every tick to decide whether the table has
    # moved - so it is called whether or not anything did, which is what
    # a tick counter needs.
    real_tick = M._gui_snapshot

    def _spy_icon(online=None):
        calls.append(online)
        return real_icon(online)

    def _spy_tick(limit=18):
        ticks.append(1)
        return real_tick(limit)

    was = (M.PORT, M.HAS_TRAY, getattr(M, "pystray", None),
           dict(M._SERVER_CFG))
    M.pystray = stub
    M.PORT = 59999
    M._SERVER_CFG["refresh_secs"] = 2
    M._make_server_tray_icon = _spy_icon
    M._gui_snapshot = _spy_tick
    fresh_db()
    root = None
    try:
        root = gui_root(tk, tray=True)
        deadline = time.time() + 20
        while time.time() < deadline and len(calls) < 2:
            root.update_idletasks()
            root.update()
            time.sleep(0.05)
        if len(calls) < 2:
            bad("set_health never took the tray off CHECKING - nothing "
                "below is a check")
            return
        eq("the icon opens with no state asked for", calls[0], None)
        eq("and set_health draws it once the probe has answered",
           calls[1], False)

        want = len(ticks) + 3
        deadline = time.time() + 30
        while time.time() < deadline and len(ticks) < want:
            root.update_idletasks()
            root.update()
            time.sleep(0.05)
        if len(ticks) < want:
            bad("the window stopped ticking")
            return
        eq("and three more ticks with the same answer draw nothing",
           len(calls), 2)
        if made:
            title = made[0].title or ""
            if "NOT RESPONDING" in title:
                ok("with the tooltip still saying what the banner says")
            else:
                bad("the tray says %r" % title)
    finally:
        M._make_server_tray_icon = real_icon
        M._gui_snapshot = real_tick
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        M.PORT, M.HAS_TRAY, M.pystray = was[:3]
        M._SERVER_CFG.clear()
        M._SERVER_CFG.update(was[3])


def check_a_quiet_tick_paints_nothing():
    """A five-second tick with nothing to say must render nothing at all.

    #176 answered two of the three surfaces that repainted unconditionally -
    the CLIENTS box and the tray icon - and left the third: `set_health` wrote
    all five of its widgets on every tick, and one of them was `banner`, a
    canvas cut out of the render. Configuring a `tk.Canvas` at all re-asserts
    its own `-width`/`-height` over the size `pack` propagated into it, `pack`
    puts it back on the next idle pass, and both hops are a `<Configure>`, so
    the tick armed a full-window composite from inside itself.

    074 deleted the render, and the banner is a `tk.Frame` now, so that half
    of the count has no counter left to keep. What is still countable is the
    other surface #176 answered and the reason this guard was written at all:
    `tk.PhotoImage`, which is the tray icon, and it has to be **zero** on a
    quiet server. It was ten per tick. The guard in `set_health` stays either
    way - it is what keeps five widget writes off a tick that has nothing to
    say - and the second half below is what holds it honest.

    Driven in the mode production runs in (ADR-0001): a real listener owns the
    port, so this window is the monitor-only one and its tick is the probe
    plus a table read, and `_iis_host` answers so the banner is the one an
    operator is actually looking at. Both halves, since a banner that never
    repaints is the worse bug - it is the surface that says whether the server
    is up - so the listener is then taken away and the answer has to move.
    """
    head("a quiet tick paints nothing")
    tk = tk_or_skip()
    if tk is None:
        return
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Stats(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"total":7,"pending":2,"confirmed":4,"out_now":3}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    port = 59997
    try:
        httpd = HTTPServer(("127.0.0.1", port), _Stats)
    except OSError as ex:
        skip("port %d could not be taken (%s)" % (port, ex))
        return
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    images = []
    ticks = []
    real_photo = tk.PhotoImage.__init__
    # The tick is counted at `_gui_snapshot` rather than at
    # `_client_rows` (#205): the CLIENTS box that called the second one
    # per tick went with the side panel, while the first is what
    # `refresh_feed` reads on every tick to decide whether the table has
    # moved - so it is called whether or not anything did, which is what
    # a tick counter needs.
    real_tick = M._gui_snapshot

    def _spy_photo(self, *a, **kw):
        images.append(1)
        return real_photo(self, *a, **kw)

    def _spy_tick(limit=18):
        ticks.append(1)
        return real_tick(limit)

    was = (M.PORT, IM._iis_host, dict(M._SERVER_CFG))
    M.PORT = port
    IM._iis_host = lambda: {"site": "AssetManager",
                            "app_pool": "AssetManagerPool"}
    M._SERVER_CFG["refresh_secs"] = 2
    # The tick counter goes on before the window opens - the first tick is
    # what settles the banner, and nothing below can wait for it otherwise.
    # The two render spies go on after it, the layout storm behind that first
    # tick being a real render.
    M._gui_snapshot = _spy_tick
    fresh_db()
    root = None
    try:
        root = gui_root(tk)

        def pump(n, settle=0.0):
            want = len(ticks) + n
            deadline = time.time() + 30
            while time.time() < deadline and len(ticks) < want:
                root.update_idletasks()
                root.update()
                time.sleep(0.02)
            end = time.time() + settle
            while time.time() < end:
                root.update_idletasks()
                root.update()
                time.sleep(0.02)
            return len(ticks) >= want

        def banner_ring():
            return _health_fill(root)

        # The first tick is the one that takes the banner off what it was
        # built as, and the layout storm behind it is a real render. What is
        # measured is the ticks after that.
        if not pump(1, settle=0.6):
            skip("the refresh tick never ran - nothing below is a check")
            return
        if banner_ring() != GM.SUCCESS:
            bad("the banner never went green over a port that is answering "
                "- nothing below is a check")
            return
        ok("the banner drew the answer the probe came back with")

        tk.PhotoImage.__init__ = _spy_photo
        if not pump(2, settle=0.6):
            bad("the window stopped ticking")
            return
        eq("two ticks over an unchanged answer render nothing",
           len(images), 0)

        httpd.shutdown()
        if not pump(2, settle=0.6):
            bad("the window stopped ticking")
            return
        if banner_ring() != GM.DANGER:
            bad("the banner still reads %r over a port that stopped "
                "answering - the guard is holding a different answer from "
                "the surface it is guarding" % banner_ring())
        else:
            ok("and an answer that moved still repaints the banner")
    finally:
        tk.PhotoImage.__init__ = real_photo
        M._gui_snapshot = real_tick
        try:
            httpd.shutdown()
        except Exception:
            pass
        httpd.server_close()
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        M.PORT, IM._iis_host = was[0], was[1]
        M._SERVER_CFG.clear()
        M._SERVER_CFG.update(was[2])


def check_the_console_probes_answer_over_a_self_signed_listener():
    """Both loopback probes get their answer out of a real self-signed port.

    #280. Both probes built a CERT_NONE context and handed it to a
    `requests` HTTPAdapter, and requests 2.32 put cert_reqs=CERT_REQUIRED
    back over it on every request. So behind IIS on a self-signed
    certificate the banner read NOT RESPONDING over a healthy server, and
    _port_locked answered False whatever /health said. The banner group
    above could not see it: it stubbed `requests` wholesale and asserted a
    URL and the word CERT_NONE, never a handshake. This one stands up a
    listener on a certificate minted just now, which nothing on this
    machine trusts, and asks both probes through it - and each answer is
    asserted both ways, so a probe that has stopped asking cannot pass.
    """
    head("the console's probes answer over a self-signed listener")
    tk = tk_or_skip()
    if tk is None:
        return
    import contextlib
    import shutil
    import ssl
    import tempfile
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from _devtools import make_cert

    served = {"port_locked": True}

    class _Answer(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                doc = {"status": "ok", "port_locked": served["port_locked"]}
            else:
                doc = {"total": 7, "pending": 2, "confirmed": 4, "out_now": 3}
            body = json.dumps(doc).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    tmp = tempfile.mkdtemp()
    cert, key = os.path.join(tmp, "cert.pem"), os.path.join(tmp, "key.pem")
    try:
        # It prints the paths it wrote, which is its command line's output
        # and not a line this suite's run should carry.
        with contextlib.redirect_stdout(io.StringIO()):
            make_cert(cert, key)
    except ImportError as ex:
        shutil.rmtree(tmp, ignore_errors=True)
        skip("cryptography is not installed (%s)" % ex)
        return
    port = 59996
    try:
        httpd = HTTPServer(("127.0.0.1", port), _Answer)
    except OSError as ex:
        shutil.rmtree(tmp, ignore_errors=True)
        skip("port %d could not be taken (%s)" % (port, ex))
        return
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(cert, key)
    httpd.socket = sctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    ticks = []
    real_tick = M._gui_snapshot

    def _spy_tick(limit=18):
        ticks.append(1)
        return real_tick(limit)

    was = (M.PORT, IM._iis_host, dict(M._SERVER_CFG), IM._port_serves_tls)
    M.PORT = port
    # The production state: a thumbprint in iis.json and no ssl_enabled, so
    # _ssl_active is the binding's answer and the probe asks over https.
    IM._iis_host = lambda: {"site": "AssetManager",
                            "app_pool": "AssetManagerPool",
                            "cert_thumbprint": "AB12"}
    IM._port_serves_tls = lambda: False
    M._SERVER_CFG.pop("ssl_enabled", None)
    M._SERVER_CFG["refresh_secs"] = 2
    M._gui_snapshot = _spy_tick
    fresh_db()
    root = None
    try:
        port_locked = sys.modules["gui_settings"]._port_locked
        eq("_port_locked reads port_locked over the listener",
           port_locked(), True)
        served["port_locked"] = False
        eq("and reads False when False is what it serves",
           port_locked(), False)

        root = gui_root(tk)

        def pump(n):
            want = len(ticks) + n
            deadline = time.time() + 30
            while time.time() < deadline and len(ticks) < want:
                root.update_idletasks()
                root.update()
                time.sleep(0.02)
            return len(ticks) >= want

        if not pump(1):
            bad("the refresh tick never ran - nothing below is a check")
            return
        eq("refresh_stats reads a self-signed port as RUNNING",
           _health_fill(root), str(GM.SUCCESS))
        httpd.shutdown()
        if not pump(2):
            bad("the window stopped ticking")
            return
        eq("and NOT RESPONDING once the port stops answering",
           _health_fill(root), str(GM.DANGER))
    finally:
        M._gui_snapshot = real_tick
        try:
            httpd.shutdown()
        except Exception:
            pass
        httpd.server_close()
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        M.PORT, IM._iis_host = was[0], was[1]
        M._SERVER_CFG.clear()
        M._SERVER_CFG.update(was[2])
        IM._port_serves_tls = was[3]
        shutil.rmtree(tmp, ignore_errors=True)


def check_the_ssl_panel_reads_who_terminates_tls():
    """Server Settings' SSL Certificate status asks the binding under IIS.

    #280, and #176/#185's defect in the one surface they missed: the panel
    read `ssl_enabled` and ssl_cert.pem alone, and under IIS nothing writes
    that key while under -PfxPath or -CertThumbprint that file may rightly
    be absent - so an HTTPS site read "Inactive (HTTP)". The states are the
    ones the banner group stages, read off the real window; the two off-IIS
    cases are the regression, the expression there being exactly what it
    was. iis.json is written rather than `_iis_host` stubbed, because the
    window asks server.py's own imported name for it, which a stub on
    server_iis does not reach.
    """
    head("the SSL Certificate panel reads who is terminating TLS")
    tk = tk_or_skip()
    if tk is None:
        return

    bound = {"site": "AssetManager", "app_pool": "AssetManagerPool",
             "cert_thumbprint": "AB12"}
    unbound = {"site": "AssetManager", "app_pool": "AssetManagerPool"}

    def iis_file(state):
        if state is None:
            if os.path.exists(M.IIS_STATE_PATH):
                os.remove(M.IIS_STATE_PATH)
        else:
            with io.open(M.IIS_STATE_PATH, "w", encoding="utf-8") as fh:
                json.dump(state, fh)

    def cert_file(present):
        if present:
            with io.open(M.SSL_CERT_PATH, "w", encoding="utf-8") as fh:
                fh.write("not a certificate, and nothing reads it here")
        elif os.path.exists(M.SSL_CERT_PATH):
            os.remove(M.SSL_CERT_PATH)

    def status(root):
        before = {str(w) for w in widgets(root) if isinstance(w, tk.Toplevel)}
        if not open_section_entry(tk, root, "System", "Server Settings"):
            return "no Server Settings entry on the System section"
        new = [w for w in widgets(root)
               if isinstance(w, tk.Toplevel) and str(w) not in before]
        if not new:
            return "Server Settings opened no window"
        said = [str(w.cget("text")) for w in widgets(new[-1])
                if w.winfo_class() == "Label"
                and str(w.cget("text")).startswith("Status:")]
        try:
            new[-1].destroy()
        except Exception:
            pass
        return said[0].split(":", 1)[1].strip() if said else "no Status line"

    was = (M.PORT, dict(M._SERVER_CFG), IM._port_serves_tls)
    # A port nothing serves: the window's own probe must not reach a real
    # server on the machine running this gate.
    M.PORT = 59999
    IM._port_serves_tls = lambda: False
    fresh_db()
    root = None
    try:
        root = gui_root(tk)
        for label, iis, enabled, cert, want in (
                ("an IIS site with a certificate bound and no ssl_cert.pem",
                 bound, None, False, "Active (HTTPS)"),
                ("an IIS site with nothing bound", unbound, None, True,
                 "Inactive (HTTP)"),
                ("off IIS with ssl_enabled and the certificate", None, True,
                 True, "Active (HTTPS)"),
                ("off IIS with no ssl_enabled", None, None, True,
                 "Inactive (HTTP)")):
            iis_file(iis)
            M._SERVER_CFG.pop("ssl_enabled", None)
            if enabled is not None:
                M._SERVER_CFG["ssl_enabled"] = enabled
            cert_file(cert)
            eq("%s: the panel reads %s" % (label, want), status(root), want)
    finally:
        cert_file(False)
        iis_file(None)
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        M.PORT = was[0]
        M._SERVER_CFG.clear()
        M._SERVER_CFG.update(was[1])
        IM._port_serves_tls = was[2]


# ── run ──────────────────────────────────────────────────────────────────────

def check_the_server_window_carries_the_app_icon():
    """The Server GUI is given the icon, and the twelve dialogs inherit it.

    `set_window_icon` passes `True` to `iconphoto`, which makes it the default
    for every Toplevel created afterwards - and every dialog here is opened
    from a callback, so there is none created before it. What is asserted is
    the reference the root parks: Tk has no query form for the icon, and that
    reference is what keeps the image alive, without which the title bar goes
    blank a moment after it was set.

    Skipped where Tk has no display, and where there is no pillow - the icon
    degrading to none is what lets a server with no pillow open its window.
    """
    head("the Server GUI carries the app icon")
    tk = tk_or_skip()
    if tk is None:
        return
    import ui_kit

    if not ui_kit.HAS_PIL:
        skip("pillow is not installed - the icon degrades to none by design")
        return

    fresh_db()
    root = gui_root(tk)
    photos = getattr(root, "_app_icon", None)
    eq("the window holds one image per window size",
       photos is not None and [(p.width(), p.height()) for p in photos],
       [(s, s) for s in ui_kit.ICON_WINDOW_SIZES])
    root.destroy()
    eq("and lets them go with the window", getattr(root, "_app_icon", "unset"),
       None)


def check_the_status_dot_is_a_real_and_separate_mark():
    """A12's light has to draw something, and it has to draw it apart from
    the badge - or `status="online"`/`status="offline"` are only true in the
    docstring.

    Pixel comparisons rather than a display: `app_icon` returns a PIL image
    with no Tk involved, so this needs no display and is not skipped for
    lacking one - only for lacking pillow, the same as every other icon
    check here.
    """
    head("the tray's status dot is a real, distinct mark")
    import ui_kit
    if not ui_kit.HAS_PIL:
        skip("pillow is not installed - there is no icon to draw")
        return

    def px(img):
        return list(img.getdata())

    checking = px(ui_kit.app_icon(64, status=None))
    plain = px(ui_kit.app_icon(64))
    eq("no status draws the same artwork the plain icon does",
       checking == plain, True)

    online = px(ui_kit.app_icon(64, status="online"))
    offline = px(ui_kit.app_icon(64, status="offline"))
    if online == plain:
        bad("status='online' changes no pixel - there is no dot to see")
    else:
        ok("status='online' draws something the plain icon does not carry")
    if offline == plain:
        bad("status='offline' changes no pixel - there is no dot to see")
    else:
        ok("status='offline' draws something the plain icon does not carry")
    if online == offline:
        bad("online and offline draw identical pixels - the light cannot "
            "be told apart at a glance")
    else:
        ok("and online reads differently from offline")

    # The Notifier's badge means something else, so the two marks must
    # still be told apart even where an icon somehow carried both.
    badge_only = px(ui_kit.app_icon(64, badge=True))
    badge_and_status = px(ui_kit.app_icon(64, badge=True, status="offline"))
    if badge_only == badge_and_status:
        bad("adding a status dot beside a badge changes nothing - the two "
            "marks would be indistinguishable on the one icon that could "
            "carry both")
    else:
        ok("the badge and the status dot are drawn as two separate marks")
