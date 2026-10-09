"""
Asset Manager - the external asset system.

The one-directional read of another system's asset list and the reconcile
that folds it into the Assets register (`_sync_cfg`, `_sync_url`,
`_sync_fetch`, `_sync_keys`, `_sync_mapping`, `_sync_rows`,
`_sync_reconcile`, `_sync_summary`, `_sync_names`, `_sync_run`,
`_sync_last_run` and `_sync_loop`), with the three wrappers that name
`sync_secret.dat` (`_sync_secret_set`, `_sync_secret_get`,
`_sync_secret_stored`).

Lifted out of `server.py` by #225 unchanged - the second of the six
clusters 046 (#220) named and left in it, behind `server_mail.py`. Not
tidiness: no route here reaches any of it, `server_gui.py`'s Asset Sync
window calls all of it as `S.<name>`, `_start_background_jobs` starts
`_sync_loop`, and `tools/server-checks.py` drives five check groups
against a stubbed opener rather than a host on the network - the cluster
already had an adapter and a gate reaching it the same way before there
was a module to name it.

**`_sync_admin_cfg` is not here.** It shares this prefix and nothing else:
it re-reads `admin_config.json` where a second process has written it -
ADR-0001's IIS deployment and the Windows Service, where the Server GUI is
monitor-only - which makes it an admin-credential helper, and it stays in
`server.py` beside the credential it is about. 046's table grouped it by
name; #225 grouped it by what it does.

What a run is allowed to do, and the three things it is not, is ADR-0014's
argument and is written out below where it was written.

Headless-safe: nothing here draws, so `server.py` imports it at module
level.

**It opens no database and resolves no path of its own.** `get_db`,
`_log_event`, `_load_assets`, `_save_asset`, `SYNC_SECRET_PATH`,
`_secret_set`, `_secret_get` and eight more are all `server.py`'s and come
over through `bind()`, handed rather than imported back for the reason
`server_cert.py`'s docstring gives - `server.py` runs as `__main__` under
`applaunch`'s `runpy.run_path`, so `from server import get_db` would
execute the whole server a second time rather than reach the one running.

`_secret_set` and `_secret_get` are the pair #224 deliberately left
behind: the mail relay's stored password (ADR-0013) was their first caller
and this credential (ADR-0014) is the second, so they answer to neither
module and are bound into both.

`_db_path` is the one name on the list that is a **callable** rather than
the value it reads. `DB_PATH` is resolved once at `server.py`'s import and
re-pointed by `tools/server-checks.py` between check groups, so a copy
taken at `bind()` would be the path as it was then - this pattern's own
failure mode, one step along: a name handed over before it is right.
"""

import base64
import json
import os
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.request

# The shape `_save_asset` holds an asset to, asked here before the write so a
# record that fails it is skipped with its reason rather than aborting the run
# (103). Imported directly, as `server_lookup.py` takes it.
from register_assets import _asset_shape_error

# Handed over by server.py's bind() below, before anything here is called.
# Named exactly as server.py names them, so the code moved in reads there
# and here as one thing. `_db_path` is the exception and is named for what
# it is: a reader of that name rather than a copy of it.
APP_VERSION = None
SYNC_SECRET_PATH = None
_IMPORT_FIELDS = None
_IMPORT_LABELS = None
_LOG_DB_TIMEOUT = None
_check_import_mapping = None
_db_path = None
_load_assets = None
_load_server_cfg = None
_log_event = None
_map_import_columns = None
_save_asset = None
_secret_get = None
_secret_set = None
get_db = None


