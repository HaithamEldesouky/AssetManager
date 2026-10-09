"""
Asset Manager - the System Log.

What was *done*, as opposed to what was moved: the one writer every act in
this build passes through (`_log_event`), the words a row reads as
(`EVENT_SENTENCES`, `event_phrase`, `event_sentence`), the readers the Server
GUI's System Log window draws with (`_log_event_names`, `_log_rows`,
`_log_entry`, `_log_client`, `_log_diff`), the clear behind the console's
button (`_log_clear`), the batch a Client ships (`_record_log`), and the two
retention bounds with the hourly job that applies them (`_log_trim`,
`_log_retention_loop`).

Lifted out of `server.py` by #227 unchanged - the fourth of the six clusters
046 (#220) named and left in it, behind `server_mail.py`, `server_sync.py`
and `server_clients.py`. Not tidiness: `server_gui.py`'s System Log window
calls most of it as `S.<name>`, every other module in this build logs
through `_log_event` over its own `bind()`, and `tools/server-checks.py`
drives the readers, the clear and the trim directly rather than over HTTP.

**`POST /clients/log` is not here.** Its handler stayed in `server.py` and
calls `_record_log` in here, which is the shape #226 gave the `/clients*`
routes and 041-043 gave the three registers - a module of what the routes
call, not of the routes - and it is what leaves `@app`, `@door`, `DOOR_OPEN`,
`request` and `jsonify` out of this file entirely, with
`docs/reference/api.md`'s row for it unchanged.

**`server.py` binds this module before it binds the other five.**
`server_cert.bind()`, the three registers' and `server_gui.bind()` are each
handed `_log_event`, and `server_mail.bind()`, `server_sync.bind()` and
`server_clients.bind()` further down are too. `server.py` imports the name
back flat at the top of the file, so every one of those calls is handed this
module's function object and there is exactly one log writer in the process.

Headless-safe: nothing here draws, so `server.py` imports it at module
level.

**It opens no database of its own.** `get_db` and `_notify_of` are
`server.py`'s and `server_mail.py`'s and come over through `bind()`, handed
rather than imported back for the reason `server_cert.py`'s docstring gives
- `server.py` runs as `__main__` under `applaunch`'s `runpy.run_path`, so
`from server import get_db` would execute the whole server a second time
rather than reach the one running.

`_db_path` is the one name on the list that is a **callable** rather than a
value, for `server_sync.py`'s reason: `DB_PATH` is resolved once at
`server.py`'s import and re-pointed by `tools/server-checks.py` between
check groups, so a copy taken at `bind()` would be the path as it was at
import. The three `sqlite3.connect` calls in here - the writer's, the
clear's and the trim's - are the only lines of the moved block that changed,
and they changed to `_db_path()`. `get_db()` resolves it at call time inside
`server.py` and needs no such treatment.

`LOG_MAX_ROWS` is the other name `tools/server-checks.py` re-points, and it
is *defined* here rather than bound, so that file sets it on this module
rather than on the server module.
"""

import json
import re
import sqlite3
import time
from datetime import datetime, timedelta

# Handed over by server.py's bind() below, before anything here is called.
# Named exactly as server.py names them, so the code moved in reads there
# and here as one thing. `_db_path` is the exception and is named for what
# it is: a reader for `DB_PATH`, not the path.
_db_path = None
_notify_of = None
get_db = None


