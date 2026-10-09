"""
Asset Manager - the Transactions register.

The four functions that read and write the `transactions` table: the one
writer of a row (`_create_transaction`), the withdrawal of one
(`_cancel_transaction`), the correction of one (`_modify_transaction`), and
what an Engineer has yet to answer (`_pending_rows`).

Lifted out of `server.py` by #216 unchanged - the Transactions third of the one
Register 039 (#210) named, and the second of the three to land. They were never
the routes' and never the window's: eleven routes in `server.py` call them,
`server_gui.py`'s Manage Records reaches three as `S.<name>` for its cancel and
modify controls and the Add Transaction dialog behind it, and
`tools/server-checks.py` calls all four directly rather than over HTTP. A
cluster two adapters and a gate already reach the same way is one a module can
name.

**Which asset a Transaction is about is the Assets register's rule, and is
asked for rather than restated here.** `_cancel_transaction`'s newest-per-asset
query builds both sides of its comparison with `_asset_key_sql`, imported from
`register_assets` below; `_create_transaction` and `_modify_transaction`
resolve the canonical Asset Number, Serial Number and type through
`_load_lookup_table` before either writes a row. That is rule 6, and it runs
through the `assets` table rather than this one - which is why 041 (#215) had
to land before this module could exist at all.

Headless-safe: nothing here draws, so `server.py` imports it at module level.

**It opens no connection of its own.** `get_db` is `server.py`'s, and comes
over through `bind()` at import the way `register_assets.py` takes its two and
`server_cert.py` takes its paths - `from server import get_db` would execute
the whole server a second time rather than reach the one running, because
`server.py` runs as `__main__` under `applaunch`'s `runpy.run_path`. Every
other name below comes the same way and for the same reason, the four caps and
column lists included: those have readers in `server.py` that are not
Transactions at all, so they stayed there and are handed over rather than
moved.
"""

from datetime import datetime

# The identity rule, from the register that owns it (#215). Called rather than
# re-derived: a copy of the expression here is Out Now and the per-Engineer
# counts disagreeing with a Cancel about which asset a row names, which is the
# failure `_asset_key_sql`'s own comment records.
from register_assets import _asset_key_sql

# Handed over by server.py's bind() below, before anything here is called.
# Named exactly as server.py names them, so the code moved in reads there and
# here as one thing.
get_db = None
_log_event = None
_load_lookup_table = None
_storekeeper_name = None
_storekeeper_actor = None
_admin_password_ok = None
_storekeeper_can_cancel = None
_within_auto_approve_cancel_window = None
_modify_detail = None
_TXN_TEXT_MAX = None
_TXN_NAME_MAX = None
MODIFIABLE = None
_MODIFY_COLS = None


def bind(*, get_db, log_event, load_lookup_table, storekeeper_name,
         storekeeper_actor, admin_password_ok, storekeeper_can_cancel,
         within_auto_approve_cancel_window, modify_detail, txn_text_max,
         txn_name_max, modifiable, modify_cols):
    """Give this module everything it reads out of server.py. Called once.

    Keyword-only and exhaustive, the same contract `register_assets.bind()` and
    `server_cert.bind()` carry: every name the moved code reads out of
    `server.py` is on this list, so what the two modules share is one signature
    to read rather than a search of the file. It is longer than the Assets
    register's because a Transaction is written against more of the server than
    an asset row is - the Lookup Sheet, the Storekeeper's name and switch, the
    admin password and the System Log all have a say in one.

    What is bound here is module state, so a process holding **two** server
    modules leaves this one pointing at whichever imported it last. A real
    install has one; `tools/server-checks.py` is the only thing that imports a
    second, and it gives each staged copy a `register_transactions` of its own.
    """
    # `global get_db` is a syntax error where `get_db` is also the parameter,
    # and the moved code calls it bare - so the module global is set the one
    # way left rather than the name being spelt differently on each side.
    globals()["get_db"] = get_db
    global _log_event, _load_lookup_table, _storekeeper_name
    global _storekeeper_actor, _admin_password_ok, _storekeeper_can_cancel
    global _within_auto_approve_cancel_window, _modify_detail
    global _TXN_TEXT_MAX, _TXN_NAME_MAX, MODIFIABLE, _MODIFY_COLS
    _log_event = log_event
    _load_lookup_table = load_lookup_table
    _storekeeper_name = storekeeper_name
    _storekeeper_actor = storekeeper_actor
    _admin_password_ok = admin_password_ok
    _storekeeper_can_cancel = storekeeper_can_cancel
    _within_auto_approve_cancel_window = within_auto_approve_cancel_window
    _modify_detail = modify_detail
    _TXN_TEXT_MAX = txn_text_max
    _TXN_NAME_MAX = txn_name_max
    MODIFIABLE = modifiable
    _MODIFY_COLS = modify_cols


