r"""Run the gates a change actually owes, in parallel, and say which and why.

    py -3.12 tools\gate.py                 what the working tree owes against main
    py -3.12 tools\gate.py --base HEAD~1   ...against some other point
    py -3.12 tools\gate.py --all           every gate and the upgrade drill: a release run
    py -3.12 tools\gate.py --list          name the plan, run nothing
    py -3.12 tools\gate.py -j 4            shards per suite (default: cores, max 8)
    py -3.12 tools\gate.py -v              pass -v down, printing every passing line

This exists because the four gates cost the same whatever moved. Measured on this
repo before it was written: `cascade-audit.py` 6s, `server-checks.py` 5m47s,
`client-checks.py` 3m01s - nine minutes, serially, on one core, for a change to a
Markdown file that no Python in the tree reads. `land.py` pays it again per land
and per merge. A gate that expensive on a commit that cannot have broken it is a
gate people learn to skip, and the ones worth having are then skipped with it.

So two separate savings, and they compose:

  * **Only the suites the diff can reach.** A docs-only change owes
    `cascade-audit.py` and nothing else, which is six seconds. The map below is
    per file rather than per check group: a check group's dependencies would be a
    second list to keep, and the first one to go stale would be the one excusing
    a suite that should have run. A path the map does not know runs **everything**
    and says so - that is the negative half, and it is the whole reason this is
    safe to put in front of `land.py`. Adding a file to the repo cannot quietly
    subtract a gate; it can only cost a full run until somebody maps it.
  * **Shards.** `server-checks.py` and `client-checks.py` take `--shard i/n` and
    slice their groups by position, so n of them run at once and the exit codes
    are aggregated here. Measured: 5m47s to 2m40s at 8 shards, 3m01s to 2m00s at
    4. Well under linear - most of both suites is Tk building real windows, and
    Windows serialises more of that than it looks - but it is most of an hour a
    day back on a branch that lands a few times.

`cascade-audit.py` always runs. It is the cheap one, it is the one a documentation
change is *about*, and `docs/CODING_STANDARDS.md` requires the cascade to land
before the gate run rather than after it.
"""
import os
import re
import subprocess
import sys
import time

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

# The five gates, by the short name the map below uses. `cascade` is not in the
# map: it runs on every invocation, including one where nothing at all changed.
GATES = {
    "cascade": [PY, "-u", os.path.join("tools", "cascade-audit.py")],
    "server": [PY, "-u", os.path.join("tools", "server-checks.py")],
    "client": [PY, "-u", os.path.join("tools", "client-checks.py")],
    "palette": [PY, "-u", os.path.join("tools", "palette-contrast.py")],
    "deploy": None,          # PowerShell, assembled in run_gate: see below
    "upgrade": [PY, "-u", os.path.join("tools", "upgrade-drill.py")],
}
# Run by --all and by nothing else. The drill (#274) packages two releases and
# drives a real upgrade, downgrade and client rollback - minutes, whatever the
# diff - and no path owes it: it proves the release, not the change. So no MAP
# row names it, and an unmapped path's "everything" leaves it out too.
RELEASE_ONLY = ("upgrade",)
SHARDABLE = ("server", "client")

# What a suite may be sharded to where that is less than the machine offers.
# client-checks.py's two popup groups (#194, #201) drive real `after` timers with
# the numbers turned down to the smallest thing a wall clock can show - on
# purpose, their docstrings arguing that reaching past the timer would pass
# against a popup whose timer was never armed. Eight shards on twelve cores takes
# that margin away and both groups fail; four does not. Measured rather than
# guessed: four came back green twice with the assertion counts summing to what
# a serial run makes, eight failed both times. Moving this number means
# measuring it again, and the thing to measure is the counts, not the colour.
# Those checks have sat in tools/client_checks/popup.py since #238, and that
# moved nothing this cap is against: the cap is on how many shards run at once,
# and --shard still slices every group by position.
# The total the sum is checked against is the serial run of the day, not a
# number copied from here - it was 872 when the cap was set and is 928 now.
#
# server-checks.py has no cap, and that is now the weaker half of this comment.
# #214 measured it after a narrow-band group (`nothing on this window is cut off
# at a narrow size`, the 1.75x/940px leg) was reported flaking under 8 shards:
# three `--all -j 8` runs and three `--all -j 4` runs, all six GREEN, the
# narrow-band leg passing every time, and the per-shard assertion counts summing
# to the serial total of the day (2615 then, 2626 now).
#
# That no longer reproduces, and the two failures behind it have different
# causes. Re-measured 2026-09-22:
#
#   tls.py's `a quiet tick paints nothing` failed once under 8 shards and is
#   green run alone with AM_GATE_OFFSCREEN=1 - load, which is what a cap is
#   for. Never diagnosed further; its own ticket if it recurs.
#
#   console.py's narrow-band leg (1.75x at 940px) was not load and not the
#   offscreen flag. It was the settle: resize() ended on two identical reads,
#   and a half-settled band reads short and then agrees with itself once
#   before the children finish. Fixed on a third read, #239 / 064.
#
# So one of the two is an argument for a cap and the other turned out not to
# be a sharding question at all. SHARD_CAP is left alone on that: one load
# failure is thinner evidence than the wall clock a cap costs every run.
SHARD_CAP = {"client": 4}

