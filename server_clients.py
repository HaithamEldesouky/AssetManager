"""
Asset Manager - the registry of installations.

What every Client machine says about itself and what may be said back to it:
the check-in that records one installation (`_record_checkin`), the command
vocabulary and the queue behind it (`COMMANDS`, `COMMAND_LABELS`,
`_command_status`, `_queue_command`, `_command_rows`), the registry as the
console reads it (`_client_rows`), and the stale sweep that clears
installations nobody has heard from (`_parse_age_threshold`,
`_format_age_threshold`, `_stale_clients`, `_clear_stale_clients`), and the
hourly job that runs the same sweep on its own (`_client_sweep_loop`, #268).

Lifted out of `server.py` by #226 unchanged - the third of the six clusters
046 (#220) named and left in it, behind `server_mail.py` and
`server_sync.py`. Not tidiness: `server_gui.py`'s Connected Clients window
calls most of it as `S.<name>`, `server_cert.py` reaches four of these
names through its own `bind()` - the one documented cross-cluster reader in
this file - and `tools/server-checks.py` drives the queue, the status and
the sweep directly rather than over HTTP, so the cluster already had two
adapters and a gate reaching it the same way before there was a module to
name it.

**The five `/clients*` routes are not here.** This is the one cluster of
046's six whose routes sat inside its own banner rather than down in the
Routes section, and #226's judgement was to split the banner where the
first `@app.route` starts: `POST /clients/checkin`, `GET /clients`, `POST
/clients/command`, `POST /clients/push_cert` and `POST /clients/clear` stay
in `server.py` and call in here. That is the shape 041-043 took and the
shape the other five tickets in this chain take - a module of what the
routes call, not of the routes - and it is what leaves `@app`, `@door`,
every `DOOR_*` constant and `jsonify` out of this file entirely.

Headless-safe: nothing here draws, so `server.py` imports it at module
level.

**It opens no database of its own.** `get_db`, `_log_event`, `APP_VERSION`,
`_client_package`, `_since_ts` and the two Engineer readers are all
`server.py`'s and come over through `bind()`, handed rather than imported
back for the reason `server_cert.py`'s docstring gives - `server.py` runs
as `__main__` under `applaunch`'s `runpy.run_path`, so `from server import
get_db` would execute the whole server a second time rather than reach the
one running.

`_member_row` and `_member_row_by_id` are `register_engineers.py`'s and are
bound rather than imported from it, the way `server_sync.py` takes
`_load_assets` and `_save_asset`: the check-in resolves an Engineer against
whichever register the `server.py` that bound this module is holding, and a
direct import would reach whichever copy of that register was imported
last.

Nothing here is re-pointed at run time, so no name on the list is handed
over as a callable the way `server_sync.py` takes `db_path`: `DB_PATH` is
never read here - `get_db()` resolves it at call time inside `server.py` -
and neither `ADMIN_CFG` nor `_load_admin_cfg`, the other two names
`tools/server-checks.py` moves between check groups, is on this list.
"""

import time
from datetime import datetime, timedelta

# Handed over by server.py's bind() below, before anything here is called.
# Named exactly as server.py names them, so the code moved in reads there
# and here as one thing.
APP_VERSION = None
_client_package = None
_load_server_cfg = None
_log_event = None
_member_row = None
_member_row_by_id = None
_since_ts = None
get_db = None