def bind(*, app_version, check_import_mapping, db_path, get_db,
         import_fields, import_labels, load_assets, load_server_cfg,
         log_db_timeout, log_event, map_import_columns, save_asset,
         secret_get, secret_set, sync_secret_path):
    """Give this module everything it reads out of server.py. Called once.

    Keyword-only and exhaustive, the same contract `server_cert.bind()`,
    the three registers' and `server_mail.bind()` carry: every name the
    moved code reads out of `server.py` is on this list, built with a
    `symtable` sweep over the moved block rather than by hand, because
    036's own note found fourteen names a hand-written list had missed.

    Two of the fifteen are `_secret_set` and `_secret_get`, the generic
    stored-secret pair #224 left in `server.py` because this credential is
    their second caller. One is `db_path`, a callable rather than the path
    it reads, for the reason the module docstring gives.

    Called from `server.py` beside `server_mail.bind()` rather than in the
    block that binds the registers, because those two secret helpers are
    defined below that block and a name handed over before it exists is
    the one real failure mode of this pattern.

    What is bound here is module state, so a process holding **two** server
    modules leaves this one pointing at whichever imported it last. A real
    install has one; `tools/server-checks.py` is the only thing that
    imports a second, and it gives each staged copy a `server_sync` of its
    own.
    """
    global APP_VERSION, SYNC_SECRET_PATH, _IMPORT_FIELDS, _IMPORT_LABELS
    global _LOG_DB_TIMEOUT, _check_import_mapping, _db_path, _load_assets
    global _load_server_cfg, _log_event, _map_import_columns, _save_asset
    global _secret_get, _secret_set
    APP_VERSION = app_version
    SYNC_SECRET_PATH = sync_secret_path
    _IMPORT_FIELDS = import_fields
    _IMPORT_LABELS = import_labels
    _LOG_DB_TIMEOUT = log_db_timeout
    _check_import_mapping = check_import_mapping
    _db_path = db_path
    _load_assets = load_assets
    _load_server_cfg = load_server_cfg
    _log_event = log_event
    _map_import_columns = map_import_columns
    _save_asset = save_asset
    _secret_get = secret_get
    _secret_set = secret_set
    # `global get_db` is a syntax error where `get_db` is also the
    # parameter, and the moved code calls it bare - so the module global is
    # set the one way left, exactly as `register_assets.bind()` sets it.
    globals()["get_db"] = get_db


# Another system already knows what hardware the department owns. This reads
# its list and reconciles it into the register - one direction, and a
# deliberately timid one. ADR-0014 is the argument; the short version is that
# this register is what rule 6 refuses Transactions against, so a remote system
# that could overwrite it silently is how an asset that has been transacted for
# a year becomes a different asset overnight.
#
# Three things this does not do, each written down here because each is a thing
# somebody will reach for:
#   - it never deletes. An asset the register has and the external system does
#     not is *reported*, because deleting it would take the Transactions' only
#     description of the thing they moved.
#   - it never overwrites a field the register has already filled in. It fills
#     empty ones and reports the rest as conflicts.
#   - it never writes outward. That is a different ticket and a different
#     argument about which system is authoritative.
#
# Identity is the identifiers, folded for case the way 025 folds them, and
# never a remote id: there is no column for one and adding one would be a
# second identity for a thing rule 3 says has exactly two.

# The whole conversation, bounded for _SMTP_TIMEOUT's reason with a little more
# room: this one is a list of every asset the department owns rather than one
# message.
_SYNC_TIMEOUT = 20
# What a payload may weigh before it is refused unread. A remote system that
# has started answering with something other than its asset list is the case
# this is for - reading it into memory first and finding out afterwards is what
# the cap avoids.
_SYNC_MAX_BYTES = 8 * 1024 * 1024
# How often the loop wakes to ask whether a run is due. The interval itself is
# the Admin's and is re-read from disk on every tick, so changing it takes
# effect without a restart, the same rule the notification rules follow.
_SYNC_TICK_SECS = 60
_SYNC_INTERVAL_DEFAULT = 60          # minutes; 0 means no scheduled run at all
_SYNC_AUTH_MODES = ("none", "bearer", "basic", "apikey")
# The header an apikey run sends the stored credential in. One spelling, here,
# because it is the whole of what tells that mode from a bearer one.
_SYNC_APIKEY_HEADER = "X-API-Key"
# How many names a System Log line carries before it says "and N more". A
# detail column is one line of context, not a report, and the report is what
# the console shows.
_SYNC_NAMES_IN_LINE = 8