def bind(*, db_path, get_db, notify_of):
    """Give this module everything it reads out of server.py. Called once.

    Keyword-only and exhaustive, the same contract `server_cert.bind()`, the
    three registers', `server_mail.bind()`'s, `server_sync.bind()`'s and
    `server_clients.bind()`'s carry: every name the moved code reads out of
    `server.py` is on this list, built with a `symtable` sweep over the moved
    block rather than by hand, because 036's own note found fourteen names a
    hand-written list had missed. `re`, `sqlite3`, `time`, `datetime` and
    `timedelta` are the five the sweep found that are not here - they are
    stdlib and this module imports them itself.

    Called from `server.py` **above** the block that binds `server_cert`, the
    three registers and `server_gui`, because every one of those calls is
    handed `_log_event` and a name handed over before it exists is this
    pattern's one real failure mode. `get_db` is defined a long way above
    that point and `_notify_of` comes off `server_mail`'s flat import at the
    top of the file, so there is nothing below it this call needs.

    `db_path` is a **reader** rather than the path, for the reason
    `server_sync.bind()` takes it that way: `DB_PATH` is re-pointed by
    `tools/server-checks.py` between check groups, and a copy taken here
    would be the path as it was at import.

    What is bound here is module state, so a process holding **two** server
    modules leaves this one pointing at whichever imported it last. A real
    install has one; `tools/server-checks.py` is the only thing that imports
    a second, and it gives each staged copy a `server_log` of its own.
    """
    global _db_path, _notify_of
    _db_path = db_path
    _notify_of = notify_of
    # `global get_db` is a syntax error where `get_db` is also the
    # parameter, and the moved code calls it bare - so the module global is
    # set the one way left, exactly as `register_assets.bind()` sets it.
    globals()["get_db"] = get_db


# ─── The System Log ───────────────────────────────────────────────────────────

# What was *done*, as opposed to what was moved. The transactions table already
# records every movement and client_commands records every command, so nothing
# here copies a row that exists elsewhere - it records the act and points at the
# row, and it records the acts that had no row at all: a refused password, a
# replaced lookup sheet, a server starting, a Notifier stopping.
#
# It lives in assets.db rather than in a rolling file beside the server. Every
# question asked of it is a filter over a column (which component, which day),
# which is a WHERE here and a parser there; it travels inside the backup
# update.ps1 already takes and the copy a migration leaves behind, rather than
# being a second thing somebody has to remember to collect; and the Server GUI
# window that reads it is a table already. What that costs is contention with
# the Transaction writes, and that is answered in _log_event rather than by
# choosing a file: a log write that cannot happen is a gap in the log, and it
# must never be a refused Transaction.

LOG_COMPONENTS = ("Server", "Storekeeper", "Notifier")
LOG_LEVELS = ("info", "warn", "error")

# Caps, for the reason _CHECKIN_MAX exists one section up: POST /clients/log is
# unauthenticated (ADR-0002, ADR-0005), so a caller on the network chooses every
# one of these strings, and how many arrive in one request.
_LOG_FIELD_MAX  = 120
_LOG_DETAIL_MAX = 400
_LOG_BATCH_MAX  = 50

# How long a log write may wait for the database before giving up. Shorter than
# get_db()'s own five seconds on purpose: every caller is in the middle of doing
# something that matters, and none of them is worth delaying for this.
_LOG_DB_TIMEOUT = 2.0

# Retention, at this end, applied by the hourly job below and by nothing on a
# request path. Two bounds rather than one, and the second is the one the
# unauthenticated endpoint makes necessary: an age bound alone cannot bound a
# table anybody on the network can write to as fast as they like. Ninety days
# is a quarter - long enough that a dispute about a movement still has the
# actions around it, short enough that the file is not the problem.
LOG_RETENTION_DAYS = 90
LOG_MAX_ROWS = 50000

