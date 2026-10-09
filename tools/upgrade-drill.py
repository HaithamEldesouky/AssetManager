r"""Prove upgrade, downgrade and client rollback against the previous release.

    py -3.12 tools\upgrade-drill.py                the newest v* tag below APP_VERSION
    py -3.12 tools\upgrade-drill.py --from 58355d6 any ref instead
    py -3.12 tools\upgrade-drill.py -v             print every passing line

On 2026-09-23 the upgrade and downgrade path was proved by hand (#274), after two
automated attempts had reported a pass without running it: one read schema 4 when
the real schema was 15, one never started a client. This is that hand run made
permanent, and every number it compares is read off a database or a file this
run wrote - nothing is carried over from notes.

  1. The previous release is checked out into a temporary worktree and packaged
     with **its own** tools/package.ps1. This tree's cannot package an older
     one: its $SourceFiles names modules the old tree does not have, and script
     and source come from one commit by design. This tree is packaged too.
  2. The old server package is unzipped into a temp install, started with
     `serve` and HTTP_PLATFORM_PORT on a loopback port, and seeded over HTTP:
     members, transactions, a confirm and a reject.
  3. PRAGMA user_version, integrity_check, foreign_key_check, the per-table
     counts and the transaction and member rows are recorded.
  4. The new package's update.ps1 upgrades it; the new build is started and
     seeded again with different assets (the server answers 409 for an asset
     that already has a pending move), and the schema must be the package's.
  5. The old package's update.ps1 downgrades it, and every row recorded in 3
     and 4 must still be there field for field, at the old schema.
  6. A client installed from the old <App>-<version>.zip is updated to the new
     one by its own client_update.py --apply and hash-compared; a second old
     install is handed a package whose launcher fails, and the rollback must
     leave the old files byte-identical.

It takes minutes - two package.ps1 runs, each compiling the installer - so it is
`gate.py --all`'s and not a normal gate run's. Python is pinned with `py -3.12`
throughout: a bare `py` picks up 3.14, and rule 13's check correctly refuses it.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERBOSE = "-v" in sys.argv
CLIENT_APP = "StorekeeperApp"

passes = 0
fails = []


def check(what, ok, detail=""):
    global passes
    if ok:
        passes += 1
        if VERBOSE:
            print("  [PASS] %s" % what)
    else:
        fails.append(what)
        print("  [FAIL] %s%s" % (what, ("  -- " + detail) if detail else ""))
    return ok


def step(title):
    print("\n== %s" % title, flush=True)


def run(cmd, cwd=None, env=None, timeout=1800):
    """Run to completion; return (rc, output) and print the output on failure."""
    p = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout)
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode != 0 or VERBOSE:
        print(out[-4000:])
    return p.returncode, out


def git(*args):
    return subprocess.check_output(["git"] + list(args), cwd=R).decode().strip()


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def app_version(path):
    m = re.search(r'^APP_VERSION = "([^"]+)"', open(path, encoding="utf-8").read(), re.M)
    return m.group(1)


def previous_release(current):
    """The newest v* tag below `current`, which is what 'the last release' means."""
    below = [t for t in git("tag", "--list", "v*").split()
             if re.fullmatch(r"v\d+\.\d+\.\d+", t)
             and version_tuple(t) < version_tuple(current)]
    if not below:
        raise SystemExit("no v* tag below %s; pass --from <ref>" % current)
    return max(below, key=version_tuple)


def py312():
    """The interpreter `py -3.12` resolves to, as a path other tools can be handed."""
    return subprocess.check_output(
        ["py", "-3.12", "-c", "import sys; print(sys.executable)"]).decode().strip()


def lib_dirs():
    """lib-server\\ and lib-client\\ from this checkout, else from the main one.

    A worktree has no vendored lib of its own - it is not tracked - and both
    package runs are handed the same pair so the old and new packages differ
    only in what their commits hold.
    """
    for root in (R, os.path.dirname(git("rev-parse", "--path-format=absolute",
                                         "--git-common-dir"))):
        srv, cli = os.path.join(root, "lib-server"), os.path.join(root, "lib-client")
        if os.path.isdir(srv) and os.path.isdir(cli):
            return srv, cli
    raise SystemExit("no lib-server\\ and lib-client\\ found; run tools\\vendor.ps1 first")


def ps(script, *args):
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
            "Bypass", "-File", script] + list(args)


def package(tree, dist, env, allow_dirty):
    srv, cli = lib_dirs()
    args = ["-ServerLibDir", srv, "-ClientLibDir", cli, "-DistDir", dist]
    if allow_dirty:
        args.append("-AllowDirty")
    rc, _ = run(ps(os.path.join(tree, "tools", "package.ps1"), *args), cwd=tree, env=env)
    if rc != 0:
        raise SystemExit("package.ps1 failed in %s" % tree)
    (version,) = os.listdir(dist)
    return os.path.join(dist, version), version


def manifest(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read("manifest.json").decode("utf-8"))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    """One `serve` process over the temp install, on loopback."""

    def __init__(self, install, python):
        self.install, self.python = install, python

    def __enter__(self):
        self.port = free_port()
        env = dict(os.environ, HTTP_PLATFORM_PORT=str(self.port))
        self.log = open(os.path.join(os.path.dirname(self.install),
                                     "serve-%d.log" % self.port), "wb")
        self.proc = subprocess.Popen(
            [self.python, os.path.join(self.install, "run_server.py"), "serve"],
            cwd=self.install, env=env, stdin=subprocess.DEVNULL,
            stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                break
            try:
                self.version = self.get("/version")
                return self
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.5)
        self.__exit__()
        raise SystemExit("the server in %s did not answer on %d"
                         % (self.install, self.port))

    def __exit__(self, *exc):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.log.close()

    def request(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=data,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def get(self, path):
        return self.request(path)[1]


def seed(srv, db, round_no, taken):
    """Two members, three moves, one confirmed and one rejected.

    Assets are taken from the install's own assets table, never one an earlier
    round moved: a second pending move of the same asset is a 409.
    """
    conn = sqlite3.connect(db)
    assets = [a for a in conn.execute(
        "SELECT asset_number, serial_number FROM assets ORDER BY rowid")
        if a not in taken][:3]
    conn.close()
    check("round %d: the lookup holds three unmoved assets" % round_no,
          len(assets) == 3, "%d found" % len(assets))
    taken.update(assets)
    names = ["Drill %d Engineer A" % round_no, "Drill %d Engineer B" % round_no]
    for name in names:
        st, body = srv.request("/members", {"name": name})
        check("round %d: member %s created" % (round_no, name), st == 200, "%s %s" % (st, body))
    ids = []
    for i, (asset_no, serial_no) in enumerate(assets):
        st, body = srv.request("/transactions", {
            "team_member": names[i % 2], "direction": ("Out Store", "In Store")[i % 2],
            "asset_number": asset_no or "", "serial_number": serial_no or "",
            "notes": "upgrade drill round %d" % round_no})
        check("round %d: transaction for %s created" % (round_no, asset_no or serial_no),
              st in (200, 201), "%s %s" % (st, body))
        conn = sqlite3.connect(db)
        ids.append(conn.execute("SELECT MAX(id) FROM transactions").fetchone()[0])
        conn.close()
    st, body = srv.request("/confirm/%d" % ids[0], {})
    check("round %d: #%d confirmed" % (round_no, ids[0]), st == 200, "%s %s" % (st, body))
    st, body = srv.request("/reject/%d" % ids[1], {"reason": "drill"})
    check("round %d: #%d rejected" % (round_no, ids[1]), st == 200, "%s %s" % (st, body))


def snapshot(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    snap = {
        "user_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "integrity": [r[0] for r in conn.execute("PRAGMA integrity_check")],
        "foreign_keys": [tuple(r) for r in conn.execute("PRAGMA foreign_key_check")],
        "counts": {t: conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
                   for t in tables},
        "transactions": {r["id"]: dict(r) for r in conn.execute("SELECT * FROM transactions")},
        "members": {r["name"]: dict(r) for r in conn.execute("SELECT * FROM team_members")},
    }
    conn.close()
    return snap


def check_healthy(label, snap, schema):
    """schema None: record it rather than assert it.

    A fresh install before #275 (100) was never stamped, so a release older
    than that reads user_version 0 until its first update. That is the old
    build's defect, recorded here; what the drill asserts is where the
    update leaves it.
    """
    if schema is None:
        print("  %s: user_version %d" % (label, snap["user_version"]))
    else:
        check("%s: schema is v%d" % (label, schema), snap["user_version"] == schema,
              "user_version %d" % snap["user_version"])
    check("%s: integrity_check is ok" % label, snap["integrity"] == ["ok"], str(snap["integrity"]))
    check("%s: foreign_key_check is empty" % label, not snap["foreign_keys"],
          str(snap["foreign_keys"][:5]))


def check_rows_kept(label, before, after):
    """Every row `before` holds is in `after`, every field `before` had equal.

    Fields only: a migration may add a column on the way up, and dropping it on
    the way down is the migration's to do.
    """
    for key in ("transactions", "members"):
        for rid, row in before[key].items():
            now = after[key].get(rid)
            if not check("%s: %s %s is still there" % (label, key, rid), now is not None):
                continue
            diff = [c for c in row if row[c] != now.get(c)]
            check("%s: %s %s is unchanged" % (label, key, rid), not diff,
                  ", ".join("%s %r -> %r" % (c, row[c], now.get(c)) for c in diff))
        check("%s: %s count unchanged" % (label, key),
              len(after[key]) == len(before[key]),
              "%d -> %d" % (len(before[key]), len(after[key])))


def update(updater_zip, package_zip, install, python, work, allow_dirty):
    """Run the updater a package carries against the temp install.

    There is no service or app pool here, so update.ps1 stops nothing and
    reports that the host did not start; the drill starts it itself, and
    -SkipHealth is what that costs.
    """
    tools = os.path.join(work, "tools")
    os.makedirs(tools)
    with zipfile.ZipFile(updater_zip) as zf:
        for name in ("tools/update.ps1", "tools/_deploy.ps1"):
            with open(os.path.join(work, name), "wb") as out:
                out.write(zf.read(name))
    args = ["-Package", package_zip, "-TargetDir", install,
            "-PythonExe", python, "-SkipHealth"]
    if allow_dirty:
        args.append("-AllowDirty")
    rc, _ = run(ps(os.path.join(tools, "update.ps1"), *args), timeout=600)
    return rc


def file_hashes(root, names):
    out = {}
    for name in names:
        path = os.path.join(root, name.replace("/", os.sep))
        out[name] = hashlib.sha256(open(path, "rb").read()).hexdigest() \
            if os.path.isfile(path) else None
    return out


def dead_pid(python):
    p = subprocess.Popen([python, "-c", "pass"])
    p.wait()
    return p.pid


def apply_client(install, zip_src, from_version, python, tmp):
    """Hand the installed client_update.py a zip in a folder of its own.

    Its own mkdtemp folder, because apply_update removes the zip's parent on
    success in the older builds, and the parent must not be anything shared.
    """
    folder = tempfile.mkdtemp(prefix="zip-", dir=tmp)
    zip_path = os.path.join(folder, os.path.basename(zip_src))
    shutil.copy2(zip_src, zip_path)
    rc, _ = run([python, os.path.join(install, "client_update.py"),
                 "--apply", zip_path, "--dest", install,
                 "--wait-pid", str(dead_pid(python)), "--from-version", from_version],
                cwd=install, timeout=300)
    return rc


def broken_copy(zip_src, dest):
    """The same package with a launcher that exits at once: a launch that fails."""
    launcher = manifest(zip_src)["launcher"]
    with zipfile.ZipFile(zip_src) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == launcher:
                data = b"import sys\nsys.exit(3)\n"
            zout.writestr(item, data)


def kill_under(tmp):
    """Stop every process whose command line names the temp folder.

    The relaunched clients are detached and the servers may have children;
    none of them is a child this script can wait on, and a live one keeps a
    file open that the folder removal below would trip on.
    """
    leaf = os.path.basename(tmp)
    subprocess.run(ps_cmd(
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*%s*' "
        "-and $_.ProcessId -ne %d } | ForEach-Object { Stop-Process -Id $_.ProcessId "
        "-Force -ErrorAction SilentlyContinue }" % (leaf, os.getpid())),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ps_cmd(command):
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]


def drill(ref, tmp):
    python = py312()
    # package.ps1 calls a bare `python`; this is what makes that the pinned one.
    env = dict(os.environ, PATH=os.path.dirname(python) + os.pathsep + os.environ["PATH"])
    current = app_version(os.path.join(R, "server.py"))

    step("Packaging %s with its own package.ps1, and this tree" % ref)
    old_tree = os.path.join(tmp, "old-tree")
    git("worktree", "add", "--detach", old_tree, ref)
    old_dist, old_ver = package(old_tree, os.path.join(tmp, "dist-old"), env, False)
    new_dist, new_ver = package(R, os.path.join(tmp, "dist-new"), env, True)
    check("the new package is APP_VERSION %s" % current, new_ver == current, new_ver)
    check("the old package is older than the new", version_tuple(old_ver) < version_tuple(new_ver),
          "%s vs %s" % (old_ver, new_ver))
    old_zip = os.path.join(old_dist, "AssetManager-%s.zip" % old_ver)
    new_zip = os.path.join(new_dist, "AssetManager-%s.zip" % new_ver)
    old_schema = manifest(old_zip)["schema_version"]
    new_schema = manifest(new_zip)["schema_version"]
    print("  %s (schema %d) -> %s (schema %d)" % (old_ver, old_schema, new_ver, new_schema))

    step("Installing %s and seeding it" % old_ver)
    install = os.path.join(tmp, "server")
    zipfile.ZipFile(old_zip).extractall(install)
    db = os.path.join(install, "assets.db")
    taken = set()
    with Server(install, python) as srv:
        check("the old build answers as %s" % old_ver,
              srv.version.get("latest") == old_ver, str(srv.version))
        seed(srv, db, 1, taken)
    baseline = snapshot(db)
    check_healthy("before the upgrade", baseline, None)

    step("Upgrading to %s with its own update.ps1" % new_ver)
    check("update.ps1 upgrade exits 0",
          update(new_zip, new_zip, install, python, os.path.join(tmp, "upd-up"), True) == 0)
    upgraded = snapshot(db)
    check_healthy("after the upgrade", upgraded, new_schema)
    check_rows_kept("after the upgrade", baseline, upgraded)
    with Server(install, python) as srv:
        check("the new build answers as %s" % new_ver,
              srv.version.get("latest") == new_ver, str(srv.version))
        seed(srv, db, 2, taken)
    before_down = snapshot(db)
    check_healthy("after seeding the new build", before_down, new_schema)

    step("Downgrading to %s with its own update.ps1" % old_ver)
    check("update.ps1 downgrade exits 0",
          update(old_zip, old_zip, install, python, os.path.join(tmp, "upd-down"), False) == 0)
    downgraded = snapshot(db)
    check_healthy("after the downgrade", downgraded, old_schema)
    check_rows_kept("after the downgrade", before_down, downgraded)
    with Server(install, python) as srv:
        check("the old build answers as %s again" % old_ver,
              srv.version.get("latest") == old_ver, str(srv.version))

    step("Updating a %s client from %s to %s" % (CLIENT_APP, old_ver, new_ver))
    old_client = os.path.join(old_dist, "%s-%s.zip" % (CLIENT_APP, old_ver))
    new_client = os.path.join(new_dist, "%s-%s.zip" % (CLIENT_APP, new_ver))
    old_files = {n: h for n, h in manifest(old_client)["files"].items() if not n.endswith("/")}
    new_files = {n: h for n, h in manifest(new_client)["files"].items() if not n.endswith("/")}

    client = os.path.join(tmp, "client-ok")
    zipfile.ZipFile(old_client).extractall(client)
    check("client --apply exits 0", apply_client(client, new_client, old_ver, python, tmp) == 0)
    got = file_hashes(client, new_files)
    wrong = [n for n in new_files if got[n] != new_files[n]]
    check("every file of %s matches its manifest hash" % new_ver, not wrong,
          "%d differ, e.g. %s" % (len(wrong), wrong[:3]))

    step("A %s update whose launch fails rolls back" % new_ver)
    client = os.path.join(tmp, "client-bad")
    zipfile.ZipFile(old_client).extractall(client)
    before = file_hashes(client, old_files)
    broken = os.path.join(tmp, "%s-%s.zip" % (CLIENT_APP, new_ver))
    broken_copy(new_client, broken)
    check("client --apply of a failing launch exits non-zero",
          apply_client(client, broken, old_ver, python, tmp) != 0)
    after = file_hashes(client, old_files)
    wrong = [n for n in old_files if after[n] != before[n] or before[n] != old_files[n]]
    check("every file of %s is byte-identical after the rollback" % old_ver, not wrong,
          "%d differ, e.g. %s" % (len(wrong), wrong[:3]))


def main():
    argv = sys.argv[1:]
    ref = None
    for i, a in enumerate(argv):
        if a == "--from" and i + 1 < len(argv):
            ref = argv[i + 1]
        elif a.startswith("--from="):
            ref = a.split("=", 1)[1]
        elif a not in ("-v", "--verbose") and (i == 0 or argv[i - 1] != "--from"):
            raise SystemExit(__doc__)
    ref = ref or previous_release(app_version(os.path.join(R, "server.py")))
    started = time.time()
    tmp = tempfile.mkdtemp(prefix="am-upgrade-drill-")
    try:
        drill(ref, tmp)
    except SystemExit as exc:
        fails.append(str(exc))
        print("  [FAIL] %s" % exc)
    finally:
        kill_under(tmp)
        subprocess.run(["git", "worktree", "remove", "--force",
                        os.path.join(tmp, "old-tree")], cwd=R,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=R)
    print("\n%s: %d passed, %d failed, against %s, in %.0fs"
          % ("all checks passed" if not fails else "FAILURE",
             passes, len(fails), ref, time.time() - started))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