_SYNC_NO_DPAPI = ("This machine cannot store a credential for the external "
                  "system: Windows DPAPI is not available here, which needs "
                  "pywin32. It is never written in plaintext instead. Choose "
                  "the None auth mode, or reach the system over a path that "
                  "needs no credential.")

# When the scheduled loop last ran, in this process. Not stored: a restart
# means the next run is one interval away rather than immediately, which is the
# right way round - a server that is being restarted repeatedly should not also
# be hammering somebody else's API.
_sync_state = {"last": 0.0, "running": False}
_sync_lock = threading.Lock()


def _sync_secret_set(credential):
    """Store the external system's credential, or clear it. "" or a refusal."""
    return _secret_set(SYNC_SECRET_PATH, "Asset Manager Sync", credential,
                       _SYNC_NO_DPAPI)


def _sync_secret_get():
    """The stored credential, or "". Never raises."""
    return _secret_get(SYNC_SECRET_PATH)


def _sync_secret_stored():
    """Whether one is on disk. The only thing about it the GUI is told."""
    return os.path.exists(SYNC_SECRET_PATH)


def _sync_cfg():
    """The sync settings, read from disk on every run.

    Not from the import-time _SERVER_CFG snapshot, for the reason _smtp_cfg is
    not: an Admin who has to restart the server to stop a sync that is fighting
    with the register will not reach for the setting in the situation that made
    them want it. The credential is not in here because it is not in that file
    at all (ADR-0014).
    """
    cfg = _load_server_cfg()
    mode = str(cfg.get("sync_auth", "none") or "none").strip().lower()
    try:
        every = int(cfg.get("sync_interval_mins", _SYNC_INTERVAL_DEFAULT))
    except (TypeError, ValueError):
        every = _SYNC_INTERVAL_DEFAULT
    mapping = cfg.get("sync_mapping", {})
    if not isinstance(mapping, dict):
        mapping = {}
    return {"base":     str(cfg.get("sync_base_url", "") or "").strip(),
            "path":     str(cfg.get("sync_list_path", "") or "").strip(),
            "list_key": str(cfg.get("sync_list_key", "") or "").strip(),
            "auth":     mode if mode in _SYNC_AUTH_MODES else "none",
            "username": str(cfg.get("sync_username", "") or "").strip(),
            "every":    max(0, every),
            # {field: the JSON key an Admin pinned}, empty where they left the
            # guess to do it. Held by name rather than by position for the
            # reason a spreadsheet import holds a column index: a payload's
            # keys are not ordered and the next answer may carry them the other
            # way round.
            "mapping":  dict((f, str(mapping.get(f, "") or "").strip())
                             for f in _IMPORT_FIELDS)}


def _sync_url(cfg=None):
    """The one URL this reads, or "". Joined here so nothing else guesses."""
    cfg = cfg or _sync_cfg()
    if not cfg["base"]:
        return ""
    return cfg["base"].rstrip("/") + "/" + cfg["path"].lstrip("/")


