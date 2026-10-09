r"""Check the repo against the cascade rule in CLAUDE.md's "How you edit this repo".

One check per row of that rule's table: every fact this project writes down in
more than one place is compared against its other copies. Reports drift and
exits non-zero; changes nothing, so it is safe to run any time.

    python tools\cascade-audit.py

Python rather than PowerShell because every check reads Python or Markdown, and
because this must run on a developer machine rather than on a server - it is not
a deployment script and does not use deploy.json.

Two lessons are baked into the checks and worth not un-learning, because both
made an earlier version of this script report a clean repo that was not:

  * Walk *every* file in tools\, not just *.ps1. Checking only .ps1 is how
    _devtools.py stayed undocumented through an audit that reported zero drift.
  * Split the API section on the next "## " heading, never on "---". A Markdown
    table's separator row is "|--------|------|", so splitting on "---"
    truncates the table to nothing and every route then looks undocumented.
"""
import ast
import fnmatch
import io
import json
import os
import re
import subprocess
import sys
import xml.dom.minidom
import zipfile

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []
notes = []


def read(rel):
    return io.open(os.path.join(R, rel), encoding="utf-8", newline="").read()


def ok(msg):
    print("  [OK]    %s" % msg)


def bad(msg):
    print("  [DRIFT] %s" % msg)
    fails.append(msg)


def note(msg):
    print("  [note]  %s" % msg)
    notes.append(msg)


def head(msg):
    print("\n=== %s ===" % msg)


def git(*args):
    return subprocess.check_output(["git", "-C", R] + list(args),
                                   stderr=subprocess.STDOUT).decode().strip()


DOCS = ("CLAUDE.md",
        "docs/reference/architecture.md",
        "docs/reference/rules.md",
        "docs/reference/cascade.md",
        "docs/reference/api.md",
        "docs/reference/database.md",
        "docs/reference/apps.md",
        "docs/reference/tooling.md",
        "docs/reference/files-on-disk.md",
        "docs/runbooks/release.md")

# CLAUDE.md is a router now, so every check below reads the whole set as one
# text. The separator is a bare "## " heading rather than a newline: the API
# check splits its section on the next "## ", and without one at each boundary
# that block would run on into whatever file happens to follow.
CM = "\n\n## _\n\n".join(read(p) for p in DOCS)

# ---- APP_VERSION across the four sources ----------------------------------
head("APP_VERSION in all four sources")
vers = {}
for f in ("server.py", "storekeeper_app.py", "notifier_app.py", "installer.py"):
    m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', read(f), re.M)
    vers[f] = m.group(1) if m else None
if len(set(vers.values())) == 1 and None not in vers.values():
    ok("all four report %s" % list(vers.values())[0])
else:
    bad("APP_VERSION disagrees: %s" % vers)

# ---- PASSWORD_MIN: server.py vs installer.py ------------------------------
# One number, two files, and deliberately no call between them: installer.py
# does not import server.py and must not - the server is not on the machine
# being installed from, and rule 10 keeps the two release paths apart - so the
# constant is written down twice and this row is the whole of what keeps the
# two equal. Which way it drifts is what makes it worth a row: every other door
# holding this bound changes a password that exists, where installer.py's sets
# the first admin password an install ever has, and that is the credential
# every capability password is measured against. Raise it in server.py alone
# and the loosest door in the system is the one at the bottom of it.
#
# Read off the module body by AST rather than by text sweep, and only the
# module body: a comment naming the bound is not an assignment of it, and a
# local of that name inside some function would answer for a constant that had
# gone. A file that has stopped stating it at all is drift rather than a quiet
# skip, this row being the only thing holding the second copy down.
head("PASSWORD_MIN in server.py vs installer.py")
mins = {}
for f in ("server.py", "installer.py"):
    for node in ast.parse(read(f)).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "PASSWORD_MIN"
                and isinstance(node.value, ast.Constant)):
            mins[f] = node.value.value
if len(mins) != 2:
    bad("PASSWORD_MIN is not a module-level constant in both: %s" % mins)
elif len(set(mins.values())) == 1:
    ok("both say %r" % list(mins.values())[0])
else:
    bad("PASSWORD_MIN disagrees: %s" % mins)

# ---- PERMISSIONS vs PERMISSION_LABELS vs the CONTEXT.md count -------------
# Both halves of rule 8 now live in server.py: 013 took the Add Engineer form
# out of the Storekeeper, so that file no longer carries a PERMISSION_LABELS
# and this check must not go looking for one - an assertion against a name that
# is not in the file passes by finding nothing, which is the shape of a gate
# that has quietly stopped checking. It also refuses a second copy coming back:
# a client mirroring the list is what rule 10 exists to prevent.
head("PERMISSIONS vs PERMISSION_LABELS (both in server.py)")
sp = read("server.py")
m = re.search(r"^PERMISSIONS\s*=\s*[\[\(](.*?)[\]\)]", sp, re.M | re.S)
perms = set(re.findall(r'["\']([a-z_]+)["\']', m.group(1))) if m else set()
# server.py's PERMISSION_LABELS is the caption on each checkbox in Manage
# Users. It is not a second list of names - the form loops over PERMISSIONS and
# looks a caption up, so a name with no caption is still offered as itself - but
# a caption for a name that no longer exists is a label nothing can ever draw,
# and a name with no caption is an Admin ticking a raw identifier. Checked here
# so neither can sit in the file unnoticed.
srv_labels = set()
for node in ast.walk(ast.parse(sp)):
    if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PERMISSION_LABELS"
            for t in node.targets) and isinstance(node.value, ast.Dict):
        srv_labels = {k.value for k in node.value.keys}
print("        names   : %s" % sorted(perms))
print("        captions: %s" % sorted(srv_labels))
if perms and srv_labels == perms:
    ok("server.py's PERMISSION_LABELS captions exactly the %d permission(s)"
       % len(perms))
else:
    bad("server.py's PERMISSION_LABELS drifted: uncaptioned=%s orphaned=%s"
        % (sorted(perms - srv_labels), sorted(srv_labels - perms)))
strays = [f for f in ("storekeeper_app.py", "notifier_app.py", "installer.py",
                      "common.py")
          if re.search(r"^PERMISSION_LABELS\s*=", read(f), re.M)]
if strays:
    bad("a client carries its own PERMISSION_LABELS again: %s - rule 8 keeps "
        "the names in server.py and rule 10 keeps a client from copying them"
        % ", ".join(strays))
else:
    ok("no client carries a second copy of the names")
# CONTEXT.md's Permission entry states how many there are, in words - and it
# is read out of that entry rather than out of the whole document. "There is
# one:" and "There are two:" is the glossary's house style across thirty-odd
# entries, so a search over the file answers with whichever of them comes
# first: where that number happens to differ from len(PERMISSIONS) this fails
# about the wrong paragraph, and where it happens to agree the real entry is
# free to drift to any number at all with nothing watching it. Same reason the
# API check splits its table out on the next heading before reading it.
#
# Not finding the entry, or finding one that no longer states a count, is
# drift rather than a quiet skip: this is the gate on rule 8's count, and a
# check that passes by finding nothing is the failure this script's own
# docstring records twice.
_ctx = read("CONTEXT.md")
if "**Permission**:" not in _ctx:
    bad("CONTEXT.md has no **Permission** entry - the count rule 8 is held to "
        "is stated there and nowhere else")
else:
    _entry = re.split(r"(?:\r?\n){2,}",
                      _ctx.split("**Permission**:", 1)[1], 1)[0]
    mctx = re.search(r"There (?:are|is) (one|two|three|four|five|\d+):",
                     _entry)
    if not mctx:
        bad("CONTEXT.md's Permission entry no longer says how many there are "
            "- that count is what catches a name added to or taken out of "
            "PERMISSIONS without the prose describing it moving too")
    else:
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        claimed = words.get(mctx.group(1)) or int(mctx.group(1))
        if claimed == len(perms):
            ok("CONTEXT.md's Permission entry says %d, matching" % claimed)
        else:
            bad("CONTEXT.md's Permission entry says there are %d permissions, "
                "the code has %d" % (claimed, len(perms)))

# ---- CAPABILITY_LABELS vs the Capability Passwords bullet -----------------
# The label is what a delegate is told their password opens, so a label that
# has drifted from the one CLAUDE.md documents is a delegation described two
# different ways. The names are checked too: a capability CLAUDE.md does not
# mention is one nobody was told is delegable.
head("CAPABILITY_LABELS (server) vs the Capability Passwords bullet")
caps, cap_labels, cap_remote, cap_reach = [], [], None, []
for node in ast.walk(ast.parse(sp)):
    if not isinstance(node, ast.Assign):
        continue
    for t in node.targets:
        if not isinstance(t, ast.Name):
            continue
        if t.id == "CAPABILITIES":
            caps = [e.value for e in node.value.elts]
        elif t.id == "CAPABILITY_LABELS":
            cap_labels = [(k.value, v.value)
                          for k, v in zip(node.value.keys, node.value.values)]
        elif t.id == "CAPABILITY_REACH":
            cap_reach = [(k.value, v.value)
                         for k, v in zip(node.value.keys, node.value.values)]
        elif t.id == "CAPABILITY_REMOTE":
            # frozenset(("a", "b")) - the names are in the call's one argument.
            arg = node.value.args[0] if isinstance(node.value, ast.Call) \
                else node.value
            cap_remote = [e.value for e in arg.elts]
if not caps or not cap_labels:
    bad("CAPABILITIES or CAPABILITY_LABELS is missing from server.py")
else:
    print("        capabilities: %s" % sorted(caps))
    if sorted(caps) == sorted(n for n, _ in cap_labels):
        ok("every capability has a label and every label a capability")
    else:
        bad("the two lists differ: %s vs %s"
            % (sorted(caps), sorted(n for n, _ in cap_labels)))
    doc = CM
    missing = [lb for _, lb in cap_labels if lb not in doc]
    if missing:
        bad("CLAUDE.md does not name these capability labels: %s" % missing)
    else:
        ok("CLAUDE.md names all %d labels" % len(cap_labels))
    if "ADR-0006" in doc:
        ok("and points at ADR-0006")
    else:
        bad("CLAUDE.md no longer points at ADR-0006")

    # CAPABILITY_REMOTE is the third column of the same fact since R1: which of
    # the four are reachable over the network. Two claims, and the second is
    # the one worth a gate - a capability that is not a capability is a typo
    # nothing would report, while ssl_cert appearing here is a decision that
    # would mean uploading ssl_key.pem to install a certificate remotely, which
    # is the one file that must never travel (rule 1). It is a deliberate
    # absence, so nothing but a check asserts it.
    if cap_remote is None:
        bad("CAPABILITY_REMOTE is missing from server.py")
    else:
        print("        remote: %s" % sorted(cap_remote))
        stray = [c for c in cap_remote if c not in caps]
        if stray:
            bad("CAPABILITY_REMOTE names what is not a capability: %s" % stray)
        else:
            ok("every remote capability is a capability")
        if "ssl_cert" in cap_remote:
            bad("ssl_cert is in CAPABILITY_REMOTE - installing a certificate "
                "remotely means uploading ssl_key.pem (rule 1)")
        else:
            ok("and ssl_cert is deliberately not one of them")
        if "CAPABILITY_REMOTE" in doc and "ADR-0015" in doc:
            ok("CLAUDE.md names CAPABILITY_REMOTE and points at ADR-0015")
        else:
            bad("CLAUDE.md no longer names CAPABILITY_REMOTE or ADR-0015")

    # CAPABILITY_REACH is the fourth column of that same fact (#170), and it
    # is here rather than only in server-checks.py for the reason the label
    # is: what a delegate's password opens is written down in server.py and
    # nowhere else, so what this holds is that the line exists for every
    # capability and that CLAUDE.md still says where it lives. A label names
    # an action, which was enough while every label described itself, and
    # "Server Settings" beside "Change Host / Port" does not - so a capability
    # with no reach line is a row on that window saying nothing about the
    # password an Admin is handing over.
    if not cap_reach:
        bad("CAPABILITY_REACH is missing from server.py")
    else:
        if sorted(caps) == sorted(n for n, _ in cap_reach):
            ok("every capability says what it reaches")
        else:
            bad("CAPABILITY_REACH and CAPABILITIES differ: %s vs %s"
                % (sorted(n for n, _ in cap_reach), sorted(caps)))
        blank = [n for n, line in cap_reach if not (line or "").strip()]
        if blank:
            bad("these capabilities have an empty reach line: %s" % blank)
        else:
            ok("and none of those lines is empty")
        if "CAPABILITY_REACH" in doc:
            ok("CLAUDE.md names CAPABILITY_REACH")
        else:
            bad("CLAUDE.md no longer names CAPABILITY_REACH")