# Which suites a path can reach, first match wins. Paths are as git reports
# them: forward slashes, relative to the repo root.
#
# `common.py` and `ui_kit.py` reach both sides. server-checks.py stages and
# imports `common.py` for the two groups that read a password door and the
# certificate bootstrap from the client side, and it measures the Server GUI's
# six `ui_kit.fit` callers; client-checks.py opens three apps built out of the
# same kit. `installer.py` is client-side here because that is the app whose
# windows client-checks.py measures - `PASSWORD_MIN`'s second copy in it is
# cascade's row, and cascade always runs.
MAP = (
    (r"^server\.py$", ("server",)),
    (r"^server_gui\.py$", ("server",)),
    (r"^server_cert\.py$", ("server",)),
    (r"^register_assets\.py$", ("server",)),
    (r"^register_transactions\.py$", ("server",)),
    (r"^register_engineers\.py$", ("server",)),
    (r"^server_mail\.py$", ("server",)),
    (r"^server_sync\.py$", ("server",)),
    (r"^server_clients\.py$", ("server",)),
    (r"^server_log\.py$", ("server",)),
    (r"^server_archive\.py$", ("server",)),
    (r"^server_lookup\.py$", ("server",)),
    (r"^server_iis\.py$", ("server",)),
    # One row rather than nine: the nine console window modules #235 split
    # server_gui.py into are the same suite as the file they came out of, and
    # nine rows saying so would be nine chances to leave one out.
    (r"^gui_\w+\.py$", ("server",)),
    (r"^migrations/", ("server",)),
    (r"^(common|ui_kit)\.py$", ("server", "client", "palette")),
    (r"^(storekeeper_app|storekeeper_export|storekeeper_bulk"
      r"|storekeeper_propose|notifier_app"
      r"|notifier_pending"
      r"|notifier_remote|installer|applaunch|client_update)\.py$",
     ("client",)),
    (r"^run_\w+\.pyw?$", ("client",)),
    (r"^tools/server-checks\.py$", ("server",)),
    # The check groups #221 split that file into. The row above is the entry
    # point this file runs; this one is the package under it, and without it an
    # edit to a group module matches nothing and owes no gate at all - the
    # unmapped case this file's docstring calls the negative half would not
    # save it, that being for a path nothing matched rather than for a suite
    # whose own checks moved one directory down.
    (r"^tools/server_checks/", ("server",)),
    (r"^tools/client-checks\.py$", ("client",)),
    # The check groups #238 split that file into, for the reason the
    # tools/server_checks/ row above gives for its own package.
    (r"^tools/client_checks/", ("client",)),
    # Both window suites import it and call it from main(), so it reaches
    # both. It is not in the row below with the rest of tools/*.py: those
    # are read by a person or by this file, and this one runs inside a gate.
    (r"^tools/_offscreen\.py$", ("server", "client")),
    # 073's own gate imports it; an edit to the checker re-runs the checker,
    # same reason as the row above.
    (r"^tools/palette-contrast\.py$", ("palette",)),
    (r"^tools/deploy-checks\.ps1$", ("deploy",)),
    (r"^tools/_deploy\.ps1$", ("deploy",)),
    (r"^tools/.*\.ps1$", ("deploy",)),
    (r"^tools/(cascade-audit|gate|land|_devtools)\.py$", ()),
    # Owes nothing on a normal run: it is RELEASE_ONLY above, so only --all
    # runs it, and an edit to it is proved by running it that way.
    (r"^tools/upgrade-drill\.py$", ()),
    (r"^requirements-", ("server", "client")),
    # Prose, and the things that are only ever read by a person or by cascade.
    (r"^(docs/|\.dev/)", ()),
    (r"^[^/]+\.md$", ()),
    (r"^\.gitignore$", ()),
    (r"^tools/deploy(\.example)?\.json$", ()),
)