def _sync_fetch(cfg=None, opener=None):
    """Read the external system's asset list. Returns (records, error).

    Exactly one of the two is meaningful: a list of dicts, or a sentence saying
    why there is not one. Never raises - every caller is either a background
    thread nobody is watching or a dialog that wants the words rather than a
    traceback, which is _smtp_send_now's split and for the same reason.

    **`urllib.request`, not `requests`.** This file imports no HTTP client and
    `requests` is not in requirements-server.txt; adding it means re-vendoring
    a vendored `lib` pinned to one Python minor version (rule 13) for a
    standard library already covers.

    **TLS verification is never relaxed.** `ssl.create_default_context()` and
    nothing done to it afterwards - no `check_hostname = False`, no
    `CERT_NONE`. Rule 1 is worded for the clients but the reason is the same
    one, and this would be the first place in this repo to walk past it. What
    that costs is that an external system with a certificate nobody trusts is
    refused here, which is the same answer a client gets and is a thing to fix
    on that system rather than here.

    A credential is **never** sent over a plain `http://` base URL. The
    refusal names it rather than sending it anyway with a warning: a bearer
    token on the wire in clear is not a thing a warning undoes, and an internal
    network is exactly where somebody assumes otherwise.

    `opener` is for the gate, which drives this against a stub rather than a
    port, the way every other check here drives Flask's test client.
    """
    cfg = cfg or _sync_cfg()
    url = _sync_url(cfg)
    if not url:
        return [], "No external system is configured."
    scheme = url.split(":", 1)[0].lower()
    if scheme not in ("http", "https"):
        return [], ("Only http:// and https:// are read. %s is not a URL this "
                    "server fetches." % url)
    headers = {"Accept": "application/json",
               "User-Agent": "AssetManager/%s" % APP_VERSION}
    if cfg["auth"] != "none":
        if scheme != "https":
            return [], ("This base URL is http://, and the credential would "
                        "cross the network in clear. Point it at https://, or "
                        "choose the None auth mode.")
        secret = _sync_secret_get()
        if not secret:
            return [], ("No credential is stored for the external system. Set "
                        "one, or choose the None auth mode.")
        if cfg["auth"] == "bearer":
            headers["Authorization"] = "Bearer %s" % secret
        elif cfg["auth"] == "apikey":
            # The credential is the whole header value, unprefixed:
            # an API key is what the external system hands out, not a
            # scheme this server names.
            headers[_SYNC_APIKEY_HEADER] = secret
        else:
            pair = "%s:%s" % (cfg["username"], secret)
            headers["Authorization"] = "Basic %s" % base64.b64encode(
                pair.encode("utf-8")).decode("ascii")
    req = urllib.request.Request(url, headers=headers)
    try:
        get = opener or (lambda r, **kw: urllib.request.urlopen(
            r, context=ssl.create_default_context(), **kw))
        resp = get(req, timeout=_SYNC_TIMEOUT)
        try:
            raw = resp.read(_SYNC_MAX_BYTES + 1)
        finally:
            try:
                resp.close()
            except Exception:
                pass
    except urllib.error.HTTPError as ex:
        # The remote system's own words, for _smtp_send_now's reason: a 401 and
        # a 404 need entirely different things done about them, and "failed" is
        # the one answer nobody can act on.
        return [], "%s answered %s %s." % (url, ex.code, ex.reason)
    except Exception as ex:
        return [], "%s could not be read: %s" % (
            url, str(ex).strip() or ex.__class__.__name__)
    if len(raw) > _SYNC_MAX_BYTES:
        return [], ("The answer is larger than %d bytes and was not read. That "
                    "is not an asset list." % _SYNC_MAX_BYTES)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception as ex:
        return [], "The answer is not JSON: %s" % ex
    if cfg["list_key"]:
        if not isinstance(data, dict) or cfg["list_key"] not in data:
            return [], ("The answer carries no %r. That is the key the list "
                        "was said to be under." % cfg["list_key"])
        data = data[cfg["list_key"]]
    if not isinstance(data, list):
        return [], ("The answer is not a list of assets. Name the key the list "
                    "sits under if it is inside an object.")
    if data and not all(isinstance(r, dict) for r in data):
        return [], "The list holds something that is not an asset record."
    return data, ""


def _sync_keys(records):
    """Every key the payload uses, in the order it first showed one.

    JSON objects are not ordered the way a spreadsheet's columns are, and two
    records of one payload need not carry the same keys. The union is what the
    mapper is shown, so a field only some records carry is still offered.
    """
    seen, out = set(), []
    for r in records:
        for k in r:
            if k not in seen:
                seen.add(k)
                out.append(str(k))
    return out


def _sync_mapping(records, cfg=None):
    """{field: the JSON key it reads}, guessed and then overridden.

    **027's mapper, over JSON keys instead of spreadsheet headers.** The same
    helper, the same aliases and the same refusal to guess where it cannot,
    because an Asset Number is called the same things in a vendor's workbook
    and in a CMDB's JSON, and two importers disagreeing about that is what
    rule 10 exists to prevent. The keys are handed to it as a header row and
    what comes back as an index is turned back into the key's own name - the
    guess is then pinnable by an Admin as a name, which survives a payload that
    carries its keys in another order tomorrow.
    """
    cfg = cfg or _sync_cfg()
    keys = _sync_keys(records)
    guess = _map_import_columns(keys)
    out = {}
    for f in _IMPORT_FIELDS:
        pinned = cfg["mapping"].get(f, "")
        if pinned:
            # An Admin's answer stands even where the payload does not carry
            # that key today: a key that has gone missing is a thing to see in
            # the refusal, not to quietly re-guess around.
            out[f] = pinned
        else:
            i = guess.get(f)
            out[f] = keys[i] if i is not None else None
    return out