# What an event name means, in words (#196).
#
# A row reads `transaction.cancelled` / `#42 reason: wrong asset`, and the Admin
# reading it has to already know what that name means. This is the sentence
# beside it.
#
# The `event` column itself does not change. It is a short stable name, every
# row already written carries it, both clients ship it, and a notification rule
# matches on it - so renaming one would split the log in half at the moment it
# changed and stop a rule firing with nothing saying so. This is a display of a
# row and never a rewrite of one, derived at read time, and the stable name
# stays on the window beside it because that is the string an Admin writing a
# rule has to type.
#
# Each value is a verb phrase that reads with the actor in front of it, because
# who did something is half of what a log line says: the System Log window puts
# it in the column after Actor, so a row reads left to right as
# `Storekeeper User | retracted a Transaction | #42 reason: wrong asset`, and
# `event_sentence` joins the two for anywhere there are no columns to read
# across. The actor is not written into the phrase itself - that would be the
# same fact twice on one row.
#
# A name with no phrase falls back to the raw event, which is PERMISSION_LABELS'
# rule (rule 8): an uncaptioned name is still offered as itself rather than
# dropping out of what the window shows. It is also what a shipped entry gets -
# POST /clients/log is unauthenticated and a caller on the network chooses the
# event name, so this is handed strings no build of ours ever writes.
#
# This is written down here and in `docs/system-log-events.md`, and the two are
# held equal by `cascade-audit.py` - both directions, so neither an event the
# code can write with no sentence, nor a sentence for an event nobody writes any
# more, can sit there unnoticed. It is a second copy on purpose: that document
# is read by a person, and nothing under `docs` ships in any package
# (`package.ps1` stages four sources, the migrations and the vendored lib), so a
# table parsed out of it at read time would be empty on every real install and
# this window would show raw event names everywhere except a developer's
# checkout - which is the one failure mode a gate would never catch. The cascade
# rule's answer to a fact that must be written twice is to hold the copies
# equal, which is what PASSWORD_MIN in `installer.py` already is.
EVENT_SENTENCES = {
    # Transactions
    "transaction.created":        "recorded a movement",
    "transaction.confirmed":      "confirmed a Transaction",
    "transaction.rejected":       "rejected a Transaction, with a reason",
    "transaction.dismissed":      "put a Transaction off to answer later - it "
                                  "is offered again on the popup's own interval",
    "transaction.cancelled":      "retracted a Transaction - the movement "
                                  "never happened",
    "transaction.modified":       "corrected a Pending Transaction",
    "transaction.deleted":        "deleted Transactions - this entry is the "
                                  "whole record of it",
    "transaction.auto_accepted":  "confirmed Transactions left Pending past "
                                  "24h, with nobody having answered",
    "records.imported":           "restored a Transaction archive",
    # The Lookup Sheet and its assets
    "asset.saved":                "added or corrected one asset",
    "asset.removed":              "removed one asset from the register",
    "lookup.replaced":            "replaced every asset from an uploaded "
                                  "workbook",
    "lookup.imported":            "added assets from somebody else's file",
    "assets.seeded":              "read the embedded workbook into a new "
                                  "register",
    "assets.ambiguous_identifier": "cleared an identifier that named two "
                                   "assets",
    "assets.duplicate_identifier": "started with an identifier that names two "
                                   "assets",
    # Proposals
    "asset.proposed":             "proposed an asset the register does not "
                                  "hold",
    "asset.proposals_imported":   "proposed a whole delivery as one file",
    "asset.proposal_approved":    "approved a proposal, which writes the "
                                  "register",
    "asset.proposal_rejected":    "refused a proposal, with a reason",
    # Engineers, the Admin and the console
    "console.unlocked":           "proved the admin password and opened "
                                  "Server Administration",
    "console.action_failed":      "hit a Server GUI action that failed - "
                                  "nothing was saved",
    "auth.refused":               "was refused - the password was wrong",
    "admin.password_changed":     "replaced the admin password",
    "capability.password_set":    "set a capability password and named its "
                                  "holder",
    "capability.password_cleared": "cleared a capability password, and the "
                                   "holder with it",
    "member.saved":               "added or edited an Engineer",
    "member.deleted":             "removed an Engineer - their Own Password "
                                  "went with it",
    "member.renamed":             "renamed an Engineer, naming both spellings",
    "member.password_set":        "set an Engineer's Own Password, which is "
                                  "Temporary",
    "member.password_cleared":    "cleared an Engineer's Own Password",
    "member.password_changed":    "replaced their own password",
    "members.name_collision":     "started with two Engineers whose names "
                                  "differ only in case",
    # The network, remotely
    "remote.action":              "opened a remote endpoint with a delegated "
                                  "credential",
    "remote.refused":             "was turned away at a remote endpoint",
    # Certificates
    "cert.installed":             "installed a certificate, naming what went "
                                  "and what came",
    "cert.removed":               "removed the certificate, naming what went",
    "cert.exported":              "exported the public certificate - nothing "
                                  "private travelled",
    "cert.generated":             "staged a next certificate, bound to "
                                  "nothing",
    "cert.pushed":                "asked every Client to trust the staged "
                                  "certificate",
    "cert.cutover":               "made the staged certificate the live one",
    "cert.cutover_failed":        "could not make the staged certificate live",
    "cert.trusted":               "added the staged certificate to what this "
                                  "machine pins",
    "cert.expiry_warning":        "warned the live certificate is due to "
                                  "expire soon",
    "cert.expiry_critical":       "warned the live certificate is about to "
                                  "expire",
    # Backup, restore and maintenance
    "backup.started":             "started a backup",
    "backup.finished":            "finished a backup",
    "backup.failed":              "could not finish a backup",
    "restore.started":            "started a restore, which replaces the "
                                  "database",
    "restore.finished":           "finished a restore, naming what was set "
                                  "aside",
    "restore.refused":            "refused a backup before a byte was written",
    "restore.failed":             "began a restore and could not finish it",
    "maintenance.entered":        "held writes for a backup or a restore",
    "maintenance.left":           "took the hold off writes",
    "write.held":                 "had a write refused while maintenance was "
                                  "held",
    # Mail and rules
    "mail.send_failed":           "could not get the relay to take a message",
    "mail.test_sent":             "sent a test mail",
    "mail.test_failed":           "could not send a test mail",
    "notify.rules_changed":       "saved the notification rules",
    # The external asset system
    "sync.configured":            "saved the connection to the external asset "
                                  "system",
    "sync.started":               "started an asset sync run",
    "sync.added":                 "added an asset, or filled an empty field, "
                                  "from the external system",
    "sync.conflict":              "found a disagreement and left it exactly "
                                  "as it was",
    "sync.finished":              "finished an asset sync run",
    "sync.failed":                "could not finish an asset sync - nothing "
                                  "was written",
    # Clients, and the server itself
    "client.command_issued":      "queued a Command for one Client",
    "client.command_collected":   "took the Command it was queued, on a "
                                  "Check-in",
    "clients.cleared":            "removed the installations nobody had "
                                  "heard from",
    "server.started":             "started this server process",
    "server.stopped":             "stopped this server process",
    "server.config_changed":      "saved a server setting",
    "server.port_moved":          "moved the IIS binding to another port",
    "log.exported":               "exported the System Log",
    "log.cleared":                "deleted System Log rows - this entry is "
                                  "the evidence it happened",
    # Both clients
    "app.started":                "started this installation",
    "app.stopped":                "stopped this installation",
    "command.obeyed":             "carried out a queued Command",
    "settings.opened_offline":    "opened Settings with nothing answering, so "
                                  "no password was checked",
    "settings.url_changed":       "changed the Server URL",
    # The update lifecycle, both clients
    "update.offered":             "was told a newer version is published",
    "update.declined":            "postponed the update",
    "update.download_failed":     "could not fetch the package - nothing was "
                                  "replaced",
    "update.verify_refused":      "refused the package it fetched - nothing "
                                  "was replaced",
    "update.staged":              "staged a verified package and is "
                                  "restarting to apply it",
    "update.applied":             "applied the update",
    "update.failed":              "never applied the update - the old build "
                                  "is still installed",
    "update.rolled_back":         "applied the update and put it back",
    # Storekeeper only
    "transaction.submitted":      "got one Transaction to the server",
    "transaction.refused":        "had a Transaction turned down by the "
                                  "server",
    "transaction.buffered":       "could not reach the server, so the "
                                  "movement is waiting to be flushed",
    "asset.propose_refused":      "had a proposal refused by the server",
    "asset.propose_failed":       "could not ask about a proposal at all - "
                                  "nothing was queued",
    # Notifier only
    "answer.buffered":            "could not get an answer taken yet, so it "
                                  "is waiting for the next tick",
    "answer.refused":             "had an answer refused for good",
    "user.logged_off":            "logged off this installation",
}