# ---- the engineer list, in three places ----------------------------------
head("TEAM_MEMBERS (common.py) vs server.py's seed list")
m = re.search(r"^TEAM_MEMBERS\s*=\s*\[(.*?)\]", read("common.py"), re.M | re.S)
client_list = re.findall(r'["\']([^"\']+)["\']', m.group(1)) if m else []
seed = []
# The server's list is not a module constant - it is inline in init_db()'s
# "if the table is empty" branch, so look for the loop feeding the INSERT.
for pat in (r"^TEAM_MEMBERS\s*=\s*\[(.*?)\]",
            r"^DEFAULT_MEMBERS\s*=\s*\[(.*?)\]",
            r"^SEED_MEMBERS\s*=\s*\[(.*?)\]",
            r"for \w+ in \[([^\]]+)\]:\s*\n\s*c\.execute\(\s*"
            r"[\"']INSERT OR IGNORE INTO team_members"):
    ms = re.search(pat, sp, re.M | re.S)
    if ms:
        seed = re.findall(r'["\']([^"\']+)["\']', ms.group(1))
        break
print("        common.py : %s" % client_list)
print("        server.py : %s" % seed)
if client_list and seed and client_list == seed:
    ok("same %d engineers, same order" % len(client_list))
elif client_list and set(client_list) == set(seed):
    note("same engineers, different order - harmless, but they drift apart easily")
else:
    bad("engineer lists differ: common-only=%s server-only=%s"
        % (sorted(set(client_list) - set(seed)), sorted(set(seed) - set(client_list))))
team_block = CM.split("## Team", 1)[1].split("---", 1)[0] if "## Team" in CM else ""
absent = [n for n in client_list if n not in team_block]
if not absent:
    ok("CLAUDE.md's Team section names all of them")
else:
    bad("CLAUDE.md's Team section is missing: %s" % absent)


# ---- table columns vs the schema block in the doc set ---------------------
def columns_of(table):
    """Columns in CREATE TABLE plus the ones init_db() adds idempotently.

    The ALTERs matter: they are what makes 001_baseline a no-op, so a column
    that only ever arrives that way is still a real column.
    """
    cols = set()
    mc = re.search(r"CREATE TABLE IF NOT EXISTS %s\s*\((.*?)\)\s*['\"]" % table, sp, re.S)
    if mc:
        for line in mc.group(1).split("\n"):
            # A digit is part of a name, here and in the two patterns
            # beside this one. The ALTER walk below has always read one
            # with \w, so a name like addr2 was a column to that half and
            # not a column to this one - and the doc block was read the
            # third way again. A column added the both-ways pattern this
            # repo requires, and documented correctly, then reported as
            # code-only: a gate crying drift over a repo that has none is
            # how a gate is trained to be ignored. One added in CREATE
            # alone and never written down is the quiet direction - missed
            # on both sides, the sets equal, and an undocumented column
            # reported as identical.
            mm = re.match(r"\s*([a-z_0-9]+)\s+(INTEGER|TEXT|REAL|BLOB)", line)
            if mm:
                cols.add(mm.group(1))
    cols |= set(re.findall(r"ALTER TABLE %s ADD COLUMN (\w+)" % table, sp))
    return cols


def documented_columns(marker):
    if marker not in CM:
        return set()
    block = CM.split(marker, 1)[1].split("```", 2)[1]
    return set(re.findall(r"^([a-z_0-9]+)\s+\w", block, re.M))


head("table columns: server.py vs docs/reference/database.md")
for table, marker in (("transactions", "Table `transactions`:"),
                      ("team_members", "Table `team_members`"),
                      ("assets", "Table `assets`"),
                      ("clients", "Table `clients`"),
                      ("client_commands", "Table `client_commands`"),
                      ("system_log", "Table `system_log`")):
    code, doc = columns_of(table), documented_columns(marker)
    if code and code == doc:
        ok("%s: identical column sets (%d), ALTERs included" % (table, len(code)))
    else:
        bad("%s column drift: code-only=%s doc-only=%s"
            % (table, sorted(code - doc), sorted(doc - code)))

# ---- this script reads a column name the same way in all three places ----
head("a column name carrying a digit is read the same way on both sides")
# The two readers above are fed a synthetic table rather than the repo's own,
# because what is under test is the reader and not the schema: every column in
# this repo is spelled a-z today, so the repo cannot demonstrate the defect,
# and a check that waits for such a column to be added is one that reports
# clean until the day it matters. The ALTER walk reads a name with \w and the
# other two read one with [a-z_], so addr2 was a column to one half and not to
# the other - documented correctly it was reported as code-only drift, and
# added in CREATE alone it was missed on both sides, the sets matched, and an
# undocumented column was reported as identical.
_sp_real, _cm_real = sp, CM
sp = ("    c.execute('''CREATE TABLE IF NOT EXISTS probe (\n"
      "        client_id  TEXT PRIMARY KEY,\n"
      "        addr2      TEXT    DEFAULT ''\n"
      "    )''')\n"
      "ALTER TABLE probe ADD COLUMN seen3 TEXT\n")
CM = ("Table `probe`:\n\n```\n"
      "client_id  TEXT PRIMARY KEY\n"
      "addr2      TEXT DEFAULT ''\n"
      "seen3      TEXT DEFAULT ''\n```\n")
_code, _doc = columns_of("probe"), documented_columns("Table `probe`:")
sp, CM = _sp_real, _cm_real
if _code == _doc == {"client_id", "addr2", "seen3"}:
    ok("CREATE, ALTER and the schema block all read addr2 and seen3")
else:
    bad("a digit in a column name is read differently by the three patterns: "
        "CREATE and ALTER gave %s, the schema block gave %s"
        % (sorted(_code), sorted(_doc)))


# ---- Flask routes vs the API table ---------------------------------------
head("Flask routes vs the API table in docs/reference/api.md")
routes = set()
for m in re.finditer(r'@app\.route\(\s*["\']([^"\']+)["\']'
                     r'(?:\s*,\s*methods\s*=\s*\[([^\]]*)\])?', sp):
    for meth in re.findall(r"['\"](\w+)['\"]", m.group(2) or "'GET'"):
        routes.add((meth.upper(), m.group(1)))
# See the module docstring: split on the next "## ", never on "---".
api_block = re.split(r"\n## ", CM.split("## API Endpoints", 1)[1], 1)[0]
doc_routes = set()
for m in re.finditer(r"^\|\s*(GET|POST|PUT|DELETE)\s*\|\s*`([^`]+)`", api_block, re.M):
    doc_routes.add((m.group(1), m.group(2).split("?")[0]))


def norm(p):
    """Ignore the parameter's name: /confirm/<id> and /confirm/<x> are one row."""
    return re.sub(r"<[^>]+>", "<>", p.rstrip("/")) or "/"


live = {(a, norm(b)) for a, b in routes}
docd = {(a, norm(b)) for a, b in doc_routes}
print("        code: %d route(s), doc: %d row(s)" % (len(live), len(docd)))
if live == docd:
    ok("every route is documented and every documented row exists")
else:
    if live - docd:
        bad("routes missing from the API table: %s" % sorted(live - docd))
    if docd - live:
        bad("API table rows with no such route: %s" % sorted(docd - live))


# ---- the API table's Credential column vs the door() declarations ---------
head("door() declarations (server.py) vs the API table's Credential column")
# The column is derived from the declarations rather than written beside them
# (#209), so this is the whole of what keeps it true. Both halves matter: a
# route whose credential moved and whose row did not says the wrong thing to
# whoever reads the table to find out what to send, and a row that names a
# credential no route asks for is a door somebody will go looking for.
_dtree = ast.parse(sp)
_labels = dict(re.findall(r'"(\w+)":\s*"([^"]+)"',
                          re.search(r"CAPABILITY_LABELS = \{(.*?)\}", sp,
                                    re.S).group(1)))
_fixed = dict(re.findall(r'^(DOOR_\w+)\s*=\s*"(\w+)"', sp, re.M))


def _door_of(fn):
    """The (credential, optional) a route function declares, or None."""
    for d in fn.decorator_list:
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                and d.func.id == "door"):
            continue
        a = d.args[0]
        cred = a.value if isinstance(a, ast.Constant) else _fixed.get(a.id, "?")
        opt = any(k.arg == "optional" and getattr(k.value, "value", False)
                  for k in d.keywords)
        return cred, opt
    return None


def _column(cred, optional):
    """What the table's Credential cell has to read for that declaration."""
    if cred in ("open", "admin", "own"):
        return cred
    return ("open · admin · " if optional else "admin · ") + _labels[cred]


_want = {}
_undeclared = []
for _n in ast.walk(_dtree):
    if not isinstance(_n, ast.FunctionDef):
        continue
    _rs = [d for d in _n.decorator_list
           if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
           and d.func.attr == "route"]
    if not _rs:
        continue
    _d = _door_of(_n)
    if _d is None:
        _undeclared.append(_n.name)
        continue
    for _r in _rs:
        _ms = ["GET"]
        for _k in _r.keywords:
            if _k.arg == "methods":
                _ms = [e.value for e in _k.value.elts]
        for _m in _ms:
            _want[(_m.upper(), norm(_r.args[0].value))] = _column(*_d)

_have = {}
for _m in re.finditer(r"^\|\s*(GET|POST|PUT|DELETE)\s*\|\s*`([^`]+)`\s*\|"
                      r"\s*([^|]*?)\s*\|", api_block, re.M):
    _have[(_m.group(1), norm(_m.group(2).split("?")[0]))] = _m.group(3)

print("        %d declared route(s), %d Credential cell(s)"
      % (len(_want), len(_have)))
if _undeclared:
    for _n in sorted(_undeclared):
        bad("%s is a route in server.py and declares no door() - "
            "tools/server-checks.py is what refuses it, and the API table "
            "has nothing to derive its Credential cell from" % _n)
elif len(_want) < 40:
    bad("only %d declared route(s) found - this file has ~48, so the parse "
        "found nothing and the comparison below is vacuous" % len(_want))
else:
    ok("every route in server.py declares a door()")
    _wrong = sorted(k for k in _want if _have.get(k) != _want[k])
    if _wrong:
        for _k in _wrong:
            bad("%s %s: server.py declares %r, the API table's Credential "
                "column says %r" % (_k[0], _k[1], _want[_k],
                                    _have.get(_k, "<no row>")))
    else:
        ok("all %d Credential cells match the declaration at the route"
           % len(_want))
    _extra = sorted(k for k in _have if k not in _want)
    if _extra:
        for _k in _extra:
            bad("the API table has a Credential cell for %s %s, which is no "
                "route" % _k)
    else:
        ok("no Credential cell names a route that does not exist")


# ---- everything in tools/ is documented ----------------------------------
head("everything in tools/ against the tooling reference")
entries = sorted(f for f in os.listdir(os.path.join(R, "tools"))
                 if os.path.isfile(os.path.join(R, "tools", f)))