def _sync_rows(records, mapping):
    """The payload as the four fields this register holds. Nothing else."""
    out = []
    for rec in records:
        row = {}
        for f in _IMPORT_FIELDS:
            key = mapping.get(f)
            value = rec.get(key) if key else None
            row[f] = "" if value is None else str(value).strip()
        out.append(row)
    return out


def _sync_reconcile(rows, actor="Sync"):
    """Fold the external system's list into the register. Returns the report.

    Four answers and no fifth:

      **added** - an identifier the register has never seen. Written through
      `_save_asset`, the one writer, so an asset a sync adds and an asset an
      Admin types are held to exactly the same rules (rule 11, 025).

      **corrected** - the register holds the asset and one of its four fields
      is *empty* where the external system has something. Only then: a value
      this register already holds is what rule 6 refuses Transactions against,
      and a remote system overwriting it silently is the failure ADR-0014 is
      about.

      **conflict** - both hold the field and they disagree; or the record's two
      identifiers name two different assets here; or two records of one payload
      claim one identifier. Reported and **left alone** in every case. Which of
      two descriptions of one asset is right is not a decision an import gets
      to make, which is the answer 027 gives a file that collides with itself.

      **absent** - the register has it and the payload does not. Reported and
      **never deleted**: the Transactions already recorded against it carry no
      more than the identifiers, so removing it would take their only
      description of the thing they moved.

    A record that is not an asset by `_asset_shape_error` - one to be added, or
    one whose corrected fields still are not - is **skipped** with the reason,
    beside the records with no identifier at all (103).

    Every write is in **one transaction**. A refusal out of `_save_asset` -
    which at this point means a race with something else writing the register -
    aborts the whole run and leaves it exactly as it was, the answer 029 gives
    a batch and for the same reason: a half-applied sync is indistinguishable
    from a register somebody edited, and nothing says which half.
    """
    assets = _load_assets()
    by_id = dict((a["id"], a) for a in assets)
    index = {}
    for a in assets:
        for col in ("asset_number", "serial_number"):
            if a[col]:
                index[(col, a[col].lower())] = a["id"]
    report = {"seen": len(rows), "added": [], "corrected": [], "conflicts": [],
              "skipped": [], "absent": [], "matched": 0}
    # Every identifier the payload mentions, and how many records mention it.
    # Counted up front rather than as the rows are walked, so two records
    # claiming one identifier are refused as a **pair**: taking the first and
    # refusing the second would be this function deciding which of two
    # descriptions of one asset is the real one, which is exactly what 027
    # refuses to do with a file that collides with itself. It is also what
    # answers the absent list below - an asset named twice is still named.
    claimed = {}
    for row in rows:
        for col in ("asset_number", "serial_number"):
            if row[col]:
                key = (col, row[col].lower())
                claimed[key] = claimed.get(key, 0) + 1
    writes = []
    for n, row in enumerate(rows, 1):
        name = row["asset_number"] or row["serial_number"] or "record %d" % n
        if not row["asset_number"] and not row["serial_number"]:
            report["skipped"].append(
                "record %d has neither an Asset Number nor a Serial Number" % n)
            continue
        if not row["asset_type"]:
            report["skipped"].append("%s has no Asset Type" % name)
            continue
        hits, twice = set(), False
        for col in ("asset_number", "serial_number"):
            if not row[col]:
                continue
            key = (col, row[col].lower())
            if claimed.get(key, 0) > 1:
                twice = True
            if key in index:
                hits.add(index[key])
        if twice:
            report["conflicts"].append(
                "%s is in the external system's list twice, describing two "
                "assets - neither of them was taken" % name)
            continue
        if len(hits) > 1:
            report["conflicts"].append(
                "%s names two assets here (ids %s) - one record cannot be both"
                % (name, ", ".join(str(i) for i in sorted(hits))))
            continue
        if not hits:
            refused = _asset_shape_error(row["asset_number"],
                                         row["serial_number"],
                                         row["asset_type"])
            if refused:
                report["skipped"].append("%s - %s" % (name, refused))
                continue
            writes.append((None, row, name))
            report["added"].append(name)
            continue
        held = by_id[hits.pop()]
        report["matched"] += 1
        merged, changed, clashes = dict(held), [], []
        for f in _IMPORT_FIELDS:
            theirs, ours = row[f], (held[f] or "")
            if not theirs:
                continue
            if not ours:
                merged[f] = theirs
                changed.append(_IMPORT_LABELS[f])
            elif theirs.lower() != ours.lower():
                clashes.append("%s %r here, %r there"
                               % (_IMPORT_LABELS[f], ours, theirs))
        if clashes:
            # Reported whole rather than partly applied: an asset described two
            # ways is one disagreement to look at, not three fields to take
            # some of.
            report["conflicts"].append("%s - %s" % (name, "; ".join(clashes)))
            continue
        if changed:
            refused = _asset_shape_error(merged["asset_number"] or "",
                                         merged["serial_number"] or "",
                                         merged["asset_type"] or "")
            if refused:
                report["skipped"].append("%s - %s" % (name, refused))
                continue
            writes.append((held["id"], merged, name))
            report["corrected"].append("%s (%s)" % (name, ", ".join(changed)))
    for a in assets:
        there = any((col, a[col].lower()) in claimed
                    for col in ("asset_number", "serial_number") if a[col])
        if not there:
            report["absent"].append(a["asset_number"] or a["serial_number"])
    if writes:
        conn = get_db()
        try:
            for asset_id, row, _name in writes:
                _save_asset(row["asset_number"], row["serial_number"],
                            row["asset_type"], row["asset_model"],
                            asset_id=asset_id, actor=actor, conn=conn)
            conn.commit()
        finally:
            conn.close()
    return report