# The phrase five converted events gain when `data` can fill it in, kept
# apart from EVENT_SENTENCES rather than folded into those entries. The
# entries above are what a row with no `data` reads as - every row from
# before this column existed, and that has to go on being exactly the
# sentence it was before #071, not this string with its `{keys}` sitting in
# it unfilled. `transaction.modified` carries `data` too but is not here:
# its facts are the structured diff `_log_diff` reads, not text for this
# phrase, and its EVENT_SENTENCES entry is unchanged for the same reason the
# other four keep theirs.
_EVENT_TEMPLATES = {
    "cert.installed":        "installed a certificate - was {was}, now {now}",
    "cert.removed":          "removed the certificate - was {was}",
    "cert.cutover":          "made the staged certificate the live one - "
                             "from {from} to {to}, {behind} of {total} "
                             "installation(s) had not collected it",
    "server.config_changed": "saved a server setting - changed {changed}",
    "server.port_moved":     "moved the IIS binding from port {from} to "
                             "port {to}",
}


def event_phrase(event, data=None):
    """What `event` means, in words, or the raw name where nothing says.

    `data` fills a template's `{keys}` where the phrase has any - most
    phrases have none, `.format()` is then a no-op, and this reads exactly as
    it did before #071. Falls back to the bare (unfilled) phrase wherever
    `data` cannot answer for it: it is None, empty, unreadable as a dict, or
    missing a key the phrase names - a row written before this ticket, and
    every row of the ~100 call sites this ticket leaves unconverted, are all
    the `data is None` case, and both must read exactly as they do today.
    `data` may be the dict `_log_event` was handed or the JSON text a row
    stores it as; a caller with a `sqlite3.Row` need not parse it first.
    """
    phrase = EVENT_SENTENCES.get(str(event or ""), "") or str(event or "")
    if not data:
        return phrase
    template = _EVENT_TEMPLATES.get(str(event or ""))
    if template is None:
        return phrase
    parsed = data
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return phrase
    if not isinstance(parsed, dict):
        return phrase
    try:
        return template.format(**parsed)
    except (KeyError, IndexError):
        return phrase