def git(*args):
    return subprocess.check_output(["git", "-C", R] + list(args),
                                   stderr=subprocess.STDOUT).decode("utf-8",
                                                                    "replace")


def default_base():
    """Where to diff from: the point this branch left `main`.

    On `main` itself there is no fork point, so the last commit is the only
    honest answer - and a caller who wants more says so with --base.
    """
    try:
        here = git("rev-parse", "--abbrev-ref", "HEAD").strip()
        if here == "main":
            return "HEAD~1"
        return git("merge-base", "main", "HEAD").strip()
    except subprocess.CalledProcessError:
        return "HEAD~1"


def changed(base):
    """Every path this tree differs from `base` in, committed or not.

    `git diff <base>` already covers the working tree and the index against
    base. Untracked files are not in a diff at all and are exactly the case
    that matters here - a new module nothing has committed yet is a new module
    a gate has never seen.
    """
    paths = set()
    try:
        for line in git("diff", "--name-only", base).splitlines():
            if line.strip():
                paths.add(line.strip())
    except subprocess.CalledProcessError as exc:
        raise SystemExit("cannot diff against %s: %s"
                         % (base, exc.output.decode("utf-8", "replace")))
    for line in git("status", "--porcelain", "--untracked-files=all").splitlines():
        if line.startswith("?? "):
            paths.add(line[3:].strip().strip('"'))
    return sorted(paths)


def plan(paths):
    """The set of gates those paths owe, and the paths nothing knew about."""
    want = {"cascade"}
    unmapped = []
    for p in paths:
        for pattern, gates in MAP:
            if re.match(pattern, p):
                want.update(gates)
                break
        else:
            unmapped.append(p)
    if unmapped:
        want.update(g for g in GATES if g not in RELEASE_ONLY)
    return want, unmapped


def run_gate(name, shards, verbose):
    """Run one gate, sharded if it takes shards, and return (rc, lines)."""
    if name == "deploy":
        # Write-Host writes to the information stream, so `2>&1` captures none
        # of it and a failing PowerShell gate comes back silent. `*>&1` is the
        # redirect that takes all six streams, and it only means that inside
        # PowerShell - hence -Command with the call operator rather than -File.
        script = os.path.join(R, "tools", "deploy-checks.ps1")
        cmds = [["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", "& '%s' *>&1" % script]]
    elif name in SHARDABLE and shards > 1:
        n = min(shards, SHARD_CAP.get(name, shards))
        cmds = [GATES[name] + ["--shard", "%d/%d" % (i, n)]
                for i in range(1, n + 1)]
    else:
        cmds = [GATES[name]]
    if verbose and name != "deploy":
        cmds = [c + ["-v"] for c in cmds]

    # AM_GATE_OFFSCREEN is read by tools/_offscreen.py, which both Python
    # window suites call first thing in main(). Set here and not in the
    # suites themselves: a gate run is the case where nobody is watching
    # the windows, and a suite run by hand while iterating on it is the
    # case where watching them is the point.
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               AM_GATE_OFFSCREEN="1")
    procs = [subprocess.Popen(c, cwd=R, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT) for c in cmds]
    rc = 0
    lines = []
    for p in procs:
        out = p.communicate()[0].decode("utf-8", "replace")
        rc = rc or p.returncode
        lines.extend(out.splitlines())
    return rc, lines


# The inline forms a gate prints as it goes. Each of the five also prints an
# aggregated list at the end of its run - "FAIL: ...", "DRIFT: ...", "note : ..."
# - so matching those as well would report every finding twice, and eight times
# over eight shards.
LOUD = ("[FAIL]", "[DRIFT]", "[note]")