scripts = [f for f in entries if f.endswith(".ps1")]
print("        %d file(s): %s" % (len(entries), ", ".join(entries)))
numbers = {6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
mcount = re.search(r"All (\w+) \*\*PowerShell\*\* scripts", CM)
if mcount:
    if numbers.get(len(scripts)) == mcount.group(1):
        ok('"All %s PowerShell scripts" matches the %d .ps1 files'
           % (mcount.group(1), len(scripts)))
    else:
        bad('the tooling reference says "All %s PowerShell scripts" but '
            'tools\\ holds %d'
            % (mcount.group(1), len(scripts)))
for s in entries:
    # A heading, not just the name somewhere: the tooling reference is one
    # section per script, so a script with no section of its own is a script
    # nothing describes - which the old table-shaped test could not tell
    # apart from one merely mentioned in a sentence.
    if "### `tools/%s`" % s in CM:
        ok("%s has a tooling section" % s)
    elif s in CM:
        ok("%s is named in the doc set, though not as a section" % s)
    else:
        bad("%s is in tools\\ but nothing in the doc set mentions it" % s)

# ---- the PowerShell scripts are pure ASCII -------------------------------
head("PowerShell scripts are pure ASCII (the PS 5.1 cp1252 trap)")
for s in scripts:
    raw = io.open(os.path.join(R, "tools", s), "rb").read()
    high = [b for b in bytearray(raw) if b > 127]
    if high:
        bad("%s has %d non-ASCII byte(s)" % (s, len(high)))
    else:
        ok("%s is ASCII" % s)

# ---- an https probe in tools\ can verify what it is probing ---------------
head("the https probes go through Invoke-PinnedRequest")
# #109. install-iis.ps1 -SelfSigned mints into Cert:\LocalMachine\My, nothing in
# tools\ or in any runbook puts a copy in LocalMachine\Root, and Windows
# PowerShell 5.1 has no -SkipCertificateCheck - so Invoke-WebRequest and
# Invoke-RestMethod cannot complete a handshake against the only certificate
# this deployment has. Both probes then reported a healthy server as a failure,
# and update.ps1's read that as a bad build and rolled a good update back over
# an already-migrated database. The answer is one helper in _deploy.ps1 that
# accepts the pinned certificate and nothing else; what this asserts is that
# nobody writes the cmdlet back in, which is an absence, and no harness here
# stands up IIS.
#
# The two call sites that must use it, and the exceptions that may not:
#   package.ps1 Get-CertFromServer - fetching the certificate, so it has
#       nothing to pin to, and says so at length.
#   dev-run.ps1 - probes over plain HTTP only, under `if (-not $Https)`, which
#       is the same trap answered by declining to probe.
_PROBE = re.compile(r"\bInvoke-(?:WebRequest|RestMethod)\b")
_PINNED = "Invoke-PinnedRequest"

if "function %s" % _PINNED in read("tools/_deploy.ps1"):
    ok("_deploy.ps1 defines %s" % _PINNED)
else:
    bad("_deploy.ps1 no longer defines %s - the two probes have nothing to "
        "verify a self-signed certificate with" % _PINNED)

for _s in ("update.ps1", "install-iis.ps1"):
    if _PINNED in read("tools/%s" % _s):
        ok("%s probes through %s" % (_s, _PINNED))
    else:
        bad("%s does not call %s" % (_s, _PINNED))

for _s in scripts:
    _lines = read("tools/%s" % _s).split("\n")
    _fn = None
    for _i, _line in enumerate(_lines):
        _m = re.match(r"^function\s+([A-Za-z][\w-]*)", _line)
        if _m:
            _fn = _m.group(1)
        if not _PROBE.search(_line):
            continue
        _where = "%s:%d" % (_s, _i + 1)
        if _s == "package.ps1" and _fn == "Get-CertFromServer":
            ok("%s fetches the certificate it cannot pin to" % _where)
        elif _s == "dev-run.ps1" and any(
                "-not $Https" in _l for _l in _lines[max(0, _i - 12):_i]):
            ok("%s probes over plain HTTP only" % _where)
        else:
            bad("%s calls %s - that cannot verify this deployment's own "
                "certificate from PS 5.1; go through %s"
                % (_where, _PROBE.search(_line).group(0), _PINNED))

# ---- a certificate replacement warning says which certificate -------------
head("the certificate warnings name both fingerprints")
# #110. update.ps1 named both sides of a replacement and install-iis.ps1 named
# neither, at the one moment an operator has to decide whether every laptop on
# the network has to be visited: a client fails closed against a certificate it
# did not pin, so the question is whether the outgoing file is the one they
# actually hold. One hash on its own can be compared with nothing, and none at
# all cannot even identify the backup copy the warning points at. Source,
# because nothing here stands up IIS or a client to read a warning off.
_CERT_WARN = re.compile(r"^\s*Warn\b.*replac", re.I)
_FP = "Get-CertFingerprint"
_cert_warns = 0

for _s in scripts:
    _lines = read("tools/%s" % _s).split("\n")
    for _i, _line in enumerate(_lines):
        if not _CERT_WARN.search(_line):
            continue
        if "ssl_cert.pem" not in _line and "certificate" not in _line.lower():
            continue
        _cert_warns += 1
        _where = "%s:%d" % (_s, _i + 1)
        # The fingerprints follow the sentence rather than opening it - the
        # operator is told what is happening first - so the window is the warning
        # block rather than the next line or two.
        if any(_FP in _l for _l in _lines[_i:_i + 20]):
            ok("%s names a fingerprint with the replacement it warns about" % _where)
        else:
            bad("%s warns that a certificate is being replaced and names neither "
                "side - a client that pinned the outgoing one fails closed, and "
                "nothing here says which one that was; go through %s"
                % (_where, _FP))

if _cert_warns >= 2:
    ok("both certificate-replacement warnings checked (%d found)" % _cert_warns)
else:
    bad("only %d certificate-replacement warning(s) found in tools\\ - update.ps1 "
        "and install-iis.ps1 each carry one, so one has been reworded past this "
        "check rather than removed" % _cert_warns)

# ---- a rollback puts back everything the update replaced -------------------
head("update.ps1 restores the record of which build is installed")
# #111. installed.json is written by update.ps1 rather than carried by the
# package, so the manifest cannot name it and the rollback list built from that
# manifest did not either: a rolled-back machine ran the old build beside a
# state file naming the version that had just been rolled back. Both $rollback
# and the upgrade/downgrade direction are resolved from that file, so the next
# attempt looked in rollback\<new-version>, found it empty, and copied the
# database - already migrated forward by the failed run - in as that run's
# "before" copy, over the top of the guard written to stop exactly that.
# Source, because nothing here stands up an IIS host to run an update against.
_up = read("tools/update.ps1").split("\n")


def _line_of(needle, lines):
    for _i, _l in enumerate(lines):
        if needle in _l:
            return _i
    return -1


_built = _line_of("$incoming = @($manifest.files", _up)
_added = _line_of("$incoming += $StateFile", _up)
_loops = [_i for _i, _l in enumerate(_up) if "foreach ($rel in $incoming)" in _l]

if _built < 0:
    bad("update.ps1 no longer builds its replaced-file list from the manifest - "
        "this check reads that list, so it can no longer say what a rollback "
        "puts back")
elif _added < 0:
    bad("update.ps1:%d builds the list of files a rollback restores from the "
        "package manifest alone, and installed.json is not in a manifest - it is "
        "this script's own record. A health-check failure then restores the old "
        "build beside a state file naming the version it rolled back, and the "
        "next run resolves rollback\\<that version>, which is empty: the guard "
        "keeping the pre-migration database copy is looking at the wrong "
        "directory. Add $StateFile to $incoming" % (_built + 1))
elif _added < _built:
    bad("update.ps1:%d adds $StateFile to $incoming before the list is built, so "
        "the assignment at line %d throws it away and installed.json is neither "
        "saved nor restored" % (_added + 1, _built + 1))
else:
    ok("update.ps1:%d puts installed.json in the list a rollback restores" % (_added + 1))

# Two loops over one list - the save before the files are written and the
# restore after a failed health check. One list is what stops the two
# disagreeing about what was replaced; a third loop, or one, means they can.
if len(_loops) == 2 and _built < _loops[0] < _loops[1]:
    ok("saved at update.ps1:%d and restored at update.ps1:%d, off that one list"
       % (_loops[0] + 1, _loops[1] + 1))
else:
    bad("update.ps1 iterates $incoming at %s - the save and the restore are one "
        "list read twice, and any other shape lets a rollback put back something "
        "other than what it replaced"
        % (", ".join(str(_i + 1) for _i in _loops) or "no line at all"))

# ---- a comment naming a switch names one that is there --------------------
head("every tools\\ switch named in a comment is one that script declares")
# #112. These comments are reasons rather than descriptions - "package.ps1
# -SelfSigned passes the real server's names instead, which is why this is a
# parameter" - and 061 deleted that switch while leaving the sentence behind.
# A reason whose subject is gone sends the next reader looking for a flag,
# finding nothing, and unable to tell which of the two is the stale one.
_FLAG = re.compile(r"\b([a-z_][a-z0-9_-]*\.ps1)\s+(-[A-Z][A-Za-z0-9]*)")
# The type cast immediately before the name, rather than the start of the line:
# a parameter carrying an attribute is written
# [Parameter(Mandatory = $true, ParameterSetName = "ByVersion")] [string] $Version
# all on one line here, and anchoring at the line start reads the attribute as
# the cast, misses the name, and then reports every mention of a parameter that
# is declared - which is a gate failing the files it is meant to pass.
_PARAM = re.compile(r"\]\s*\$([A-Za-z0-9]+)")
_declared = {}

for _s in scripts:
    _txt = read("tools/%s" % _s)
    _blk = re.search(r"(?ms)^param\s*\((.*?)^\)", _txt)
    _declared[_s.lower()] = set(n.lower() for n in _PARAM.findall(_blk.group(1))) if _blk else set()
    # -WhatIf and -Confirm are declared by SupportsShouldProcess rather than in
    # param(), and are as real as any name in there: five of these scripts say
    # "supports -WhatIf" about themselves and one of them writes it out as an
    # example. Reading only param() reported those as a flag that had been
    # removed, which is a gate failing a file for using the feature correctly -
    # the same shape as the anchoring bug the _PARAM comment above records.
    if re.search(r"SupportsShouldProcess\s*=\s*\$true", _txt):
        _declared[_s.lower()] |= set(["whatif", "confirm"])

# Both languages: the drift this catches was one comment in each.
_named = 0
for _f in sorted(set(["tools/%s" % _s for _s in scripts] +
                     ["tools/_devtools.py", "tools/cascade-audit.py",
                      "tools/server-checks.py", "tools/client-checks.py"])):
    for _i, _line in enumerate(read(_f).split("\n")):
        # The whole line, not the part after a "#". Three of the four places
        # these sentences live carry no "#" at all - a .ps1 <# .. #> help
        # block, a Python docstring, and the .SYNOPSIS text inside the first -
        # and the docstring is where #112's own drift was sitting, so a check
        # reading only "#" comments would have passed the file it is named for.
        # A line of code passing a switch on is read too, and should be: it
        # names the same flag and would be just as wrong.
        for _script, _flag in _FLAG.findall(_line):
            if _script.lower() not in _declared:
                continue
            _named += 1
            if _flag[1:].lower() in _declared[_script.lower()]:
                ok("%s:%d names %s %s" % (_f.split("/")[-1], _i + 1, _script, _flag))
            else:
                bad("%s:%d says %s %s and that script declares no such parameter "
                    "- the switch was removed and the sentence explaining "
                    "something by it was left behind"
                    % (_f.split("/")[-1], _i + 1, _script, _flag))

if _named:
    ok("%d switch mention(s) in tools\\ checked against the declaring script" % _named)
else:
    bad("no script switch is named in any comment in tools\\ - these scripts "
        "explain themselves by each other's flags throughout, so finding none "
        "means this check has stopped reading what it is meant to read")

# ---- an interpreter is resolved before it is invoked ---------------------
head("tools scripts resolve an interpreter before invoking it")
# $ErrorActionPreference = "Stop" makes the CommandNotFoundException that `&`
# raises for a name that is not on PATH terminating, so a refusal written
# underneath such a call and reading $LASTEXITCODE never runs for the case it
# was written for. vendor.ps1 carried one: what an operator with no python on
# PATH actually got was PowerShell's own "The term 'python' is not
# recognized", naming neither -Python nor the role being vendored. What the
# scripts that get this right do is ask Get-Command first - or Test-Path, for
# a variable already holding a full path.
_INTERP = re.compile(r'\[string\]\s*\$(\w*[Pp]ython\w*)\b')
for s in scripts:
    body = read("tools/" + s)
    if '$ErrorActionPreference = "Stop"' not in body:
        continue
    for var in sorted(set(_INTERP.findall(body))):
        call = re.search(r'&\s*\$%s\b' % var, body)
        if not call:
            continue
        before = body[:call.start()]
        if (re.search(r'Get-Command\s+\$?\w*[Pp]ython\w*', before) or
                re.search(r'Test-Path\s+\$%s\b' % var, before)):
            ok("%s resolves $%s before it invokes it" % (s, var))
        else:
            bad("%s invokes $%s with nothing resolving it first - a name not on "
                "PATH dies on CommandNotFoundException, not on the refusal "
                "written under the call" % (s, var))

# ---- and the indirect case: decided in one file, invoked in another ------
head("a runner decided in a helper is resolved in that helper")
# The check above reads a script's own [string] $Python* parameter and the &
# that invokes it, which is the direct shape. Resolve-ServerRunner is the
# other one and was invisible to it: the name is decided in _deploy.ps1 and
# both callers invoke it a file away as "& $runner.File", so neither end
# looks wrong on its own. It handed back the bare "python" where no pythonExe
# was set, and update.ps1 reaches that & after the app pool is stopped and the
# database copied aside - a terminating CommandNotFoundException there is a
# server that is down with no rollback, and the refusal written under the
# call never runs while $ErrorActionPreference is Stop.
_dep = read("tools/_deploy.ps1")
_m = re.search(r"function Resolve-ServerRunner\b(.*?)\n}", _dep, re.S)
if not _m:
    bad("no Resolve-ServerRunner in _deploy.ps1 - this check reads the function "
        "that decides which interpreter a source install's migrations run "
        "under, and finding none means it has stopped reading anything")
elif re.search(r"Get-Command\s+\$pythonExe\b", _m.group(1)):
    ok("_deploy.ps1 resolves $pythonExe through Get-Command inside "
       "Resolve-ServerRunner")
else:
    bad("Resolve-ServerRunner hands back $pythonExe with nothing resolving it "
        "first - the & is in its callers, so a name not on PATH dies there on "
        "CommandNotFoundException, after update.ps1 has stopped the host")
_indirect = 0
for _s in scripts:
    # _deploy.ps1 is where the function is defined and never a caller: the one
    # "& $r.File" in it is the calling convention written in its own help.
    if _s == "_deploy.ps1":
        continue
    _body = read("tools/" + _s)
    for _var in sorted(set(re.findall(r"&\s*\$(\w+)\.File\b", _body))):
        _indirect += 1
        if re.search(r"\$%s\s*=\s*Resolve-ServerRunner\b" % _var, _body):
            ok("%s invokes $%s.File and takes it from Resolve-ServerRunner"
               % (_s, _var))
        else:
            bad("%s invokes $%s.File without taking it from "
                "Resolve-ServerRunner - a second thing deciding what to run is "
                "a second place for an unresolved name to reach an &"
                % (_s, _var))
if not _indirect:
    bad("nothing in tools\\ invokes a runner's .File - update.ps1 and "
        "migrate.ps1 both do, so finding none means this check has stopped "
        "reading what it is meant to read")

# ---- a comment above a function is about that function -------------------
head("a comment block above a function is about the function under it")
# A comment block sits above the function it explains, and moving a function
# does not move it. _deploy.ps1's nine lines on why Resolve-Switch takes a
# [bool] rather than a [switch] - trap three in CLAUDE.md, and a bug that
# shipped here - were left on top of Resolve-ServerRunner when 2bea743
# inserted that function between them and Resolve-Switch. Nothing said so:
# the file parses either way, and the next reader of Resolve-Switch finds no
# reason at all not to give it the [switch] it looks like it wants. So a
# block naming some other function of the same file, and not the one it sits
# on, is read as having been left behind by whatever landed in between.
for s in scripts:
    lines = read("tools/" + s).split("\n")
    lines = [ln.rstrip('\r') for ln in lines]
    defined = set()
    for ln in lines:
        m = re.match(r'function\s+([\w-]+)', ln)
        if m:
            defined.add(m.group(1))
    blocks = 0
    for i, ln in enumerate(lines):
        m = re.match(r'function\s+([\w-]+)', ln)
        if not m:
            continue
        name, j, text = m.group(1), i - 1, []
        while j >= 0 and lines[j].startswith("#"):
            text.append(lines[j])
            j -= 1
        if not text:
            continue
        blocks += 1
        text = "\n".join(text)
        if re.search(r'\b%s\b' % re.escape(name), text):
            continue
        stray = sorted(o for o in defined if o != name and
                       re.search(r'\b%s\b' % re.escape(o), text))
        if stray:
            bad("%s: the comment above %s is about %s" %
                (s, name, ", ".join(stray)))
    if blocks:
        ok("%s: %d comment block(s) above a function, none about another one"
           % (s, blocks))

# ---- one client knows how a password is verified -------------------------
head("the two password doors live in common.py alone (rule 10)")
# Rule 10, enforced rather than remembered. /auth/verify has to be paired with a
# fallback to /admin/verify for a server that predates it, and that pair lived
# inside the Notifier until the installer needed the same answer. A second copy
# is how a security fix comes to be made twice and be right once.
#
# The test is which module *calls* it, not which mentions it: a comment or a
# docstring explaining why the call is not here would otherwise fail this. Any
# call shape counts, not just this repo's api() helper - a copy written
# requests.post() would be the same second copy, and matching one spelling
# would let the one thing this gate exists to stop walk through it.
for _mod in ("common.py", "notifier_app.py", "storekeeper_app.py",
             "installer.py"):
    _src = read(_mod)
    _tree = ast.parse(_src)
    _calls = [n for n in ast.walk(_tree)
              if isinstance(n, ast.Call) and "/auth/verify" in ast.unparse(n)]
    if _mod == "common.py":
        _fns = [n for n in ast.walk(_tree)
                if isinstance(n, ast.FunctionDef)
                and "/auth/verify" in ast.unparse(n)]
        if len(_calls) != 1:
            bad("common.py calls /auth/verify %d time(s), expected exactly 1"
                % len(_calls))
        elif not _fns or "verify_admin_password" not in ast.unparse(_fns[0]):
            # The pairing, not just the call. /auth/verify alone would leave a
            # client that updates first unable to reach a server that predates
            # the endpoint, which is the whole reason the fallback exists. The
            # test is the call to the other door rather than the URL, because
            # the fallback goes through that door and asking the URL here would
            # be the second copy this rule is about.
            bad("common.py calls /auth/verify without falling back through "
                "verify_admin_password - a server that predates the endpoint "
                "answers 404 and there would be nothing to fall back to")
        else:
            ok("common.py calls it once, falling back through "
               "verify_admin_password in the same function")
    elif _calls:
        bad("%s calls /auth/verify itself - go through "
            "common.verify_password, or its fallback to /admin/verify becomes "
            "a second copy (rule 10)" % _mod)
    else:
        ok("%s does not call /auth/verify itself" % _mod)

    # The admin-only door, same rule and now the same shape (#23). Exactly one
    # call, inside verify_admin_password: verify_password's fallback comes
    # through that function rather than asking the endpoint a second time, so
    # one is the honest number and a second call anywhere is the copy this rule
    # exists to refuse.
    _admin_calls = [n for n in ast.walk(_tree)
                    if isinstance(n, ast.Call)
                    and "/admin/verify" in ast.unparse(n)]
    if _mod == "common.py":
        # The function the call node actually sits in, not one whose
        # unparse mentions the URL - a docstring saying why the call is
        # not here would otherwise answer for it.
        _admin_fns = [n.name for n in ast.walk(_tree)
                      if isinstance(n, ast.FunctionDef)
                      and _admin_calls
                      and any(d is _admin_calls[0]
                              for d in ast.walk(n))]
        if len(_admin_calls) != 1:
            bad("common.py calls /admin/verify %d time(s), expected exactly 1 "
                "- verify_admin_password is the one place that asks it"
                % len(_admin_calls))
        elif _admin_fns[:1] != ["verify_admin_password"]:
            bad("common.py asks /admin/verify from %s rather than from "
                "verify_admin_password" % (_admin_fns[:1] or ["nowhere"])[0])
        else:
            ok("common.py asks /admin/verify once, from verify_admin_password")
    elif _admin_calls:
        bad("%s calls /admin/verify itself - go through "
            "common.verify_admin_password (rule 10). Do not reach for "
            "verify_password instead: that one also accepts an engineer's own "
            "password" % _mod)
    else:
        ok("%s does not call /admin/verify itself" % _mod)

# ---- the Storekeeper's role label, on both sides of the wire --------------
head("the Storekeeper's label is worded the same on both sides")
# The server appends it for a caller that sent no name, and the Storekeeper
# appends it to every entry it ships. The two cannot go through common.py - the
# server does not import it (rule 10) - so this is the same shape as
# TEAM_MEMBERS, a fact written down twice and held to agreeing here. What
# breaks if they drift is invisible: half the System Log reads "X (Storekeeper)"
# and half "X (storekeeper)", and a filter over the column matches one of them.
SK_LABEL = '"%s (Storekeeper)"'
_sk_server = read("server.py").count(SK_LABEL)
_sk_client = read("storekeeper_app.py").count(SK_LABEL)
if _sk_server == 1 and _sk_client == 1:
    ok("server.py and storekeeper_app.py word it once each, identically")
else:
    bad("the role label is written %d time(s) in server.py and %d in "
        "storekeeper_app.py - each must word it exactly once, and the same "
        "way, or the System Log says two things about one person"
        % (_sk_server, _sk_client))

# The default behind it, in the four places that state it: the column default
# in server.py's schema, the constant the server falls back to, the client
# config's default, and the Notifier popup's fallback for a row whose column is
# empty. A row written by an old client and a row written by a server with no
# name configured are the same fact. The fourth is a display fallback rather
# than a source of truth, and is held here anyway: it is the same literal, and
# it is what an Engineer is shown a Transaction came from. That fourth one is
# a **named constant** since 079 rather than a literal in the popup's own
# expression: the Notifier draws it in two places now - the popup and the
# Pending detail pane - and a literal at each would be a second copy inside
# one file, which is the thing this section exists to find.
_srv = read("server.py")
_defaults = {
    "STOREKEEPER_DEFAULT in server.py":
        'STOREKEEPER_DEFAULT = "Storekeeper User"' in _srv,
    "the transactions.storekeeper column default":
        "storekeeper      TEXT    DEFAULT 'Storekeeper User'" in _srv,
    "DEFAULT_CFG in storekeeper_app.py":
        '"storekeeper_name": "Storekeeper User"' in read("storekeeper_app.py"),
    "the Notifier's display fallback":
        'STOREKEEPER_FALLBACK = "Storekeeper User"' in read("notifier_app.py"),
}
_missing = [k for k, v in _defaults.items() if not v]
if _missing:
    bad("the Storekeeper default disagrees with itself - not found in: %s"
        % ", ".join(_missing))
else:
    ok("the default name agrees in all %d of its homes" % len(_defaults))

# ---- the client package names, on both sides of the download -------------
head("the client package names agree across the four places")
# server.py hands a client zip out of dist\ by name; bundle-client.ps1 is what
# writes that zip; and each client app says which key it asks under. Four
# copies of one fact, and none of them can reach the others at runtime - the
# server does not import common.py (rule 10) and a .ps1 imports nothing at
# all. Drift is a 404 for a package sitting beside the server, on the one
# path that exists to stop a client being stranded.
_srv_tree = ast.parse(read("server.py"))
_pkgs = {}
for _node in _srv_tree.body:
    if (isinstance(_node, ast.Assign) and len(_node.targets) == 1
            and isinstance(_node.targets[0], ast.Name)
            and _node.targets[0].id == "CLIENT_PACKAGES"):
        _pkgs = ast.literal_eval(_node.value)
_bundle = read("tools/bundle-client.ps1")
_bundle_names = dict(re.findall(
    r'^\s*(\w+)\s*=\s*@\{\s*$\s*^\s*Name\s*=\s*"([^"]+)"',
    _bundle, re.M))
_keys = {
    "notifier_app.py":    read("notifier_app.py"),
    "storekeeper_app.py": read("storekeeper_app.py"),
}
if not _pkgs:
    bad("server.py has no CLIENT_PACKAGES map - GET /download/client/<key> has nothing to resolve against")
elif _pkgs != _bundle_names:
    bad("server.py's CLIENT_PACKAGES %r and bundle-client.ps1's $Apps %r "
        "disagree - the server would hand out 404s for a zip that is there"
        % (_pkgs, _bundle_names))
else:
    _wrong = []
    for _src, _text in sorted(_keys.items()):
        _m = re.search(r'^UPDATE_APP_KEY = "([^"]+)"', _text, re.M)
        if not _m:
            _wrong.append("%s states no UPDATE_APP_KEY" % _src)
        elif _m.group(1) not in _pkgs:
            _wrong.append("%s asks under %r, which server.py does not serve"
                          % (_src, _m.group(1)))
    if _wrong:
        bad("; ".join(_wrong))
    else:
        ok("%d package name(s) agree in server.py, bundle-client.ps1 and "
           "both clients" % len(_pkgs))

# ---- and that a release directory is built carrying them ----------------
head("package.ps1 writes the client update packages beside the installer")
# The names agreeing is only half of it: a server hands out
# GET /download/client/<key> from dist\ beside it, and dist\<version>\ is the
# unit that gets carried to a machine - so a release directory holding the
# setup exe and not the two zips is a server that answers /version with
# `latest` and an empty `client_packages`, tells every installation it is
# behind and offers it nothing but the browser. Nothing else here can see that:
# it is a property of what a build run produces, so the only place to assert it
# is that package.ps1 invokes bundle-client.ps1 in BOTH of its shapes - -StageTo
# for the payload PyInstaller embeds, and the zip shape for the packages a
# client updates itself from.
_pkg_ps1 = read("tools/package.ps1")
_splats = re.findall(
    r'&\s*\(Join-Path\s+\$PSScriptRoot\s+"bundle-client\.ps1"\)\s*@(\w+)',
    _pkg_ps1)
_shapes = {}
for _var in _splats:
    _m = re.search(r'^\s*\$%s\s*=\s*@\{(.*?)\}' % re.escape(_var),
                   _pkg_ps1, re.M | re.S)
    _shapes[_var] = _m.group(1) if _m else ""
_staged = [v for v, t in _shapes.items() if "StageTo" in t]
_zipped = [v for v, t in _shapes.items()
           if "DistDir" in t and "StageTo" not in t]
if not _splats:
    bad("package.ps1 invokes bundle-client.ps1 through no splatted hashtable - "
        "an array splat binds positionally (trap eight), so this check cannot "
        "read what it was passed")
elif not _staged:
    bad("package.ps1 never calls bundle-client.ps1 -StageTo - the installer "
        "would carry no client payload")
elif not _zipped:
    bad("package.ps1 calls bundle-client.ps1 only to stage the installer's "
        "payload, so dist\<version>\ carries no client update packages - "
        "every client is told it is behind and offered nothing to apply")
else:
    ok("package.ps1 runs bundle-client.ps1 in both shapes - the staged payload "
       "and the %d update package(s)" % len(_pkgs or {}))

# ---- what a client install consists of, in the two lists that say so ----
head("the two client payload lists agree")
# $Payload plus that app's own Source and Launcher is what bundle-client.ps1
# puts in the zip and stages for PyInstaller; SOURCE_FILES[key] is what
# installer.py copies onto the machine. One set per app, written down twice in
# two languages, and neither list can read the other at runtime. Both drift
# directions are silent exactly where it costs most: a name in the bundle and
# not in SOURCE_FILES rides along in the zip and is never installed, so the app
# dies on the import under pythonw.exe with no console; a name in SOURCE_FILES
# and not in the bundle is quieter still, since _payload_mode requires every
# name in that list to sit beside the installer before it will call the payload
# a source one - so a name nothing staged makes the installer refuse its own
# payload without saying which file was missing. client_update.py needed both
# lists in 063 and nothing but reading the code said so.
#
# $Vehicle is deliberately not in this: installer.py and run_installer.pyw are
# how a zip installs itself, left out of a -StageTo run on purpose, and they
# have no counterpart in SOURCE_FILES.
_m = re.search(r'^\$Payload\s*=\s*[@]\(([^)]*)\)', _bundle, re.M)
_payload = re.findall(r'"([^"]+)"', _m.group(1)) if _m else []
_inst_files = {}
for _node in ast.parse(read("installer.py")).body:
    if (isinstance(_node, ast.Assign) and len(_node.targets) == 1
            and isinstance(_node.targets[0], ast.Name)
            and _node.targets[0].id == "SOURCE_FILES"):
        _inst_files = ast.literal_eval(_node.value)
if not _payload:
    bad("bundle-client.ps1 states no $Payload - nothing says what a client "
        "install carries")
elif not _inst_files:
    bad("installer.py has no SOURCE_FILES map - nothing says what an install "
        "copies onto the machine")
else:
    _wrong = []
    for _key in sorted(_bundle_names):
        _blk = re.search(r'^\s*%s\s*=\s*[@]\{(.*?)^\s*\}' % re.escape(_key),
                         _bundle, re.M | re.S)
        _own = re.findall(r'^\s*(?:Source|Launcher)\s*=\s*"([^"]+)"',
                          _blk.group(1), re.M) if _blk else []
        if len(_own) != 2:
            _wrong.append("bundle-client.ps1's $Apps.%s names no Source and "
                          "Launcher pair" % _key)
            continue
        # Extra is that app's own second module - the Notifier's Pending
        # decisions (#208) - staged beside its Source and installed with it,
        # while the Storekeeper's Extra is empty. It is read here rather than
        # assumed away because a name in SOURCE_FILES that nothing staged is
        # the quieter of the two drifts: _payload_mode refuses its own payload
        # without saying which file was missing.
        _ex = re.search(r'^\s*Extra\s*=\s*@\(([^)]*)\)', _blk.group(1), re.M)
        _own += re.findall(r'"([^"]+)"', _ex.group(1)) if _ex else []
        _staged = set(_payload) | set(_own)
        _copied = set(_inst_files.get(_key, []))
        if not _copied:
            _wrong.append("installer.py's SOURCE_FILES has no %r at all" % _key)
            continue
        _only_zip = sorted(_staged - _copied)
        _only_inst = sorted(_copied - _staged)
        _parts = []
        if _only_zip:
            _parts.append("the bundle stages %s, which installer.py never "
                          "copies onto the machine" % _only_zip)
        if _only_inst:
            _parts.append("installer.py copies %s, which the bundle never "
                          "stages" % _only_inst)
        if _parts:
            _wrong.append("%s: %s" % (_key, " and ".join(_parts)))
    if _wrong:
        bad("; ".join(_wrong))
    else:
        ok("%d client payload(s) agree between bundle-client.ps1's $Payload "
           "and installer.py's SOURCE_FILES" % len(_bundle_names))

# ---- the three appliers replace lib\\ wholesale ---------------------------
head(r"the three appliers replace lib\ wholesale")
# The vendored lib\\ is tied to one Python minor version (rule 13) and the three
# things that write one onto a machine each have to replace the whole directory
# rather than merge a new pin set into the old one: a renamed or split module,
# a dropped submodule or a bumped <pkg>-<version>.dist-info leaves files nothing
# removes, still on applaunch's sys.path entry and still shadowing the new copy.
# PYVER catches a lib\\ built for the wrong Python; nothing catches a half-merged
# one, and a downgrade - the moment somebody is backing out of a build that does
# not work - produces it without failing at all.
#
# That is one rule written down in three languages, in three files that cannot
# read each other, which is what this script is for. installer.py replaces it,
# client_update.py moves it aside and replaces it, and update.ps1 does the same
# - and both of the two that keep a rollback must ALSO keep lib\\ out of their
# per-file save and restore, or half of each tree goes back over the other.
_APPLIERS = [
    ("installer.py", "_deploy_component", [
        (r"shutil\.rmtree\(\s*lib_dst",
         "does not clear the installed lib\\ before writing the payload's"),
        (r"shutil\.copytree\([^)]*\"lib\"",
         "does not copy the payload's lib\\ in as one tree"),
    ]),
    ("client_update.py", "_save_for_rollback", [
        (r"shutil\.move\(\s*lib_src",
         "does not move lib\\ into the rollback directory as one thing"),
        (r"startswith\(\"lib/\"\)",
         "does not keep lib\\ out of the per-file rollback copy"),
    ]),
    ("client_update.py", "_restore", [
        (r"shutil\.copytree\(\s*lib_saved",
         "does not put lib\\ back as one tree"),
        (r"==\s*\"lib\"",
         "does not keep lib\\ out of the per-file restore"),
    ]),
    ("client_update.py", "_extract", [
        (r"shutil\.rmtree\(os\.path\.join\(dest,\s*\"lib\"\)",
         "does not empty lib\\ before writing the package's into it"),
    ]),
]
_wrong = []
for _f, _fn, _wanted in _APPLIERS:
    _seg = None
    for _node in ast.walk(ast.parse(read(_f))):
        if isinstance(_node, ast.FunctionDef) and _node.name == _fn:
            _seg = "\n".join(read(_f).splitlines()[_node.lineno - 1:_node.end_lineno])
    if _seg is None:
        _wrong.append("%s has no %s() - the applier this rule is about is gone "
                      "or renamed" % (_f, _fn))
        continue
    for _pat, _why in _wanted:
        if not re.search(_pat, _seg):
            _wrong.append("%s's %s() %s" % (_f, _fn, _why))
# update.ps1 is the third, and the one this check was written for: it wrote lib\
# file by file and never cleared it, so an update, a downgrade and a failed
# health check each left a tree that was neither release's.
_upd = read("tools/update.ps1")
for _pat, _why in (
        (r"Move-Item \$libDir \$libSave",
         "does not move lib\\ into the rollback directory as one thing"),
        (r"Copy-Item \$libSave \$libDir -Recurse",
         "does not put lib\\ back as one tree on a failed health check"),
        (r"\$_\.Name -notlike \"lib/\*\"",
         "does not keep lib/* out of $incoming, so the per-file restore fights "
         "the wholesale one")):
    if not re.search(_pat, _upd):
        _wrong.append("tools/update.ps1 %s" % _why)
if _wrong:
    bad("; ".join(_wrong))
else:
    ok("installer.py, client_update.py and tools/update.ps1 all replace lib\\ "
       "wholesale")

# ---- every repo file these two scripts name is one git tracks ------------
head("the release scripts name only committed files")
# package.ps1 refuses a dirty working tree because "the manifest's commit is the
# only record of what went into the payload". `git status --porcelain` does not
# report an ignored file, so that refusal cannot see one - and package.ps1
# staged config.json as an "extra" until #108, guarded by a bare Test-Path and
# left out of its own prerequisites check because an extra was allowed to be
# absent. It is a per-machine *client* file - server_url, current_user,
# client_id - that the server never reads, and it went into the zip hashed into
# manifest.json beside server.py, then into every install directory, update.ps1
# writing every name a manifest carries. Two machines building one version
# produced two different packages stamped with the same commit and nothing on
# either side said so.
#
# So the property is asserted from this end: what a release is assembled from is
# committed, and a name git does not track is drift whatever Test-Path finds
# beside it. Read as every top-level `$Name = @("...")` list in the two scripts
# rather than as the four lists by name, because the one that went wrong was a
# fifth nobody was looking at; a list element that does not look like a file at
# all - a component name, a version - is not a claim about the repo and is left
# alone.
_FILEISH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.[A-Za-z][A-Za-z0-9]*$")
_named = {}


def _name_it(rel, where):
    _named.setdefault(rel.replace("\\", "/"), set()).add(where)


for _script, _text in (("package.ps1", read("tools/package.ps1")),
                       ("bundle-client.ps1", _bundle)):
    for _m in re.finditer(r'^\$(\w+)\s*=\s*[@]\(([^()]*)\)', _text, re.M):
        for _n in re.findall(r'"([^"]+)"', _m.group(2)):
            if _FILEISH.match(_n):
                _name_it(_n, "%s $%s" % (_script, _m.group(1)))
# The per-app names sit inside $Apps rather than in a list of their own, and
# are half of what a client bundle stages: the Source/Launcher pair, and the
# Extra beside it - the Notifier's Pending decisions and Remote Admin, the
# Storekeeper's export. Extra is read here too because this set is what the
# manifest check below derives SHIPS from, and a module staged only as an
# Extra ships in exactly one zip and would otherwise reach neither list.
for _key in sorted(_bundle_names):
    _blk = re.search(r'^\s*%s\s*=\s*[@]\{(.*?)^\s*\}' % re.escape(_key),
                     _bundle, re.M | re.S)
    _own = re.findall(r'^\s*(?:Source|Launcher)\s*=\s*"([^"]+)"',
                      _blk.group(1), re.M) if _blk else []
    _ex = (re.search(r'^\s*Extra\s*=\s*@\(([^)]*)\)',
                     _blk.group(1), re.M) if _blk else None)
    _own += re.findall(r'"([^"]+)"', _ex.group(1)) if _ex else []
    for _n in _own:
        _name_it(_n, "bundle-client.ps1 $Apps.%s" % _key)
try:
    _tracked = set(git("ls-files").split("\n"))
except (subprocess.CalledProcessError, OSError):
    _tracked = None
    note("no git history available - skipping the committed-payload check")
if _tracked is None:
    pass
elif not _named:
    bad("neither release script names a repo file - the lists that say what a "
        "package is made of could not be read at all")
else:
    _loose = sorted(_n for _n in _named if _n not in _tracked)
    if _loose:
        bad("; ".join("%s is named by %s and git does not track it"
                      % (_n, " and ".join(sorted(_named[_n]))) for _n in _loose))
    else:
        ok("all %d file(s) the release scripts name are tracked" % len(_named))

# ---- dev-run.ps1 stages what the apps actually import ---------------------
head("dev-run.ps1 stages what the apps actually import")
# The third copy of "what a client consists of", after $Payload in
# bundle-client.ps1 and SOURCE_FILES in installer.py - and the one nothing held.
# Each app gets a staged directory of its own, which is its own import root, so
# sys.path[0] is that directory and no other file of this repo is on the path. A
# module missing from the list is not a degraded run: the app dies on its own
# import block, and because the console is hidden, Start-App still prints a pid,
# the pid still goes into dev-pids.json and the script still ends on "Running".
# client_update.py was the one that proved it - both clients have imported it at
# module level since it landed, and neither started here again until 081.
#
# Derived rather than compared against a fourth list written down here: what
# each app needs is what it imports, so that is what this reads. Transitive,
# through _repo_closure - the same helper the package.ps1 check below uses -
# because a module reached only through another staged module - one the app
# itself never names - is invisible to one hop, and that is exactly the miss
# #234 found: this check was green with a module missing from the server line
# because it only read server.py's own imports.
_dev = read("tools/dev-run.ps1")
_m = re.search(r'\$ClientShared\s*=\s*@\(([^)]*)\)', _dev)
_client_shared = re.findall(r'"([^"]+)"', _m.group(1)) if _m else []
_staged = {}
for _line in _dev.replace("\r\n", "\n").split("\n"):
    if "New-AppDir" not in _line or _line.lstrip().startswith("#"):
        continue
    _names = re.findall(r'"([^"]+\.py)"', _line)
    if not _names:
        continue
    _all = set(_names)
    if "$ClientShared" in _line:
        _all |= set(_client_shared)
    _staged[_names[0]] = _all


def _module_imports(tree):
    # Module level only, descending into if/try - a lazy import inside a
    # function is resolved when it is called and is not what kills an app at
    # startup. Both client apps import at the top; server.py guards tkinter.
    found, stack = set(), list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Import):
            found |= set(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
        elif isinstance(node, (ast.If, ast.Try)):
            stack.extend(node.body)
            stack.extend(node.orelse)
            stack.extend(getattr(node, "finalbody", []))
            for handler in getattr(node, "handlers", []):
                stack.extend(handler.body)
    return found


def _repo_closure(roots):
    # Follows _module_imports transitively rather than stopping one hop out,
    # so a module reached only through another staged module, never named by
    # the app itself, does not read as absent. Shared with the package.ps1
    # check below, which needs the same thing for the same reason.
    seen, stack = set(), list(roots)
    while stack:
        f = stack.pop()
        if f in seen or not os.path.exists(os.path.join(R, f)):
            continue
        seen.add(f)
        for mod in _module_imports(ast.parse(read(f))):
            cand = mod + ".py"
            if os.path.exists(os.path.join(R, cand)) and cand not in seen:
                stack.append(cand)
    return seen


if not _staged:
    bad("dev-run.ps1 stages nothing through New-AppDir - the harness this check "
        "is about works some other way now")
else:
    _wrong = []
    for _app in sorted(_staged):
        if not os.path.exists(os.path.join(R, _app)):
            _wrong.append("dev-run.ps1 stages %s, which is not in this repo" % _app)
            continue
        _needs = _repo_closure({_app}) - {_app}
        _missing = sorted(_needs - _staged[_app])
        if _missing:
            _wrong.append("dev-run.ps1 does not stage %s beside %s, which imports "
                          "it at module level - that app dies on the import and "
                          "the run says nothing" % (_missing, _app))
    if _wrong:
        bad("; ".join(_wrong))
    else:
        ok("dev-run.ps1 stages every repo module the %d staged app(s) import"
           % len(_staged))

# ---- package.ps1 ships what the server actually imports ------------------
head("package.ps1 ships what the server actually imports")
# $SourceFiles is what the server zip contains, and until 059 nothing asked
# whether it held everything the server imports - only, two groups above, that
# every name already in it is a file git tracks. A module missing from it is
# not packaged at all, and the server dies on its own import line on the
# machine it was installed to, under a service host with no console, saying
# nothing a reader can act on.
#
# It is the copy with the most riding on it: 056 made SHIPS derive from this
# list, so a module that never reaches it is invisible to the manifest drift
# check as well - one omission costs the package and the check that would have
# reported the package stale.
#
# dev-run.ps1's own server list is the near miss that makes this reachable
# rather than theoretical. Adding a module there is what makes the dev harness
# run, so it is the list a developer edits first and the one the group above
# rewards; $SourceFiles is edited at packaging time, by whoever is doing the
# release, which is not the same sitting.
#
# Transitive, which is where this differs from the group above it copies. A
# module no app names, reached only because another staged module imports it,
# is one a zip can be built without - and the install then dies on that
# module's own import line, silently, under pythonw.exe (#222, #234).
#
# Both roots, because they are two different entry points into the same
# install: run_server.py is what Windows starts and applaunch.py is reached
# only through it, while server.py is what everything else hangs off.
_SERVER_ROOTS = ("server.py", "run_server.py")
_m = re.search(r'^\$SourceFiles\s*=\s*[@]\(([^)]*)\)', _pkg_ps1, re.M)
_source_files = set(re.findall(r'"([^"]+)"', _m.group(1))) if _m else set()


if not _source_files:
    bad("package.ps1 states no $SourceFiles - nothing says what the server "
        "package contains")
else:
    _needed = _repo_closure(_SERVER_ROOTS)
    _unshipped = sorted(_needed - _source_files)
    # A name in the list that nothing imports is reported rather than failed:
    # it is either dead weight in the zip or a lazy import no AST walk can see,
    # and only one of those is a defect. A gate that cannot tell them apart
    # should say so and let a reader decide, not go red on the guess.
    _unimported = sorted(_source_files - _needed)
    if _unshipped:
        bad("package.ps1's $SourceFiles does not name %s, which the server "
            "imports at module level - the zip does not carry it, and the "
            "install dies on that import with no console to say so"
            % _unshipped)
    else:
        ok("$SourceFiles names every one of the %d repo module(s) the server "
           "imports" % len(_needed))
    if _unimported:
        note("$SourceFiles names %s, which nothing the server imports reaches "
             "- dead weight in the zip, or a lazy import this cannot see"
             % _unimported)

# ---- install-iis.ps1's web.config is well-formed XML ---------------------
head("install-iis.ps1's web.config is well-formed XML")
# The only file in this repo that is generated by string interpolation and then
# parsed by something other than us, and IIS refuses the whole site over a
# character rather than ignoring the attribute. Two of the three values
# interpolated into it carry characters XML gives its own meaning to:
# $processArgs on a source install is `"<path>" serve`, the launcher path quoted
# because it can contain spaces, and a literal quote inside a quoted attribute
# closes it - the emitted line was not XML at all, so every source-mode install
# got 500.19 with an empty httpplatform-stdout, that being a log the handler
# never started a process to write. An & in InstallDir does the same more
# quietly. Source mode is the only mode (rule 14) and IIS is the supported host
# (ADR-0001), so that was the whole supported deploy path; exe mode passes the
# bare word `serve` and was never affected, which is why nothing saw it.
#
# So two claims, and the second is what makes the first stay true: every
# interpolation in that template names a value the script escaped first, and the
# template with hostile values in it still parses.
_iis = read("tools/install-iis.ps1")
_safe = set(re.findall(r'^\s*\$(\w+)\s*=\s*Escape-XmlAttr\b', _iis, re.M))
_tpl = re.search(r'\$webConfig\s*=\s*@"\r?\n(.*?)\r?\n"@', _iis, re.S)
if not _safe:
    bad("install-iis.ps1 escapes nothing for web.config - Escape-XmlAttr is gone "
        "or nothing is assigned from it")
elif not _tpl:
    bad("install-iis.ps1 has no $webConfig here-string - the file this check is "
        "about is written some other way now")
else:
    _t = _tpl.group(1)
    _used = set(re.findall(r'\$(\w+)', _t))
    _raw = sorted(_used - _safe)
    if _raw:
        bad("install-iis.ps1's web.config interpolates %s straight into an "
            "attribute - run each through Escape-XmlAttr, or a quote or an "
            "ampersand in it makes IIS refuse the file with 500.19" % _raw)
    else:
        # A quote, an ampersand and an angle bracket in every slot, escaped the
        # one way the script escapes them. Parsing this is what says the escape
        # is enough and that the template around it is still well-formed.
        _hostile = '"R&D <x>" serve'
        for _c, _ent in (("&", "&amp;"), ("<", "&lt;"),
                         (">", "&gt;"), ('"', "&quot;")):
            _hostile = _hostile.replace(_c, _ent)
        _filled = re.sub(r'\$(\w+)', lambda _m: _hostile, _t)
        try:
            xml.dom.minidom.parseString(_filled)
            ok("install-iis.ps1's web.config escapes all %d interpolated value(s) "
               "and parses" % len(_used))
        except Exception as _exc:
            bad("install-iis.ps1's web.config does not parse as XML once its "
                "values are filled in: %s" % _exc)

# ---- package manifests vs the payload they contain -----------------------
head("package manifests vs the payload they contain")
# A manifest behind HEAD is drift only if a file that actually ships changed in
# between. A docs-only commit does not invalidate a package; treating it as
# drift would mean rebuilding every package on every documentation edit, which
# trains the rule to be ignored.
# What ships is derived from _named above - every top-level `$Name = @(...)`
# list in package.ps1 and bundle-client.ps1 plus each app's Source, Launcher
# and Extra - rather than written down here a second time. It was a hand-kept
# list until 056, and by then it had drifted in six places: the three
# registers 041-043 added, server_cert.py, client_update.py, and both of
# package.ps1's $ToolFiles. Each of 050-055 edited this line to add its own
# module and none of them noticed the rest, which is the argument for reading
# the lists rather than keeping a copy of them: a module that ships and is
# not named here leaves a stale package reported as current, silently, which
# is the one failure this whole group exists for.
#
# migrations/ and requirements- stay by hand because neither is in a list to
# read - package.ps1 puts them into a zip by walking them, not by naming
# them - and they are prefixes rather than names, which is why they are a
# second alternative here and not members of the first.
#
# An empty derivation is reported rather than quietly compiled. A SHIPS that
# matches nothing does not fail: it calls every manifest docs-only and passes
# the group green, which is worse than the drift it was watching for.
_SHIPPED = sorted(_named)
if not _SHIPPED:
    bad("the release scripts name no payload file - what ships could not be "
        "derived, so no manifest below is judged")
SHIPS = re.compile("^(?:%s)$|^(?:migrations/|requirements-)"
                   % "|".join(re.escape(_n) for _n in _SHIPPED))
# dist\ rather than a flat directory: everything releasable is written to
# dist\<version>\, so the zips sit one level down and a walk is what finds
# them whatever the version is called. The name reported is relative to dist\,
# which is what makes two versions of one package tell themselves apart.
pk = os.path.join(R, "dist")
try:
    head_sha = git("rev-parse", "HEAD")
    print("        HEAD = %s" % head_sha[:12])
except (subprocess.CalledProcessError, OSError):
    head_sha = None
    note("no git history available - skipping the manifest check")
if head_sha and not os.path.isdir(pk):
    note("no dist\\ directory - nothing built on this machine yet")
elif head_sha:
    found = []
    for base, _d, files in os.walk(pk):
        for f in files:
            if f.endswith(".zip"):
                full = os.path.join(base, f)
                found.append((os.path.relpath(full, pk), full))
    zips = sorted(found)
    if not zips:
        note("dist\\ holds no packages - nothing built on this machine yet")
    # Only the current version's packages are judged, and that is the whole of
    # what this row can honestly hold. A package for a version already released
    # is stamped with the commit that released it, and the payload has moved
    # since by definition - that is what shipping the next version means, not
    # drift. Walking every directory under dist\ therefore failed this group on
    # every run for ever, and it can never be made green: no rebuild fixes a
    # 2.3.0 zip. A gate that is red before the change is a gate nobody reads,
    # which costs more than the row was ever worth.
    #
    # The version is read off server.py's APP_VERSION rather than off the
    # directory name, so a directory named after something else is still
    # reported rather than quietly excusing itself. With no APP_VERSION to
    # compare against, every zip is judged the way it was before: an unreadable
    # version must not turn this group into one that measures nothing.
    cur = vers.get("server.py")
    if cur:
        judged = [(z, p) for z, p in zips
                  if z.replace("/", "\\").split("\\")[0] == cur]
        if len(zips) > len(judged):
            note("%d package(s) under dist\\ are for a version other than %s "
                 "- released packages are not judged against this HEAD"
                 % (len(zips) - len(judged), cur))
        if zips and not judged:
            note("nothing built for %s yet" % cur)
    else:
        judged = zips
        note("APP_VERSION is unreadable - judging every package under dist\\")
    for z, zpath in judged:
        # utf-8-sig rather than utf-8: a manifest written by Set-Content
        # -Encoding UTF8 under Windows PowerShell 5.1 carries a BOM - trap six
        # in CLAUDE.md - and this walk reads every zip in dist\, server and
        # client alike, so packages built before package.ps1 and
        # bundle-client.ps1 moved to a no-BOM WriteAllText are still sitting
        # on build machines with the BOM in them. ValueError
        # covers what is left of that class, a JSONDecodeError for a manifest
        # that is not JSON and a UnicodeDecodeError for one that is not text:
        # a manifest this cannot parse is drift about that package, reported
        # naming it, and never a reason for the gate to stop before the checks
        # below it. A gate that dies is a gate nobody can run, and its
        # non-zero exit then says the script crashed rather than what drifted.
        try:
            with zipfile.ZipFile(zpath) as zf:
                man = json.loads(zf.read("manifest.json").decode("utf-8-sig"))
        except (KeyError, zipfile.BadZipFile, ValueError) as exc:
            bad("%s has no readable manifest.json (%s)" % (z, exc))
            continue
        sha = man.get("git_commit") or ""
        if man.get("git_dirty"):
            bad("%s was built from a dirty tree - its provenance is unusable" % z)
        elif sha == head_sha:
            ok("%s matches HEAD" % z)
        else:
            try:
                changed = git("diff", "--name-only", sha, head_sha).split("\n")
            except subprocess.CalledProcessError:
                bad("%s is stamped %s, which is not a commit here" % (z, sha[:12]))
                continue
            moved = [c for c in changed if c and SHIPS.match(c)]
            if moved:
                bad("%s is stamped %s and the payload moved since: %s"
                    % (z, sha[:12], ", ".join(moved[:6])))
            else:
                behind = len(git("rev-list", "%s..%s" % (sha, head_sha)).split())
                ok("%s is stamped %s, %d commit(s) back, all docs-only "
                   "- payload current" % (z, sha[:12], behind))

# ---- what the apps name beside themselves is gitignored -------------------
head("files the apps name beside themselves are gitignored")
# Every file one of these modules writes next to itself is named once, as a
# module-level NAME = os.path.join(<DIR>, "<literal>"), so the set is derivable
# rather than a list somebody has to keep in step by hand - which is the point,
# because the list in docs/reference/files-on-disk.md is prose and the one that
# actually matters is this one. An app run from a source checkout writes those
# names into the repo root, and an untracked file is what package.ps1 refuses
# to build over: seen_proposals.json (#71), update_rollback (#104) and iis.json
# (#105) were each found by somebody trying to package a release.
#
# The answer is read out of .gitignore rather than asked of `git check-ignore`,
# which cannot be asked this question. A bare `lib` comes back unignored,
# because `lib/` is a directory pattern and nothing on disk says that name is a
# directory; `update_rollback/` came back *ignored*, against a blank line. So a
# pattern's trailing slash is dropped here and a name matches whichever kind it
# is - the AST says what the app calls the thing, never whether it is a file or
# a directory.
#
# A name git already tracks is not an artefact at all (migrations\ is one), so
# it is reported as that rather than demanded to be ignored.
BESIDE_MODULES = ("server.py", "storekeeper_app.py", "notifier_app.py",
                  "common.py", "client_update.py", "applaunch.py",
                  "installer.py", "ui_kit.py")
beside = {}
for f in BESIDE_MODULES:
    for node in ast.parse(read(f)).body:            # module level only
        if not isinstance(node, ast.Assign):
            continue
        v = node.value
        if not (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                and v.func.attr == "join" and len(v.args) == 2):
            continue
        base, leaf = v.args
        if not (isinstance(base, ast.Name) and isinstance(leaf, ast.Constant)
                and isinstance(leaf.value, str)):
            continue
        names = ", ".join(t.id for t in node.targets if isinstance(t, ast.Name))
        beside.setdefault(leaf.value, []).append(
            "%s:%d (%s)" % (f, node.lineno, names or "?"))

ignore_pats, negations = [], []
for line in read(".gitignore").replace("\r\n", "\n").split("\n"):
    p = line.strip()
    if not p or p.startswith("#"):
        continue
    if p.startswith("!"):
        negations.append(p)
        continue
    body = p.strip("/")
    if "/" not in body:          # a pattern naming a path cannot match a leaf
        ignore_pats.append(body)
if negations:
    note(".gitignore carries %d negation(s) this check does not read: %s"
         % (len(negations), ", ".join(negations)))
tracked = set(git("ls-files").split("\n"))
print("        %d name(s) written beside an app, %d .gitignore pattern(s)"
      % (len(beside), len(ignore_pats)))
for leaf in sorted(beside):
    where = "; ".join(beside[leaf])
    hits = [p for p in ignore_pats if fnmatch.fnmatchcase(leaf, p)]
    if hits:
        ok("%s is gitignored by %s - %s" % (leaf, ", ".join(hits), where))
    elif any(t == leaf or t.startswith(leaf + "/") for t in tracked):
        ok("%s is tracked, so it is not an artefact - %s" % (leaf, where))
    else:
        bad("%s is named beside an app and is neither gitignored nor tracked,"
            " so running that app from source leaves it untracked in the repo"
            " root and package.ps1 refuses to build - %s" % (leaf, where))

# ---- ui_kit.fit's call count vs the sentence that states it --------------
head("ui_kit.fit's call count vs what the ui_kit.py row says")
# The cascade rule's last line says a documented measurement is re-derived from
# the source rather than copied forward, and this is the number that had never
# had it done: the row said fit was called from twenty-three windows, twelve of
# them in the Server GUI, while the Server GUI alone had twenty-three call
# sites and the Storekeeper had eight. Six windows were added over a year and
# none of them touched the sentence, because nothing reads that sentence except
# somebody deciding whether the window they are adding is an ordinary one.
#
# Call sites rather than windows, which is what drifted: two stages of one
# import window each call fit, so "how many windows" is a judgement and "how
# many calls" is a measurement. Written in words because that is this
# document's house style for a count, and parsed back the same way.
_WORD_ONES = ("zero one two three four five six seven eight nine ten eleven "
              "twelve thirteen fourteen fifteen sixteen seventeen eighteen "
              "nineteen").split()
_WORD_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
              "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def _from_words(w):
    """"thirty-six" -> 36. None for anything this does not recognise."""
    w = w.strip().lower()
    if w == "none":
        return 0
    if w in _WORD_ONES:
        return _WORD_ONES.index(w)
    head_, _, tail = w.partition("-")
    if head_ in _WORD_TENS:
        if not tail:
            return _WORD_TENS[head_]
        if tail in _WORD_ONES[1:10]:
            return _WORD_TENS[head_] + _WORD_ONES.index(tail)
    return None


# Files per app rather than a file per app: #218 moved the Notifier's
# Remote Admin windows into notifier_remote.py and six of that app's
# eleven fit callers went with them, and #219 took the Storekeeper's
# Export window into storekeeper_export.py with one more. The sentence
# below counts by app, which is the honest unit - a window is the
# Notifier's wherever the class that draws it is written down - so the
# count is summed over the files the app is made of rather than split
# into a row nobody reading that sentence would know to add up.
_FIT_APPS = [("Server GUI", ("server_gui.py", "gui_assets.py",
                             "gui_backup.py", "gui_clients.py", "gui_log.py",
                             "gui_mail.py", "gui_proposals.py",
                             "gui_records.py", "gui_settings.py",
                             "gui_users.py")),
             ("Storekeeper", ("storekeeper_app.py", "storekeeper_export.py",
                              "storekeeper_bulk.py",
                              "storekeeper_propose.py")),
             ("Notifier", ("notifier_app.py", "notifier_remote.py")),
             ("installer", ("installer.py",))]
_counted = {}
for _label, _files in _FIT_APPS:
    _counted[_label] = sum(
        1 for _f in _files for _n in ast.walk(ast.parse(read(_f)))
        if isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
        and _n.func.attr == "fit" and isinstance(_n.func.value, ast.Name)
        and _n.func.value.id == "ui_kit")

_stated = re.search(
    r"`fit` is called from ([a-z\-]+) places[^a-z]{1,4}([a-z\-]+) in the Server "
    r"GUI, ([a-z\-]+) in the Storekeeper, ([a-z\-]+) in the Notifier and "
    r"([a-z\-]+) in the installer", CM)
if not _stated:
    bad("the ui_kit.py row no longer states where ui_kit.fit is called from - "
        "that sentence is the one place the count is written down, so a "
        "rewording that drops it leaves nothing for this check to hold")
else:
    _total, _said = _stated.group(1), {}
    for _i, (_label, _files) in enumerate(_FIT_APPS):
        _said[_label] = _from_words(_stated.group(_i + 2))
    _bad = [l for l in _said if _said[l] is None]
    if _bad or _from_words(_total) is None:
        bad("the ui_kit.py row states a count this cannot read back: %s"
            % _stated.group(0)[:120])
    else:
        _drifted = False
        for _label, _files in _FIT_APPS:
            if _said[_label] != _counted[_label]:
                _drifted = True
                bad("ui_kit.fit is called %d time(s) in %s, and the ui_kit.py "
                    "row says %d" % (_counted[_label], " + ".join(_files),
                                     _said[_label]))
        if _from_words(_total) != sum(_counted.values()):
            _drifted = True
            bad("the ui_kit.py row says fit is called from %s places, and it "
                "is called from %d" % (_total, sum(_counted.values())))
        if not _drifted:
            ok("fit: %s, and the ui_kit.py row says so"
               % ", ".join("%d in %s" % (_counted[_l], " + ".join(_fs))
                           for _l, _fs in _FIT_APPS))

# ---- the palette is written down once ------------------------------------
head("the apps take their colours from ui_kit rather than restating them")
# ui_kit.DARK is the table, and ui_kit.Theme binds those names into each app's
# module globals. All three apps used to write the fourteen out again as
# literals underneath their Theme() call, agreeing with that table by hand -
# and their own _EXTRA_DARK values a second time, seven lines under the dict
# they were defined in. They agreed, which is the only reason nothing showed:
# retint repaints a widget by reading its colour back off it and looking it up
# in reverse(old), where old is ui_kit's table, so a widget painted from a
# drifted literal has no entry, is skipped, and stays dark inside a light
# window. Nothing raises and the rest of the window repaints around it.
_UIKIT = ast.parse(read('ui_kit.py'))
_KIT_NAMES = set()
for _n in ast.walk(_UIKIT):
    if (isinstance(_n, ast.Assign) and len(_n.targets) == 1
            and isinstance(_n.targets[0], ast.Name)
            and _n.targets[0].id in ("TOKENS", "DARK")):
        if isinstance(_n.value, ast.Tuple):
            _KIT_NAMES |= set(e.value for e in _n.value.elts)
        elif isinstance(_n.value, ast.Dict):
            _KIT_NAMES |= set(k.value for k in _n.value.keys)

_seeds = []
for _n in ast.walk(_UIKIT):
    if isinstance(_n, ast.ClassDef) and _n.name == "Theme":
        for _m in _n.body:
            if (isinstance(_m, ast.FunctionDef)
                    and _m.name == "__init__"):
                _seeds = [_c for _c in ast.walk(_m)
                          if isinstance(_c, ast.Call)
                          and isinstance(_c.func, ast.Attribute)
                          and _c.func.attr == "_bind"]
if _seeds:
    ok("ui_kit.Theme.__init__ binds the table into the app it was handed")
else:
    bad("ui_kit.Theme.__init__ does not call _bind - nothing seeds the colour "
        "names, and an app that stopped writing its own would have none until "
        "the first theme switch, which is a NameError on the first window")

# Each file paired with the one whose ui_kit.Theme binds the names it draws
# with. The nine window modules #235 split out of server_gui.py call no Theme
# of their own - they seed their globals off that one's palette through
# _bind_palette - so the four extras they must not restate are server_gui.py's,
# and are read from the file that declares them.
_THEMED = [("server_gui.py", "server_gui.py"),
           ("storekeeper_app.py", "storekeeper_app.py"),
           ("notifier_app.py", "notifier_app.py"),
           ("gui_assets.py", "server_gui.py"),
           ("gui_backup.py", "server_gui.py"),
           ("gui_clients.py", "server_gui.py"),
           ("gui_log.py", "server_gui.py"),
           ("gui_mail.py", "server_gui.py"),
           ("gui_proposals.py", "server_gui.py"),
           ("gui_records.py", "server_gui.py"),
           ("gui_settings.py", "server_gui.py"),
           ("gui_users.py", "server_gui.py")]
for _app, _extras in _THEMED:
    _tree = ast.parse(read(_app))
    _own = set()
    for _n in ast.parse(read(_extras)).body:
        if (isinstance(_n, ast.Assign) and len(_n.targets) == 1
                and isinstance(_n.targets[0], ast.Name)
                and _n.targets[0].id in ("_EXTRA_DARK", "_EXTRA_LIGHT")
                and isinstance(_n.value, ast.Dict)):
            _own |= set(k.value for k in _n.value.keys)
    _restated = sorted(
        _n.targets[0].id for _n in _tree.body
        if isinstance(_n, ast.Assign) and len(_n.targets) == 1
        and isinstance(_n.targets[0], ast.Name)
        and _n.targets[0].id in (_KIT_NAMES | _own))
    if _restated:
        bad("%s writes %s at module level - the palette ui_kit.Theme binds, restated: %s" % (_app, "a colour" if len(_restated) == 1 else "colours",
                 ", ".join(_restated)))
    else:
        ok("%s restates none of the %d names the Theme it draws in binds"
           % (_app, len(_KIT_NAMES | _own)))

# ---- the faces are written down once -------------------------------------
head("the apps take their typefaces from ui_kit rather than naming them")
# The palette's argument one file over. A face was stated at every one of the
# ~620 construction sites in these four apps, with no name anywhere saying
# what the text *was*, so changing the product's typeface meant editing 620
# call sites and being right 620 times. ui_kit.FAMILIES is the table now and
# ui_kit.ROLES says what each level is, bound in as `font` by Theme beside
# the colours. What a family literal left behind costs is not a NameError
# the way a drifted colour is invisible - it is a widget that silently stays
# on the old face while everything around it moves, which is the same defect
# with a different surface.
_FAMILIES = set()
for _n in ast.walk(_UIKIT):
    if (isinstance(_n, ast.Assign) and len(_n.targets) == 1
            and isinstance(_n.targets[0], ast.Name)
            and _n.targets[0].id == "FAMILIES"
            and isinstance(_n.value, ast.Dict)):
        _FAMILIES = set(v.value for v in _n.value.values)

if not _FAMILIES:
    bad("ui_kit.FAMILIES names no typeface - the table the four apps were "
        "emptied in favour of is not there")
else:
    ok("ui_kit.FAMILIES holds the %d faces this product draws in"
       % len(_FAMILIES))

_font_seed = []
for _n in ast.walk(_UIKIT):
    if isinstance(_n, ast.ClassDef) and _n.name == "Theme":
        for _m in ast.walk(_n):
            if (isinstance(_m, ast.Subscript)
                    and isinstance(_m.value, ast.Attribute)
                    and _m.value.attr == "g"
                    and isinstance(_m.slice, ast.Constant)
                    and _m.slice.value == "font"):
                _font_seed.append(_m)
if _font_seed:
    ok("ui_kit.Theme.__init__ seeds font into the app it was handed")
else:
    bad("ui_kit.Theme does not bind font - every role call in the four apps "
        "is a NameError on the first window drawn")

# An openpyxl Font() is a cell's typeface in an exported workbook rather than
# a widget's, and the Excel file is not this product's window: it is read in
# Excel, in whatever the reader has installed, so it is left naming its own.
for _app in ("server.py", "storekeeper_app.py", "notifier_app.py",
             "installer.py"):
    _tree = ast.parse(read(_app))
    _sheet = set()
    for _n in ast.walk(_tree):
        if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Name)
                and _n.func.id == "Font"):
            for _c in ast.walk(_n):
                if isinstance(_c, ast.Constant):
                    _sheet.add(id(_c))
    _named = sorted(set(
        "%s:%d" % (_app, _c.lineno) for _c in ast.walk(_tree)
        if isinstance(_c, ast.Constant) and _c.value in _FAMILIES
        and id(_c) not in _sheet))
    if _named:
        bad("%s names a typeface itself rather than asking font() for a "
            "role: %s" % (_app, ", ".join(_named)))
    else:
        ok("%s names no typeface of its own" % _app)