def event_sentence(event, actor="", detail="", data=None):
    """One line saying what happened, for anywhere with no columns to read
    across - the export, and anything that shows one row on its own.

    The actor goes in front because that is how the phrase is written; with
    none, the phrase opens the sentence and is capitalised for it. The detail
    is appended verbatim rather than parsed into the sentence: it is one line
    of context whose shape is each call site's own, and a reader who is
    reconstructing a dispute needs what was actually written down rather than
    this function's reading of it. `data` passes straight through to
    `event_phrase` - this function reads no key of it itself.
    """
    phrase = event_phrase(event, data)
    who = str(actor or "").strip()
    if who:
        line = "%s %s" % (who, phrase)
    else:
        line = (phrase[:1].upper() + phrase[1:]) if phrase else ""
    tail = str(detail or "").strip()
    return "%s - %s" % (line, tail) if tail else line


def _log_event(event, detail="", component="Server", actor="", level="info",
               client_id="", address="", client_ts="", data=None):
    """Write one System Log row. The one writer, and it never raises.

    `data` is a dict a call site hands over beside its own free-text
    `detail`, serialised here with `sort_keys` so two calls with the same
    facts write the same bytes. Capped at `_LOG_DETAIL_MAX` like every other
    field, but dropped to NULL rather than cut where it does not fit - a
    truncated JSON document is not a smaller JSON document, it is not JSON at
    all, and `event_phrase`'s own fallback already answers for a row with no
    `data` exactly as it must answer for one this cap discarded. The row
    itself is never refused for it; only `data` is.

    The shape of an entry is decided here and nowhere else, the way
    _create_transaction is the one writer of a Transaction: POST /clients/log
    goes through this function too, so a shipped entry and one this server
    wrote itself cannot end up meaning different things by the same column.

    `ts` is always this server's clock. A shipped entry's own claim about its
    clock arrives as `client_ts` and is stored beside it rather than in place of
    it - a laptop that was offline for a day ships a batch that all lands at one
    server time, and a clock is one more thing an unauthenticated caller
    chooses. `address` is the source address the server actually saw and is
    empty for exactly the rows written in process here, which is what makes a
    caller claiming component "Server" from the network read as the mismatch it
    is instead of being believed.

    Every failure is swallowed, deliberately and completely. A locked database,
    a full disk, a db_path that has gone away - none of them may turn a recorded
    Transaction into a refused one, or stop an Engineer confirming one. That is
    the failure this whole system exists to prevent, and a log line is never
    worth it. Returns True when the row was written, which only the endpoint
    below reads: every other caller is an operation that must not care.
    """
    try:
        lvl = str(level or "info").strip().lower()
        data_json = None
        if data is not None:
            try:
                encoded = json.dumps(data, sort_keys=True)
            except (TypeError, ValueError):
                encoded = None
            if encoded is not None and len(encoded.encode("utf-8")) <= _LOG_DETAIL_MAX:
                data_json = encoded
        row = (datetime.now().isoformat(),
               (str(component or "Server").strip() or "Server")[:_LOG_FIELD_MAX],
               str(event or "")[:_LOG_FIELD_MAX],
               lvl if lvl in LOG_LEVELS else "info",
               str(actor or "").strip()[:_LOG_FIELD_MAX],
               str(detail or "").strip()[:_LOG_DETAIL_MAX],
               str(client_id or "").strip()[:_LOG_FIELD_MAX],
               str(address or "").strip()[:_LOG_FIELD_MAX],
               str(client_ts or "").strip()[:_LOG_FIELD_MAX],
               data_json)
        conn = sqlite3.connect(_db_path(), timeout=_LOG_DB_TIMEOUT)
        try:
            conn.execute("INSERT INTO system_log (ts, component, event, level,"
                         " actor, detail, client_id, address, client_ts, data)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?)", row)
            conn.commit()
        finally:
            conn.close()
        # Where a mailed notification is decided, and the only place (031). Not
        # a call per interesting event: a rule pointed at an event nobody emits
        # mails nothing, which is visible and harmless, while an event somebody
        # forgot to wire mails nothing and looks configured.
        #
        # Handed the row's own values rather than the arguments behind them:
        # what a rule matches on and what a reader is mailed has to be what was
        # stored, capped and defaulted exactly as the table holds it.
        #
        # Its own try rather than the one above. A failure in here must not
        # make this function answer False about a row it really wrote - the
        # endpoint below reads that answer - and the promise this function
        # makes is about the row, not about the mail.
        try:
            _notify_of(row[2], row[3], row[1], row[4], row[5], row[0], row[9])
        except Exception:
            pass
        return True
    except Exception:
        return False