def _create_transaction(data, timestamp=None, actor=None):
    """Create a Transaction. Returns (payload, http_status).

    The one door, same shape and same reason as _cancel_transaction. The Server
    GUI's Add Transaction calls this rather than reimplementing it, so the
    lookup-sheet rule (rule 6) cannot hold at the endpoint and quietly not in
    the window an admin uses - the Server GUI becoming the way an asset absent
    from the sheet gets in is the exact hole this is guarded against.

    `timestamp` is a parameter rather than a field of `data`, deliberately.
    POST /transactions is unauthenticated (see ADR-0002), so reading a
    timestamp out of the body would let anyone on the network write history at
    a date of their choosing. Only a caller that has already proved the admin
    password passes one, and the endpoint never does.

    confirmed_at is still now even for a backdated row: the movement happened
    then, the confirmation happens now, and they are different facts.

    `actor` is a parameter for the same reason `timestamp` is one: the caller
    states who it is rather than having it inferred from the body. The Server
    GUI records "Admin (Server GUI)" on the row and means it, so deriving the
    log label from that column would write "Admin (Server GUI) (Storekeeper)" -
    and sniffing the string for brackets to avoid it would be a rule nobody can
    see. Given none, the act is the Storekeeper's, which is what an
    unauthenticated POST /transactions is.
    """
    if not data.get('team_member') or not data.get('direction'):
        return {"error": "Missing required fields"}, 400
    if not data.get('serial_number') and not data.get('asset_number'):
        return {"error": "Provide at least Serial Number or Asset Number"}, 400

    asset_no  = (data.get('asset_number',  '') or '').strip()
    serial_no = (data.get('serial_number', '') or '').strip()

    # An asset the lookup sheet does not know is not accepted, and a pair where
    # only one identifier is right is corrected to the sheet's values. This check
    # lived only in the Storekeeper's submit handler, so every other caller - the
    # offline buffer flush, a future client, a curl - could insert an asset nobody
    # can identify. An empty or unreadable sheet skips the check, matching the
    # clients' own fallback: no sheet is not the same as an unknown asset.
    table = _load_lookup_table()
    if table:
        entry = table.get(asset_no.lower()) or table.get(serial_no.lower())
        if not entry:
            return {
                "error": "Asset not in the lookup sheet: %s"
                         % (asset_no or serial_no),
                "code": "not_in_lookup",
            }, 400
        asset_no  = entry.get("asset_number")  or asset_no
        serial_no = entry.get("serial_number") or serial_no
        if entry.get("asset_type"):
            data['asset_type'] = entry["asset_type"]
        # Filled from the sheet only when the caller sent none. The schema says
        # asset_model comes from the sheet's 4th column, and a caller that
        # cannot type it - the Server GUI, a curl - would otherwise store ''
        # where a Storekeeper's row has the model. Never an override: a caller
        # that sent one is not corrected, because that is not what rule 6 says
        # is corrected.
        if entry.get("asset_model") and not (data.get('asset_model') or '').strip():
            data['asset_model'] = entry["asset_model"]

    conn = get_db()

    # Block duplicate pending transactions for the same asset. A cancelled one
    # does not count: the whole point of cancelling a mis-scan is to be able to
    # record the right transaction immediately afterwards.
    conditions, params = [], []
    if asset_no:
        conditions.append("(asset_number=? AND asset_number != '')")
        params.append(asset_no)
    if serial_no:
        conditions.append("(serial_number=? AND serial_number != '')")
        params.append(serial_no)
    if conditions:
        existing = conn.execute(
            f"SELECT id FROM transactions WHERE ({' OR '.join(conditions)}) "
            f"AND confirmed=0 AND rejected=0 AND cancelled=0",
            params
        ).fetchone()
        if existing:
            conn.close()
            return {"error": "This asset already has a pending transaction. "
                             "Confirm or reject it first."}, 409

    # Auto-approve members have no Notifier — their transactions confirm
    # immediately. The row is found whatever case the caller typed, the column
    # being NOCASE, and the name is then written down in the Engineer's own
    # spelling rather than the caller's - the same correction rule 6 makes to
    # the two identifiers and the type, and for the same reason: this column is
    # read back by people and filtered on by clients that compare it as a
    # string. An Engineer who is not on the list keeps what was sent, there
    # being nothing to correct it against.
    auto_row = conn.execute(
        "SELECT name, auto_approve FROM team_members WHERE name=?",
        (data['team_member'],)
    ).fetchone()
    if auto_row:
        data['team_member'] = auto_row['name']
    auto_approve = bool(auto_row and auto_row['auto_approve'])
    now_iso = datetime.now().isoformat()
    stamp   = timestamp or now_iso
    # Resolved once: the column below and the System Log entry at the end are
    # the same fact, and a caller that sent no name must not end up recorded as
    # one storekeeper on the row and another in the log.
    keeper  = (data.get('storekeeper') or '').strip() or _storekeeper_name()

    cur  = conn.execute(
        '''INSERT INTO transactions
           (asset_type, serial_number, asset_number, asset_model,
            team_member, direction, timestamp, notes, storekeeper,
            confirmed, confirmed_at, auto_approved, origin)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (
            data.get('asset_type',   'Laptop'),
            serial_no,
            asset_no,
            (data.get('asset_model', '') or '').strip(),
            data['team_member'],
            data['direction'],
            stamp,
            str(data.get('notes') or '')[:_TXN_TEXT_MAX],
            keeper,
            1 if auto_approve else 0,
            now_iso if auto_approve else '',
            # Recorded rather than worked out later (#198). The flag it comes
            # from lives on the Engineer and an Admin may untick it an hour
            # from now, so asking `team_members` at cancel time would answer
            # about the Engineer as they are rather than about how this row
            # came to be Confirmed - and the direction that costs something is
            # the other one: a row an Engineer really confirmed would start
            # reading as auto-approved the moment somebody ticked the box, and
            # the window below would open over their confirmation.
            1 if auto_approve else 0,
            # Decided here, from what happened, and not from `data` (#282).
            "auto" if auto_approve else None,
        )
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    # The one writer of a Transaction is also where its System Log entry is
    # written, so the endpoint and the Server GUI's Add Transaction cannot
    # record the same act differently. A pointer, not a copy: the row itself is
    # in `transactions` and nothing here duplicates it.
    _log_event("transaction.created",
               "#%d  %s  %s  %s%s" % (new_id, data['team_member'],
                                      data['direction'],
                                      asset_no or serial_no,
                                      "  (auto-approved)" if auto_approve
                                      else ""),
               actor=actor or _storekeeper_actor(keeper))
    return {"id": new_id, "status": "auto_approved" if auto_approve else "created",
            "auto_approved": auto_approve}, 201


def _pending_rows(member):
    conn = get_db()
    rows = conn.execute(
        # COLLATE NOCASE for the reason GET /transactions gives, and this is
        # the query where it matters most: a Notifier whose configured name is
        # cased differently from the row polled for ever, was offered nothing,
        # and reported no error - an Engineer who stops being asked to confirm
        # anything, which is the failure that app exists to prevent.
        'SELECT * FROM transactions WHERE team_member=? COLLATE NOCASE '
        'AND confirmed=0 AND rejected=0 '
        'AND cancelled=0 ORDER BY timestamp',
        (member,)
    ).fetchall()
    conn.close()
    return rows


def _cancel_transaction(tid, reason, cancelled_by="", password=None,
                        authorised_as=None):
    """Cancel one Transaction. Returns (payload, http_status).

    Authorisation lives here, not at the endpoint, for the same reason the
    newest-per-asset rule does: the Server GUI calls this function directly, and
    a check written at the endpoint would hold for a curl and not for the window
    an admin actually uses.

    password=None means no admin password was offered, which is the ordinary
    Storekeeper path and is allowed for a Pending Transaction while the switch
    is on. A correct password is the admin path: it opens a Confirmed
    Transaction and ignores the switch. A wrong one is refused outright rather
    than falling back to the unauthenticated path - falling back would mean a
    typo silently downgrades an admin to a Storekeeper and produces a refusal
    that names the wrong reason.

    `authorised_as` is the other way in, and it is the endpoint saying a
    credential has **already** been proved and naming who every entry is to be
    attributed to (#169). It is how the **Manage Transaction History**
    capability password reaches this rule: that password is replayed rather
    than compared, so whether it may be accepted at all is a question about the
    transport, which only the endpoint can answer - where the admin password is
    a hash comparison this function can make anywhere and still does. It opens
    a Confirmed Transaction and overrides the switch exactly as the admin
    password does, and it is the one thing recorded: a `cancelled_by` sent
    beside it is ignored rather than allowed to dress a delegate's act under
    any name somebody typed. The two are mutually exclusive and passing both
    raises - a cancel is authorised once.

    Cancelled means the movement never physically happened - a mis-scan
    withdrawn. Rejected means the Engineer denies a movement recorded against
    them. The difference is who says so, and the two are never merged.

    The row survives, marked, carrying who cancelled it, when and why. Deleting
    it would leave no trace that anything was ever recorded or why it was
    withdrawn, which is exactly why /transactions/delete is not the answer here.

    One enforcement point on purpose: the endpoint and the Server GUI both come
    through this function, so the newest-per-asset rule cannot hold in one and
    quietly not in the other.
    """
    # Both capped here rather than at the UPDATE below, the way
    # POST /reject/<id> caps its own reason: `reason` is put in front of
    # _log_event a few lines on and `cancelled_by` decides the actor beside it,
    # so one truncation is what keeps the row and the System Log entry saying
    # the same thing. Truncated rather than refused for _TXN_TEXT_MAX's reason
    # - a cancel is a correction somebody is standing there making, and a long
    # reason must not be what refuses it. The blank check below is a different
    # rule and stays where it is: nothing said is not too much said.
    reason = (reason or "").strip()[:_TXN_TEXT_MAX]
    cancelled_by = (cancelled_by or "").strip()[:_TXN_NAME_MAX]
    if not reason:
        return {"error": "A reason is required to cancel.",
                "code": "reason_required"}, 400

    if authorised_as is not None and password is not None:
        raise ValueError("A cancel is authorised once, not twice.")

    admin = False
    if authorised_as is not None:
        admin = True
    elif password is not None:
        if not _admin_password_ok(password):
            return {"error": "Wrong admin password.",
                    "code": "bad_password"}, 401
        admin = True
    if not admin and not _storekeeper_can_cancel():
        return {"error": "Cancelling has been switched off for the storekeeper. "
                         "An admin can still cancel with the admin password.",
                "code": "cancel_disabled"}, 403

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM transactions WHERE id=?",
                           (tid,)).fetchone()
        if row is None:
            return {"error": "No such transaction.", "code": "not_found"}, 404
        if row["cancelled"]:
            return {"error": "This transaction is already cancelled.",
                    "code": "already_cancelled"}, 409
        if row["rejected"]:
            return {"error": "A rejected transaction cannot be cancelled - the "
                             "engineer has already answered it, and that answer "
                             "is the record.",
                    "code": "rejected"}, 409
        by_window = False
        if row["confirmed"] and not admin:
            # The one Confirmed row a caller with no password may retract
            # (#198): an auto-approved one, inside the window, because that
            # Transaction was Confirmed a millisecond after the scan by an
            # Engineer who has no Notifier and was never asked. Without this
            # the ordinary mis-scan against an Auto-Approve Engineer is slower
            # to undo than the scan that made it, which is the exact thing the
            # Storekeeper switch exists to prevent for every other Engineer.
            #
            # It is not a way past a confirmation: `auto_approved` is on the
            # row, written when the row was written, so a Transaction an
            # Engineer actually answered is refused here whatever the clock
            # says. And it is not a second door around the switch either - that
            # refusal is above this and still answers first.
            by_window = _within_auto_approve_cancel_window(row)
            if not by_window:
                return {"error": "This transaction is already confirmed. Cancelling "
                                 "a confirmed transaction needs the admin password.",
                        "code": "confirmed"}, 409

        # The same newest-per-asset rule Out Now runs on. Cancelling an older
        # Transaction would leave the history asserting a return that preceded
        # no departure. "Newest" ignores rows already cancelled, because a
        # cancelled Transaction never happened - so repeated cancels unwind the
        # history one row at a time, each needing its own reason.
        newest = conn.execute(
            """SELECT id FROM transactions
               WHERE cancelled = 0
                 AND (%s) = (%s)
               ORDER BY timestamp DESC, id DESC LIMIT 1"""
            % (_asset_key_sql(), _asset_key_sql("?", "?")),
            (row["asset_number"], row["asset_number"], row["serial_number"])
        ).fetchone()
        if newest and newest["id"] != row["id"]:
            return {"error": "Only the newest transaction for an asset can be "
                             "cancelled - cancel #%d first." % newest["id"],
                    "code": "not_newest", "newest_id": newest["id"]}, 409

        # Blank means the Storekeeper: it is the only client that reaches this
        # unauthenticated and it is a single-operator app, so the row's own
        # storekeeper is the truthful fallback. The Server GUI names itself. A
        # nameless admin is recorded as one rather than as the storekeeper, who
        # did not do it.
        who = (authorised_as or cancelled_by
               or ("Admin" if admin else (row["storekeeper"] or "")))
        # The column takes the name and the System Log takes the role with it -
        # the same split _create_transaction makes, and for the same reason: a
        # caller that named itself must not be dressed as the Storekeeper. The
        # two conditions are what separate them. `cancelled_by` means the
        # caller said who it was, which the Server GUI does with "Admin (Server
        # GUI)"; `admin` with no name means an Admin nobody named. What is left
        # is the unauthenticated path, and the Storekeeper is its only client -
        # the same reasoning the fallback above already rests on.
        # A credential that was proved at the endpoint names the actor
        # outright: `authorised_as` is what opened the door, and no `cancelled_by`
        # in the body may put another name in front of it.
        actor = (authorised_as if authorised_as is not None
                 else (who if (cancelled_by or admin)
                       else _storekeeper_actor(who)))
        conn.execute(
            "UPDATE transactions SET cancelled=1, cancelled_at=?, cancelled_by=?, "
            "cancel_reason=? WHERE id=?",
            (datetime.now().isoformat(), who, reason, tid))
        conn.commit()
    finally:
        conn.close()
    # Which of the three opened it (#198). A cancel with no password at all
    # against a row that is *Confirmed* is a different act from the ordinary
    # Pending one and from an Admin's, and the entry is the only place that
    # difference is recorded - the row itself ends up looking the same
    # whichever door was used.
    _log_event("transaction.cancelled",
               "#%d  %s%s" % (tid, reason,
                              "  (within the auto-approve cancel window)"
                              if by_window else ""),
               actor=actor, level="warn")
    return {"status": "cancelled", "id": tid, "cancelled_by": who}, 200


def _modify_transaction(tid, fields, actor="Admin (Server GUI)",
                        address=""):
    """Correct one Pending Transaction. Returns (payload, http_status).

    `actor` is who is asking, and it is a parameter rather than a literal
    since R1: this is reachable over the network now, and an entry naming
    `Admin (Server GUI)` for a correction made by a delegate from somewhere
    else is the one part of the record that cannot be reconstructed. It takes
    no password and never will (rule 7's shape) - the door has already
    answered, here as at the console.

    A Transaction recorded wrongly could not be corrected at all: the only
    tools were Cancel, which says the movement never happened, and Delete,
    which leaves no trace it was ever recorded. Neither is what a typo needs.

    Only while Pending. A **Confirmed** Transaction is never edited - the
    Engineer's confirmation is the only evidence the verification step
    produces, and editing the row underneath it would destroy that evidence
    while leaving the row still claiming to be confirmed. The remedy is Cancel
    and record it again, which keeps both facts. Rejected is the Engineer's own
    answer, and Cancelled says the movement never happened; correcting either
    would be arguing with somebody else's statement rather than fixing a typo.

    **The door is the caller, not this function.** There is deliberately no
    endpoint for a correction, and the one window that reaches it opens behind
    Server Administration, which proved the admin password once at the door
    (_console_unlock). So this took a password for as long as there were two
    credentials that could open it, and now takes none - the same shape
    _save_asset, _decide_proposal and _queue_command already have, where the
    window checks and the one writer enforces the rules about the row. There is
    still no unauthenticated path at all, unlike _cancel_transaction, where
    undoing a mis-scan has to be as quick as making one. Editing somebody
    else's record is not that.

    Any field not named keeps its current value, the same convention as
    POST /members, so a caller correcting the direction cannot blank the notes
    by omission.

    The row **stays Pending**: the Engineer is asked about the corrected
    version, which is the whole point of correcting it before they answer.
    Nothing here confirms a row, not even when the corrected Engineer is
    Auto-Approve - that would hand an admin a way to confirm a Transaction
    nobody verified. Such a row is Confirmed by the 24h Auto-Accept job
    instead, one day later and by the rule that applies to everybody.
    """
    unknown = sorted(k for k in fields if k not in MODIFIABLE)
    if unknown:
        return {"error": "Not a correctable field: %s" % ", ".join(unknown),
                "code": "bad_field"}, 400

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM transactions WHERE id=?",
                           (tid,)).fetchone()
        if row is None:
            return {"error": "No such transaction.", "code": "not_found"}, 404
        if row["cancelled"]:
            return {"error": "A cancelled transaction records a movement that "
                             "never happened - there is nothing in it to "
                             "correct. Record the real movement instead.",
                    "code": "already_cancelled"}, 409
        if row["rejected"]:
            return {"error": "A rejected transaction cannot be edited - the "
                             "engineer has already answered it, and that answer "
                             "is the record.",
                    "code": "rejected"}, 409
        if row["confirmed"]:
            return {"error": "This transaction is already confirmed and cannot "
                             "be edited - the engineer's confirmation is the "
                             "evidence, and editing the record underneath it "
                             "would destroy it. Cancel it and record the "
                             "movement again.",
                    "code": "confirmed"}, 409

        new = {}
        for k in _MODIFY_COLS:
            v = fields.get(k, row[k]) if k in MODIFIABLE else row[k]
            new[k] = v.strip() if isinstance(v, str) else v

        if new["direction"] not in ("Out Store", "In Store"):
            return {"error": "Direction must be Out Store or In Store.",
                    "code": "bad_direction"}, 400
        if not new["team_member"]:
            return {"error": "An engineer is required.",
                    "code": "bad_member"}, 400
        # Rule 5, which a correction can break in a way a creation cannot: the
        # row had one, and blanking the field would leave a Transaction naming
        # no asset at all.
        if not new["asset_number"] and not new["serial_number"]:
            return {"error": "Provide at least Serial Number or Asset Number",
                    "code": "no_identifier"}, 400
        try:
            when = datetime.fromisoformat(str(new["timestamp"]))
        except (TypeError, ValueError):
            return {"error": "The time must be ISO format, e.g. "
                             "2026-01-31T14:05:00.", "code": "bad_time"}, 400
        if when > datetime.now():
            return {"error": "That time is in the future. A transaction records "
                             "a movement that has already happened.",
                    "code": "future"}, 400
        new["timestamp"] = when.isoformat()

        # Rule 6, but only when the identifiers actually change. Re-running it
        # over identifiers nobody touched would refuse a correction whenever the
        # sheet had been replaced since the row was created - punishing the
        # admin for an edit they may not have made, and leaving a wrong Pending
        # row to be Auto-Accepted in 24 hours. A changed identifier is a new
        # claim about which asset moved, and goes through the same gate any
        # creation does.
        if (new["asset_number"], new["serial_number"]) != (
                row["asset_number"], row["serial_number"]):
            table = _load_lookup_table()
            if table:
                entry = (table.get(new["asset_number"].lower())
                         or table.get(new["serial_number"].lower()))
                if not entry:
                    return {"error": "Asset not in the lookup sheet: %s"
                                     % (new["asset_number"]
                                        or new["serial_number"]),
                            "code": "not_in_lookup"}, 400
                new["asset_number"]  = (entry.get("asset_number")
                                        or new["asset_number"])
                new["serial_number"] = (entry.get("serial_number")
                                        or new["serial_number"])
                if entry.get("asset_type"):
                    new["asset_type"] = entry["asset_type"]
                if entry.get("asset_model"):
                    new["asset_model"] = entry["asset_model"]

            # The same guard creation has, minus this row itself: pointing a
            # correction at an asset that already has a Pending Transaction
            # would leave two open rows for one asset, which is the state that
            # guard exists to prevent.
            conditions, params = [], []
            if new["asset_number"]:
                conditions.append("(asset_number=? AND asset_number != '')")
                params.append(new["asset_number"])
            if new["serial_number"]:
                conditions.append("(serial_number=? AND serial_number != '')")
                params.append(new["serial_number"])
            clash = conn.execute(
                "SELECT id FROM transactions WHERE (%s) AND id != ? "
                "AND confirmed=0 AND rejected=0 AND cancelled=0"
                % " OR ".join(conditions), params + [tid]).fetchone()
            if clash:
                return {"error": "That asset already has a pending transaction "
                                 "(#%d). Confirm, reject or cancel it first."
                                 % clash["id"],
                        "code": "duplicate_pending"}, 409

        conn.execute(
            "UPDATE transactions SET asset_number=?, serial_number=?, "
            "asset_type=?, asset_model=?, team_member=?, direction=?, "
            "notes=?, timestamp=? WHERE id=?",
            (new["asset_number"], new["serial_number"], new["asset_type"],
             new["asset_model"], new["team_member"], new["direction"],
             new["notes"], new["timestamp"], tid))
        conn.commit()
    finally:
        conn.close()
    # What changed rather than what the row now reads (#200): the row itself is
    # in front of whoever is reading this, and what they cannot get anywhere
    # else is what it read before. No credential is in `_MODIFY_COLS`, so this
    # keeps `_log_event`'s standing rule that no call names a password.
    #
    # `_modify_detail` now hands back the changes beside the line it always
    # printed (#071), so `data` and `detail` describe the same diff rather
    # than a second copy of the fields that moved being worked out here too.
    # Empty where nothing changed, so a "no field changed" entry gets no
    # `data` and `_log_diff` falls through to `detail` for it exactly as it
    # already does for every other event with nothing to read structurally.
    detail, changes, dropped = _modify_detail(tid, row, new)
    _log_event("transaction.modified", detail,
               actor=actor, level="warn", address=address,
               data={"changes": changes, "dropped": dropped}
                    if changes else None)
    return {"status": "modified", "id": tid,
            "fields": {k: new[k] for k in _MODIFY_COLS}}, 200