# ---- every path the docs name actually exists ----------------------------
head("files referenced by the docs exist")
docs = {"CLAUDE.md": read("CLAUDE.md"), "CONTEXT.md": read("CONTEXT.md")}
for base, _dirs, files in os.walk(os.path.join(R, "docs")):
    for f in files:
        if f.endswith(".md"):
            rel = os.path.relpath(os.path.join(base, f), R).replace("\\", "/")
            docs[rel] = read(rel)
refs = set()
for name, text in docs.items():
    for m in re.finditer(r"`((?:docs|tools|migrations)/[A-Za-z0-9_./-]+?"
                         r"\.(?:md|ps1|py|json))`", text):
        refs.add((name, m.group(1)))
    for m in re.finditer(r"\]\(((?:\.\./)?[A-Za-z0-9_./-]+?\.md)\)", text):
        here = os.path.dirname(os.path.join(R, name))
        target = os.path.normpath(os.path.join(here, m.group(1)))
        refs.add((name, os.path.relpath(target, R).replace("\\", "/")))
# Absent on purpose, and not drift: a naming *pattern* (migrations/NNN_slug.py),
# and a per-machine file the docs tell you to create, which is gitignored
# (tools/deploy.json - deploy.example.json is what ships).
BY_DESIGN = ("NNN", "<", "deploy.json")
missing, expected = [], []
for a, b in sorted({(a, b) for a, b in refs
                    if not os.path.exists(os.path.join(R, b))}):
    (expected if any(t in b for t in BY_DESIGN) else missing).append((a, b))