def _log_event_names():
    """The event names this log has actually seen, for the rules window.

    Read off the table rather than kept as a catalogue beside it: a second list
    of the names _log_event is called with is a fact written down twice, and
    the copy nobody reads is the one that goes stale (rule 10's shape). A rule
    may still name an event that has never happened - the window offers these
    and refuses nothing.
    """
    try:
        conn = get_db()
        try:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT event FROM system_log ORDER BY event")]
        finally:
            conn.close()
    except Exception:
        return []


def _log_rows(component="", since="", until="", limit=500):
    """The System Log, newest first, for the window below.

    Read from the table rather than through an endpoint, for the reason
    _client_rows gives: this is a record of who did what on the internal
    network, and the Admin at this console is reading the database it is stored
    in. `since` and `until` may be plain dates - `until` is widened to the end
    of its day here, because a person filtering "to the 9th" means the 9th
    included and ISO timestamps sort as text.
    """
    sql = ["SELECT * FROM system_log WHERE 1=1"]
    params = []
    if component:
        sql.append("AND component=?")
        params.append(component)
    if since:
        sql.append("AND ts >= ?")
        params.append(since)
    if until:
        sql.append("AND ts <= ?")
        params.append(until if "T" in until else until + "T23:59:59.999999")
    sql.append("ORDER BY id DESC LIMIT ?")
    params.append(int(limit))
    conn = get_db()
    try:
        return conn.execute(" ".join(sql), params).fetchall()
    finally:
        conn.close()


