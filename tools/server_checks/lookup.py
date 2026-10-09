r"""The Lookup Sheet's write path, the proposals, the identifiers.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import base64
import io
import os
import sqlite3
from datetime import datetime, timedelta

from server_checks.stage import console_door
from server_checks.stage import (GUI_SRC, M, R, SRC_ALL, SRC_LOOKUP_ALL, STAGE,
                                 _admin, _blank_lookup, _caps, _code,
                                 _owners_of, _stub_lookup, bad, eq, fresh_db,
                                 gui_root, head, log_rows, ok, stage_name,
                                 tk_or_skip, txn, widgets)



def _legacy_assets_db():
    """A database whose `assets` table predates 010: no collation, no indexes.

    Built by rebuilding the table `init_db` just made, rather than by writing
    the 009 DDL out again here - a second copy of a schema is the copy that
    goes stale, and what this needs is only the absence of the two things 010
    adds.
    """
    db = fresh_db()
    conn = sqlite3.connect(db)
    for name in ("idx_assets_number", "idx_assets_serial"):
        conn.execute("DROP INDEX IF EXISTS %s" % name)
    conn.execute(M._ASSETS_NOCASE_SCHEMA.replace(" COLLATE NOCASE", ""))
    cols = ", ".join(M._ASSETS_COLS)
    conn.execute("INSERT INTO assets_new(%s) SELECT %s FROM assets"
                 % (cols, cols))
    conn.execute("DROP TABLE assets")
    conn.execute("ALTER TABLE assets_new RENAME TO assets")
    conn.commit()
    conn.close()
    return db


def _assets_sql(db):
    conn = sqlite3.connect(db)
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'"
                       " AND name='assets'").fetchone()[0]
    conn.close()
    return sql


def check_a_file_of_proposals_is_taken_whole_or_not_at_all():
    """A delivery arrives as a file and is proposed as one batch (029).

    Two halves. The first is that a client can be told what a file is without
    carrying the rules: `POST /assets/import/preview` writes nothing and
    answers with 027's own `_map_import_columns`, `_check_import_mapping` and
    `_validate_import_rows`, which is the same set the Server GUI's Import
    Assets shows the Admin. A second copy in a client is what rule 10 exists to
    prevent, and the shape it would take is a file this door accepts and the
    Admin's refuses.

    The second is that a batch is **all or nothing**. Half a delivery recorded
    is worse than none, because the rows that went in are indistinguishable
    from rows somebody typed and nothing says which half arrived. That is also
    the only honest answer to a file that collides **with itself**: written row
    by row, the first row would be taken and the second refused with "somebody
    has already proposed this", and the somebody would be this same file one
    line earlier.
    """
    head("a file of proposals is taken whole or not at all")
    fresh_db()
    _stub_lookup([("6001", "RS-1", "Laptop", "T14")])
    c = M.app.test_client()
    headers = ["Asset No", "Serial Number", "Type", "Model"]

    def preview(**body):
        r = c.post("/assets/import/preview", json=body)
        return r.status_code, (r.get_json() or {})

    code, body = preview(headers=headers)
    eq("the header row alone is answered with the guess, and nothing else",
       (code, body.get("guessed"), body.get("mapping"), body.get("verdicts")),
       (200, True, {"asset_number": 0, "serial_number": 1, "asset_type": 2,
                    "asset_model": 3}, []))
    code, body = preview(headers=headers, rows=[["1001", "", "Laptop", ""]],
                         mapping={"asset_number": 0, "serial_number": 0,
                                  "asset_type": 2, "asset_model": 3})
    eq("two fields on one column is refused rather than validated against",
       (code, body.get("code")), (400, "bad_mapping"))
    code, body = preview(headers=headers, rows=[["1001", "", "Laptop", ""]],
                         mapping={"asset_number": 0, "serial_number": 1,
                                  "asset_type": None, "asset_model": 3})
    eq("  and an unmapped Asset Type, which no import may invent (rule 2)",
       (code, body.get("code")), (400, "bad_mapping"))

    mapping = {"asset_number": 0, "serial_number": 1, "asset_type": 2,
               "asset_model": 3}
    _code, body = preview(
        headers=headers, mapping=mapping,
        rows=[["7001", "FS-1", "Laptop", "T14"],
              ["", "", "Laptop", ""],
              ["6001", "FS-9", "Laptop", ""],
              ["7005", "fs-1", "Screen", ""],
              ["X-1", "XS-1", "Laptop", ""],
              ["7006", "", "Laptop", ""]])
    eq("every row is answered at once, with the register and the file itself"
       " checked the same way",
       [(v["line"], v["error"][:24]) for v in body.get("verdicts", [])],
       [(2, ""), (3, "An asset needs an Asset "),
        (4, "Asset Number 6001 is alr"), (5, "Serial Number fs-1 is on"),
        (6, "Asset Number X-1 is not "), (7, "An asset needs a Serial ")])
    eq("  and a preview writes nothing at all",
       (len(M._load_assets()), len(M._load_proposals())), (1, 0))

    # ── the batch ────────────────────────────────────────────────────────────
    def propose(rows, **extra):
        body = {"client_id": "store-1",
                "proposed_by": "Storekeeper User (Storekeeper)",
                "source": "delivery.xlsx", "rows": rows}
        body.update(extra)
        r = c.post("/assets/propose", json=body)
        return r.status_code, (r.get_json() or {})

    good = [{"asset_number": "700%d" % n, "serial_number": "FS-%d" % n,
             "asset_type": "Laptop", "asset_model": "T14"}
            for n in (1, 2, 3)]
    code, body = propose(good + [{"asset_number": "6001",
                                  "serial_number": "FS-9",
                                  "asset_type": "Laptop"}])
    eq("one row the register already holds refuses the whole file",
       (code, body.get("code"), [x["line"] for x in body.get("refusals", [])]),
       (409, "bad_rows", [5]))
    eq("  and none of the rest is recorded - nothing says which half arrived",
       len(M._load_proposals()), 0)
    code, body = propose([{"asset_number": "7101", "serial_number": "Z-1",
                           "asset_type": "Laptop"},
                          {"asset_number": "7102", "serial_number": "z-1",
                           "asset_type": "Laptop"}])
    eq("a file that collides with itself is refused as a file, not row by row",
       (code, body.get("code"), [x["line"] for x in body.get("refusals", [])],
        len(M._load_proposals())), (409, "bad_rows", [3], 0))

    code, body = propose(good)
    eq("a file every row of which is an asset is taken, with no password",
       (code, body.get("proposed"), len(body.get("proposal_ids", []))),
       (200, 3, 3))
    pending = M._load_proposals("pending")
    eq("  every row stamped with the one moment the batch arrived, which is"
       " what the Server GUI groups a delivery on",
       (len({p["proposed_at"] for p in pending}), body.get("proposed_at")),
       (1, pending[0]["proposed_at"]))
    eq("  and attributed to the Storekeeper that sent it",
       sorted({(p["proposed_by"], p["client_id"]) for p in pending}),
       [("Storekeeper User (Storekeeper)", "store-1")])
    eq("a file of proposals is not a file of assets - the register is"
       " unchanged", [a["asset_number"] for a in M._load_assets()], ["6001"])
    eq("  and rule 6 still refuses every row of it",
       (c.get("/lookup?q=7001").get_json() or {}).get("found"), False)
    code, body = propose(good)
    eq("sending the same file twice is refused whole, naming every line",
       (code, body.get("code"), len(body.get("refusals", [])),
        len(M._load_proposals())), (409, "bad_rows", 3, 3))

    code, body = propose([])
    eq("an empty file is refused", (code, body.get("code")), (400, "no_rows"))
    code, body = propose([{"asset_number": "B-%d" % n, "asset_type": "Laptop"}
                          for n in range(M._PROPOSAL_BATCH_MAX + 1)])
    eq("one longer than a batch may carry is refused with the count, the way"
       " POST /clients/log caps its own",
       (code, body.get("code"), str(M._PROPOSAL_BATCH_MAX) in body.get("error", "")),
       (400, "too_many", True))
    eq("  and a preview of one is refused the same way, before it is typed",
       preview(headers=headers, mapping=mapping,
               rows=[["x", "", "Laptop", ""]]
                    * (M._PROPOSAL_BATCH_MAX + 1))[1].get("code"), "too_many")

    conn = sqlite3.connect(M.DB_PATH)
    events = [r[0] for r in conn.execute(
        "SELECT event FROM system_log WHERE event LIKE 'asset.propos%'")]
    conn.close()
    eq("a batch is one System Log entry rather than one per row",
       (events.count("asset.proposals_imported"),
        events.count("asset.proposed")), (1, 0))

    # Source checks: the window that reads these rules is a Tk callback no
    # harness reaches, and what matters is that there is one copy of each rule
    # rather than what either importer does with it.
    eq("still only `_propose_asset` records a proposal, a row of a batch"
       " included", _owners_of("INSERT INTO asset_proposals"),
       {"_propose_asset"})
    # SRC_LOOKUP_ALL since #229: the two routes below are here and the
    # four helpers they are asserted to call are in server_lookup.py.
    tree = ast.parse(SRC_LOOKUP_ALL)
    fns  = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns.setdefault(node.name, node)

    def src_of(name):
        return "" if name not in fns else (
            ast.get_source_segment(SRC_LOOKUP_ALL, fns[name]) or "")

    for name, helper in (("import_assets", "_check_import_mapping("),
                         ("preview_import", "_check_import_mapping("),
                         ("preview_import", "_map_import_columns("),
                         ("preview_import", "_validate_import_rows("),
                         ("_propose_batch", "_validate_import_rows("),
                         ("_propose_batch", "_propose_asset(")):
        if helper in src_of(name):
            ok("%s reads %s rather than a copy of it" % (name, helper[:-1]))
        else:
            bad("%s does not call %s" % (name, helper[:-1]))
    if "INSERT" in src_of("preview_import") or "UPDATE" in src_of(
            "preview_import"):
        bad("the preview writes something")
    else:
        ok("and the preview writes nothing, which is what makes it open")
    fresh_db()
    _blank_lookup()


def check_the_storekeeper_proposes_and_the_admin_approves():
    """A proposal changes nothing until an Admin says so (028, ADR-0012).

    The endpoint is unauthenticated, like every other endpoint a Client calls
    (ADR-0002), and what makes that safe here is the state rather than the
    door: a proposal cannot be transacted, cannot be looked up, and reaches the
    register only through `_save_asset` on an Admin's decision at the console.
    So what is asserted is exactly that - what the endpoint refuses on the
    spot, that a decision is the only thing that writes an asset, and that a
    rejection writes none and keeps the row.

    The two refusals a Storekeeper actually meets are worth telling apart, and
    they carry different codes for that reason: `duplicate_identifier` is the
    answer they wanted - the asset is in the register already and can be
    transacted now - while `already_proposed` means somebody has asked and the
    answer is coming.
    """
    head("the Storekeeper proposes an asset and the Admin approves it")
    fresh_db()
    _stub_lookup([("6001", "RS-1", "Laptop", "T14")])
    c = M.app.test_client()

    def propose(**body):
        r = c.post("/assets/propose", json=body)
        return r.status_code, (r.get_json() or {})

    code, body = propose(asset_number="", serial_number="",
                         asset_type="Laptop")
    eq("a proposal with neither identifier is refused",
       (code, body.get("code")), (400, "bad_asset"))
    code, body = propose(asset_number="5001", serial_number="PS-8",
                         asset_type="")
    eq("  and one with no Asset Type (rule 2)",
       (code, body.get("code")), (400, "bad_asset"))
    # 103: an asset carries both identifiers, and its Asset Number is digits.
    for label, an, sn, said in (
            ("no Serial Number", "5021", "", "needs a Serial Number"),
            ("no Asset Number", "", "PS-21", "needs an Asset Number"),
            ("letters in the Asset Number", "P-21", "PS-21", "digits only"),
            ("a digit that is not 0-9", "50\u00b2", "PS-21", "digits only")):
        code, body = propose(asset_number=an, serial_number=sn,
                             asset_type="Laptop")
        eq("a proposal with %s is refused, saying so" % label,
           (code, body.get("code"), said in body.get("error", "")),
           (400, "bad_asset", True))
    code, body = propose(asset_number="6001", serial_number="NEW-SN",
                         asset_type="Laptop")
    eq("an identifier the register already holds is refused on the spot",
       (code, body.get("code")), (409, "duplicate_identifier"))
    eq("  naming the asset that holds it, in `_save_asset`'s own words",
       "6001" in body.get("error", ""), True)
    code, body = propose(asset_number="5009", serial_number="rs-1",
                         asset_type="Laptop")
    eq("  the serial the same way, case not significant",
       (code, body.get("code")), (409, "duplicate_identifier"))

    code, body = propose(asset_number="5001", serial_number="PS-1",
                         asset_type="Screen", asset_model="U2419H",
                         proposed_by="Storekeeper User (Storekeeper)",
                         client_id="store-1")
    eq("a proposal for an asset nobody holds is taken, with no password at all",
       (code, body.get("proposal_status")), (200, "pending"))
    pid = body.get("proposal_id")
    code, body = propose(asset_number="5001", serial_number="PS-7",
                         asset_type="Screen")
    eq("the same asset proposed twice is refused, naming the one waiting",
       (code, body.get("code"), "#%d" % pid in body.get("error", "")),
       (409, "already_proposed", True))

    listed = c.get("/assets/proposals?status=pending").get_json()
    eq("the Storekeeper can read what it asked for",
       [(p["id"], p["asset_number"], p["proposed_by"]) for p in listed],
       [(pid, "5001", "Storekeeper User (Storekeeper)")])
    eq("  and an unknown status is refused rather than answered with the lot",
       c.get("/assets/proposals?status=nonsense").status_code, 400)
    eq("a proposal is not an asset - the register is unchanged",
       [a["asset_number"] for a in M._load_assets()], ["6001"])
    eq("  and rule 6 still refuses it, which is the whole of what a state buys",
       (M.app.test_client().get("/lookup?q=5001").get_json() or {}).get("found"),
       False)

    # ── the decision ─────────────────────────────────────────────────────────
    try:
        M._decide_proposal(pid, False)
        bad("a rejection with no reason was taken")
    except ValueError as ex:
        eq("a rejection needs a reason - it is what the Storekeeper is told",
           getattr(ex, "code", ""), "no_reason")
    M._decide_proposal(pid, True)
    eq("approving writes exactly one asset, through the one writer",
       sorted((a["asset_number"], a["serial_number"], a["asset_type"],
               a["asset_model"]) for a in M._load_assets()),
       [("5001", "PS-1", "Screen", "U2419H"), ("6001", "RS-1", "Laptop", "T14")])
    eq("  and the proposal is answered rather than deleted",
       [(p["status"], p["decided_by"]) for p in M._load_proposals()
        if p["id"] == pid], [("approved", "Admin (Server GUI)")])
    try:
        M._decide_proposal(pid, True)
        bad("the same proposal was decided twice")
    except ValueError as ex:
        eq("  and deciding it again is refused, naming what was already said",
           (getattr(ex, "code", ""), "approved" in str(ex)),
           ("already_decided", True))

    _code, body = propose(asset_number="5011", serial_number="NOPE-1",
                          asset_type="Laptop")
    rid = body.get("proposal_id")
    before = len(M._load_assets())
    M._decide_proposal(rid, False, reason="Already registered as 6001.")
    eq("a rejection writes no asset", len(M._load_assets()), before)
    eq("  and keeps the row, with the reason on it - ADR-0003's answer",
       [(p["status"], p["reason"]) for p in M._load_proposals()
        if p["id"] == rid],
       [("rejected", "Already registered as 6001.")])
    eq("  a rejected proposal blocks nothing: the hardware may turn up after all",
       propose(asset_number="5011", serial_number="nope-1",
               asset_type="Laptop")[0], 200)

    # An identifier that reached the register while the proposal waited is
    # refused by `_save_asset`, which leaves the proposal in the state it is
    # actually in - pending - rather than approved over an asset it did not
    # write.
    _code, body = propose(asset_number="5013", serial_number="RACE-1",
                          asset_type="Laptop")
    raced = body.get("proposal_id")
    M._save_asset("5014", "RACE-1", "Laptop")
    try:
        M._decide_proposal(raced, True)
        bad("a proposal was approved over an identifier the register holds")
    except ValueError as ex:
        eq("an approval racing the register is refused in 025's words",
           "already in the Lookup Sheet" in str(ex), True)
    eq("  and the proposal is left pending, which is what it is",
       [p["status"] for p in M._load_proposals() if p["id"] == raced],
       ["pending"])

    conn = sqlite3.connect(M.DB_PATH)
    events = [r[0] for r in conn.execute(
        "SELECT event FROM system_log WHERE event LIKE 'asset.propos%'")]
    conn.close()
    eq("every proposal and every decision is a System Log entry",
       (events.count("asset.proposed"), events.count("asset.proposal_approved"),
        events.count("asset.proposal_rejected")), (4, 1, 1))

    # Source checks: the window is a Tk callback no harness reaches, and what
    # matters about it is an absence - that it has no writer of its own.
    ins = _owners_of("INSERT INTO asset_proposals")
    upd = _owners_of("UPDATE asset_proposals")
    eq("only `_propose_asset` records a proposal", ins, {"_propose_asset"})
    eq("only `_decide_proposal` answers one", upd, {"_decide_proposal"})
    saves = _owners_of("_save_asset(")
    eq("  and the proposals window writes no asset of its own",
       "asset_proposals" in saves, False)
    eq("the decision is admin-password only, asked at the console's door "
       "on every open and not again in the window (096)",
       ("_admin_password_ok" in GUI_SRC
        .split("def asset_proposals(")[1].split("\ndef ")[0],
        console_door("Asset Proposals")), (False, "admin"))
    eq("  and the one endpoint that decides one is the delegated door "
       "#173 added, which forwards to that same `_decide_proposal`",
       sorted(r.rule for r in M.app.url_map.iter_rules()
              if "proposal" in r.rule and r.rule != "/assets/proposals"),
       ["/assets/proposals/decide"])
    fresh_db()
    _blank_lookup()


def check_a_proposal_is_answerable_over_the_delegated_channel():
    """Asset Proposals from somewhere else (#173).

    The console's Asset Proposals window put on the network behind the
    **Server Settings** capability password, and what has to hold across that
    move is that nothing about the decision itself moved: `_decide_proposal`
    and `_save_asset` are the one path either way, so a delegate meets the
    same refusals in the same words and an approval is the same write.

    What the wire adds, and what is asserted here:

      - **The transport rule is strict on both credentials.** These routes are
        new, so no shipped client sends the admin password to this one over
        plain HTTP and there is no install to break - `admin_is_native` is a
        wire-compatibility allowance rather than a property of the admin
        password, and a route that never had those callers does not get it.
      - **The act is attributed to the delegate**, in the `decided_by` column
        and in the System Log entry beside it, and a `decided_by` the caller
        sent is **ignored**: this is a credential rather than a person, the
        way `POST /transactions/cancel` reads one.
      - **The race leaves the proposal pending.** An identifier that reached
        the register while the proposal waited is refused in `_save_asset`'s
        own words (025), and the row stays `pending`, which is the state it
        is actually in - the half a status code cannot show.
      - **Replacing the sheet did not move with it** (rule 11):
        `POST /lookup/upload` still refuses this password.
      - **The knock writes nothing.** A body with no id is answered `no_id`
        *after* the credential was examined, which is what makes it the door
        the Remote Admin window may knock on - `GET /assets/proposals` beside
        it needs no credential at all and would answer for any password.
    """
    head("a proposal is answerable over the delegated channel (#173)")
    db = fresh_db()
    _stub_lookup([("6001", "RS-1", "Laptop", "T14")])
    _caps(server_settings="setpw", manage_records="mrpw")
    M.ADMIN_CFG["capability_holders"] = {"server_settings": "Ops on-call"}
    c = M.app.test_client()
    HTTPS = "https://localhost"

    def propose(**body):
        return (c.post("/assets/propose", json=body).get_json()
                or {}).get("proposal_id")

    def decide(pid, decision, password, base=HTTPS, **extra):
        r = c.post("/assets/proposals/decide", base_url=base,
                   json=dict(extra, id=pid, decision=decision,
                             password=password))
        return r.status_code, (r.get_json() or {})

    p1 = propose(asset_number="5001", serial_number="PS-1",
                 asset_type="Screen", asset_model="U2419H",
                 proposed_by="Storekeeper User (Storekeeper)")
    p2 = propose(asset_number="5002", serial_number="PS-2",
                 asset_type="Screen",
                 proposed_by="Storekeeper User (Storekeeper)")
    p3 = propose(asset_number="5003", serial_number="PS-3",
                 asset_type="Laptop",
                 proposed_by="Storekeeper User (Storekeeper)")

    # ── the door ─────────────────────────────────────────────────────────────
    code, body = decide(p1, "approve", "setpw", base="http://localhost")
    eq("a capability password over plain HTTP is refused before it is examined",
       (code, body.get("code")), (403, "insecure"))
    code, body = decide(p1, "approve", "admin", base="http://localhost")
    eq("  and so is the admin password - these routes are new, so there is no "
       "install to break by holding both to the transport rule",
       (code, body.get("code")), (403, "insecure"))
    code, body = decide(p1, "approve", "wrong")
    eq("a wrong password is a different answer from a refused transport",
       (code, body.get("code")), (401, "bad_password"))
    code, body = decide(p1, "approve", "mrpw")
    eq("  and another capability's password opens nothing here",
       (code, body.get("code")), (401, "bad_password"))
    eq("nothing was written by any of them",
       [p["status"] for p in M._load_proposals()], ["pending"] * 3)

    # ── the knock ────────────────────────────────────────────────────────────
    r = c.post("/assets/proposals/decide", base_url=HTTPS,
               json={"password": "setpw"})
    eq("the knock - a body with no id - is answered after the credential",
       (r.status_code, (r.get_json() or {}).get("code")), (400, "no_id"))
    r = c.post("/assets/proposals/decide", base_url=HTTPS,
               json={"password": "wrong"})
    eq("  which is what makes it a knock: a wrong password answers 401 there",
       r.status_code, 401)
    eq("  and neither changed anything",
       [p["status"] for p in M._load_proposals()], ["pending"] * 3)
    code, body = decide(p1, "sideways", "setpw")
    eq("a decision that is neither approve nor reject is refused",
       (code, body.get("code")), (400, "bad_decision"))

    # ── the decision ─────────────────────────────────────────────────────────
    code, body = decide(p1, "approve", "setpw",
                        decided_by="Somebody Else")
    eq("the Server Settings password approves one proposal",
       (code, body.get("proposal_status")), (200, "approved"))
    eq("  writing exactly one asset, through the one writer",
       sorted(a["asset_number"] for a in M._load_assets()), ["5001", "6001"])
    answered = {p["id"]: p for p in M._load_proposals()}
    eq("  attributed to the delegate, with the caller's decided_by ignored",
       answered[p1]["decided_by"],
       'Delegate: Server Settings held by "Ops on-call" (remote)')

    code, body = decide(p2, "reject", "setpw")
    eq("a rejection with no reason is refused - it is what the Storekeeper "
       "is told", (code, body.get("code")), (400, "no_reason"))
    code, body = decide(p2, "reject", "setpw", reason="Already in the store.")
    eq("  and with one it is taken, the row kept",
       (code, body.get("proposal_status")), (200, "rejected"))
    answered = {p["id"]: p for p in M._load_proposals()}
    eq("  carrying the reason and the delegate",
       (answered[p2]["reason"],
        answered[p2]["decided_by"].startswith("Delegate: Server Settings")),
       ("Already in the store.", True))
    code, body = decide(p2, "approve", "setpw")
    eq("a proposal already answered is refused",
       (code, body.get("code")), (409, "already_decided"))
    code, body = decide(0, "approve", "setpw")
    eq("  and an id that is not one is not a 404 about a missing proposal",
       (code, body.get("code")), (400, "no_id"))
    code, body = decide(9999, "approve", "setpw")
    eq("  while an id naming no proposal is",
       (code, body.get("code")), (404, "no_proposal"))

    # ── the race (025) ───────────────────────────────────────────────────────
    M._save_asset("5903", "PS-3", "Laptop")
    code, body = decide(p3, "approve", "setpw")
    eq("an approval racing the register is refused in _save_asset's own words",
       (code, body.get("code"), "PS-3" in body.get("error", "")),
       (409, "duplicate_identifier", True))
    eq("  and the proposal stays pending, which is the state it is in",
       [p["status"] for p in M._load_proposals() if p["id"] == p3],
       ["pending"])

    # ── what did not move (rule 11) ──────────────────────────────────────────
    r = c.post("/lookup/upload", base_url=HTTPS,
               json={"password": "setpw", "file_data": ""})
    eq("replacing the sheet is still the admin password and nothing else",
       r.status_code in (401, 403), True)

    # ── the record ───────────────────────────────────────────────────────────
    acts = [x for x in log_rows(db) if x["event"] == "remote.action"]
    eq("every use of the capability wrote remote.action before it, at warn",
       len(acts) > 0 and acts[-1]["level"], "warn")
    decided = [x for x in log_rows(db)
               if x["event"].startswith("asset.proposal_")]
    eq("  and the decisions are on the record under the delegate's name",
       all(x["actor"].startswith("Delegate: Server Settings")
           for x in decided) and len(decided) > 0, True)


def check_the_proposal_door_is_one_route_and_one_writer():
    """#173, asserted as source: an absence, and a shape.

    Three claims, none of which a request demonstrates.

    **There is no `_proposal_door`.** A named door exists in this file where
    *several* routes ask one question and the decision must not be made three
    ways - `_member_door` over three `/members` routes, `_mail_door` over
    five. This capability reaches **one** route, so it calls
    `_remote_authorise` directly, exactly as `POST /records/import` and
    `POST /admin/server_config` already do; a helper wrapping a single call
    site would be a byte-identical copy of `_mail_door` under another name,
    which is the duplication rule 10 exists to prevent.

    **It is `_remote_authorise` and not `_remote_admit(..., admin_is_native)`.**
    That flag is a wire-compatibility allowance for doors that predate this
    channel, and this route has no shipped caller at all.

    **The endpoint writes no asset and no proposal of its own**: it forwards
    to `_decide_proposal`, which is the one answerer, the way `_save_asset` is
    the one writer. The group one door up asserts that for the console; this
    asserts it for the wire, so the two cannot drift.
    """
    head("the proposal door is one route and one writer (#173)")
    tree = ast.parse(SRC_ALL)
    fns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fns.setdefault(node.name, node)

    def src_of(name):
        return "" if name not in fns else (
            ast.get_source_segment(SRC_ALL, fns[name]) or "")

    eq("the endpoint is there", "decide_asset_proposal" in fns, True)
    eq("and there is deliberately no _proposal_door, a single call site being "
       "what `_member_door` and `_mail_door` are not for",
       "_proposal_door" in SRC_ALL, False)
    body = src_of("decide_asset_proposal")
    eq("it asks _remote_authorise directly",
       "_remote_authorise(" in body, True)
    eq('  naming the server_settings capability',
       '"server_settings"' in body, True)
    eq("  and never _remote_admit's admin_is_native, which is an allowance "
       "for doors that predate this channel",
       "admin_is_native" in body, False)
    eq("it forwards to _decide_proposal", "_decide_proposal(" in body, True)
    eq("  and writes no asset of its own", "_save_asset(" in body, False)
    eq("  and no proposal of its own", "_propose_asset(" in body, False)
    eq("it takes no decided_by from the caller - this is a credential rather "
       "than a person", "'decided_by'" in body or '"decided_by"' in body,
       False)


def check_a_proposal_waiting_is_visible_from_the_console():
    """Asset Proposals is a row on Assets, and it says how many (A10).

    Two doors until #240/065 - the Lookup Sheet window's own footer, and a
    second entry in Server Administration with the count - and neither said
    the other existed on the row itself. 065 folded Asset Proposals into the
    Lookup Sheet's own hub, 077 deleted both hubs onto the console's Assets
    section, and **086 took the row away as well**: it is the list under
    Lookup Sheet and Asset Sync now, read by arriving at Assets rather than
    by clicking a name that says how many are waiting. **090 put the row
    back**, as the one that opens a window: the count is the row's subtitle,
    a callable `show_section` asks each time Assets is opened, so what is
    waiting is still read by arriving at Assets, and the list is a pop-up
    over the console rather than a pane under the rows. A proposal nobody
    sees is still rule 6 stopping the delivery.

    The count is still counted off `_load_proposals`, narrowed to the ones
    nobody has answered - two spellings of "which proposals are pending" is
    what the cascade rule is about, and the second one is the copy that goes
    stale. The row's subtitle, `_proposals_caption`, reads the same
    `_load_proposals("pending")` the window's own line does, so the row and
    the window cannot disagree about the number.

    **Where the re-read lives is the thing this group is really holding.** It
    was the window's own `<Destroy>`, read back through
    `show_section("Assets")`, and never `wait_window` - a **nested event
    loop** started inside a console callback does not return until the window
    goes, which is a console that has stopped repainting and, here, a gate
    that hangs rather than fails. 077 had to take that out and it must not
    come back, the pop-up 090 wraps the list in included. The re-read is in
    the decision path itself, which is the only thing that moves the number.

    **Source**, for the reason every check about this console is: this is a
    Tk callback behind a password no harness can answer. What is asserted is
    that the row is on the section, that both counts read the one reader,
    that the list hands a pane back and the row's opener is what makes the
    window, and that answering a proposal re-reads it.
    """
    head("a proposal waiting is visible from the console (A10)")
    fns = {n.name: n for n in ast.walk(ast.parse(SRC_ALL))
           if isinstance(n, ast.FunctionDef)}

    if "run_gui" not in fns or "asset_proposals" not in fns:
        bad("run_gui or asset_proposals is not in server.py any more")
        return
    ok("the console still has an Asset Proposals list")
    eq("and the row has its one opener and one caption, and no older helper",
       [n for n in ("proposals_label", "open_proposals", "_proposals_caption")
        if n in fns], ["open_proposals", "_proposals_caption"])

    prop = ast.get_source_segment(SRC_ALL, fns["asset_proposals"]) or ""

    # The count, which was the entry's subtitle and is the pane's own line.
    eq("the count comes from the one reader of a pending proposal",
       "_load_proposals(" in prop, True)
    eq("  narrowed to the ones nobody has answered",
       '"pending"' in prop, True)
    eq("  and not from a query of its own",
       ("get_db(" in prop) or ("conn.execute" in prop), False)
    eq("  it says nothing is waiting rather than showing a bare 0",
       "nothing waiting" in prop, True)

    # A pane, not a window: nothing to open twice, nothing to close, and
    # nothing to wait on. Read off the tree rather than out of the text,
    # unlike the count above: this function's own prose says what `<Destroy>`
    # and `wait_window` used to do here and why neither may come back, and a
    # substring search cannot tell that sentence from the call it warns off.
    def calls(attr):
        return [n for n in ast.walk(fns["asset_proposals"])
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == attr]

    eq("the list opens no window of its own - the row's opener does",
       bool(calls("Toplevel")), False)
    eq("  so there is no close to hear about",
       [n for n in calls("bind") if n.args
        and isinstance(n.args[0], ast.Constant)
        and n.args[0].value == "<Destroy>"], [])
    eq("  and the console's loop is never blocked to read the count back",
       bool(calls("wait_window")), False)

    # The re-read, in the one place that moves the number.
    decide = next((n for n in ast.walk(fns["asset_proposals"])
                   if isinstance(n, ast.FunctionDef) and n.name == "decide"),
                  None)
    if decide is None:
        bad("asset_proposals has no decide() - the decision path is what the "
            "count re-read hangs off since 086")
        return
    eq("answering a proposal re-reads the count",
       "load_rows()" in (ast.get_source_segment(SRC_ALL, decide) or ""), True)
    eq("  and the pane offers that same reader to the section that shows it",
       "_ui_reload = load_rows" in prop, True)

    # The pane has to hand itself back, or the section has nothing to pack.
    returns = [n for n in ast.walk(fns["asset_proposals"])
               if isinstance(n, ast.Return) and isinstance(n.value, ast.Name)
               and n.value.id == "pane"]
    eq("Asset Proposals hands its pane back", bool(returns), True)

    # And the door: the admin password at the entry, every open (096), and
    # the same writer behind it.
    eq("the decision asks nothing itself - its entry asks at the door",
       ("_admin_password_ok(" in prop, console_door("Asset Proposals")),
       (False, "admin"))
    eq("  and still goes through the one writer of a decision",
       "_decide_proposal(" in prop, True)

    console = ast.get_source_segment(SRC_ALL, fns["run_gui"]) or ""
    eq("the console is still behind the admin password at the door",
       "_console_unlock(" in console, True)
    eq("  and the Assets section carries the row, counted by its caption",
       '("Asset Proposals", _proposals_caption' in console, True)
    cap = ast.get_source_segment(SRC_ALL, fns["_proposals_caption"]) or ""
    eq("  which counts off the same reader, narrowed the same way",
       '_load_proposals("pending")' in cap, True)
    opener = [n for n in ast.walk(fns["open_proposals"])
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)]
    eq("  and the row's opener is a window that does not block the loop",
       (any(n.func.attr == "Toplevel" for n in opener),
        any(n.func.attr == "wait_window" for n in opener)), (True, False))


def check_migration_011_adds_the_proposals_table():
    """011 creates it, `init_db` creates it too, and a downgrade keeps it.

    The both-ways pattern every table here has: a fresh database and an
    upgraded one are identical without anybody running `migrate`. `down()`
    keeps the table for the reason 004, 005 and 007 give - an older build never
    reads it, while dropping it would throw away every pending proposal, which
    is the list of assets somebody is holding and nobody has answered about.
    """
    head("migration 011")
    path = os.path.join(R, "migrations", "011_asset_proposals.py")
    if not os.path.exists(path):
        bad("migrations/011_asset_proposals.py is missing")
        return
    mod = {}
    exec(compile(io.open(path, encoding="utf-8").read(), path, "exec"), mod)

    db = stage_name("prop_", ".db")
    conn = sqlite3.connect(db)

    def has_table():
        return bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table'"
            " AND name='asset_proposals'").fetchone())

    def has_index():
        return bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index'"
            " AND name='idx_asset_proposals_status'").fetchone())

    eq("a pre-011 database has no proposals table", has_table(), False)
    mod["up"](conn)
    conn.commit()
    eq("up() creates the table and its index", (has_table(), has_index()),
       (True, True))
    conn.execute("INSERT INTO asset_proposals(asset_number, asset_type,"
                 " proposed_by, proposed_at, status)"
                 " VALUES ('MP-1','Laptop','Storekeeper','now','pending')")
    conn.commit()
    eq("the identifiers are NOCASE, so one case is one proposal",
       conn.execute("SELECT COUNT(*) FROM asset_proposals WHERE"
                    " asset_number = 'mp-1'").fetchone()[0], 1)
    mod["up"](conn)
    conn.commit()
    eq("  and running it twice changes nothing",
       conn.execute("SELECT COUNT(*) FROM asset_proposals").fetchone()[0], 1)

    mod["down"](conn)
    conn.commit()
    eq("down() drops the index", has_index(), False)
    eq("  and keeps the table, with every proposal still on it",
       (has_table(),
        conn.execute("SELECT COUNT(*) FROM asset_proposals").fetchone()[0]),
       (True, 1))
    conn.close()

    fresh_db()
    conn = sqlite3.connect(M.DB_PATH)
    eq("init_db creates it the other way, index and all",
       [bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?",
                          (n,)).fetchone())
        for n in ("asset_proposals", "idx_asset_proposals_status")],
       [True, True])
    conn.close()
    _blank_lookup()


def check_a_file_of_assets_is_mapped_before_it_is_imported():
    """The import's three stages, held at the two helpers rather than the window.

    The window is a Tk callback behind a file dialog no harness can answer, and
    what it does is ask - which column is which, and is this what you meant. The
    answers it asks about are `_map_import_columns` and `_validate_import_rows`,
    and those are where an import can be wrong without anybody noticing: a
    header guessed wrong writes the serial numbers into the Asset Number column
    of three hundred assets, and the first anybody hears of it is a scan that
    finds nothing.

    So: a guess is made under punctuation and case, a header that cannot be
    guessed is left **unmapped** rather than pointed at the nearest thing, a
    file that collides with itself is refused naming the row it collides with,
    a file that collides with the Lookup Sheet is refused naming the asset that
    holds the identifier, and a commit writes exactly the rows that passed and
    nothing else.
    """
    head("a file of assets is mapped before it is imported")

    g = M._map_import_columns(["Asset No.", "SERIAL NUMBER", " asset_type ",
                               "Model"])
    eq("a header is guessed under punctuation, case and spacing",
       [g[f] for f in M._IMPORT_FIELDS], [0, 1, 2, 3])
    eq("the column order in the file is not assumed",
       M._map_import_columns(["Model", "Type", "Serial", "Asset Tag"]),
       {"asset_number": 3, "serial_number": 2, "asset_type": 1,
        "asset_model": 0})

    g = M._map_import_columns(["ID", "Description", "Location"])
    eq("a header that cannot be guessed is left unmapped, not guessed anyway",
       [g[f] for f in M._IMPORT_FIELDS], [None, None, None, None])
    eq("  `No` is a row number at least as often as an Asset Number",
       M._map_import_columns(["No", "Type"])["asset_number"], None)
    g = M._map_import_columns(["Serial", "SN", "Type"])
    eq("a column is claimed by one field only", g["serial_number"], 0)
    eq("  and the field it did not claim stays where it was",
       [g["asset_number"], g["asset_model"]], [None, None])

    # ── the file itself ──────────────────────────────────────────────────────
    csv_path = os.path.join(STAGE, "import_check.csv")
    with io.open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n\r\n"                       # a blank row above it all
                "Asset No.,Serial,Type,Model\r\n"
                " 4001 , IS-1 , Laptop , T14 \r\n"
                "\r\n"                             # and a blank one inside it
                "4002,,Laptop,\r\n")
    headers, rows = M._import_file_rows(csv_path)
    eq("a csv is read, the header row found past the blank ones above it",
       headers, ["Asset No.", "Serial", "Type", "Model"])
    eq("  every cell arrives stripped, and an empty row is not a row",
       rows, [["4001", "IS-1", "Laptop", "T14"], ["4002", "", "Laptop", ""]])

    try:
        import openpyxl
    except ImportError:
        ok("openpyxl is not installed here - the .xlsx leg is skipped")
    else:
        xlsx_path = os.path.join(STAGE, "import_check.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        for r in (["Asset No.", "Serial", "Type", "Model"],
                  ["4001", "IS-1", "Laptop", "T14"],
                  ["4002", None, "Laptop", None]):
            ws.append(r)
        wb.save(xlsx_path)
        eq("an .xlsx reads back as the same headers and the same rows",
           M._import_file_rows(xlsx_path), (headers, rows))

    # ── what each row would become ───────────────────────────────────────────
    fresh_db()
    _stub_lookup([("6001", "RS-1", "Laptop", "T14")])
    mapping = M._map_import_columns(headers)
    verdicts = M._validate_import_rows(
        [["4001", "IS-1", "Laptop", "T14"],      # good
         ["6001", "IS-9", "Laptop", ""],         # the register holds it
         ["4009", "rs-1", "Laptop", ""],         # ...by its other identifier
         ["", "", "Laptop", ""],                  # rule 5's shape
         ["4004", "IS-4", "", ""],               # rule 2's
         ["4001", "IS-5", "Laptop", ""]],        # row 2 of this same file
        mapping)
    eq("the header is row 1, so the first row of data is row 2",
       [v["line"] for v in verdicts], [2, 3, 4, 5, 6, 7])
    eq("a row this sheet can take is refused nothing", verdicts[0]["error"], "")
    eq("  and says what it would become",
       [verdicts[0][f] for f in M._IMPORT_FIELDS],
       ["4001", "IS-1", "Laptop", "T14"])
    eq("an Asset Number the Lookup Sheet holds is refused naming the asset",
       ("already in the Lookup Sheet" in verdicts[1]["error"]
        and "6001" in verdicts[1]["error"]), True)
    eq("  and so is a Serial Number it holds, case not significant",
       ("already in the Lookup Sheet" in verdicts[2]["error"]
        and "6001" in verdicts[2]["error"]), True)
    eq("  in `_save_asset`'s own words, worded once",
       verdicts[1]["error"],
       M._IDENTIFIER_TAKEN % ("Asset Number", "6001", "6001", "Laptop"))
    eq("a row with neither identifier is refused (103)",
       "needs an Asset Number" in verdicts[3]["error"], True)
    eq("a row with no Asset Type is refused (rule 2)",
       verdicts[4]["error"], "An asset needs an Asset Type.")
    eq("a row colliding with an earlier row of the same file is refused",
       "on row 2 of this file" in verdicts[5]["error"], True)
    eq("  which is a different sentence from the register's, and says so",
       "already in the Lookup Sheet" in verdicts[5]["error"], False)
    eq("nothing was written by asking", len(M._load_assets()), 1)

    # A field this file does not carry is not invented: the rows still read,
    # with that column empty, which is what an unmapped optional field means.
    no_model = dict(mapping)
    no_model["asset_model"] = None
    eq("an unmapped field is empty rather than fatal",
       [v["asset_model"] for v in M._validate_import_rows(
           [["4001", "IS-1", "Laptop", "T14"]], no_model)], [""])

    # ── and only then, the write ─────────────────────────────────────────────
    n = M._import_assets(verdicts)
    eq("exactly the rows that passed are written", n, 1)
    eq("  the refused rows are not, and what was already there is untouched",
       sorted(a["asset_number"] for a in M._load_assets()),
       ["4001", "6001"])
    eq("  the one that was written carries every field it was read with",
       [(a["serial_number"], a["asset_type"], a["asset_model"])
        for a in M._load_assets() if a["asset_number"] == "4001"],
       [("IS-1", "Laptop", "T14")])
    conn = sqlite3.connect(M.DB_PATH)
    conn.row_factory = sqlite3.Row
    logged = conn.execute("SELECT detail FROM system_log WHERE event=?",
                          ("lookup.imported",)).fetchall()
    conn.close()
    eq("the import is one System Log entry, saying how many were refused",
       (len(logged), "1 asset(s) added" in logged[0]["detail"],
        "5 row(s) refused" in logged[0]["detail"]), (1, True, True))

    # This door **adds**; POST /lookup/upload replaces. That is the whole
    # difference between a file in this application's shape and one somebody
    # else wrote, and it is the half a second import would get wrong.
    M._import_assets(M._validate_import_rows(
        [["4007", "IS-7", "Screen", ""]], mapping))
    eq("a second import adds to the sheet rather than replacing it",
       sorted(a["asset_number"] for a in M._load_assets()),
       ["4001", "4007", "6001"])
    fresh_db()
    _blank_lookup()


def check_swapped_asset_and_serial_columns_warn_not_refuse():
    """#269: a likely-swapped mapping is a warning, never a refusal.

    `_check_import_mapping` only ever sees the header, so it cannot tell an
    Asset Number column from a Serial Number column beside it - both are free
    text. `_check_swapped_columns` looks at what the two mapped columns
    actually hold: when the Asset Number column's values match the
    register's Serial Numbers more than its Asset Numbers, and the Serial
    Number column's match the other way round, that is very likely the two
    columns swapped, and it says so - without refusing anything, because a
    register with nothing to compare against is silence, not evidence.
    """
    head("swapped Asset Number / Serial Number columns")
    fresh_db()
    _stub_lookup([("6001", "RS-1", "Laptop", ""),
                  ("6002", "RS-2", "Laptop", "")])
    mapping = {"asset_number": 0, "serial_number": 1, "asset_type": 2,
              "asset_model": None}

    straight = [["4001", "IS-1", "Laptop"], ["4002", "IS-2", "Laptop"]]
    eq("a mapping that matches nothing in the register warns of nothing",
       M._check_swapped_columns(straight, mapping), "")

    swapped = [["RS-1", "6001", "Laptop"], ["RS-2", "6002", "Laptop"]]
    warning = M._check_swapped_columns(swapped, mapping)
    eq("values that match the register the other way round are warned about",
       bool(warning), True)
    eq("  the warning names both mapped columns",
       ("Asset Number" in warning and "Serial Number" in warning), True)

    eq("with either column unmapped, there is nothing to compare",
       M._check_swapped_columns(swapped,
                                {"asset_number": None, "serial_number": 1,
                                 "asset_type": 2, "asset_model": None}), "")
    eq("with no rows, there is nothing to compare",
       M._check_swapped_columns([], mapping), "")

    # It never refuses: a warned mapping still validates and imports.
    verdicts = M._validate_import_rows(
        [["RS-1", "6009", "Laptop"]], mapping, M._load_assets())
    eq("a warned mapping still produces a verdict rather than refusing",
       len(verdicts), 1)
    fresh_db()
    _blank_lookup()


def check_an_imported_asset_type_folds_onto_the_sheets_spelling():
    """An Asset Type differing only by case is that type, not a new one.

    Both import doors ask before adding an Asset Type the sheet does not have,
    because it reaches every client's dropdown (rule 2) - and both asked that
    question against a case-folded comparison while writing the case they were
    handed. A vendor's delivery note in upper case therefore made `fresh`
    empty, asked nothing, and put LAPTOP into the sheet beside Laptop, which is
    exactly the case the question exists for: GET /asset_types then serves both
    and every client's dropdown carries two entries for one type.

    The comparison was the half that was right - `known_models` already narrows
    on a folded type, and rule 6 already corrects a Transaction's type to the
    sheet's canonical value rather than recording it as typed - so the write is
    what moved. It is folded in `_validate_import_rows` rather than in
    `_save_asset`, because the one writer is also what POST /lookup/upload goes
    through and that door **replaces** the sheet; and because this function is
    what the operator is shown before committing, so the Asset Type column now
    says what will actually be written.
    """
    head("an imported Asset Type folds onto the sheet's spelling")
    fresh_db()
    _blank_lookup()
    M._save_asset("6001", "RS-1", "Laptop", "T14")

    mapping = {"asset_number": 0, "serial_number": 1, "asset_type": 2,
               "asset_model": 3}
    v = M._validate_import_rows([["4001", "IS-1", "LAPTOP", ""],
                                 ["4002", "IS-2", "  laptop  ", ""],
                                 ["4003", "IS-3", "Docking Station", ""]],
                                mapping)
    eq("a type matching the sheet apart from case becomes the sheet's spelling",
       [r["asset_type"] for r in v[:2]], ["Laptop", "Laptop"])
    eq("and a type the sheet really does not have is carried through as typed",
       v[2]["asset_type"], "Docking Station")
    eq("nothing was written by asking", len(M._load_assets()), 1)

    M._import_assets(v)
    eq("the sheet gains one Asset Type, not three spellings of one",
       M._lookup_asset_types(), ["Docking Station", "Laptop"])
    eq("  and every client is offered that one list",
       M.app.test_client().get("/asset_types").get_json()["asset_types"],
       ["Docking Station", "Laptop"])

    # The window decides what to ask about from the same verdicts, so the
    # question is now asked for exactly the types that are new. Asserted
    # against the verdicts rather than the window, which is a Tk callback
    # behind a file dialog no harness can answer.
    known = {t.lower() for t in M._lookup_asset_types()}
    v2 = M._validate_import_rows([["4004", "IS-4", "LAPTOP", ""]], mapping)
    eq("a second file in another case asks about nothing",
       [r["asset_type"] for r in v2
        if r["asset_type"].lower() not in known], [])

    # First occurrence wins, `_load_assets` being ordered by id: a sheet that
    # already holds two spellings folds onto the older of them rather than onto
    # whichever sorted first, so an import does not silently move assets from
    # one of them to the other.
    M._save_asset("6002", "RS-2", "LAPTOP")
    v3 = M._validate_import_rows([["4005", "IS-5", "laptop", ""]], mapping)
    eq("a sheet holding two spellings folds onto the older row's",
       v3[0]["asset_type"], "Laptop")

    fresh_db()
    _blank_lookup()


def check_asset_models_serves_what_the_register_holds():
    """The models on the wire are the models the console offers (G2).

    `GET /asset_models` is the wire form of an answer this server already
    computed for itself: the Lookup Sheet window's Asset Model combobox has
    listed the models the sheet holds for the type currently picked since 026.
    Two spellings of one query is what rule 10 exists to prevent - a client
    offering a model list the console does not, or the other way round, is a
    sheet growing a fourth spelling of one laptop, which is the defect 026 was
    written for. So both halves are asserted: what the endpoint answers, and -
    as **source**, the window being a Tk callback and the absence of a second
    query being what is claimed - that `known_models` holds no query of its own.

    The two answers worth telling apart are an empty model and an unknown type.
    An empty model is not a model - `''` is what the sheet says where it is
    N/A - so it is never served; an unknown type is an empty **list** rather
    than a 400, a type nobody has recorded a model against being an ordinary
    state and the same answer the console gives.
    """
    head("GET /asset_models (G2)")
    fresh_db()
    _stub_lookup([("2001", "S-1", "Laptop", "ThinkPad T14"),
                  ("2002", "S-2", "Laptop", "EliteBook 840"),
                  ("2003", "S-3", "Laptop", "ThinkPad T14"),
                  ("2004", "S-4", "Screen", "U2419H"),
                  ("2005", "S-5", "Screen", "")])
    c = M.app.test_client()

    def models(qs=""):
        r = c.get("/asset_models" + qs)
        return r.status_code, (r.get_json() or {}).get("asset_models")

    eq("every model the register holds, sorted and each once",
       models(), (200, ["EliteBook 840", "ThinkPad T14", "U2419H"]))
    eq("  narrowed by type", models("?type=Laptop"),
       (200, ["EliteBook 840", "ThinkPad T14"]))
    eq("  a type matched without regard to case, 027's fold",
       models("?type=LAPTOP"), (200, ["EliteBook 840", "ThinkPad T14"]))
    eq("an empty model is not a model and is never served",
       models("?type=Screen"), (200, ["U2419H"]))
    eq("a type no model is recorded against is an empty list, not a 400",
       models("?type=Cisco Phone"), (200, []))
    eq("  and so is one the register has never heard of",
       models("?type=Nonsense"), (200, []))
    eq("no credential is asked for - it answers nothing GET /lookup does not",
       c.get("/asset_models").status_code, 200)

    # `_load_assets` caches nothing, so a row written now is in the next
    # answer. That is the property the console's combobox rests on too - it
    # re-reads on every repaint rather than holding a list built at open.
    M._save_asset("2006", "S-6", "Screen", "P2723DE")
    eq("a model is served the moment its row lands",
       models("?type=Screen"), (200, ["P2723DE", "U2419H"]))

    # Source: the window may not carry a second spelling of this query.
    tree = ast.parse(SRC_ALL)
    body = ""
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "known_models":
            body = _code(fn)
    if not body:
        bad("known_models is gone - the console offers no model list at all")
    elif "_asset_models(" in body and "SELECT" not in body.upper():
        ok("the Lookup Sheet window reads the same helper, not a query of"
           " its own")
    else:
        bad("known_models has a query of its own beside GET /asset_models")

    fresh_db()
    _blank_lookup()


def check_the_asset_form_picks_a_model_that_exists():
    """Asset Model is a picker, and the Lookup Sheet window is measured (026).

    Asset Type was already an editable combobox and Asset Model was a bare
    Entry, so the same machine was typed in freehand every time and the sheet
    ended up holding `ThinkPad T14`, `Thinkpad T14` and `T14` as three models of
    one laptop. It is the same widget now, listing the models this sheet already
    has **for the Asset Type currently picked** - the department's whole model
    list is noise in front of somebody adding a Screen - and re-read when that
    type changes.

    Editable, not readonly, for the reason the Type field is: a model nobody has
    bought before has to be typeable somewhere, and this window is where the
    sheet grows one. Unlike a Type it is not confirmed with a question - a Type
    reaches every client's dropdown and changes what rule 2 serves, a Model is
    filled into a Transaction that sent none and reaches nothing else - which is
    asserted by stubbing the question and requiring that it is never asked.

    This is also the first group to open the **Lookup Sheet window and its asset
    form at all**. Both are named in `CLAUDE.md`'s list of the dialogs held to
    their own children's size, and neither was reachable from the size group's
    openers - that group opens Database Location by its status chip, and the
    button through to this one is inside it - so they are measured here, by the
    rule that group states: a fixed axis must hold what its children asked for.

    Skipped rather than failed when Tk cannot open a display.
    """
    head("the asset form picks a model that exists")
    tk = tk_or_skip()
    if tk is None:
        return
    from tkinter import ttk

    fresh_db()
    _stub_lookup([("2001", "SN-1", "Laptop", "ThinkPad T14"),
                  ("2002", "SN-2", "Laptop", "Latitude 5540"),
                  ("2003", "SN-3", "Laptop", "ThinkPad T14"),
                  ("2004", "SN-4", "Screen", "Dell U2419H"),
                  ("2005", "SN-5", "UPS", "")])
    root = gui_root(tk)

    def tops():
        return {str(w) for w in widgets(root) if isinstance(w, tk.Toplevel)}

    def opened(before):
        new = [w for w in widgets(root)
               if isinstance(w, tk.Toplevel) and str(w) not in before]
        root.update_idletasks()
        root.update()
        return new[-1] if new else None

    def pills_of(w):
        return [p for x in widgets(w)
                for p in (getattr(x, "_ui_row").pills
                          if getattr(x, "_ui_row", None) is not None else [])]

    def press(w, key):
        hits = [p for p in pills_of(w) if key in str(p.full)]
        if not hits:
            bad("no control matching %r in %r" % (key, w.title()))
            return
        hits[0].command()
        root.update_idletasks()
        root.update()

    def measure(dlg, name):
        """The rule the size group states, for the windows it cannot open."""
        dlg.update_idletasks()
        gw, gh = dlg.resizable()
        w, h = dlg.winfo_width(), dlg.winfo_height()
        rw, rh = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        if gw and gh:
            ok("%s: %dx%d against its children's %dx%d - resizable on both "
               "axes, so the opening size is not judged" % (name, w, h, rw, rh))
            return
        short = [a for a, n, g in (("narrower", rw - w, gw),
                                   ("shorter", rh - h, gh)) if n > 0 and not g]
        if short:
            bad("%s: %dx%d is %s than its children's %dx%d"
                % (name, w, h, " and ".join(short), rw, rh))
        else:
            ok("%s: %dx%d holds its children's %dx%d" % (name, w, h, rw, rh))

    before = tops()
    M.manage_assets(root)
    win = opened(before)
    if win is None:
        bad("the Lookup Sheet window opened nothing")
        root.destroy()
        return
    eq("the Lookup Sheet window lists every asset in the table",
       len([k for x in widgets(win) if isinstance(x, ttk.Treeview)
            for k in x.get_children()]), 5)
    measure(win, "Lookup Sheet")

    # Every change here takes the admin password, asked at the door on every
    # open (096) - so the window has no password field of its own.
    pw = [e for e in widgets(win)
          if e.winfo_class() == "Entry" and str(e.cget("show"))]
    eq("the window asks for no password; its entry does, every open",
       (len(pw), console_door("Lookup Sheet")), (0, "admin"))

    before = tops()
    press(win, "Add Asset")
    dlg = opened(before)
    if dlg is None:
        bad("Add Asset opened no window")
        root.destroy()
        return
    measure(dlg, "Add Asset")

    boxes = [c for c in widgets(dlg) if isinstance(c, ttk.Combobox)]
    eq("the form offers two pickers, Asset Type and Asset Model",
       len(boxes), 2)
    at_cb, am_cb = boxes[0], boxes[1]
    eq("Asset Type lists the types the sheet has",
       sorted(at_cb.cget("values")), ["Laptop", "Screen", "UPS"])
    eq("Asset Model is a combobox and not an Entry",
       am_cb.winfo_class(), "TCombobox")
    eq("  editable, so a model nobody has bought yet can be typed",
       str(am_cb.cget("state")) != "readonly", True)
    eq("with no type picked it offers every model in the sheet, each once",
       sorted(am_cb.cget("values")),
       ["Dell U2419H", "Latitude 5540", "ThinkPad T14"])

    at_cb.set("Laptop")
    dlg.update_idletasks()
    eq("picking a type narrows it to that type's models",
       sorted(am_cb.cget("values")), ["Latitude 5540", "ThinkPad T14"])
    at_cb.set("Screen")
    dlg.update_idletasks()
    eq("  and changing the type again re-reads it",
       sorted(am_cb.cget("values")), ["Dell U2419H"])
    at_cb.set("UPS")
    dlg.update_idletasks()
    eq("  a type with no model yet offers nothing rather than everything",
       sorted(am_cb.cget("values")), [])

    # A model in no list is still saved - the field is editable and this window
    # is where the sheet grows one - and nothing is asked about it, unlike a
    # new Asset Type, which is why the question is stubbed rather than answered.
    import tkinter.messagebox as mb
    real_ask, asked = mb.askyesno, []
    mb.askyesno = lambda *a, **k: (asked.append(a), True)[1]
    try:
        entries = [e for e in widgets(dlg)
                   if e.winfo_class() == "Entry" and not str(e.cget("show"))]
        entries[0].insert(0, "2006")
        entries[1].insert(0, "S-2006")
        at_cb.set("Laptop")
        am_cb.set("EliteBook 840")
        dlg.update_idletasks()
        save = [b for b in widgets(dlg)
                if b.winfo_class() == "Button"
                and "Save" in str(b.cget("text"))]
        eq("the form has its Save control", len(save), 1)
        save[0].invoke()
        root.update_idletasks()
        root.update()
    finally:
        mb.askyesno = real_ask
    saved = {a["asset_number"]: a["asset_model"] for a in M._load_assets()}
    eq("a model that is in no list is saved as typed",
       saved.get("2006"), "EliteBook 840")
    eq("  and nothing was asked about it - a model reaches no dropdown", asked,
       [])
    root.destroy()
    fresh_db()
    _blank_lookup()


def check_an_identifier_names_one_asset():
    """Uniqueness is the store's rule, not one window's (025).

    It was computed in the Lookup Sheet window, over the rows that window
    happened to be showing, and `POST /lookup/upload` walked straight past it -
    `_load_lookup_table` then kept the last of two rows claiming one Asset
    Number and the earlier one was shadowed with nothing said. So the rule is
    in `_save_asset`, which every writer already goes through, and in two
    partial unique indexes underneath it.

    Partial because **an empty identifier is not an identifier**: an asset
    written before 103 may carry only a serial, and two of those are not a
    collision; since 103 no door writes one. Case-insensitive because
    `_load_lookup_table` has always keyed the sheet on the lowercased
    identifiers, so `SN-1` and `sn-1` were already one entry there and two rows
    in the table - the mismatch this closes.
    """
    head("an identifier names one asset")
    db = fresh_db()
    _blank_lookup()
    eq("init_db declares both identifiers NOCASE",
       _assets_sql(db).upper().count("COLLATE NOCASE"), 2)
    conn = sqlite3.connect(db)
    idx = sorted(r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
        " AND tbl_name='assets' AND sql IS NOT NULL"))
    partial = [r[0] for r in conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index'"
        " AND tbl_name='assets' AND sql IS NOT NULL")]
    conn.close()
    eq("  and creates both unique indexes",
       idx, ["idx_assets_number", "idx_assets_serial"])
    eq("  each over the rows that have that identifier",
       all("WHERE" in p and "<> ''" in p for p in partial), True)

    M._save_asset("2001", "SN-1", "Laptop")
    try:
        M._save_asset("2001", "SN-2", "Laptop")
        bad("a second asset took an Asset Number another already holds")
    except ValueError as ex:
        ok("two rows with one Asset Number are one collision")
        eq("  and the refusal names the asset in the way",
           "2001" in str(ex) and "Laptop" in str(ex), True)
    try:
        M._save_asset("2002", "sn-1", "Laptop")
        bad("a second asset took a Serial Number differing only in case")
    except ValueError as ex:
        eq("the Serial Number is held the same way",
           "Serial Number" in str(ex), True)
    eq("  and neither was written", len(M._load_assets()), 1)

    # Since 103 an asset carries both, so the one writer refuses an asset
    # with only one of the two before the partial indexes are reached.
    for an, sn, said in (("", "SN-9", "needs an Asset Number"),
                         ("2009", "", "needs a Serial Number"),
                         ("AB-9", "SN-9", "digits only")):
        try:
            M._save_asset(an, sn, "Screen")
            bad("the one writer took %r / %r" % (an, sn))
        except ValueError as ex:
            eq("the one writer refuses %r / %r, saying why" % (an, sn),
               said in str(ex), True)
    eq("  and wrote none of them", len(M._load_assets()), 1)

    # Correcting an asset is not a collision with itself.
    mine = {a["asset_number"]: a["id"] for a in M._load_assets()}
    M._save_asset("2001", "SN-1", "Laptop", "X1", asset_id=mine["2001"])
    eq("an asset does not collide with itself",
       [a["asset_model"] for a in M._load_assets()
        if a["id"] == mine["2001"]], ["X1"])

    # The upload door is the one that had no check at all.
    _admin()
    c = M.app.test_client()
    before = sorted(a["asset_number"] for a in M._load_assets())
    sheet = M._lookup_xlsx_bytes([("8001", "US-1", "Laptop", ""),
                                  ("8002", "US-2", "Laptop", ""),
                                  ("8003", "us-1", "Laptop", "")])
    r = c.post("/lookup/upload",
               json={"password": "admin",
                     "file_data": base64.b64encode(sheet).decode()})
    eq("the upload endpoint refuses a sheet that collides with itself",
       (r.status_code, r.get_json().get("code")), (400, "duplicate_identifier"))
    said = r.get_json().get("error", "")
    eq("  naming the row it was found at", "Asset 3 of 3" in said, True)
    eq("  and the identifier", "us-1" in said, True)
    eq("  and it is not called an invalid workbook",
       "Invalid Excel file" in said, False)
    eq("  the upload is all-or-nothing: nothing was written",
       sorted(a["asset_number"] for a in M._load_assets()), before)

    # 103: rows that are not assets are refused together, every one named,
    # before anything is deleted - not dropped by the reader, not the first.
    sheet = M._lookup_xlsx_bytes([("X-1", "US-1", "Laptop", ""),
                                  ("8002", "", "Laptop", ""),
                                  ("8003", "US-3", "Laptop", ""),
                                  ("", "US-4", "Laptop", "")])
    r = c.post("/lookup/upload",
               json={"password": "admin",
                     "file_data": base64.b64encode(sheet).decode()})
    got = r.get_json() or {}
    eq("a sheet with rows that are not assets is refused, naming each of them",
       (r.status_code, got.get("code"),
        [x["line"] for x in got.get("refusals", [])]),
       (400, "bad_rows", [1, 2, 4]))
    eq("  each with its reason",
       [("digits only" in x["error"], "Serial Number" in x["error"],
         "Asset Number." in x["error"]) for x in got.get("refusals", [])],
       [(True, False, False), (False, True, False), (False, False, True)])
    eq("  and nothing was replaced",
       sorted(a["asset_number"] for a in M._load_assets()), before)

    sheet = M._lookup_xlsx_bytes([("8001", "US-1", "Laptop", ""),
                                  ("8002", "US-2", "Laptop", "")])
    r = c.post("/lookup/upload",
               json={"password": "admin",
                     "file_data": base64.b64encode(sheet).decode()})
    eq("a sheet that does not collide replaces the Lookup Sheet",
       (r.status_code, r.get_json().get("assets_loaded")), (200, 2))
    _blank_lookup()


def check_migration_010_makes_an_identifier_unique():
    """up() rebuilds and indexes, refuses a collision, down() keeps every row.

    The same shape as 008 and for the same reason - a column's collation cannot
    be ALTERed - with one difference worth the check: which of two rows
    describing one asset is the real one is not a decision a migration gets to
    make, so it names the pairs and applies nothing.
    """
    head("migration 010")
    path = os.path.join(R, "migrations", "010_asset_identity.py")
    if not os.path.exists(path):
        bad("migrations/010_asset_identity.py is missing")
        return
    mod = {}
    exec(compile(io.open(path, encoding="utf-8").read(), path, "exec"), mod)

    db = _legacy_assets_db()
    eq("a pre-010 table has no collation",
       "COLLATE NOCASE" in _assets_sql(db).upper(), False)
    conn = sqlite3.connect(db)
    now = datetime.now().isoformat()
    for an, sn in (("MG-1", "MS-1"), ("MG-2", ""), ("", "MS-3")):
        conn.execute("INSERT INTO assets(asset_number, serial_number,"
                     " asset_type, created_at) VALUES (?,?,'Laptop',?)",
                     (an, sn, now))
    conn.commit()
    mod["up"](conn)
    conn.commit()
    eq("up() gives both identifiers NOCASE",
       _assets_sql(db).upper().count("COLLATE NOCASE"), 2)
    eq("  and keeps every row, the two half-identified ones included",
       conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 3)
    eq("  and the stored spelling is the one that was typed",
       conn.execute("SELECT asset_number FROM assets WHERE"
                    " asset_number='mg-1'").fetchone()[0], "MG-1")
    try:
        conn.execute("INSERT INTO assets(asset_number, serial_number,"
                     " asset_type, created_at) VALUES ('mg-1','','Laptop',?)",
                     (now,))
        bad("the unique index did not refuse a second MG-1")
    except sqlite3.IntegrityError:
        ok("  the index refuses a second row for that Asset Number")
    conn.rollback()

    mod["down"](conn)
    conn.commit()
    eq("down() puts the collation back",
       "COLLATE NOCASE" in _assets_sql(db).upper(), False)
    eq("  drops the indexes",
       conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index'"
                    " AND name LIKE 'idx_assets_%'").fetchone()[0], 0)
    eq("  and keeps every row",
       conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 3)
    conn.close()

    # A shared identifier where each row carries the other one: the value
    # names two assets and so names neither, and it is cleared from all but the
    # lowest id. Both assets are kept - this is the real Lookup Sheet's case,
    # 6 of its 3462 rows sharing a Serial Number with another row.
    share = _legacy_assets_db()
    conn = sqlite3.connect(share)
    for an in ("SH-1", "SH-2"):
        conn.execute("INSERT INTO assets(asset_number, serial_number,"
                     " asset_type, created_at) VALUES (?,'DUP','Laptop',?)",
                     (an, now))
    conn.commit()
    cleared = mod["up"](conn)
    conn.commit()
    eq("up() clears an identifier two assets share",
       cleared, [("serial_number", "DUP", 1)])
    eq("  keeping both assets",
       [tuple(r) for r in conn.execute(
           "SELECT asset_number, serial_number FROM assets ORDER BY id")],
       [("SH-1", "DUP"), ("SH-2", "")])
    eq("  and leaving the value naming exactly one of them",
       conn.execute("SELECT COUNT(*) FROM assets WHERE serial_number='dup'"
                    " COLLATE NOCASE").fetchone()[0], 1)
    conn.close()

    # The other kind, where clearing would leave a row with no identifier at
    # all: that row would stop being an asset, so nothing is applied.
    clash = _legacy_assets_db()
    conn = sqlite3.connect(clash)
    for an in ("CL-1", "cl-1"):
        conn.execute("INSERT INTO assets(asset_number, asset_type,"
                     " created_at) VALUES (?,'Laptop',?)", (an, now))
    conn.commit()
    try:
        mod["up"](conn)
        bad("up() applied over two assets claiming one Asset Number")
    except RuntimeError as ex:
        eq("up() refuses where clearing would leave a row unidentified",
           "CL-1" in str(ex), True)
        eq("  and writes nothing",
           conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 2)
        eq("  leaving both spellings as they were",
           sorted(r[0] for r in conn.execute(
               "SELECT asset_number FROM assets")), ["CL-1", "cl-1"])
        eq("  and the table as it found it",
           "COLLATE NOCASE" in _assets_sql(clash).upper(), False)
    conn.close()

    # init_db meets the same database and answers differently on purpose: it
    # runs on every boot, and a store that cannot record a movement today
    # because of a duplicate created months ago is the worse failure.
    M.DB_PATH = clash
    M.init_db()
    conn = sqlite3.connect(clash)
    said = conn.execute("SELECT detail FROM system_log WHERE"
                        " event='assets.duplicate_identifier'").fetchall()
    conn.close()
    eq("init_db starts over the same collision rather than refusing",
       len(said), 1)
    eq("  and says which identifier names two assets",
       "CL-1" in said[0][0], True)
    eq("  and leaves the rows exactly as found",
       "COLLATE NOCASE" in _assets_sql(clash).upper(), False)
    fresh_db()


def check_the_seed_survives_a_sheet_that_contradicts_itself():
    """A first boot over the real Lookup Sheet, which holds duplicate serials.

    6 of the shipped sheet's 3462 rows share a Serial Number with another row,
    each pair carrying two distinct Asset Numbers. A unique index over that is
    an `IntegrityError` on the very first `init_db()`, which is a server that
    cannot start - so the seed applies the same rule the table does: a value
    naming two assets names neither, it is cleared from all but the first, and
    both assets are kept and still identified. The System Log says which, since
    an Admin looking for an asset by a serial that has stopped answering needs
    to find that line.
    """
    head("the seed survives a sheet that contradicts itself")
    rows = [("AN-1", "DUP", "Laptop", ""),
            ("AN-2", "DUP", "Laptop", ""),
            ("AN-3", "dup", "Laptop", ""),
            ("AN-4", "OK-4", "Screen", "")]
    keep = io.open(M.LOOKUP_PATH, "rb").read()
    try:
        with io.open(M.LOOKUP_PATH, "wb") as f:
            f.write(M._lookup_xlsx_bytes(rows))
        db = fresh_db()
        got = [(a["asset_number"], a["serial_number"]) for a in M._load_assets()]
        eq("every asset in the sheet is seeded",
           got, [("AN-1", "DUP"), ("AN-2", ""), ("AN-3", ""), ("AN-4", "OK-4")])
        eq("  and the shared serial names exactly one of them",
           M.app.test_client().get("/lookup?q=dup").get_json()["asset_number"],
           "AN-1")
        conn = sqlite3.connect(db)
        said = conn.execute("SELECT detail FROM system_log WHERE"
                            " event='assets.ambiguous_identifier'").fetchall()
        conn.close()
        eq("the System Log says what was cleared", len(said), 1)
        eq("  naming the identifier", "DUP" in said[0][0], True)
        eq("  and it is not fatal - the server has a Lookup Sheet",
           len(M._lookup_asset_types()), 2)
    finally:
        with io.open(M.LOOKUP_PATH, "wb") as f:
            f.write(keep)
    fresh_db()
    _blank_lookup()


def check_adding_after_the_fact_obeys_the_lookup_sheet():
    """Rule 6 holds for the Admin's own entries, refusal and correction both.

    The Server GUI must not become the one door an asset absent from the sheet
    can come through - an asset genuinely missing is fixed by uploading a sheet
    that has it. The correction half matters as much: an Admin typing an asset
    number from a paper note is the caller most likely to get one of the two
    identifiers wrong.
    """
    head("adding after the fact obeys the lookup sheet")
    db = fresh_db()
    _stub_lookup([("2100", "SN-100", "Screen", "Dell U2419H"),
                  ("2200", "SN-200", "Laptop", "Latitude 5540")])
    back = (datetime.now() - timedelta(days=2)).replace(
        microsecond=0).isoformat()

    payload, status = M._create_transaction({
        "team_member": "Brian Dawson", "direction": "Out Store",
        "asset_number": "NOT-IN-SHEET"}, timestamp=back)
    eq("an unknown asset is refused", status, 400)
    eq("with the same code any other caller gets", payload.get("code"),
       "not_in_lookup")
    conn = sqlite3.connect(db)
    eq("and nothing was written",
       conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 0)
    conn.close()

    # Serial right, number missing, type wrong: all three come back corrected.
    payload, status = M._create_transaction({
        "team_member": "Brian Dawson", "direction": "In Store",
        "serial_number": "sn-100", "asset_type": "Laptop"}, timestamp=back)
    eq("a known asset is accepted", status, 201)
    row = txn(db, payload["id"])
    eq("the asset number is filled from the sheet", row["asset_number"],
       "2100")
    eq("the serial number is the sheet's spelling", row["serial_number"],
       "SN-100")
    eq("the type is corrected", row["asset_type"], "Screen")
    eq("the model is filled from the sheet", row["asset_model"],
       "Dell U2419H")
    eq("and the backdate survived all of that", row["timestamp"], back)

    # Filled, never overridden - a caller that sent a model is not corrected,
    # because that is not one of the three fields rule 6 says is corrected.
    # A different asset: the one above is still Pending, and the duplicate
    # guard is right to refuse a second Pending row for the same asset.
    payload, status = M._create_transaction({
        "team_member": "Carol Evans", "direction": "Out Store",
        "asset_number": "2200", "asset_model": "what the label says"},
        timestamp=back)
    eq("a second asset is accepted", status, 201)
    eq("a supplied model is left alone", txn(db, payload["id"])["asset_model"],
       "what the label says")


def check_a_backdated_add_confirms_an_auto_approve_engineer():
    """Auto-approve still applies, and confirmed_at is now, not the backdate.

    The two are different facts: the movement happened when the Admin says it
    did, the confirmation happened when the row was written. Storing the
    backdate in confirmed_at would say the engineer confirmed something days
    before anybody recorded it.
    """
    head("a backdated add for an auto-approve engineer")
    db = fresh_db()
    _blank_lookup()
    conn = sqlite3.connect(db)
    conn.execute("UPDATE team_members SET auto_approve=1 WHERE name=?",
                 ("Brian Dawson",))
    conn.commit()
    conn.close()
    back = (datetime.now() - timedelta(days=5)).replace(
        microsecond=0).isoformat()

    payload, status = M._create_transaction({
        "team_member": "Brian Dawson", "direction": "Out Store",
        "asset_number": "AA-1", "storekeeper": "Admin (Server GUI)"},
        timestamp=back)
    eq("it is created", status, 201)
    eq("and reported as auto-approved", payload.get("auto_approved"), True)
    row = txn(db, payload["id"])
    eq("it is Confirmed immediately", row["confirmed"], 1)
    eq("the movement is still backdated", row["timestamp"], back)
    if row["confirmed_at"][:10] == datetime.now().isoformat()[:10]:
        ok("but confirmed_at is today: %s" % row["confirmed_at"])
    else:
        bad("confirmed_at is %s - the confirmation happened now, not when the "
            "movement did" % row["confirmed_at"])


def check_the_add_dialog_is_shaped_right():
    """A source check: the dialog cannot be opened from here.

    What is worth pinning is everything the acceptance criteria put on it and
    nothing a behaviour check can reach - the admin password, the refusal of a
    future time, the Admin attribution, the absence of an INSERT of its own,
    and the field order rules 3 and 4 put on every form in this project.
    """
    head("the Add Transaction dialog")
    tree = ast.parse(SRC_ALL)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    if "add_transaction" not in fns:
        bad("add_transaction is gone - there is no way to add one")
        return
    seg = ast.get_source_segment(SRC_ALL, fns["add_transaction"])

    for needed, why in (
            ("timestamp=", "the dialog is the only caller that may backdate"),
            ("> datetime.now()", "a time in the future records nothing and "
                                 "would sit outside the 24h window"),
            ('"Admin (Server GUI)"', "the Admin must be the recorded "
                                     "originator")):
        if needed not in seg:
            bad("%s: %s" % (needed, why))
        else:
            ok("the dialog has %s" % needed)

    # Adding asks for the admin password at the door, every open (096), and
    # the form carries no field of its own.
    eq("Add Transaction asks at the door and not in the form",
       ("_admin_password_ok(" in seg, console_door("Add Transaction")),
       (False, "admin"))

    if "INSERT INTO" in seg:
        bad("the dialog inserts a row of its own - rule 6 would then hold at "
            "the endpoint and not here")
    else:
        ok("the dialog writes nothing itself")

    if "Asset Name" in seg:
        bad("Asset Name appears in the dialog - rule 3")
    else:
        ok("no Asset Name field, as per rule 3")

    order = [seg.find('"Asset Number"'), seg.find('"Serial Number"'),
             seg.find('"Engineer"')]
    if -1 in order:
        bad("the dialog is missing one of Asset Number / Serial Number / "
            "Engineer")
    elif order != sorted(order):
        bad("Asset No. and Serial No. are not the first fields - rule 4")
    else:
        ok("Asset No. and Serial No. come first, as per rule 4")

    # The way in, and the caption beside it. The filename stopped being fixed
    # when db_path landed, so a caption naming assets.db is now a claim the
    # server cannot keep.
    entries = {}
    console = next((n for n in ast.walk(ast.parse(SRC_ALL))
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "run_gui"), None)
    for node in ast.walk(console) if console else ():
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "SECTIONS" for t in node.targets):
            entries = {e.elts[0].value: ast.unparse(e.elts[3])
                       for sec in node.value.elts for e in sec.elts[1].elts}
    if entries.get("Add Transaction") != "add_transaction":
        bad("nothing opens the dialog")
    else:
        ok("the Transactions section opens the dialog")
    if "read from assets.db" in SRC_ALL:
        bad("the feed still says it reads assets.db, which db_path can move")
    else:
        ok("the feed caption no longer names a filename db_path can move")