print("        %d reference(s) across %d document(s)" % (len(refs), len(docs)))
if missing:
    for a, b in missing:
        bad("%s points at %s, which does not exist" % (a, b))
else:
    ok("all %d referenced paths resolve" % (len(refs) - len(expected)))
for a, b in expected:
    ok("%s -> %s absent by design (a pattern, or per-machine and gitignored)"
       % (a, b))

# ---- every event name this build writes is documented --------------------
# L2. The Notification Rules window offers only the names this server's log has
# already *seen* (031, `_log_event_names`), on the grounds that a catalogue kept
# beside the call sites would be the event list written down twice and would be
# the copy that goes stale. That still holds - but it means anything worth
# subscribing to is missing from the box on the day somebody comes to subscribe
# to it, so the names are written down for a **person** instead, in
# docs/system-log-events.md. This is what stops that document becoming the stale
# copy 031 refused to keep: it is derived from the calls rather than compared
# against a fourth list, so a new event that nobody documented is drift.
#
# The other direction is asserted too, and is the half that rots quietly: a name
# in the document that nothing emits any more is a rule an Admin can write that
# will never mail, which reads as a mail layer that is broken.
head("every System Log event name is in docs/system-log-events.md")
_EVENT_SOURCES = ("server.py", "server_gui.py", "gui_log.py",
                  "gui_proposals.py", "gui_records.py", "gui_settings.py",
                  "server_cert.py",
                  "register_assets.py", "register_transactions.py",
                  "register_engineers.py", "server_mail.py",
                  "server_sync.py", "server_clients.py",
                  "server_log.py", "server_archive.py",
                  "server_lookup.py",
                  "common.py", "storekeeper_app.py", "storekeeper_bulk.py",
                  "storekeeper_propose.py",
                  "notifier_app.py", "notifier_remote.py")