def _log_entry(eid):
    """One System Log row by its id, or None where it has gone (#195).

    The window below opens a row on a double-click and the table it was read
    from goes on moving - retention runs hourly and Clear is two controls
    away - so the row is re-read rather than drawn out of what the tree
    happens to be holding, and a row that is no longer there is an answer
    rather than a raise.
    """
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM system_log WHERE id=?",
                            (int(eid),)).fetchone()
    finally:
        conn.close()


def _log_client(client_id):
    """The installation a shipped entry came from, or None (#195).

    A `client_id` on a System Log row is the Client's own claim about itself
    (ADR-0005), so the hostname and the Windows account behind it are joined
    from `clients` at read time rather than copied into the entry. **A client
    row that is no longer there is None** and the entry is shown without it:
    an installation can be reset or removed long after it wrote a line, and an
    entry that cannot be opened because the machine that shipped it has gone
    is the record failing at exactly the moment it is being read.
    """
    if not client_id:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT hostname, os_user FROM clients WHERE client_id=?",
            (client_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"hostname": row["hostname"] or "", "os_user": row["os_user"] or ""}


# What a correction's diff looks like once `_modify_detail` has written it
# (#200): the Transaction's own "#<id>  " head, then one `field: "old" -> "new"`
# per field that moved, joined by ";  ", then an optional count of the fields
# that did not fit. Read back here rather than stored as columns, because the
# System Log records the act and points at the row - a diff table beside it
# would be a second copy of what `detail` already says.
_DIFF_HEAD = re.compile(r"^#\d+\s+")
_DIFF_TAIL = re.compile(r"\s+\(\+(\d+) more not shown\)$")
_DIFF_PART = re.compile(r'^([a-z_]+): "(.*?)" -> "(.*?)"$')


def _log_diff(row):
    """The field changes a `transaction.modified` entry recorded, or None.

    Only that event: every other entry's `detail` is a line of context rather
    than a diff, and guessing at one would put made-up old values in front of
    somebody reconstructing a dispute. None as well where the line does not
    parse - an entry written by a build before #200, or one whose values held
    the separator this reads on - and the window then shows `detail` as it is,
    which is what it did for every entry before this.

    Answers `(changes, dropped)`: a list of `(field, old, new)` in the order
    the entry names them, and how many fields the entry says it could not fit.
    """
    if not row or row["event"] != "transaction.modified":
        return None
    try:
        raw = row["data"]
    except (IndexError, KeyError):
        raw = None
    if raw:
        try:
            parsed = json.loads(raw)
            changes = [(c[0], c[1], c[2]) for c in parsed["changes"]]
            dropped = int(parsed["dropped"])
            return changes, dropped
        except (TypeError, ValueError, KeyError, IndexError):
            pass  # not a shape this reads - fall back to detail below
    detail = row["detail"] or ""
    if not _DIFF_HEAD.match(detail):
        return None
    body = _DIFF_HEAD.sub("", detail)
    dropped, tail = 0, _DIFF_TAIL.search(body)
    if tail:
        dropped = int(tail.group(1))
        body = body[:tail.start()]
    changes = []
    for part in body.split(";  "):
        m = _DIFF_PART.match(part.strip())
        if not m:
            return None
        changes.append((m.group(1), m.group(2), m.group(3)))
    return changes, dropped


def _log_clear(component="", since="", until=""):
    """Delete every System Log row the given filter matches. Returns the count.

    Takes its rows from `_log_rows` itself rather than a second copy of the
    WHERE it builds, asked for with `LOG_MAX_ROWS` as the limit - that is this
    table's own ceiling, so it is every row the filter can possibly match
    rather than the 500-row page the window happens to be showing. Clear acts
    on what the filter matches (ticket A9), not on the whole table and not on
    only what is on screen.
    """
    ids = [r["id"] for r in _log_rows(component=component, since=since,
                                      until=until, limit=LOG_MAX_ROWS)]
    if not ids:
        return 0
    conn = sqlite3.connect(_db_path(), timeout=_LOG_DB_TIMEOUT)
    try:
        qmarks = ",".join("?" * len(ids))
        conn.execute("DELETE FROM system_log WHERE id IN (%s)" % qmarks, ids)
        conn.commit()
    finally:
        conn.close()
    return len(ids)