# #214: a Tk `Variable` collected after `mainloop()` has returned tries to
# unset itself in Tcl and finds the interpreter gone, so `Variable.__del__`
# raises into `sys.unraisablehook` at interpreter exit - on a green run, with
# nothing in either suite that leaked it. Measured on a `server-checks.py`
# shard: the block is always five lines under "Traceback (most recent call
# last):" and always ends "RuntimeError: main thread is not in main loop", or
# ends naming the `refresh_stats` `after` callback's stale Tcl command
# ("invalid command name ...refresh_stats") when the second call in `__del__`
# is the one that lands after teardown. Either terminal line means the block
# is this known noise and is dropped rather than printed as a finding; any
# other traceback still prints - fixing the leak itself belongs in
# server-checks.py, a separate change.
_TK_TEARDOWN_TAIL = re.compile(
    r"RuntimeError: main thread is not in main loop$"
    r"|invalid command name .*refresh_stats")


def _is_tk_teardown_noise(lines, i):
    """True if the traceback starting at lines[i] is the #214 noise above."""
    for line in lines[i + 1:i + 9]:
        s = line.strip()
        if not s:
            break
        if _TK_TEARDOWN_TAIL.search(s):
            return True
    return False


def report(name, rc, lines, secs, verbose):
    """One line for a green gate, the findings themselves for a red one."""
    mark = "OK  " if rc == 0 else "FAIL"
    print("\n%s  %-8s %5.1fs" % (mark, name, secs))
    if verbose:
        for line in lines:
            print("    %s" % line)
        return
    shown = False
    for i, line in enumerate(lines):
        s = line.strip()
        if "Traceback" in s:
            if _is_tk_teardown_noise(lines, i):
                continue
            print("    %s" % s)
            shown = True
        elif s.startswith(LOUD):
            print("    %s" % s)
            shown = True
        elif s.startswith("=== "):
            # A group heading earns its line only above the group that had
            # something to say. cascade-audit.py prints one per group either
            # way, which is 40-odd headings of nothing on a green run.
            nxt = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
            if nxt.startswith(LOUD):
                print("    %s" % s)
    # A gate that died before it asserted anything exits non-zero with nothing
    # this recognises on stdout, and a silent FAIL is the one report worse than
    # a noisy one. Show the tail instead of nothing.
    if rc and not shown:
        for line in lines[-15:]:
            print("    %s" % line)


def main():
    argv = sys.argv[1:]
    verbose = "-v" in argv or "--verbose" in argv
    listing = "--list" in argv
    every = "--all" in argv
    base = None
    shards = min(os.cpu_count() or 1, 8)
    for i, a in enumerate(argv):
        if a == "--base" and i + 1 < len(argv):
            base = argv[i + 1]
        elif a.startswith("--base="):
            base = a.split("=", 1)[1]
        elif a in ("-j", "--jobs") and i + 1 < len(argv):
            shards = max(1, int(argv[i + 1]))
        elif a.startswith("-j="):
            shards = max(1, int(a.split("=", 1)[1]))

    if every:
        want, unmapped, paths = set(GATES), [], []
        print("running every gate (--all)")
    else:
        base = base or default_base()
        paths = changed(base)
        want, unmapped = plan(paths)
        print("%d path(s) changed against %s" % (len(paths), base))
        for p in paths[:20]:
            print("    %s" % p)
        if len(paths) > 20:
            print("    ... and %d more" % (len(paths) - 20))
        if unmapped:
            print("\n%d path(s) the map does not know, so every gate runs:"
                  % len(unmapped))
            for p in unmapped:
                print("    %s" % p)
            print("  Map them in tools/gate.py and document the row in "
                  "docs/reference/tooling.md.")

    order = [g for g in ("cascade", "server", "client", "palette", "deploy",
                         "upgrade")
             if g in want]
    print("\ngates: %s   (up to %d shard(s) where a suite takes them)"
          % (", ".join(order), shards))
    if listing:
        return 0

    started = time.time()
    rc = 0
    for name in order:
        t = time.time()
        one, lines = run_gate(name, shards, verbose)
        rc = rc or one
        report(name, one, lines, time.time() - t, verbose)

    print("\n" + "=" * 66)
    print("%s in %.0fs (%s)"
          % ("GREEN" if rc == 0 else "RED", time.time() - started,
             ", ".join(order)))
    return rc


if __name__ == "__main__":
    sys.exit(main())