_emitted = {}
for _app in _EVENT_SOURCES:
    for _n in ast.walk(ast.parse(read(_app))):
        if not isinstance(_n, ast.Call):
            continue
        _fn = getattr(_n.func, "id", None) or getattr(_n.func, "attr", None)
        if _fn not in ("_log_event", "log_event") or not _n.args:
            continue
        _a = _n.args[0]
        if isinstance(_a, ast.Constant) and isinstance(_a.value, str):
            _emitted.setdefault(_a.value, set()).add(_app)
            continue
        # `_log_event(x if new else y, ...)` and the shipped-entry call, whose
        # name is the client's. The first names two events and both are real;
        # the second names none, every name it can carry being one of these.
        if isinstance(_a, ast.IfExp):
            for _side in (_a.body, _a.orelse):
                if isinstance(_side, ast.Constant):
                    _emitted.setdefault(_side.value, set()).add(_app)
# What common.py states rather than calls: the applier cannot log, so the three
# outcomes it can leave behind are a table read at the next start (#148).
for _n in ast.walk(ast.parse(read("common.py"))):
    if (isinstance(_n, ast.Assign) and len(_n.targets) == 1
            and getattr(_n.targets[0], "id", "") == "UPDATE_RESULT_EVENTS"
            and isinstance(_n.value, ast.Dict)):
        for _v in _n.value.values:
            if isinstance(_v, ast.Tuple) and isinstance(_v.elts[0], ast.Constant):
                _emitted.setdefault(_v.elts[0].value, set()).add("common.py")