def _record_log(data, address):
    """Take one shipped batch of Client entries. Returns (payload, status).

    Unauthenticated like every other Client channel (ADR-0002, ADR-0005), so
    anything on the internal network can write here. That is accepted and it is
    not a reason to skip the defences _record_checkin already applies to the
    values a network caller chooses: every field is capped, the batch is capped,
    and the source address the server saw is recorded beside whatever the caller
    claims about itself.

    Refused politely rather than fatally. An over-long batch has its first
    _LOG_BATCH_MAX entries taken and is told how many were dropped, instead of
    being rejected whole - a Client that cannot deliver keeps its local copy and
    carries on, which is the whole reason the local file is not optional.

    An entry's `data` is read where it is there and is NULL where it is not
    (#247/072). Nothing is versioned and no flag decides it: this function
    picks the keys it names, so a Client old enough to send none writes the
    column NULL and a Client new enough to send one against a server old
    enough to ignore it loses the structure and keeps the row - which is the
    mid-rollout rule, held by the shape of the read rather than by a
    negotiation.
    """
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        return {"error": "entries is required", "code": "no_entries"}, 400
    cid     = str(data.get("client_id") or "").strip()[:_LOG_FIELD_MAX]
    claimed = str(data.get("component") or "").strip()[:_LOG_FIELD_MAX]
    # Never blank, so "has a source address" is exactly "arrived over the wire".
    seen = str(address or "").strip()[:_LOG_FIELD_MAX] or "unknown"
    written = 0
    for e in entries[:_LOG_BATCH_MAX]:
        if not isinstance(e, dict):
            continue
        # A dict or nothing. `_log_event` would serialise a list or a bare
        # string just as happily, and the column would then hold documents
        # that no reader of it - `event_phrase`, `_log_diff` - can answer a
        # question from; an unauthenticated caller chooses this value like
        # every other one here.
        shipped = e.get("data")
        if not isinstance(shipped, dict):
            shipped = None
        if _log_event(e.get("event") or "",
                      detail=e.get("detail") or "",
                      component=(str(e.get("component") or claimed).strip()
                                 or "Client"),
                      actor=e.get("actor") or "",
                      level=e.get("level") or "info",
                      client_id=cid, address=seen,
                      client_ts=e.get("ts") or "",
                      data=shipped):
            written += 1
    return {"status": "ok", "accepted": written,
            "dropped": len(entries) - written}, 200


def _log_trim(now=None):
    """Apply both retention bounds. Returns the number of rows removed.

    Swallows everything, like the writer: a trim that cannot run leaves a bigger
    log, which is a thing to notice, while an exception out of a background
    thread is a job that has silently stopped.
    """
    try:
        cutoff = ((now or datetime.now())
                  - timedelta(days=LOG_RETENTION_DAYS)).isoformat()
        conn = sqlite3.connect(_db_path(), timeout=_LOG_DB_TIMEOUT)
        try:
            gone = conn.execute("DELETE FROM system_log WHERE ts < ?",
                                (cutoff,)).rowcount
            gone += conn.execute(
                "DELETE FROM system_log WHERE id <= (SELECT id FROM system_log"
                " ORDER BY id DESC LIMIT 1 OFFSET ?)",
                (LOG_MAX_ROWS,)).rowcount
            conn.commit()
        finally:
            conn.close()
        return max(gone, 0)
    except Exception:
        return 0


def _log_retention_loop():
    """Background job: apply the System Log's retention hourly."""
    while True:
        try:
            _log_trim()
        except Exception:
            pass
        time.sleep(3600)  # re-check hourly