def _sync_summary(report):
    """One line saying what a run did. What the console shows and the log holds."""
    return ("%d seen · %d added · %d corrected · %d conflict(s) · %d skipped · "
            "%d in the register the external system does not have"
            % (report["seen"], len(report["added"]), len(report["corrected"]),
               len(report["conflicts"]), len(report["skipped"]),
               len(report["absent"])))


def _sync_names(names):
    """A few names and then a count. A detail column is one line of context."""
    if len(names) <= _SYNC_NAMES_IN_LINE:
        return "; ".join(names)
    return "%s; and %d more" % ("; ".join(names[:_SYNC_NAMES_IN_LINE]),
                                len(names) - _SYNC_NAMES_IN_LINE)


def _sync_run(actor="Sync", address="", opener=None):
    """One whole run. Returns (report or None, error). Never raises.

    The System Log is how a run reaches a mailbox: `sync.started`,
    `sync.added`, `sync.conflict` and `sync.failed` are ordinary events, and
    **031's rules** are what mails them. There is no mail code in here at all,
    which is the whole of this feature's dependency on that one.

    `sync.finished` is the fifth name and is the one the console reads. A run
    that changed nothing would otherwise write only `sync.started`, which is
    indistinguishable from a run that never came back - and "a scheduled job
    whose outcome is only in a log is a job nobody knows has been failing" is
    the thing this feature is not allowed to become.

    One run at a time. A hand-started run while the scheduled one is still
    reading is refused rather than queued: they would read the same list and
    race each other into the same rows, and the answer to wanting one now is
    the one already running.
    """
    with _sync_lock:
        if _sync_state["running"]:
            return None, ("A sync is already running. It is one at a time - "
                          "two would read the same list and race each other "
                          "into the same rows.")
        _sync_state["running"] = True
        # Here rather than in the loop, because what the interval spaces
        # out is reads of somebody else's API and a run started at the
        # console is one of those. It was the loop's alone, so Run now a
        # minute before the interval elapsed was answered by a scheduled
        # run a minute later - the thing _sync_loop's own docstring says
        # it is avoiding. Under the lock, beside the flag that decides
        # whether this is a run at all.
        _sync_state["last"] = time.time()
    try:
        cfg = _sync_cfg()
        url = _sync_url(cfg)
        _log_event("sync.started", "from %s" % (url or "nothing configured"),
                   actor=actor, address=address)
        records, err = _sync_fetch(cfg, opener=opener)
        if err:
            _log_event("sync.failed", err, actor=actor, level="error",
                       address=address)
            return None, err
        mapping = _sync_mapping(records, cfg)
        bad = _check_import_mapping(mapping)
        if bad:
            err = "%s The keys this answer carries are: %s." % (
                bad, ", ".join(_sync_keys(records)) or "none")
            _log_event("sync.failed", err, actor=actor, level="error",
                       address=address)
            return None, err
        try:
            report = _sync_reconcile(_sync_rows(records, mapping), actor=actor)
        except Exception as ex:
            # Nothing was written: the reconcile holds every write in one
            # transaction and commits at the end, so a refusal on the last row
            # leaves the register exactly as it was.
            err = ("The external system's list could not be reconciled and "
                   "nothing was written: %s"
                   % (str(ex).strip() or ex.__class__.__name__))
            _log_event("sync.failed", err, actor=actor, level="error",
                       address=address)
            return None, err
        if report["added"] or report["corrected"]:
            _log_event("sync.added",
                       "%d added, %d corrected from %s · %s"
                       % (len(report["added"]), len(report["corrected"]), url,
                          _sync_names(report["added"] + report["corrected"])),
                       actor=actor, level="warn", address=address)
        if report["conflicts"] or report["skipped"] or report["absent"]:
            _log_event("sync.conflict",
                       "%d left alone · %d skipped · %d not in the external "
                       "system · %s"
                       % (len(report["conflicts"]), len(report["skipped"]),
                          len(report["absent"]),
                          _sync_names(report["conflicts"]
                                      + report["skipped"])),
                       actor=actor, level="warn", address=address)
        _log_event("sync.finished", _sync_summary(report), actor=actor,
                   address=address)
        return report, ""
    finally:
        with _sync_lock:
            _sync_state["running"] = False