_doc = read("docs/system-log-events.md")
_documented = set(re.findall(r"`([a-z_]+\.[a-z_]+)`", _doc))
print("        %d event name(s) across %d source(s)"
      % (len(_emitted), len(_EVENT_SOURCES)))
_undoc = sorted(e for e in _emitted if e not in _documented)
if _undoc:
    for _e in _undoc:
        bad("%s is written by %s and is in no row of "
            "docs/system-log-events.md" % (_e, ", ".join(sorted(_emitted[_e]))))
else:
    ok("all %d event names this build writes are documented" % len(_emitted))
# A documented name nothing emits. Scoped to the event-shaped tokens the
# document uses as *row headings* rather than every backticked word in it, since
# the prose names files and settings in the same punctuation.
_rows = set(re.findall(r"^\| `([a-z_]+\.[a-z_]+)`", _doc, re.M))
# A row heading naming two names at once, which is how the pairs that only ever
# happen together are written (`backup.started` / `backup.finished`).
for _m in re.finditer(r"^\| `([a-z_]+\.[a-z_]+)` / `([a-z_]+\.[a-z_]+)`",
                      _doc, re.M):
    _rows.add(_m.group(1))
    _rows.add(_m.group(2))
_gone = sorted(r for r in _rows if r not in _emitted)
if _gone:
    for _r in _gone:
        bad("docs/system-log-events.md has a row for %s, which nothing "
            "writes any more" % _r)