def bind(*, app_version, client_package, get_db, load_server_cfg, log_event,
         member_row, member_row_by_id, since_ts):
    """Give this module everything it reads out of server.py. Called once.

    Keyword-only and exhaustive, the same contract `server_cert.bind()`,
    the three registers', `server_mail.bind()`'s and `server_sync.bind()`'s
    carry: every name the moved code reads out of `server.py` is on this
    list, built with a `symtable` sweep over the moved block rather than by
    hand, because 036's own note found fourteen names a hand-written list
    had missed. `datetime` and `timedelta` are the two the sweep found that
    are not here - they are stdlib and this module imports them itself.

    Called from `server.py` after `_since_ts`, which is the last of the
    eight to be defined and sits a long way down that file beside the other
    readers the console draws with. `_load_server_cfg` is #268's addition -
    `_client_sweep_loop` re-reads it every tick rather than capturing a
    threshold at start-up, `_sync_loop`'s rule (032). Later than the other
    five `bind()`
    calls for that one reason and no other: a name handed over before it
    exists is this pattern's one real failure mode, and nothing here runs
    before a request, a window or a background tick reaches it - including
    `server_cert.bind()` above, which is handed four of this module's
    function objects rather than calling them.

    What is bound here is module state, so a process holding **two** server
    modules leaves this one pointing at whichever imported it last. A real
    install has one; `tools/server-checks.py` is the only thing that
    imports a second, and it gives each staged copy a `server_clients` of
    its own.
    """
    global APP_VERSION, _client_package, _load_server_cfg, _log_event
    global _member_row, _member_row_by_id, _since_ts
    APP_VERSION = app_version
    _client_package = client_package
    _load_server_cfg = load_server_cfg
    _log_event = log_event
    _member_row = member_row
    _member_row_by_id = member_row_by_id
    _since_ts = since_ts
    # `global get_db` is a syntax error where `get_db` is also the
    # parameter, and the moved code calls it bare - so the module global is
    # set the one way left, exactly as `register_assets.bind()` sets it.
    globals()["get_db"] = get_db


# ─── Clients (the registry of installations) ──────────────────────────────────

# What a Client says about itself. Capped in length because this endpoint is
# unauthenticated (ADR-0002, ADR-0005) and every one of these is a short label -
# a hostname, an account name, a version string. Without the cap a caller on the
# network could put a megabyte in each.
#
# `cert_fingerprint` is the certificate the Client says it trusts, and it is a
# claim like every other field here rather than something this server measured:
# what is worth knowing is what that installation would present its pinned copy
# against, and only that installation can say.
#
# `reported_address` is the address the Client says it has, beside the
# `address` this server saw and never in place of it: behind a NAT or VPN
# gateway the peer is the gateway for every Client, and only the machine knows
# its own. Displayed, and trusted for nothing.
_CHECKIN_FIELDS = ("hostname", "os_user", "app", "version", "member",
                   "cert_fingerprint", "reported_address")
_CHECKIN_MAX = 120
# Where the Engineer sits in the tuple above, named rather than counted from
# either end: the resolution below rewrites that one value, and a field added
# after it moved what `vals[-1]` meant without changing a line of this file.
_CHECKIN_MEMBER_AT = _CHECKIN_FIELDS.index("member")


