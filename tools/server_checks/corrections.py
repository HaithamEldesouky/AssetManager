r"""The Admin can correct a Pending Transaction.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import inspect
from datetime import datetime, timedelta

from server_checks.stage import (M, SRC_ALL, SRC_TXN_ALL, _admin,
                                 _blank_lookup, _code, _stub_lookup, add_txn,
                                 bad, eq, fresh_db, head, log_rows, ok, txn)



def check_a_pending_transaction_can_be_corrected():
    """The four fields the ticket names, and the row stays Pending.

    Before this there was no way to fix a typo at all: Cancel says the movement
    never happened and Delete leaves no trace it was recorded, and neither is
    what a wrong engineer name needs.
    """
    head("a Pending Transaction can be corrected")
    db = fresh_db()
    _blank_lookup()
    _admin()
    tid = add_txn(db, asset_number="MD-1", team_member="Brian Dawson",
                  direction="Out Store", notes="first go",
                  timestamp="2026-09-01T08:00:00")
    when = (datetime.now() - timedelta(days=1)).replace(
        microsecond=0).isoformat()

    payload, status = M._modify_transaction(tid, {
        "team_member": "Carol Evans", "direction": "In Store",
        "notes": "corrected", "timestamp": when})
    eq("the correction is accepted", status, 200)
    row = txn(db, tid)
    eq("the engineer is corrected", row["team_member"], "Carol Evans")
    eq("the direction is corrected", row["direction"], "In Store")
    eq("the notes are corrected", row["notes"], "corrected")
    eq("the time is corrected", row["timestamp"], when)
    eq("and it is still Pending",
       (row["confirmed"], row["rejected"], row["cancelled"]), (0, 0, 0))
    eq("confirmed_at was not touched", row["confirmed_at"], "")
    eq("the asset is untouched", row["asset_number"], "MD-1")
    eq("and so is the originator", row["storekeeper"], "Storekeeper User")

    # Any field not named keeps its value, the same convention POST /members
    # has - a caller correcting the direction must not blank the notes by
    # omission.
    payload, status = M._modify_transaction(tid, {"direction": "Out Store"})
    eq("a one-field correction is accepted", status, 200)
    row = txn(db, tid)
    eq("that field changed", row["direction"], "Out Store")
    eq("and the notes survived the omission", row["notes"], "corrected")
    eq("as did the time", row["timestamp"], when)


def check_a_correction_says_what_it_changed():
    """The `transaction.modified` entry carries the diff (#200).

    The entry named who corrected which Transaction and what the row read
    afterwards, which is the half the reader already has in front of them -
    the row is right there. What they cannot get anywhere else is what it read
    before, and that is the half a dispute turns on. So this drives a real
    correction and reads the entry back.

    Three properties, and each is one the diff would be useless without. Only
    changed fields, since a caller sends the whole form and an entry naming
    all seven every time is not a diff. Both sides of each, since a new value
    on its own says no more than the row does. And the truncation saying so:
    `notes` may be 500 characters where `_LOG_DETAIL_MAX` is 400, so a long
    note can fill the entry on its own, and a diff silently cut in half reads
    as a complete record of a smaller change.
    """
    head("a correction says what it changed (#200)")
    db = fresh_db()
    _blank_lookup()
    _admin()
    tid = add_txn(db, asset_number="DF-1", serial_number="SN-1",
                  team_member="Brian Dawson", direction="Out Store",
                  notes="first go")

    payload, status = M._modify_transaction(
        tid, {"serial_number": "SN-2", "direction": "In Store",
              "notes": "first go"})
    eq("the correction is accepted", status, 200)
    said = [r for r in log_rows(db) if r["event"] == "transaction.modified"]
    eq("it wrote one entry and not one per field", len(said), 1)
    detail = said[0]["detail"]
    eq("  naming the Transaction, so #195 and the detail popup still match it",
       detail.startswith("#%d " % tid), True)
    eq("  and both changed fields, each with both of its values",
       ('serial_number: "SN-1" -> "SN-2"' in detail
        and 'direction: "Out Store" -> "In Store"' in detail), True)
    eq("  and not the field that was sent with the value it already had",
       "notes" in detail, False)
    eq("  and not one of the four nobody touched",
       [k for k in ("asset_number", "asset_type", "team_member", "timestamp")
        if k in detail], [])
    eq("the actor is unchanged by any of this",
       said[0]["actor"], "Admin (Server GUI)")
    eq("  and so is the level, a correction still being worth reading",
       said[0]["level"], "warn")

    # A correction that changes nothing is still an act somebody performed, so
    # it is still an entry - saying that, rather than an empty diff that reads
    # as a lost one.
    payload, status = M._modify_transaction(tid, {"direction": "In Store"})
    eq("a correction that moved nothing is accepted", status, 200)
    said = [r for r in log_rows(db) if r["event"] == "transaction.modified"]
    eq("  and is still an entry", len(said), 2)
    eq("  saying so rather than carrying an empty diff",
       "no field changed" in said[1]["detail"], True)

    # The delegate's wording is what #74 put there and this must not move it.
    M._modify_transaction(tid, {"direction": "Out Store"},
                          actor='Delegate: Manage Transaction History '
                                'held by "Sam" (remote)')
    said = [r for r in log_rows(db) if r["event"] == "transaction.modified"]
    eq("a delegate's correction is still filed under the delegate",
       said[-1]["actor"],
       'Delegate: Manage Transaction History held by "Sam" (remote)')
    eq("  and carries the diff like any other",
       'direction: "In Store" -> "Out Store"' in said[-1]["detail"], True)


def check_a_long_diff_is_truncated_and_says_so():
    """An over-long diff drops whole fields and writes down how many (#200).

    `notes` is `_TXN_TEXT_MAX` (500) where `detail` is `_LOG_DETAIL_MAX` (400),
    so one long note fills the entry on its own. Two answers, and the group
    drives both: each value is cut to `_DIFF_VALUE_MAX` by itself, so the last
    field named keeps both of its values rather than the first field's note
    eating the budget and everything after it falling off the end of
    `_log_event`'s own cut; and where the fields still do not fit, they are
    dropped from the end and counted.

    Driven rather than read off the source, because what is asserted is the
    length of a string after two independent truncations - this one's and
    `_log_event`'s - and a source read cannot see either of them meet.
    """
    head("an over-long diff is truncated and says so (#200)")
    db = fresh_db()
    _blank_lookup()
    _admin()
    tid = add_txn(db, asset_number="TR-1", team_member="Brian Dawson",
                  direction="Out Store", notes="x" * 400)

    payload, status = M._modify_transaction(
        tid, {"notes": "y" * 400, "direction": "In Store"})
    eq("the correction is accepted", status, 200)
    detail = [r for r in log_rows(db)
              if r["event"] == "transaction.modified"][-1]["detail"]
    eq("the entry fits the column rather than being cut by the writer",
       len(detail) <= M._LOG_DETAIL_MAX, True)
    eq("  with each value cut on its own rather than the line cut at the end",
       ('"%s..."' % ("x" * M._DIFF_VALUE_MAX)) in detail, True)
    eq("  so the field named after the long one still carries both values",
       'direction: "Out Store" -> "In Store"' in detail, True)

    # And where the fields themselves do not fit, the count of what went is
    # what stops a partial diff reading as a complete one.
    tid2 = add_txn(db, asset_number="TR-2", serial_number="s" * 200,
                   team_member="Brian Dawson", direction="Out Store",
                   notes="a" * 200, timestamp="2026-09-01T08:00:00")
    payload, status = M._modify_transaction(
        tid2, {"asset_number": "TR-3", "serial_number": "t" * 200,
               "asset_type": "Desktop", "team_member": "Carol Evans",
               "direction": "In Store", "notes": "b" * 200,
               "timestamp": "2026-09-02T08:00:00"})
    eq("the seven-field correction is accepted", status, 200)
    detail = [r for r in log_rows(db)
              if r["event"] == "transaction.modified"][-1]["detail"]
    eq("the entry still fits the column",
       len(detail) <= M._LOG_DETAIL_MAX, True)
    eq("  and says how many fields it could not name",
       "more not shown" in detail, True)
    eq("  having named the first of them whole",
       'asset_number: "TR-2" -> "TR-3"' in detail, True)


def check_a_resolved_transaction_is_never_edited():
    """Confirmed, Rejected and Cancelled are all refused, each for its own
    reason.

    Confirmed is the one that matters. The Engineer's confirmation is the only
    evidence the verification step produces, and editing the row underneath it
    would destroy that evidence while leaving the row still claiming to be
    confirmed - so the refusal has to name the remedy, which is to Cancel it
    and record the movement again.
    """
    head("a resolved Transaction is never edited")
    db = fresh_db()
    _blank_lookup()
    _admin()

    conf = add_txn(db, asset_number="RS-1", confirmed=1,
                   confirmed_at=datetime.now().isoformat())
    payload, status = M._modify_transaction(
        conf, {"team_member": "Carol Evans"})
    eq("a Confirmed Transaction is refused", status, 409)
    eq("with the documented code", payload.get("code"), "confirmed")
    if "ancel" in payload.get("error", ""):
        ok("and the refusal names Cancel as the remedy")
    else:
        bad("the refusal does not point at Cancel: %s" % payload.get("error"))
    eq("nothing was written", txn(db, conf)["team_member"], "Brian Dawson")

    rej = add_txn(db, asset_number="RS-2", rejected=1,
                  rejection_reason="never had it")
    payload, status = M._modify_transaction(
        rej, {"team_member": "Carol Evans"})
    eq("a Rejected Transaction is refused", status, 409)
    eq("with the documented code", payload.get("code"), "rejected")
    eq("nothing was written", txn(db, rej)["team_member"], "Brian Dawson")

    can = add_txn(db, asset_number="RS-3", cancelled=1,
                  cancel_reason="mis-scan")
    payload, status = M._modify_transaction(
        can, {"team_member": "Carol Evans"})
    eq("a Cancelled Transaction is refused", status, 409)
    eq("with the documented code", payload.get("code"), "already_cancelled")
    eq("nothing was written", txn(db, can)["team_member"], "Brian Dawson")

    payload, status = M._modify_transaction(
        99999, {"team_member": "Carol Evans"})
    eq("an id that is not there is a 404", status, 404)
    eq("with the documented code", payload.get("code"), "not_found")


def check_correcting_takes_no_password_of_its_own():
    """The door is the caller, and there is exactly one caller.

    There is still no unauthenticated path, unlike cancelling - editing
    somebody else's record is not a mis-scan being undone as quickly as it was
    made. What changed is *where* that is enforced: this helper took a
    password while two credentials could open the window above it, and since
    ADR-0015 the window is behind `_console_unlock` and the helper takes none,
    which is the shape `_save_asset`, `_decide_proposal` and `_queue_command`
    already had.

    So the behaviour leg is that it no longer has a password parameter at all
    - a caller left passing one would be a TypeError at the moment somebody
    clicks Save Correction - and the source leg is which doors reach it.

    **There are two since R1** (ADR-0015): the console's dialog and
    `POST /transactions/modify`, which is the same door from somewhere else
    rather than a second one. It still takes no password either way - the
    endpoint has already answered through `_remote_authorise` and hands the
    actor down, exactly as the console hands down a literal - so the rule the
    signature carries is unchanged and what widened is the list below.
    """
    head("correcting takes no password of its own")
    db = fresh_db()
    _blank_lookup()
    _admin()
    tid = add_txn(db, asset_number="PW-1", team_member="Brian Dawson")

    names = inspect.signature(M._modify_transaction).parameters
    eq("the helper takes the id, the fields and who is asking",
       list(names), ["tid", "fields", "actor", "address"])
    try:
        # Built rather than written, so a sweep that strips a password kwarg
        # off every call in this file cannot quietly take it off the one call
        # that means to pass one.
        M._modify_transaction(tid, {"team_member": "Carol Evans"},
                              **{"pass" + "word": "admin"})
        bad("it still accepts a password - a second credential would then be "
            "checkable here, behind a door that has already answered")
    except TypeError:
        ok("and a call that passes one is a TypeError rather than a second "
           "gate")
    eq("nothing was written by the refused call",
       txn(db, tid)["team_member"], "Brian Dawson")

    # Two call sites, and each is a door that has already answered. The three
    # console names are nested one inside the other - do_modify is the Save in
    # modify_selected, which is opened from manage_records - so
    # enclosing-function matching answers three times for the one call; the
    # fourth is the endpoint. A fifth would be a way to correct a Transaction
    # from somewhere nobody proved either password.
    callers = sorted({fn.name for fn in ast.walk(ast.parse(SRC_ALL))
                      if isinstance(fn, ast.FunctionDef)
                      and "_modify_transaction(" in _code(fn)
                      and fn.name != "_modify_transaction"})
    eq("and the call sites are the console dialog and the R1 endpoint",
       callers, ["do_modify", "manage_records", "modify_selected",
                 "modify_transaction"])


def check_a_correction_is_validated_against_the_lookup_sheet():
    """Rule 6 applies to a changed identifier, and only to a changed one.

    A changed identifier is a new claim about which asset moved, so it goes
    through the same gate a creation does. Re-running the gate over identifiers
    nobody touched would refuse a correction whenever the sheet had been
    replaced since the row was created - punishing the admin for an edit they
    may not have made, and leaving a wrong Pending row to be Auto-Accepted 24
    hours later.
    """
    head("a correction is validated against the lookup sheet")
    db = fresh_db()
    _admin()
    _stub_lookup([("2100", "SN-100", "Screen", "Dell U2419H"),
                  ("2200", "SN-200", "Laptop", "Latitude 5540")])
    tid = add_txn(db, asset_number="2100", serial_number="SN-100",
                  asset_type="Screen", asset_model="Dell U2419H")

    payload, status = M._modify_transaction(
        tid, {"asset_number": "NOT-IN-SHEET", "serial_number": ""})
    eq("a changed identifier the sheet does not know is refused", status, 400)
    eq("with the same code any creation gives", payload.get("code"),
       "not_in_lookup")
    eq("and nothing was written", txn(db, tid)["asset_number"], "2100")

    # Serial alone, in the wrong case, with the type left wrong on purpose.
    payload, status = M._modify_transaction(
        tid, {"asset_number": "", "serial_number": "sn-200",
              "asset_type": "Laptop"})
    eq("a changed identifier the sheet knows is accepted", status, 200)
    row = txn(db, tid)
    eq("the asset number is filled from the sheet", row["asset_number"],
       "2200")
    eq("the serial is the sheet's spelling", row["serial_number"], "SN-200")
    eq("the type is the sheet's", row["asset_type"], "Laptop")
    eq("the model followed the asset", row["asset_model"], "Latitude 5540")

    # A second Pending row for the asset this correction points at.
    other = add_txn(db, asset_number="2100", serial_number="SN-100")
    payload, status = M._modify_transaction(
        tid, {"asset_number": "2100", "serial_number": "SN-100"})
    eq("pointing a correction at an asset already Pending is refused",
       status, 409)
    eq("with a code of its own", payload.get("code"), "duplicate_pending")
    if "#%d" % other in payload.get("error", ""):
        ok("and the refusal names the row in the way")
    else:
        bad("the refusal does not name the clashing row: %s"
            % payload.get("error"))

    # Grandfathered: the sheet no longer knows the asset, and correcting the
    # engineer still works because the identifiers did not change.
    _stub_lookup([("2999", "SN-999", "Laptop", "Latitude 5540")])
    payload, status = M._modify_transaction(
        tid, {"team_member": "Carol Evans"})
    eq("an untouched identifier is not re-litigated", status, 200)
    eq("and the correction landed", txn(db, tid)["team_member"],
       "Carol Evans")

    # An empty or unreadable sheet skips the check, matching creation: no sheet
    # is not the same as an unknown asset.
    _blank_lookup()
    payload, status = M._modify_transaction(
        tid, {"asset_number": "ANYTHING", "serial_number": ""})
    eq("with no sheet the check is skipped, as at creation", status, 200)
    eq("and the identifier is taken as given",
       txn(db, tid)["asset_number"], "ANYTHING")


def check_a_correction_refuses_nonsense():
    """The refusals that are about the fields themselves, not the row's state.

    Rule 5 is the one a correction can break in a way a creation cannot: the
    row already had an identifier, and blanking the field would leave a
    Transaction naming no asset at all.
    """
    head("a correction refuses nonsense")
    db = fresh_db()
    _blank_lookup()
    _admin()
    tid = add_txn(db, asset_number="NS-1", serial_number="",
                  team_member="Brian Dawson", direction="Out Store",
                  timestamp="2026-09-01T08:00:00")

    cases = (
        ("a time in the future",
         {"timestamp": (datetime.now() + timedelta(days=1)).isoformat()},
         400, "future"),
        ("an unparseable time", {"timestamp": "last tuesday"}, 400,
         "bad_time"),
        ("a direction that is neither", {"direction": "Sideways"}, 400,
         "bad_direction"),
        ("an empty engineer", {"team_member": ""}, 400, "bad_member"),
        ("blanking both identifiers",
         {"asset_number": "", "serial_number": ""}, 400, "no_identifier"),
        ("a field that is not correctable", {"confirmed": 1}, 400,
         "bad_field"),
        ("the originator, which is not correctable",
         {"storekeeper": "somebody else"}, 400, "bad_field"),
    )
    for label, fields, want_status, want_code in cases:
        payload, status = M._modify_transaction(tid, fields)
        eq("%s is refused" % label, status, want_status)
        eq("  with code", payload.get("code"), want_code)
    row = txn(db, tid)
    eq("the row is exactly as it was",
       (row["asset_number"], row["team_member"], row["direction"],
        row["timestamp"], row["confirmed"]),
       ("NS-1", "Brian Dawson", "Out Store", "2026-09-01T08:00:00", 0))


def check_the_modify_dialog_is_shaped_right():
    """A source check: the dialog cannot be opened from here.

    The parts worth pinning are the ones a behaviour check cannot reach - that
    it asks for the admin password, that it writes nothing itself, that it
    points a Confirmed row at Cancel rather than at nothing, and the field
    order rules 3 and 4 put on every form in this project.
    """
    head("the Modify Transaction dialog")
    tree = ast.parse(SRC_TXN_ALL)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    if "modify_selected" not in fns:
        bad("modify_selected is gone - there is no way to correct one")
        return
    seg = ast.get_source_segment(SRC_TXN_ALL, fns["modify_selected"])

    # The password field is gone from this form: the window it sits in is
    # behind _console_unlock, so a field here would be the admin password
    # asked for a second time inside a console that has already answered.
    seg_pw = ast.get_source_segment(SRC_TXN_ALL, fns["modify_selected"])
    if "_pw_caption(" in seg_pw or "_authorise(" in seg_pw:
        bad("the dialog still carries a password of its own, behind a door "
            "that has already been answered (ADR-0015)")
    else:
        ok("the dialog carries no password field - the door is the window")

    for needed, why in (
            ("_modify_transaction(", "the dialog must go through the one "
                                     "enforcement point"),
            ("Cancel it and record the movement again",
             "a Confirmed row must be pointed at its remedy")):
        if needed not in seg:
            bad("%s: %s" % (needed, why))
        else:
            ok("the dialog has %s" % needed)

    if "UPDATE transactions" in seg:
        bad("the dialog writes its own UPDATE - the Pending-only rule would "
            "then hold in the helper and not here")
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

    # The footer is an elastic row now, so the callback is an element of the
    # pill's spec rather than a `command=` keyword on a button.
    if "modify_selected)" not in SRC_ALL:
        bad("nothing opens the dialog")
    else:
        ok("the Manage Transaction History footer opens the dialog")

    # Nothing in here may confirm a row. Correcting the engineer to an
    # Auto-Approve one must not hand an admin a way to confirm a Transaction
    # nobody verified; the 24h Auto-Accept rule resolves such a row instead.
    seg2 = ast.get_source_segment(SRC_TXN_ALL, fns["_modify_transaction"])
    for banned in ("confirmed=1", "confirmed = 1", "auto_approve"):
        if banned in seg2:
            bad("_modify_transaction mentions %s - a correction must not "
                "confirm anything" % banned)
    ok("the helper cannot confirm a row")