def _sync_last_run():
    """(ts, ok, detail) for the last run, or None. Derived, never stored.

    Off the System Log's own rows, the way `client_commands` derives `queued`
    and `collected` from two dates rather than keeping a status beside them: a
    stored "last run" would be a second copy of what those rows already say,
    and it is the copy that goes stale when a run dies between writing the row
    and updating the key.
    """
    try:
        # `_db_path()` rather than a bound `DB_PATH`: that name is a value
        # in `server.py`, resolved at import and re-pointed by
        # `tools/server-checks.py` between check groups, so a copy taken at
        # `bind()` would be the path as it was then. Every other name on
        # that list is a constant or a function.
        conn = sqlite3.connect(_db_path(), timeout=_LOG_DB_TIMEOUT)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT ts, event, detail FROM system_log WHERE event IN"
                " ('sync.finished','sync.failed') ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row:
        return None
    return (row["ts"], row["event"] == "sync.finished", row["detail"] or "")


def _sync_loop():
    """Background job: run the sync when the configured interval says to.

    The interval is re-read every tick rather than slept on, so an Admin who
    changes it - or switches it off with a 0 - is obeyed within the minute and
    without a restart. A server that has just started waits one interval before
    its first run: a machine being restarted repeatedly should not also be
    hammering somebody else's API.
    """
    # The seed, and only that: every run stamps this itself, so what this
    # line does is make a just-started server wait one interval before its
    # first.
    _sync_state["last"] = time.time()
    while True:
        try:
            cfg = _sync_cfg()
            if cfg["every"] and cfg["base"]:
                if time.time() - _sync_state["last"] >= cfg["every"] * 60:
                    _sync_run(actor="Sync (scheduled)")
        except Exception:
            pass
        time.sleep(_SYNC_TICK_SECS)