else:
    ok("all %d documented row(s) name an event something still writes"
       % len(_rows))

# ---- and every one of them reads as a sentence ----------------------------
#
# `EVENT_SENTENCES` in server_log.py is what the System Log window puts beside
# a row (#196), and it is the second copy of what that document holds - on
# purpose, because nothing under docs\ ships in any package, so a table parsed
# out of the document at read time would be empty on every real install. What
# keeps a second copy honest is this check, in both directions: an event the
# code can write with no sentence beside it is a window falling back to the raw
# name, and a sentence for a row nobody documents any more is a phrase for an
# event that has gone.
head("EVENT_SENTENCES (server_log.py) vs docs/system-log-events.md")
_sentences = {}
for _n in ast.walk(ast.parse(read("server_log.py"))):
    if (isinstance(_n, ast.Assign) and len(_n.targets) == 1
            and getattr(_n.targets[0], "id", "") == "EVENT_SENTENCES"
            and isinstance(_n.value, ast.Dict)):
        _sentences = ast.literal_eval(_n.value)
print("        %d phrase(s) against %d documented row(s)"
      % (len(_sentences), len(_rows)))
if not _sentences:
    bad("server_log.py states no EVENT_SENTENCES at all, so nothing was compared")
else:
    _nophrase = sorted(r for r in _rows if r not in _sentences)
    if _nophrase:
        for _r in _nophrase:
            bad("%s is documented and has no phrase in EVENT_SENTENCES, so the "
                "System Log shows the raw name for it" % _r)
    else:
        ok("every documented event has a phrase")
    _stale = sorted(e for e in _sentences if e not in _rows)
    if _stale:
        for _e in _stale:
            bad("EVENT_SENTENCES has a phrase for %s, which no row of "
                "docs/system-log-events.md names" % _e)
    else:
        ok("every phrase names an event the document still has a row for")
    # A phrase reads with the actor in front of it, so it opens with a verb
    # rather than with the actor's name or with a capital of its own.
    _shape = sorted(e for e, p in _sentences.items()
                    if not p or p[:1].isupper() or p.endswith("."))
    if _shape:
        for _e in _shape:
            bad("%s's phrase does not read with an actor in front of it: %r"
                % (_e, _sentences[_e]))
    else:
        ok("every phrase reads with the actor in front of it")

# ---- migrations are contiguous from 001 ----------------------------------
head("migrations contiguous from 001")
mig = sorted(f for f in os.listdir(os.path.join(R, "migrations"))
             if re.match(r"^\d{3}_.*\.py$", f))
nums = [int(f[:3]) for f in mig]
print("        %s" % ", ".join(mig))
if nums == list(range(1, len(nums) + 1)):
    ok("%d migration(s), contiguous" % len(nums))
else:
    bad("migration numbering has a gap: %s" % nums)

# ---- summary -------------------------------------------------------------
print("\n" + "=" * 66)
if not fails:
    print("no drift (%d note(s))" % len(notes))
else:
    print("%d DRIFT(S), %d note(s)" % (len(fails), len(notes)))
    for f in fails:
        print("  DRIFT: %s" % f)
for n in notes:
    print("  note : %s" % n)
sys.exit(1 if fails else 0)
