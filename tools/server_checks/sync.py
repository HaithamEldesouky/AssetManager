r"""The external asset system, read one way and reconciled in.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import base64
import io
import json
import os
import sqlite3
import time

from server_checks.stage import console_door
from server_checks.stage import (M, SRC_SYNC_ALL, _blank_lookup, _call_name,
                                 bad, eq, fresh_db, head, ok, read_server_cfg)



def _sync_reset():
    """Clear the sync settings and the credential between legs."""
    M._save_server_cfg(sync_base_url="", sync_list_path="", sync_list_key="",
                       sync_auth="none", sync_username="",
                       sync_interval_mins=0, sync_mapping={})
    M._sync_secret_set("")
    M._sync_state.update({"last": 0.0, "running": False})


class _StubAnswer(object):
    """What the external system said, without a port to say it on.

    The whole file drives Flask's test client rather than a socket, for the
    reason stated at the top of it; the same argument applies to the one
    outbound call this server makes. `_sync_fetch` takes the opener for exactly
    this, so what is under test is the reading and the reconciling rather than
    urllib.
    """

    def __init__(self, raw):
        self.raw = raw

    def read(self, n=None):
        return self.raw[:n] if n else self.raw

    def close(self):
        pass


def _stub_opener(payload=None, raw=None, blow_up=None):
    """An opener answering one payload, and remembering what it was asked."""
    body = raw if raw is not None else json.dumps(payload).encode("utf-8")

    def go(req, **_kw):
        go.asked.append(req)
        if blow_up is not None:
            raise blow_up
        return _StubAnswer(body)

    go.asked = []
    return go


def check_a_sync_adds_corrects_and_leaves_alone():
    """The four answers a run gives one asset, and no fifth (032, ADR-0014).

    Added, corrected where **this register's field is empty**, conflict where
    both hold it and they differ, and absent where the register has an asset
    the external system does not. The third and the fourth are the ones worth
    proving: the register is what rule 6 refuses Transactions against, so an
    external system that could overwrite a type silently is how an asset
    transacted as a Laptop for a year becomes a Screen overnight - and an
    absence is the least trustworthy thing a remote system can report, every
    failure of the connection looking exactly like one.
    """
    head("a sync adds, corrects an empty field, and leaves the rest alone (032)")
    fresh_db()
    _blank_lookup()
    _sync_reset()
    M._save_server_cfg(sync_base_url="https://cmdb.local",
                       sync_list_path="/assets")
    pay = [{"Asset Tag": "1001", "Serial No": "S-1", "Type": "Laptop",
            "Model": "T14"},
           {"Asset Tag": "1002", "Serial No": "S-2", "Type": "Desktop",
            "Model": ""}]
    eq("027's mapper answers over JSON keys, not spreadsheet headers",
       M._sync_mapping(pay),
       {"asset_number": "Asset Tag", "serial_number": "Serial No",
        "asset_type": "Type", "asset_model": "Model"})

    report, err = M._sync_run(actor="Check", opener=_stub_opener(pay))
    eq("a first run adds what the register does not have",
       (err, report["added"], report["corrected"], report["conflicts"]),
       ("", ["1001", "1002"], [], []))
    eq("  written through the one writer, so the register really holds them",
       [(a["asset_number"], a["asset_type"], a["asset_model"])
        for a in M._load_assets()],
       [("1001", "Laptop", "T14"), ("1002", "Desktop", "")])

    report, _err = M._sync_run(actor="Check", opener=_stub_opener(pay))
    eq("running it again changes nothing at all",
       (report["added"], report["corrected"], report["conflicts"],
        report["matched"]), ([], [], [], 2))

    pay2 = [{"Asset Tag": "1001", "Serial No": "S-1", "Type": "Laptop",
             "Model": "T14 Gen 3"},          # we hold T14 - a conflict
            {"Asset Tag": "1002", "Serial No": "S-2", "Type": "Desktop",
             "Model": "OptiPlex"},           # ours is empty - corrected
            {"Asset Tag": "1003", "Serial No": "S-3", "Type": "Screen",
             "Model": "U27"}]                # new - added
    report, _err = M._sync_run(actor="Check", opener=_stub_opener(pay2))
    eq("a field this register already holds is a conflict, not an overwrite",
       len(report["conflicts"]), 1)
    eq("  named, with both values, because somebody has to settle it",
       ("1001" in report["conflicts"][0] and "T14" in report["conflicts"][0]
        and "T14 Gen 3" in report["conflicts"][0]), True)
    eq("  a field this register left empty is filled in",
       report["corrected"], ["1002 (Asset Model)"])
    eq("  and an asset it had never seen is added", report["added"], ["1003"])
    eq("the conflicting asset is untouched on disk",
       [a["asset_model"] for a in M._load_assets()
        if a["asset_number"] == "1001"], ["T14"])

    before = len(M._load_assets())
    report, _err = M._sync_run(actor="Check", opener=_stub_opener(pay2[:1]))
    eq("an asset the external system does not have is reported",
       sorted(report["absent"]), ["1002", "1003"])
    eq("  and never deleted - the Transactions' only description of what moved"
       " is on that row", len(M._load_assets()), before)

    # Identity is the identifiers, folded for case the way 025 folds them, and
    # never a remote id: the payload's own key changes and nothing here does.
    report, _err = M._sync_run(actor="Check", opener=_stub_opener(
        [{"id": 90210, "Asset Tag": "1001", "Serial No": "s-1",
          "Type": "Laptop", "Model": "T14"}]))
    eq("a re-cased identifier is the same asset, and a remote id is not an"
       " identity at all",
       (report["added"], report["matched"]), ([], 1))
    _sync_reset()
    fresh_db()


def check_a_sync_that_cannot_be_read_changes_nothing():
    """A payload this server cannot use is refused whole (032).

    Every one of these leaves the register exactly as it was, which is the
    property that makes a scheduled job pointed at somebody else's API safe to
    leave running: the worst a broken answer does is a `sync.failed` row.
    """
    head("a sync that cannot be read leaves the register exactly as it was")
    fresh_db()
    _blank_lookup()
    _sync_reset()
    M._save_server_cfg(sync_base_url="https://cmdb.local",
                       sync_list_path="/assets")
    M._save_asset("1001", "S-1", "Laptop", "T14")
    before = [dict(a) for a in M._load_assets()]

    for label, opener in (
            ("an answer that is not JSON", _stub_opener(raw=b"<html>")),
            ("an answer that is not a list", _stub_opener({"assets": []})),
            ("a list holding something that is not a record",
             _stub_opener([1, 2])),
            ("a transport that fell over",
             _stub_opener(blow_up=OSError("connection refused")))):
        report, err = M._sync_run(actor="Check", opener=opener)
        eq("%s is refused, with the reason in words" % label,
           (report, bool(err)), (None, True))
    eq("nothing was written by any of them", M._load_assets(), before)

    # A payload whose keys cannot describe an asset: 027's own check, and the
    # refusal names the keys the answer did carry, because "bad mapping" with
    # nothing beside it is the one answer nobody can act on.
    _r, err = M._sync_run(actor="Check", opener=_stub_opener(
        [{"thing": "x", "colour": "red"}]))
    eq("an unmappable payload is refused by 027's own check",
       ("Asset Type" in err, "thing, colour" in err), (True, True))

    # Two records claiming one identifier: refused as a pair rather than taken
    # first-come, which is 027's answer to a file that collides with itself.
    report, _err = M._sync_run(actor="Check", opener=_stub_opener(
        [{"Asset Tag": "1009", "Serial No": "S-9", "Type": "UPS"},
         {"Asset Tag": "1009", "Serial No": "S-10", "Type": "UPS"}]))
    eq("a payload colliding with itself takes neither of the two",
       (report["added"], len(report["conflicts"])), ([], 2))

    # A record that is not an asset is skipped and said so, rather than
    # refusing the run: this is one row of somebody else's system, not a shape
    # this server cannot read.
    report, _err = M._sync_run(actor="Check", opener=_stub_opener(
        [{"Asset Tag": "", "Serial No": "", "Type": "Laptop"},
         {"Asset Tag": "1007", "Serial No": "", "Type": ""},
         {"Asset Tag": "1008", "Serial No": "S-8", "Type": "Switch"},
         {"Asset Tag": "X-11", "Serial No": "S-11", "Type": "Switch"},
         {"Asset Tag": "1012", "Serial No": "", "Type": "Switch"}]))
    eq("a row with no identifier and one with no type are skipped by name",
       (len(report["skipped"]), report["added"]), (4, ["1008"]))
    eq("  and so are the two 103 refuses, each with the writer's sentence",
       [s for s in report["skipped"]
        if s.startswith(("X-11 - ", "1012 - "))],
       ["X-11 - Asset Number X-11 is not a number - an Asset Number is "
        "digits only.", "1012 - An asset needs a Serial Number."])
    eq("  and the run still took the row that was an asset",
       [a["asset_number"] for a in M._load_assets()], ["1001", "1008"])
    _sync_reset()
    fresh_db()


def check_the_sync_credential_is_never_written_where_it_can_be_read():
    """The second replayable secret, and where it is not (032, ADR-0014).

    The same four absences 030 asserts of the SMTP password: not in
    `server_config.json`, not in a System Log row, not readable back by the
    window that sets it, and refused rather than written in plaintext where
    DPAPI is unavailable. Plus the one thing this secret has that the mail
    password does not - it is **never sent over a plain http:// base URL**,
    refused instead, because a token crossing an internal network in clear is
    not something a warning undoes.
    """
    head("the sync credential is never written where it can be read (032)")
    fresh_db()
    _blank_lookup()
    _sync_reset()
    secret = "tok-" + "7" * 16
    M._save_server_cfg(sync_base_url="http://cmdb.local",
                       sync_list_path="/assets", sync_auth="bearer")
    _rows, err = M._sync_fetch()
    eq("a credential is refused over http:// rather than sent in clear",
       ("http://" in err and "clear" in err), True)

    M._save_server_cfg(sync_base_url="https://cmdb.local")
    _rows, err = M._sync_fetch()
    eq("an auth mode with no credential stored says so",
       "No credential is stored" in err, True)

    stored = M._sync_secret_set(secret)
    if M.HAS_DPAPI:
        eq("a credential is stored, encrypted", (stored,
                                                 M._sync_secret_stored()),
           ("", True))
        raw = io.open(M.SYNC_SECRET_PATH, "rb").read()
        eq("  encrypted rather than written down", secret.encode() in raw,
           False)
        opener = _stub_opener([{"Asset Tag": "1001", "Type": "Laptop"}])
        M._sync_run(actor="Check", opener=opener)
        sent = dict(opener.asked[-1].headers)
        eq("  and replayed to the external system and nowhere else",
           [v for k, v in sent.items() if k.lower() == "authorization"],
           ["Bearer %s" % secret])
        M._save_server_cfg(sync_auth="basic", sync_username="svc-assets")
        opener = _stub_opener([{"Asset Tag": "1001", "Type": "Laptop"}])
        M._sync_run(actor="Check", opener=opener)
        sent = dict(opener.asked[-1].headers)
        eq("  basic sends the username with it, base64 and nothing else",
           [v for k, v in sent.items() if k.lower() == "authorization"],
           ["Basic %s" % base64.b64encode(
               ("svc-assets:%s" % secret).encode()).decode()])
    else:
        # The refusal is the behaviour, not a skip: ADR-0013's answer, which
        # ADR-0014 takes unchanged.
        eq("where DPAPI is unavailable the credential is refused, with the"
           " reason named", (bool(stored), M._sync_secret_stored()),
           (True, False))

    cfg_text = io.open(M.SERVER_CFG_PATH, encoding="utf-8").read()
    eq("the credential is not in server_config.json, in any form",
       secret in cfg_text, False)
    eq("  and neither is a key that would say where it is",
       [k for k in read_server_cfg()
        if k.startswith("sync_") and ("secret" in k or "token" in k
                                      or "password" in k)], [])
    conn = sqlite3.connect(M.DB_PATH)
    rows = conn.execute("SELECT event, detail, actor FROM system_log"
                        " WHERE event LIKE 'sync%'").fetchall()
    conn.close()
    eq("and no System Log row anywhere holds it",
       [r for r in rows if secret in str(r)], [])
    eq("the file has a name of its own rather than sharing the mail one",
       (os.path.basename(M.SYNC_SECRET_PATH),
        M.SYNC_SECRET_PATH == M.SMTP_SECRET_PATH),
       ("sync_secret.dat", False))
    eq("clearing it takes the file with it",
       (M._sync_secret_set(""), M._sync_secret_stored(),
        M._sync_secret_get()), ("", False, ""))

    # Source checks: the window is a Tk callback no request reaches, and what
    # matters about it is an absence.
    tree = ast.parse(SRC_SYNC_ALL)
    fns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns.setdefault(node.name, node)

    def src_of(name):
        return "" if name not in fns else (
            ast.get_source_segment(SRC_SYNC_ALL, fns[name]) or "")

    touches = []

    class _V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_FunctionDef(self, n):
            self.stack.append(n.name)
            self.generic_visit(n)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Name(self, n):
            if n.id == "SYNC_SECRET_PATH" and self.stack:
                touches.append(self.stack[-1])

    _V().visit(tree)
    # `bind` is where the path arrives, not a reader of the file: #225
    # moved these three into `server_sync.py` and `SYNC_SECRET_PATH` is one
    # of the fifteen names `server.py` hands over, so the assignment inside
    # that signature is a mention and not a touch. Subtracted by name rather
    # than widened into the wanted set, which would stop this answering the
    # question it asks.
    eq("three helpers reach the credential's file and nothing else does",
       set(touches) - {"bind"}, {"_sync_secret_set", "_sync_secret_get",
                                 "_sync_secret_stored"})
    if "_sync_secret_get(" in src_of("asset_sync"):
        bad("the window reads the stored credential back")
    else:
        ok("the window never reads the stored credential back - it is told"
           " only whether one is there")
    eq("every change here takes the admin password, at the entry's door "
       "on every open and not again in the window (096)",
       ("_admin_password_ok(" in src_of("asset_sync"),
        console_door("Asset Sync")), (False, "admin"))
    if "_authorise(" in src_of("asset_sync"):
        bad("asset_sync is delegable to a capability password")
    else:
        ok("and it is not a fifth capability (ADR-0006)")
    # The console itself since 077, the Lookup Sheet hub having been the
    # door until it was deleted: Asset Sync is an entry on the Assets
    # section, beside the Lookup Sheet rather than behind it.
    if "asset_sync(" in src_of("run_gui"):
        ok("the console's Assets section is the door to it")
    else:
        bad("nothing reaches asset_sync()")
    _sync_reset()
    fresh_db()


def check_the_sync_writes_through_the_one_writer_and_never_deletes():
    """Source checks: an absence, in a file that is allowed to add (032).

    No request demonstrates the absence of a delete, and the one that would is
    the one nobody wants to have written. So it is asserted here: nothing in
    the sync calls `_delete_asset`, nothing in it executes SQL of its own
    against `assets`, and `_save_asset` is the only way a row gets written -
    the same shape 028 asserts of the proposals window.

    Beside them the two transport facts, which are also absences:
    `urllib.request` and not `requests` (rule 13 - the vendored lib is pinned
    to one Python minor version), and TLS verification never relaxed, which
    would otherwise be the first place in this repo to turn it off.
    """
    head("the sync writes through the one writer, and never deletes (032)")
    tree = ast.parse(SRC_SYNC_ALL)
    fns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns.setdefault(node.name, node)

    def src_of(name):
        return "" if name not in fns else (
            ast.get_source_segment(SRC_SYNC_ALL, fns[name]) or "")

    def code_of(name):
        """The function's body with its own docstring taken out.

        These are absences, and every one of them is a phrase the docstring
        beside it *names* in saying why it is absent - "no unverified context",
        "not `requests`". A text scan that could not tell the two apart would
        fail on the comment explaining itself, so the prose comes out first.
        """
        node = fns.get(name)
        if node is None:
            return ""
        whole = ast.get_source_segment(SRC_SYNC_ALL, node) or ""
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            doc = ast.get_source_segment(SRC_SYNC_ALL, body[0])
            if doc:
                whole = whole.replace(doc, "", 1)
        return whole

    sync_fns = sorted(n for n in fns if n.startswith("_sync_")) + ["asset_sync"]
    for name in sync_fns:
        body = code_of(name)
        if "_delete_asset" in body or "DELETE FROM assets" in body:
            bad("%s deletes an asset" % name)
        if "UPDATE assets" in body or "INSERT INTO assets" in body:
            bad("%s writes the register without going through _save_asset"
                % name)
    ok("nothing in the sync deletes an asset or writes one behind the writer")
    eq("and the one that does write goes through _save_asset",
       [n for n in sync_fns if "_save_asset(" in code_of(n)],
       ["_sync_reconcile"])

    eq("the mapper is 027's, not a second one",
       ("_map_import_columns(" in code_of("_sync_mapping"),
        "_check_import_mapping(" in code_of("_sync_run")), (True, True))

    # Scoped to this function rather than to the file: `run_gui`'s own liveness
    # probe reaches for `requests` behind a try/except and pins the server's
    # certificate with `check_hostname` off over loopback, which is a different
    # argument and an older one. What is asserted here is about the one
    # outbound call this server makes to somebody else's system.
    fetch = code_of("_sync_fetch")
    eq("the transport is urllib.request, not requests (rule 13)",
       ("urllib.request." in fetch, "requests" in fetch), (True, False))
    eq("  TLS verification is never relaxed",
       ("create_default_context()" in fetch,
        "CERT_NONE" in fetch, "check_hostname" in fetch,
        "_create_unverified_context" in fetch),
       (True, False, False, False))

    # The loop is a daemon thread whose exceptions are swallowed, so nothing
    # else would report that the scheduler had stopped being started - the same
    # reason the Auto-Accept job is asserted as a source check.
    eq("the scheduled run is started with the other background jobs",
       "_sync_loop" in src_of("_start_background_jobs"), True)
    eq("  and it re-reads the interval rather than sleeping on it",
       "_sync_cfg()" in src_of("_sync_loop"), True)

    # No mail code in here at all: a run reaches a mailbox through 031's rules
    # on the sync.* events, which is the whole of this feature's dependency on
    # that one.
    for name in sync_fns:
        body = code_of(name)
        if "_send_mail(" in body or "_smtp_send_now(" in body:
            bad("%s mails its own result instead of leaving it to a rule"
                % name)
    ok("a run reaches a mailbox through 031's rules, not through mail code")

    # The run's own events, not the window's: `asset_sync` also writes a
    # `sync.configured` when an Admin saves, which is a rule-able event but is
    # not something a run does.
    events = set()
    for name in [n for n in sync_fns if n != "asset_sync"]:
        for node in ast.walk(fns[name]):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_log_event" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                events.add(node.args[0].value)
    eq("every run writes the events a rule can be pointed at",
       sorted(e for e in events if e.startswith("sync.")),
       ["sync.added", "sync.conflict", "sync.failed", "sync.finished",
        "sync.started"])
    eq("  and the window says when the settings behind them changed",
       [n.args[0].value
        for n in ast.walk(fns["asset_sync"])
        if isinstance(n, ast.Call) and _call_name(n.func) == "_log_event"
        and n.args
        and isinstance(n.args[0], ast.Constant)], ["sync.configured"])


def check_the_last_run_is_derived_from_the_log():
    """A scheduled job whose outcome is only in a log is one nobody watches.

    So the console shows it - and shows it **derived** from the rows the run
    already wrote, the way `client_commands` derives `queued` and `collected`
    from two dates rather than storing a status beside them. A stored one is a
    second copy of what those rows say, and it is the copy that goes stale when
    a run dies between writing the row and updating the key.
    """
    head("the last run's result is derived from the System Log (032)")
    fresh_db()
    _blank_lookup()
    _sync_reset()
    eq("with no run yet, there is nothing to show", M._sync_last_run(), None)

    M._save_server_cfg(sync_base_url="https://cmdb.local",
                       sync_list_path="/assets")
    M._sync_run(actor="Check",
                opener=_stub_opener([{"Asset Tag": "1001", "Serial No": "S-1",
                                      "Type": "Laptop"}]))
    ts, good, detail = M._sync_last_run()
    eq("a run that finished says so, with what it did",
       (bool(ts), good, "1 added" in detail), (True, True, True))

    M._sync_run(actor="Check", opener=_stub_opener(raw=b"<html>"))
    _ts, good, detail = M._sync_last_run()
    eq("and a run that failed says that instead, in the reason's own words",
       (good, "not JSON" in detail), (False, True))

    eq("nothing about it is stored beside the rows",
       [k for k in read_server_cfg() if "last" in k.lower()], [])

    # Whoever started it, it was a read of somebody else's API, so it is what
    # the interval counts from. It was the loop's own stamp alone, so Run now
    # a minute before the interval elapsed was answered by a scheduled run a
    # minute later - a second fetch of the same list, which is the thing
    # _sync_loop's docstring says the wait after a boot exists to avoid. The
    # interval is stated here rather than left to the default, since what is
    # being asserted is measured against it.
    M._save_server_cfg(sync_interval_mins=60)
    M._sync_state["last"] = time.time() - M._sync_cfg()["every"] * 60
    M._sync_run(actor="Admin (Server GUI)",
                opener=_stub_opener([{"Asset Tag": "1002",
                                      "Type": "Laptop"}]))
    eq("a run started at the console is a run the schedule counts from",
       time.time() - M._sync_state["last"] >= M._sync_cfg()["every"] * 60,
       False)

    # One at a time: two runs would read the same list and race each other into
    # the same rows, and the answer to wanting one now is the one running.
    M._sync_state["running"] = True
    try:
        report, err = M._sync_run(actor="Check", opener=_stub_opener([]))
        eq("a second run while one is going is refused, not queued",
           (report, "already running" in err), (None, True))
    finally:
        M._sync_state["running"] = False
    _sync_reset()
    fresh_db()