def _record_checkin(data, address):
    """Record one Client check-in. Returns (payload, status).

    Keyed on the Client's own `client_id`, an identifier it generates once and
    keeps in its configuration, so a machine that was renamed or picked up a new
    DHCP lease updates its row instead of adding a second one. Hostname and
    address are recorded as facts about the installation rather than as its
    identity, because both of them move. A reinstall that clears the
    configuration appears as a new row, because it is a new installation.

    Every field is overwritten, not merged - unlike POST /members, where an
    omitted field keeps its value because the caller is an admin editing one
    thing. A check-in is the Client's whole statement about itself, and a blank
    is meaningful: the Storekeeper has no configured Engineer, and a Notifier
    that has just been reset to nobody must stop claiming the last one.

    `address` is passed in rather than read from the request, so the Server GUI
    and the checker can record a check-in without a request context - the same
    shape as `_create_transaction` and `_cancel_transaction`.
    """
    cid = str(data.get("client_id") or "").strip()
    if not cid:
        return {"error": "client_id is required",
                "code": "no_client_id"}, 400
    if len(cid) > _CHECKIN_MAX:
        return {"error": "client_id is too long (max %d characters)"
                         % _CHECKIN_MAX,
                "code": "bad_client_id"}, 400
    vals = [str(data.get(f) or "").strip()[:_CHECKIN_MAX]
            for f in _CHECKIN_FIELDS]
    # Which Engineer this installation is configured as, resolved to the row
    # rather than taken at the caller's word - and answered with, which is the
    # half that matters. A laptop holds its Engineer's name in `config.json`
    # and that name is the one it was installed with: after a rename it names
    # nobody, `GET /pending/<name>` has nothing for it, and that is an Engineer
    # who stops being asked to confirm anything. This is where it finds out.
    #
    # By **id first** and by name second, never the other way round, since the
    # name is the thing that went stale. An id naming no row falls back to the
    # name, so an install carrying an id from a database that has since been
    # restored from a backup is not stranded by the id either. A Client that
    # has never learnt one - every Client built before this, and the
    # Storekeeper, which is configured as no Engineer at all - sends none and
    # is answered exactly as it was.
    mrow = None
    mid = str(data.get("member_id") or "").strip()
    if mid.isdigit():
        mrow = _member_row_by_id(int(mid))
    if mrow is None and vals[_CHECKIN_MEMBER_AT]:
        mrow = _member_row(vals[_CHECKIN_MEMBER_AT])
    if mrow is not None and vals[_CHECKIN_MEMBER_AT]:
        # An id that names a **different** Engineer who exists, beside a name
        # that also names one, is not a rename: a renamed-away name names
        # nobody, which is the whole reason the id is asked for. What it is
        # instead is an id from some other database - one restored from a
        # backup taken before these were handed out - and following it would
        # silently re-point this Notifier at somebody else, which is the one
        # thing worse than it going deaf. The name wins there.
        by_name = _member_row(vals[_CHECKIN_MEMBER_AT])
        if by_name is not None and by_name["id"] != mrow["id"]:
            mrow = by_name
    if mrow is not None:
        # The row's own spelling, so `clients.member` and the Engineer list
        # cannot read as two different people in the Server GUI.
        vals[_CHECKIN_MEMBER_AT] = str(mrow["name"])[:_CHECKIN_MAX]
    now = datetime.now().isoformat()
    conn = get_db()
    row = conn.execute("SELECT first_seen FROM clients WHERE client_id=?",
                       (cid,)).fetchone()
    first = (row["first_seen"] or now) if row else now
    conn.execute("""INSERT OR REPLACE INTO clients
                    (client_id, hostname, os_user, app, version, member,
                     cert_fingerprint, reported_address, address, first_seen,
                     last_seen)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                 tuple([cid] + vals + [str(address or ""), first, now]))
    # Whatever is queued for this Client and neither collected nor expired,
    # handed back in this response and marked collected in the same commit.
    #
    # At most once, deliberately. There is no channel for a Client to say it
    # obeyed, so a command left queued until an acknowledgement arrived would
    # be handed out again on every check-in - and a laptop that crashed
    # mid-logoff would be logged off for ever, with the Admin unable to stop
    # it. A command that was collected and not obeyed shows as collected, which
    # is a thing the Admin can see and act on; one handed out for ever is not.
    due = conn.execute(
        "SELECT id, command, issued_at FROM client_commands"
        " WHERE client_id=? AND collected_at='' AND expires_at > ?"
        " ORDER BY id", (cid, now)).fetchall()
    if due:
        conn.executemany(
            "UPDATE client_commands SET collected_at=? WHERE id=?",
            [(now, r["id"]) for r in due])
    conn.commit()
    conn.close()
    if due:
        # Handed over exactly once, so this line is the only record of the
        # moment it left. The check-in itself is not logged: it is already a row
        # in `clients`, and one per Client every fifteen seconds would bury
        # everything else in here.
        _log_event("client.command_collected",
                   ", ".join("#%d %s" % (r["id"], r["command"]) for r in due),
                   client_id=cid, address=str(address or ""))
    return {"status": "ok",
            "client_id": cid,
            "known_since": first,
            "last_seen": now,
            # Additive, like every other key on this answer: a Client built
            # before these reads the ones it knows and behaves as it did.
            # `member` is the Engineer's current spelling, which is what a
            # Client whose own copy has gone stale adopts; empty where this
            # installation is configured as no Engineer.
            "member": vals[_CHECKIN_MEMBER_AT],
            "member_id": (mrow["id"] if mrow is not None else ""),
            # The key was on the wire from the first version of this endpoint,
            # empty, so a queue arriving in it is not a change of shape.
            "commands": [{"id": r["id"], "command": r["command"],
                          "issued_at": r["issued_at"]} for r in due]}, 200


# The three commands that exist, and nothing else. A command no Client obeys
# must not be in this list, for the reason rule 8 gives about a permission that
# gates nothing: an Admin queues it, watches it be collected, and believes
# something happened on the machine. All three are obeyed in common.py, on the
# Client's next check-in: `logoff` closes the app through its own quit path,
# `reset_identity` throws the identifier away, so the next check-in registers a
# new installation, and `trust_cert` appends this server's staged certificate
# to the file that Client pins (C3, ADR-0020). None of them ends the Windows
# session, which is not this system's to end - the labels below are the
# promise.
#
# `trust_cert` carries **no PEM**, and that is the whole of why it is a command
# at all rather than a payload: `client_commands` has no payload column, and a
# command is handed over exactly once, collected in the same transaction as the
# check-in that took it. A hand-over lost to a crash would strand that machine
# permanently with the server believing it had been told. A signal is
# re-issuable; a one-shot payload is not. So the Client fetches `/cert/next`
# itself, over the connection its current certificate already verifies.
COMMANDS = ("logoff", "reset_identity", "trust_cert", "update_now")
COMMAND_LABELS = {
    "logoff":         "Log the app off",
    "reset_identity": "Reset identity  ·  the setup wizard runs again",
    "trust_cert":     "Trust the staged certificate  ·  nothing is "
                      "replaced",
    "update_now":     "Apply the published update  ·  the app restarts "
                      "itself",
}

# Which client package answers a Client's `app` column. The check-in records
# what the app calls itself ("Notifier", "Storekeeper") and CLIENT_PACKAGES is
# keyed on what the zip is filed under, so `update_now` cannot be queued
# without the mapping between them - and it is written here rather than being a
# lower()ed guess, since a guess that stopped matching would refuse every push
# on the whole fleet while looking like a server with no packages on it.
_APP_PACKAGE_KEY = {"notifier": "notifier", "storekeeper": "storekeeper"}

# Commands that must not be queued against one Client at the same time. There
# is one pair and it is `update_now` with `logoff` (#177): both end the process
# and only one of them brings the app back, so obeyed in one batch they race -
# the update handler returns the moment its worker starts, and the logoff
# behind it either takes the process down mid-download or is undone by the
# applier relaunching the app it just closed. No order in `_COMMAND_ORDER`
# settles that, neither handler being synchronous, so the pair is refused here
# instead, which is also the answer the Admin can act on: a sentence at the
# moment of the click rather than a `collected` row that turned out to mean
# nothing. Written as pairs in both directions, so which of the two was queued
# first does not change what the second is told.
_COMMAND_CONFLICTS = {"update_now": ("logoff",), "logoff": ("update_now",)}
# Seven days. A command issued a month ago must not fire on a laptop coming
# back from long leave: by then nobody remembers issuing it and the machine may
# have been reassigned. Written into the row at issue time rather than computed
# on read, so changing this later cannot silently move the deadline of a
# command that is already waiting.
COMMAND_TTL_DAYS = 7

# The floor under "not heard from for longer than X" (#203), and the default
# threshold a fresh install starts with before an Admin ever opens Clear Old
# (#268). A threshold of nothing at all would take out the machine that
# checked in a second ago, which is a fleet reset rather than housekeeping,
# and the delete is not reversible - so the floor dropped from a week to a
# day at #268 rather than to zero: an entry field invites a threshold finer
# than the radio buttons it replaced ever offered, and a day is still long
# enough that nothing still running is caught by it.
CLEAR_AGE_MIN_DAYS = 1
CLEAR_AGE_DEFAULT_DAYS = 30


def _command_status(row, now=None):
    """"collected", "expired" or "queued" - derived, never stored.

    A status column would be a second copy of what `collected_at` and
    `expires_at` already say, and it is the copy that goes stale: a row still
    reading "queued" a fortnight after its expiry is exactly the untruth this
    list exists to prevent. Same reason `_status_of` derives a Transaction's
    state from its own columns.
    """
    if row["collected_at"]:
        return "collected"
    if (now or datetime.now().isoformat()) > (row["expires_at"] or ""):
        return "expired"
    return "queued"


def _queue_command(client_id, command, issued_by="Admin (Server GUI)"):
    """Queue one command for one Client. Returns (payload, status).

    **The door is the caller's and the actor is what it hands over**, which is
    the split `_modify_transaction` made at R1 and this one makes at #174.
    It checked the admin password itself while the console was the only caller;
    now `POST /clients/command` is a second one, opened by the admin password
    **or** the Server Settings capability over HTTPS, and a helper holding a
    password could only ever know about the first of those. So what reaches it
    is the sentence `_remote_actor` worded or the console's own literal, which
    is the one thing a caller knows and this function cannot work out.

    There is still no unauthenticated path at all: this reaches into a machine
    somebody may be working at and logs their app off, or sends a Notifier back
    through its setup wizard, so unlike `POST /transactions/cancel` there is no
    quick door beside the credentialled one.

    Refused for a Client that has never checked in. A command queued against an
    installation the server has never heard from could never be collected, and
    the Admin would be waiting on something that cannot happen - which is the
    same reason the Server GUI offers these controls only for a Client that is
    in the list.

    The same command queued twice while the first is still waiting is refused
    rather than stacked. Two log-offs in a row are not what a second click
    meant, and a Client collects everything due in one check-in, so the second
    would arrive in the same response as the first.

    `update_now` adds the two refusals `_APP_PACKAGE_KEY` and
    `_COMMAND_CONFLICTS` are for (#177): a Client whose app this server holds
    no package for, and one already carrying the command that cannot be obeyed
    beside this one. What is deliberately **not** refused is a Client whose
    `version` column already reads APP_VERSION - that column is a claim made at
    the last check-in and is stale by however long ago that was, so refusing on
    it would turn a legitimate push into an error on a machine that had just
    updated itself by hand. The client compares versions when it obeys, which
    is where the current copy of that fact is.
    """
    if command not in COMMANDS:
        return {"error": "Unknown command: %s" % (command,),
                "code": "bad_command"}, 400
    cid = str(client_id or "").strip()
    conn = get_db()
    known = conn.execute("SELECT client_id, app FROM clients WHERE client_id=?",
                         (cid,)).fetchone()
    if not known:
        conn.close()
        return {"error": "No Client has checked in with that identifier",
                "code": "unknown_client"}, 404
    if command == "update_now":
        # An update this server has no package for is a command whose only
        # honest answer at the other end is to open a browser at the installer,
        # which is not what an Admin pressing this asked for and is not
        # something a queue can be told about afterwards. Refused here, naming
        # what is missing, rather than collected and answered with nothing.
        key = _APP_PACKAGE_KEY.get(str(known["app"] or "").strip().lower())
        if not key or not _client_package(key):
            conn.close()
            return {"error": "This server holds no %s package at %s, so there "
                             "is nothing to apply"
                             % (known["app"] or "client", APP_VERSION),
                    "code": "no_package"}, 409
    now = datetime.now().isoformat()
    waiting = conn.execute(
        "SELECT id FROM client_commands WHERE client_id=? AND command=?"
        " AND collected_at='' AND expires_at > ?",
        (cid, command, now)).fetchone()
    if waiting:
        conn.close()
        return {"error": "That command is already waiting for this Client "
                         "(#%d)" % waiting["id"],
                "code": "already_queued", "id": waiting["id"]}, 409
    for other in _COMMAND_CONFLICTS.get(command, ()):
        clash = conn.execute(
            "SELECT id FROM client_commands WHERE client_id=? AND command=?"
            " AND collected_at='' AND expires_at > ?",
            (cid, other, now)).fetchone()
        if clash:
            conn.close()
            return {"error": "%s is already waiting for this Client (#%d), and "
                             "the two cannot be obeyed together"
                             % (COMMAND_LABELS.get(other, other), clash["id"]),
                    "code": "conflicts", "id": clash["id"],
                    "command": other}, 409
    expires = (datetime.now() + timedelta(days=COMMAND_TTL_DAYS)).isoformat()
    cur = conn.execute(
        "INSERT INTO client_commands (client_id, command, issued_at,"
        " issued_by, expires_at, collected_at) VALUES (?,?,?,?,?,'')",
        (cid, command, now, issued_by or "Admin", expires))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    # client_commands already holds the row; what the log adds is this act on
    # the one timeline beside everything else, which is the whole point of a
    # command that reaches into a machine somebody is working at.
    _log_event("client.command_issued",
               "#%d  %s  ->  %s" % (new_id, command, cid),
               actor=issued_by or "Admin", level="warn")
    return {"status": "queued", "id": new_id, "client_id": cid,
            "command": command, "expires_at": expires}, 201


def _command_rows(client_id):
    """Every command ever issued to one Client, newest first.

    Collected and expired ones are kept and shown, not deleted: the Admin needs
    to see that a command was issued and never collected, which is the whole
    signal that the machine has not been running.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM client_commands WHERE client_id=? ORDER BY id DESC",
        (str(client_id or ""),)).fetchall()
    conn.close()
    return rows


def _client_rows():
    """Every known installation, most recently heard from first.

    There was deliberately no GET endpoint behind this until #174, and what
    changed is where the Admin is standing rather than what the registry is:
    it is a map of hostnames, Windows account names and addresses of machines
    on the internal network, so `GET /clients` is **never open** - the admin
    password, or the Server Settings capability over HTTPS, and nothing else.
    That is the whole difference between it and `GET /asset_models` or
    `GET /permissions`, which answer facts about this build rather than about
    the network it is on. The console reads this function directly, as it
    always did.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM clients ORDER BY last_seen DESC").fetchall()
    conn.close()
    return rows


def _parse_age_threshold(text):
    """Parse a "d:h:m" age threshold into days as a float. Raises ValueError.

    #268 replaced the radio buttons with a typed field, so what used to be
    four fixed choices is now whatever an Admin writes - "1:12:0" is a day
    and a half, "30" alone is still thirty days and ":6" is six hours, each
    part optional the way an empty field always meant zero. One parser
    beside `_stale_clients` so the console and `POST /clients/clear` read a
    threshold the same way, the reason `_stale_clients` itself is one reader
    for the count and the delete.
    """
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("bad threshold: %r" % (text,))
    parts = [p.strip() for p in raw.split(":")]
    if len(parts) > 3:
        raise ValueError("bad threshold: %r" % (text,))
    parts += ["0"] * (3 - len(parts))
    d, h, m = (int(p) if p else 0 for p in parts)
    if d < 0 or h < 0 or m < 0:
        raise ValueError("bad threshold: %r" % (text,))
    return d + h / 24.0 + m / 1440.0


def _format_age_threshold(days):
    """The inverse of `_parse_age_threshold` - what the field shows back.

    Rounded to the minute: a threshold saved from the field can only ever
    have named a whole minute, so this never shows a fraction the field
    itself could not have typed.
    """
    total_minutes = round(float(days) * 1440.0)
    d, rem = divmod(total_minutes, 1440)
    h, m = divmod(rem, 60)
    return "%d:%d:%d" % (d, h, m)


def _stale_clients(days):
    """The installations last heard from more than `days` ago (#203).

    One reader for the count the console puts in front of the Admin and for
    the delete itself, so the sentence somebody confirms and the rows that
    actually go cannot be decided by two different rules - which is the whole
    of why that sentence may name a number at all.

    **A row whose `last_seen` cannot be read is kept.** That column is the one
    thing this measures, and `_since_ts` answers None where it cannot be read
    at all; a delete is not reversible and the row is evidence, so a timestamp
    nothing can measure is a reason to leave the row alone rather than a reason
    to treat it as infinitely old.
    """
    cutoff = float(days) * 86400.0
    out = []
    for r in _client_rows():
        age = _since_ts(r["last_seen"])
        if age is not None and age > cutoff:
            out.append(r)
    return out


def _clear_stale_clients(days, actor="Admin (Server GUI)",
                         log_when_empty=True):
    """Remove every installation not heard from for more than `days`.
    Returns (payload, status). #203.

    **An age threshold rather than a row-by-row delete**, because there is no
    such thing as a disconnected Client here: nothing holds a connection, a
    Client is listed because it checked in, and how long ago is the only
    question this list answers. Offered a per-row delete an Admin would remove
    whichever row looked stale, and a laptop that has been off for a fortnight
    looks exactly like a machine that was reimaged. A threshold is a statement
    about the fleet, and it is the same fact the age column is already
    coloured by.

    **The door is the caller's and the actor is what it hands over**, the shape
    `_queue_command` and `_push_next_cert` settled at #174: this is reached
    from the console and from `POST /clients/clear`, and a helper holding a
    password could only ever know about the first of the two.

    **`client_commands` is left alone, orphaned on purpose, and that is a
    decision rather than an oversight.** Those rows are keyed on `client_id`
    and are not a foreign key, and nothing in this feature has ever deleted
    one: an uncollected command is the evidence that the machine was not
    running, and the `client.command_issued` beside it records an Admin
    reaching into somebody's machine - `transaction.deleted`'s argument, that
    the record of an act outlives the thing it acted on, applied one table
    over. A command older than `COMMAND_TTL_DAYS` can never fire again
    whatever happens to the row beside it, so what is kept is a record rather
    than a loaded gun.

    **Which is the other thing this is not, and the reason the two go
    together.** The Client keeps the identifier it generated once, so an
    installation that is still running reappears under the same `client_id` on
    its next check-in with its command history intact - correct, because it is
    the same installation, and a command issued to it and still unexpired is
    still owed to it. **So this is not a way to withdraw a queued command**:
    nothing was done to any machine, and the window says so.

    One `clients.cleared` entry at `warn` naming the count and the threshold,
    which is the **whole** record those rows existed - written even where
    nothing matched, since an Admin asking is an act whether or not the
    answer was zero.

    **Unless `log_when_empty` is False**, which is `_client_sweep_loop`'s
    argument alone (#268): that job ticks hourly rather than once a quarter,
    so a "0 installations removed" entry every single hour would flood the
    System Log with the same nothing, and it is not an Admin asking - the
    console and `POST /clients/clear` never pass this, so a person confirming
    a clear is told the same way #203 always told them.
    """
    try:
        d = float(days)
    except (TypeError, ValueError):
        d = -1.0
    if d < CLEAR_AGE_MIN_DAYS:
        return {"error": "A threshold of at least %s day%s is required."
                         % (("%g" % CLEAR_AGE_MIN_DAYS),
                            "" if CLEAR_AGE_MIN_DAYS == 1 else "s"),
                "code": "bad_age"}, 400
    rows = _stale_clients(d)
    if rows:
        conn = get_db()
        conn.executemany("DELETE FROM clients WHERE client_id=?",
                         [(r["client_id"],) for r in rows])
        conn.commit()
        conn.close()
    left = len(_client_rows())
    if rows or log_when_empty:
        _log_event("clients.cleared",
                   "%d installation%s last heard from more than %s days ago  "
                   "\u00b7  %d left"
                   % (len(rows), "" if len(rows) == 1 else "s", ("%g" % d),
                      left),
                   actor=actor or "Admin", level="warn")
    return {"status": "cleared", "removed": len(rows), "days": d,
            "remaining": left}, 200


def _client_sweep_loop():
    """Background job: run `_clear_stale_clients` hourly, on its own (#268).

    **The threshold is read fresh from `server_config.json` every tick**
    rather than captured once at start-up - `_sync_loop`'s rule (032) - so an
    Admin who saves a new threshold from the Clear Old dialog gets it applied
    on the very next hour, with no restart. `CLEAR_AGE_DEFAULT_DAYS` is what a
    fresh install sweeps with before an Admin has ever opened that dialog.

    **`actor="Auto-clear"`** rather than `"Admin (Server GUI)"`, so a
    `clients.cleared` entry this loop wrote is never mistaken for one an Admin
    confirmed at the console, and **`log_when_empty=False`**, so the sixty
    ticks that found nothing stale in an hour do not become sixty identical
    entries the System Log's readers have to scroll past to find the one that
    mattered.
    """
    while True:
        try:
            days = float(_load_server_cfg().get(
                "clear_age_threshold_days", CLEAR_AGE_DEFAULT_DAYS))
            _clear_stale_clients(days, actor="Auto-clear",
                                 log_when_empty=False)
        except Exception:
            pass
        time.sleep(3600)  # hourly
