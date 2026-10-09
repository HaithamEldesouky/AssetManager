#!/usr/bin/env python
"""Land a finished branch: check it, test it, merge it into local `main`, push, clean up.

    py -3.12 tools/land.py
    py -3.12 tools/land.py --dry-run    say what would happen, change nothing

It refuses rather than guesses. A dirty tree, a conflict with `main`, `main` held
by another worktree, or a red suite each stop it before anything is published,
and it says what it found instead of working around it.

Committing is deliberately not its job. A commit carries a message somebody chose,
and a script that stages whatever it finds will eventually sweep another session's
half-written file into `main`. Commit first, land second.
"""

import argparse
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = "main"
REMOTE = "origin"

# One command, and it is the runner rather than a suite: `gate.py --all` runs all
# five gates this repo has, shards the two long ones across cores and aggregates
# the exit codes. Landing is the one moment that has to be the *full* run, so
# --all rather than gate.py's own diff-scoped default - what a branch changed is
# not what the merge produces.
#
# It ran server-checks.py and client-checks.py directly and serially until
# gate.py arrived: nine minutes, and the other two gates, cascade-audit.py and
# deploy-checks.ps1, were not run by a land at all. Standard library only and no
# test framework, per `docs/CODING_STANDARDS.md`; the vendored lib directory is
# pinned to one Python minor version, which is why the launcher is asked for 3.12
# by name.
SUITE = [["py", "-3.12", "tools/gate.py", "--all"]]
SUITE_ENV = {}

# A ticket number is the trailing "-123" or "-#123" of a branch name. Anything else --
# "test/req-routes-covered", "claude/happy-swirles-cc0d96" -- parses to None, and
# the issue is left alone rather than guessed at. A hex suffix is not a ticket.
TICKET = re.compile(r"[-/]#?(\d+)$")


def fail(msg):
    print("land: refused -- " + msg)
    raise SystemExit(1)


def run(argv, check=True, **kw):
    p = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, **kw)
    if check and p.returncode:
        fail("%s exited %d\n%s%s" % (" ".join(argv), p.returncode, p.stdout, p.stderr))
    return p


def git(*args, **kw):
    return run(["git"] + list(args), **kw).stdout


def worktree_of(branch):
    """Path of the worktree holding `branch`, or None.

    `git worktree list --porcelain` prints one block per worktree; the branch
    line carries a full ref, so it is matched whole rather than by substring.
    """
    path = None
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.strip() == "branch refs/heads/" + branch:
            return path
    return None


def close_ticket(number):
    view = run(["gh", "issue", "view", number, "--json", "state,title"], check=False)
    if view.returncode:
        print("issue #%s not found on this remote -- nothing closed" % number)
        return
    issue = json.loads(view.stdout)
    if issue.get("state") == "CLOSED":
        print("issue #%s is already closed" % number)
        return
    run(["gh", "issue", "close", number, "--comment", "Landed on %s." % MAIN])
    print("closed issue #%s -- %s" % (number, issue.get("title", "")))


def main():
    ap = argparse.ArgumentParser(description="Land the current branch on " + MAIN)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and stop before the suite; changes nothing")
    ap.add_argument("--keep-remote-branch", action="store_true",
                    help="leave the branch on the remote after landing it")
    args = ap.parse_args()

    # The suite writes straight to this terminal while our own prints are block
    # buffered once output is piped, which reorders a captured log: the suite
    # appears above the plan it was supposed to follow.
    sys.stdout.reconfigure(line_buffering=True)

    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch == "HEAD":
        fail("detached HEAD -- check out the branch you mean to land")
    if branch == MAIN:
        fail("already on %s -- there is nothing to land" % MAIN)

    dirty = git("status", "--porcelain").strip()
    if dirty:
        fail("the tree is dirty, and landing does not commit for you. Commit or "
             "stash these first:\n" + dirty)

    print("fetching %s" % REMOTE)
    git("fetch", REMOTE)
    base = "%s/%s" % (REMOTE, MAIN)

    held = worktree_of(MAIN)
    if held and os.path.normpath(held) != os.path.normpath(REPO):
        fail("%s is checked out in another worktree (%s). Land from there, or "
             "remove it first -- this one cannot check %s out." % (MAIN, held, MAIN))

    ahead = git("rev-list", "--count", "%s..HEAD" % base).strip()
    if ahead == "0":
        fail("%s carries nothing that is not already on %s" % (branch, base))

    conflict = run(["git", "merge-tree", "--write-tree", base, "HEAD"], check=False)
    if conflict.returncode:
        fail("%s conflicts with %s. Merge %s in and resolve it first.\n%s"
             % (branch, base, base, conflict.stdout))

    print("\n%s -> %s, %s commit(s):" % (branch, MAIN, ahead))
    print(git("log", "--oneline", "%s..HEAD" % base).rstrip())
    print("\nfiles:")
    print(git("diff", "--numstat", "%s...HEAD" % base).rstrip() or "  (none)")

    found = TICKET.search(branch)
    ticket = found.group(1) if found else None
    print("\nticket: " + ("#" + ticket if ticket
                          else "none in %r -- no issue will be closed" % branch))

    if args.dry_run:
        print("\n--dry-run: stopping here, before the suite. Nothing changed.")
        return

    for cmd in SUITE:
        print("\nrunning %s" % " ".join(cmd))
        env = dict(os.environ)
        env.update(SUITE_ENV)
        if subprocess.run(cmd, cwd=REPO, env=env).returncode:
            fail("%s failed -- a red branch is not landed" % " ".join(cmd))

    print("\nmerging into local %s" % MAIN)
    git("checkout", MAIN)
    git("merge", "--ff-only", base)
    git("merge", "--no-ff", branch, "-m", "Merge %s" % branch)
    print("pushing %s" % MAIN)
    git("push", REMOTE, MAIN)

    tree = worktree_of(branch)
    if tree:
        print("removing worktree %s" % tree)
        git("worktree", "remove", tree)
    git("branch", "-d", branch)
    print("deleted local branch %s" % branch)

    if not args.keep_remote_branch:
        gone = run(["git", "push", REMOTE, "--delete", branch], check=False)
        print("deleted %s/%s" % (REMOTE, branch) if not gone.returncode
              else "remote branch left alone: " + gone.stderr.strip())

    if ticket:
        close_ticket(ticket)

    print("\nlanded. %s is merged, pushed, and the tree is clean." % MAIN)


if __name__ == "__main__":
    main()
