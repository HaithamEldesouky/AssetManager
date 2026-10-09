"""
Asset Manager — Asset Server
- HTTP / HTTPS (internal domain network)
- SQLite database
- Admin password protected settings
- Asset lookup from the assets table, exchanged as asset_lookup.xlsx
- Minimises to system tray
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import sqlite3, json, os, sys, socket, threading, time, hashlib, base64, io, ctypes
import atexit
import contextlib
import hmac
import secrets
# Nothing in this file sends mail since #224 - `server_mail.py` does, and
# imports `smtplib` itself. This one stays because `tools/server-checks.py`
# reaches the module through `M.smtplib` to put a stub SMTP in front of four
# checks; a module object is shared, so that patch is what the send in
# `server_mail.py` actually meets.
import smtplib
from datetime import datetime, timedelta

# The window kit shared with the two clients: the palette tables, the live
# retint, and the button row that lays itself out against the width it actually
# has. Safe to import here despite this module having to stay importable
# headless - ui_kit imports tkinter inside its functions for the same reason
# server_gui.py does. What is left to use it here, since #207 moved the console
# out, is _make_server_tray_icon's icon below - server_gui.py imports ui_kit
# again for its own windows.
import ui_kit

# The certificate lifecycle - staging, pushing, the cutover and the export
# (ADR-0020). Its own module since #206: it is called both from the routes
# above and from the Server GUI below, so it could not stay inside the window
# code it sat in. Names are imported flat because every call site here, route
# and window alike, was written against them. It draws nothing, so this import
# is safe at module level; bind() below hands it the paths and the helpers.
import server_cert
from server_cert import (CERT_ERROR_DAYS, CERT_NEXT_DAYS, CERT_WARN_DAYS,
                         _bind_cert_command, _cert_expiry, _cert_expiry_check,
                         _cert_expiry_loop, _cert_fingerprint, _cert_names,
                         _cert_to_pem, _clients_behind_staged, _cut_over_cert,
                         _export_public_cert, _push_next_cert,
                         _stage_new_cert)

# Is there an IIS in front of this process, and what has it bound - its
# own module since #243, lifted out of here and server_cert.py together:
# neither is about certificates alone, and this is what #224-#229 have
# been emptying server.py into. Imported flat for server_cert.py's own
# reason: every call site, route and window alike, was written against
# the bare names, and server_gui.py reaches _iis_host and _iis_tls_bound
# as S.<name>. It draws nothing, so this import is safe at module level;
# bind() below hands it BASE_DIR, PORT and IIS_STATE_PATH.
import server_iis
from server_iis import (_bind_port_command, _iis_host, _iis_tls_bound,
                        _iis_served_undetected, _port_serves_tls,
                        _recycle_pool_command, _remote_tls_ok)

# The four functions that read and write the `assets` table, and the refusal
# `_save_asset` raises - their own module since #215, for the reason #206 gave
# the certificate lifecycle one: the routes here and the Server GUI's three
# asset windows both call them, so they belong to neither. Imported flat
# because every call site, route and window alike, was written against the
# bare names, and `server_gui.py` reaches them as `S.<name>` off this module.
# It draws nothing and opens no connection of its own, so this import is safe
# at module level; bind() below hands it `get_db` and `_log_event`.
import register_assets
from register_assets import (_IDENTIFIER_TAKEN, _asset_key_sql, _delete_asset,
                             _load_assets, _save_asset)

# And the four that read and write the `transactions` table - their own module
# since #216, for the reason the two above have one: eleven routes here and the
# Server GUI's Manage Records call the same writers, so they belong to neither.
# It is the module 041 had to land before, because the newest-per-asset rule
# asks `register_assets` which asset a row is about rather than re-deriving it.
# Imported flat because every call site, route and window alike, was written
# against the bare names, and `server_gui.py` reaches them as `S.<name>` off
# this module. It draws nothing and opens no connection of its own, so this
# import is safe at module level; bind() below hands it the thirteen names the
# moved code reads here.
import register_transactions
from register_transactions import (_cancel_transaction, _create_transaction,
                                   _modify_transaction, _pending_rows)

# And the six that read and write the `team_members` table - their own module
# since #217, the last third of the one Register 039 (#210) named and the one
# it named first: nineteen routes here and the Server GUI's Manage Users call
# the same six, so they belong to neither. Nothing in it asks the other two
# registers anything - an Engineer carries no asset identity - so it could
# have been written before 042 as easily as after it. Imported flat because
# every call site, route and window alike, was written against the bare names,
# and `server_gui.py` reaches them as `S.<name>` off this module. `_KEEP` is
# imported back with them: it is a sentinel compared by identity and
# `_save_member`'s signature defaults to it, so it is defined there and read
# here rather than the other way round. It draws nothing and opens no
# connection of its own, so this import is safe at module level; bind() below
# hands it the ten names the moved code reads here.
import register_engineers
from register_engineers import (_KEEP, _delete_member, _member_row,
                                _member_row_by_id, _member_rows,
                                _rename_member, _save_member)

# Mail, and which System Log entries reach a mailbox - their own module since
# #224, the first of the six clusters 046 (#220) named and left in this file.
# Two banners that were one concern: a rule is what says an event is worth
# mailing and `_send_mail` is the only thing that can send it, and neither
# half is the routes' or the console's. The three `/admin/mail*` and
# `/admin/notify_rules` routes stay here, `server_gui.py`'s Mail Settings and
# Notification Rules windows reach it as `S.<name>`, and
# `tools/server-checks.py` drives most of it directly. Imported flat because
# every call site, route and window alike, was written against the bare names.
# `_secret_set` and `_secret_get` did not go with it - they are the generic
# stored-secret pair and the external asset system is the other caller - so
# they are on the `bind()` list below rather than in that module. It draws
# nothing and opens nothing of its own, so this import is safe at module
# level; bind() further down hands it the eight names the moved code reads
# here.
import server_mail
from server_mail import (_NOTIFY_HOURLY_MAX, _NOTIFY_MIN_SECS,
                         _SMTP_PORT_DEFAULT, _notify_gate, _notify_of,
                         _notify_rules, _notify_state, _save_mail_settings,
                         _save_notify_rules, _send_mail, _send_mail_worker,
                         _send_test_mail, _smtp_cfg, _smtp_secret_get,
                         _smtp_secret_set, _smtp_secret_stored,
                         _smtp_send_now)

# The external asset system - its own module since #225, the second of the
# six clusters 046 (#220) named and left in this file. One direction and a
# deliberately timid one (ADR-0014): it reads another system's asset list
# and folds it into the Assets register, never deletes, never overwrites a
# field this register has already filled in, and never writes outward. No
# route here reaches it at all - `server_gui.py`'s Asset Sync window calls
# all of it as `S.<name>`, `_start_background_jobs` below starts
# `_sync_loop`, and `tools/server-checks.py` drives it against a stubbed
# opener. Imported flat because every call site was written against the
# bare names. `_sync_admin_cfg` did **not** go with it: it shares the
# prefix and nothing else, being the helper that re-reads
# `admin_config.json` where a second process has written it, and it stays
# beside the credential it is about. It draws nothing and opens nothing of
# its own, so this import is safe at module level; bind() further down
# hands it the fifteen names the moved code reads here.
import server_sync
from server_sync import (_SYNC_AUTH_MODES, _SYNC_NO_DPAPI, _sync_cfg,
                         _sync_fetch, _sync_keys, _sync_last_run,
                         _sync_loop, _sync_mapping, _sync_names,
                         _sync_reconcile, _sync_rows, _sync_run,
                         _sync_secret_get, _sync_secret_set,
                         _sync_secret_stored, _sync_state, _sync_summary,
                         _sync_url)

# The registry of installations - its own module since #226, the third of
# the six clusters 046 (#220) named and left in this file. What every
# Client machine says about itself and what may be said back to it: the
# check-in, the command vocabulary and the queue behind it, the registry as
# the console reads it, and the stale sweep. **The five `/clients*` routes
# did not go with it** - this was the one cluster of the six whose routes
# sat inside its own banner, and #226 split that banner where the first
# `@app.route` starts, which is the shape 041-043 took and leaves `@app`,
# `@door` and `jsonify` out of that module entirely. `server_gui.py`'s
# Connected Clients window reaches it as `S.<name>`, `server_cert.bind()`
# below is handed four of its function objects, and
# `tools/server-checks.py` drives the queue, the status and the sweep
# directly. Imported flat because every call site, route and window alike,
# was written against the bare names. It draws nothing and opens nothing of
# its own, so this import is safe at module level; bind() further down
# hands it the seven names the moved code reads here.
import server_clients
from server_clients import (CLEAR_AGE_DEFAULT_DAYS, CLEAR_AGE_MIN_DAYS,
                            COMMANDS, COMMAND_LABELS, COMMAND_TTL_DAYS,
                            _APP_PACKAGE_KEY, _CHECKIN_FIELDS, _CHECKIN_MAX,
                            _CHECKIN_MEMBER_AT, _COMMAND_CONFLICTS,
                            _clear_stale_clients, _client_rows,
                            _client_sweep_loop, _command_rows,
                            _command_status, _format_age_threshold,
                            _parse_age_threshold, _queue_command,
                            _record_checkin, _stale_clients)

# The System Log - its own module since #227, the fourth of the six clusters
# 046 (#220) named and left in this file. The one writer every act in this
# build passes through, the words a row reads as, the readers the console's
# System Log window draws with, the clear behind its button, the batch a
# Client ships, and the two retention bounds with the hourly job that
# applies them. **`POST /clients/log` did not go with it** - its handler is
# still here and calls `_record_log` in there, which is the shape #226 gave
# the `/clients*` routes and 041-043 gave the three registers, and it leaves
# `@app`, `@door`, `DOOR_OPEN`, `request` and `jsonify` out of that module
# entirely. Imported flat because every call site - this file's, the
# window's, the other modules' `bind()` lists and the gate's - was written
# against the bare names, and because `_log_event` has to be a live object
# here before the block that hands it to `server_cert`, the three registers
# and `server_gui`. It draws nothing and opens nothing of its own, so this
# import is safe at module level; bind() further down hands it the three
# names the moved code reads here.
import server_log
from server_log import (EVENT_SENTENCES, LOG_COMPONENTS, LOG_LEVELS,
                        LOG_MAX_ROWS, LOG_RETENTION_DAYS, _DIFF_HEAD,
                        _DIFF_PART, _DIFF_TAIL, _LOG_BATCH_MAX,
                        _LOG_DB_TIMEOUT, _LOG_DETAIL_MAX, _LOG_FIELD_MAX,
                        _log_clear, _log_client, _log_diff, _log_entry,
                        _log_event, _log_event_names, _log_retention_loop,
                        _log_rows, _log_trim, _record_log, event_phrase,
                        event_sentence)
# Backup, restore, the schema migrations and the archive - their own module
# since #228, the fifth of the six clusters 046 (#220) named and left in this
# file. Two banners that are one concern: a backup is a copy of this
# install's state and a restore puts it back, a migration is what makes a
# copy an older build took fit to be put back at all, and the archive is the
# same act one table down. **No route went with it** - there is no
# `@app.route` in the moved block at all, and `POST /records/import` here
# calls `_import_records_xlsx` in, which is the shape #226 and #227 gave
# their own routes. `server_gui.py`'s Backup and Restore window and its
# Manage Records reach nine of these as `S.<name>`, the `migrate` verb of
# `__main__` below calls `_migrate_cli`, and `tools/server-checks.py` drives
# the backup, the restore and the migrations directly. Imported flat because
# every call site, route and window alike, was written against the bare
# names. **The three `os.path.join(BASE_DIR, ...)` constants the moved block
# defined stayed here**, above: computing them inside that module's `bind()`
# would take them out of `tools/cascade-audit.py`'s `BESIDE_MODULES` scan,
# and `CERT_ROLLBACK_DIR` is read by `server_cert.py` alone anyway. It draws
# nothing and opens nothing of its own, so this import is safe at module
# level; bind() further down hands it the twelve names the moved code reads
# here.
import server_archive
from server_archive import (BACKUP_EXCLUDED, BACKUP_KIND,
                            BACKUP_MANIFEST_NAME, _ARCHIVE_COLS, _backup_db,
                            _backup_members, _export_log_xlsx,
                            _export_records_xlsx, _import_records_xlsx,
                            _latest_schema_version, _log_cell, _migrate_cli,
                            _migration_files, _read_backup_manifest,
                            _restore_backup, _restore_preflight,
                            _restore_target, _schema_version, _sha256_file,
                            _take_backup, _verify_backup, run_migrations)
# The asset lookup's write path and the proposals - their own module since
# #229, the last of the six clusters 046 (#220) named and left in this file.
# How an asset gets into the Assets register and how one is asked for: the
# embedded sheet a first run writes, the workbook both directions of the
# interchange format use, the column mapping and the row verdicts an import
# is decided by, the proposals a Client raises and the Admin answers
# (ADR-0017), and the three readers every caller asks what the sheet says.
# **None of the nine routes went with it** - `/lookup`, `/asset_types`,
# `/asset_models`, `/lookup/file`, `/lookup/upload`, `/assets/propose`,
# `/assets/import/preview`, `/assets/proposals` and
# `/assets/proposals/decide` are all still here and call in, which is the
# shape #226, #227 and #228 gave their own. `server_gui.py`'s Manage Assets
# and Asset Proposals windows reach it as `S.<name>` and
# `tools/server-checks.py` drives the mapping, the verdicts, the proposals
# and the decisions directly. Imported flat because every call site, route
# and window alike, was written against the bare names - and because five
# of those names have to be live objects before `register_transactions.
# bind()` and `server_sync.bind()` further down, each of which is handed
# some of them. **`DEFAULT_LOOKUP_B64` did not go with it** (rule 11): the
# workbook stays embedded here with the two doors that update it, and
# travels over `bind()`. The three `register_assets` names the moved code
# reads are **not** on that list either - that module is imported from
# there directly, the way `register_transactions.py` takes
# `_asset_key_sql`. It draws nothing and opens nothing of its own, so this
# import is safe at module level; bind() further down hands it the five
# names the moved code reads here.
import server_lookup
from server_lookup import (PROPOSAL_STATUSES, _AssetRefused,
                           _IMPORT_ALIASES, _IMPORT_COLUMNS_MAX,
                           _IMPORT_FIELDS, _IMPORT_LABELS,
                           _PROPOSAL_BATCH_MAX, _PROPOSAL_PENDING,
                           _asset_models, _check_import_mapping,
                           _check_swapped_columns, _decide_proposal,
                           _ensure_sample_lookup,
                           _import_assets, _import_file_rows, _import_key,
                           _load_lookup_table, _load_proposals,
                           _lookup_asset_types, _lookup_xlsx_bytes,
                           _map_import_columns, _propose_asset,
                           _propose_batch, _replace_assets,
                           _seed_assets_if_empty, _validate_import_rows,
                           _xlsx_asset_rows)

# pywin32 — optional; required only for Windows Service mode
try:
    import win32serviceutil, win32service, win32event, servicemanager
    HAS_WIN32SVC = True
except ImportError:
    HAS_WIN32SVC = False

# The other half of pywin32, guarded separately from the Service half above.
# Separately because they are needed for different things and a source install
# may reasonably have neither: without the first this server cannot run as a
# Windows Service, and without this one it cannot store a mail password at all
# - which is a refusal rather than a fallback, for the reason ADR-0013 gives.
try:
    import win32crypt
    HAS_DPAPI = True
except ImportError:
    HAS_DPAPI = False

try:
    import pystray
    # pillow is checked through ui_kit rather than imported here: the drawing
    # these two lines used to feed moved there, and a tray with no image to
    # put in it is not a tray.
    HAS_TRAY = ui_kit.HAS_PIL
except ImportError:
    HAS_TRAY = False

def _make_server_tray_icon(online=None):
    """The product icon, at the size a Windows tray asks for.

    The artwork is `ui_kit`'s: this file and `notifier_app.py` each held a
    byte-identical copy of a crude one drawn here, which is what rule 10 is
    about. No badge - the Notifier's badge means transactions are waiting on
    that engineer, and nothing waits on this process. `online` draws the
    status dot instead - green while the server is answering, red while it is
    not, and no dot at all for `None`, the CHECKING moment before anything has
    been asked. `set_health` is the only caller that passes a real answer, and
    it reads the same `online` it writes the tray title from, so the light and
    the title can never disagree about what was asked.
    """
    return ui_kit.app_icon(64, status={True: "online", False: "offline"}.get(online))

APP_VERSION = "2.10.1"   # bump when releasing a new build; clients compare against this

app = Flask(__name__)
CORS(app)

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Every one of these is beside the server and stays there. The database is
# the exception: it is the only file here an admin may want on another drive,
# so DB_PATH is resolved below once server_config.json has been read. Nothing
# else moves with it - the lookup sheet, the certificate and the two config
# files are part of the install, not part of the data.
DB_DEFAULT_PATH = os.path.join(BASE_DIR, "assets.db")
ADMIN_CFG_PATH  = os.path.join(BASE_DIR, "admin_config.json")
SERVER_CFG_PATH = os.path.join(BASE_DIR, "server_config.json")
LOOKUP_PATH     = os.path.join(BASE_DIR, "asset_lookup.xlsx")
SSL_CERT_PATH   = os.path.join(BASE_DIR, "ssl_cert.pem")
SSL_KEY_PATH    = os.path.join(BASE_DIR, "ssl_key.pem")
# The next certificate, generated at the console and bound to nothing (C1,
# ADR-0020). Named beside the live pair rather than in a directory of their
# own, because what makes them safe is that no reader of the live names ever
# resolves these: the listener is bound to SSL_CERT_PATH, GET /cert serves
# SSL_CERT_PATH, and every client pins what GET /cert answered.
SSL_CERT_NEXT_PATH = os.path.join(BASE_DIR, "ssl_cert_next.pem")
SSL_KEY_NEXT_PATH  = os.path.join(BASE_DIR, "ssl_key_next.pem")
# tools\install-iis.ps1 writes this when it binds the site, and it is the
# only thing on the machine that says IIS owns this process rather than the
# AssetManagerServer service - see _iis_host below.
IIS_STATE_PATH  = os.path.join(BASE_DIR, "iis.json")
# The SMTP password, encrypted. A file of its own rather than a key in
# server_config.json, which is read-modify-written by install-iis.ps1, by
# installer.py and by dev-run.ps1 - none of which should ever be holding a
# ciphertext it might rewrite. See ADR-0013 and the Mail section below.
# What a backup or a restore leaves on disk while it runs, so a write that
# arrives mid-copy is refused rather than landing in a file that is about to be
# replaced. A file of its own rather than a key in server_config.json, which
# install-iis.ps1 and installer.py both read-modify-write: a server held shut
# by a value one of those could rewrite is a server shut for a reason nobody
# typed. See ADR-0018.
MAINTENANCE_PATH = os.path.join(BASE_DIR, "maintenance.json")
SMTP_SECRET_PATH = os.path.join(BASE_DIR, "smtp_secret.dat")
# The external asset system's credential, encrypted the same way and for the
# same reason: a bearer token or a basic-auth password is replayed on every
# sync, so it has to be readable back. A file of its own rather than a second
# value in smtp_secret.dat - the mail relay and the external system are
# unrelated, and clearing one must not be able to take the other with it. See
# ADR-0014 and the Sync section below.
SYNC_SECRET_PATH = os.path.join(BASE_DIR, "sync_secret.dat")

# Where the migration engine looks for the numbered steps it runs.
MIGRATIONS_DIR = os.path.join(BASE_DIR, "migrations")

# Where a restore puts the files it is about to replace, before it replaces
# them - `update.ps1`'s `rollback\<version>\` one level down, and for its
# reason: the moment worth having a copy at is the moment before the write,
# not after somebody has noticed. One directory per restore, so a second
# restore does not overwrite what the first set aside.
RESTORE_ASIDE_DIR = os.path.join(BASE_DIR, "restore_aside")

# Where a cutover puts the pair it is about to replace (C4, ADR-0020). One
# generation, which is `update_rollback\` beside a client rather than
# `restore_aside\` above: a restore is a rare, deliberate act whose earlier
# copies are worth keeping, while what is here is a **private key**, and every
# generation kept is another copy of the one file that must never travel
# (rule 1). The generation that is kept is the pair that was live a moment
# ago, which is the only one anything could be rolled back to.
CERT_ROLLBACK_DIR = os.path.join(BASE_DIR, "cert_rollback")

# Server GUI display settings. Both are bounded, and the refresh bound is the
# load-bearing one: that same tick is the liveness probe behind the banner, so
# a long interval would leave the window captioned LIVE while showing
# minute-old state - a banner lying about being healthy is the exact defect
# this GUI was rebuilt to remove.
FEED_LIMIT_DEFAULT,   FEED_LIMIT_RANGE   = 18, (5, 200)
REFRESH_SECS_DEFAULT, REFRESH_SECS_RANGE = 5, (2, 60)


def _load_server_cfg():
    # feed_limit and refresh_secs drive the Server GUI only. They live here
    # rather than in a per-user file because the GUI may be the Windows
    # Service's monitor front-end, opened by whoever is at the console - the
    # setting belongs to the machine, not to a login.
    default = {"host": "0.0.0.0", "port": 8081,
               "feed_limit": FEED_LIMIT_DEFAULT,
               "refresh_secs": REFRESH_SECS_DEFAULT,
               # system / dark / light. Belongs to the machine for the same
               # reason the two above do - this window may be the Service's
               # monitor front-end, opened by whoever is at the console.
               "theme": "system",
               # Clear Old's threshold (#268), in days - `_client_sweep_loop`
               # re-reads this key every hour, so it belongs beside the other
               # settings a background job applies without a restart.
               "clear_age_threshold_days": server_clients.CLEAR_AGE_DEFAULT_DAYS}
    if os.path.exists(SERVER_CFG_PATH):
        try:
            with open(SERVER_CFG_PATH) as f:
                d = json.load(f)
            default.update(d)
        except Exception:
            pass
    return default

_SERVER_CFG = _load_server_cfg()
HOST = _SERVER_CFG["host"]
PORT = _SERVER_CFG["port"]


# Is there an IIS in front of this process, and what has it bound - its
# own module since #243, the shape #224-#229 already gave everything
# else server.py used to hold alone. Three names come over through
# server_iis.bind(), all of them already resolved above: BASE_DIR at
# this file's import, IIS_STATE_PATH beside it, PORT two lines up.
server_iis.bind(base_dir=BASE_DIR, port=PORT, iis_state_path=IIS_STATE_PATH)


def _validate_port(value):
    """Return (port, error_message). Exactly one of the two is None."""
    try:
        port = int(str(value).strip())
    except (ValueError, TypeError):
        return None, "Port must be a number between 1 and 65535."
    if not (1 <= port <= 65535):
        return None, "Port must be a number between 1 and 65535."
    return port, None


DRIVE_REMOTE = 4        # what GetDriveTypeW returns for a mapped network share


def _validate_db_path(value):
    """Return (absolute_path, error_message). Exactly one of the two is None.

    Same contract as _validate_port and _validate_range, so all three read the
    same way at the call site.

    Local paths only, and that is not caution. SQLite's locking is built on
    advisory locks that an SMB redirector emulates rather than honours, so two
    writers on one share do not see each other's locks and interleave the file
    instead of queueing - the corruption is silent and the backup is on the
    same share. A UNC path is refused on its text; a mapped drive is refused by
    asking Windows what kind of drive it is, because the letter says nothing.
    """
    p = str(value or "").strip().strip('"')
    if not p:
        return None, "The database path cannot be empty."
    if p.startswith("\\\\") or p.startswith("//"):
        return None, ("A network path is not allowed. SQLite cannot lock a file "
                      "over SMB, so two writers would corrupt it. Use a local "
                      "drive.")
    if not os.path.isabs(p):
        return None, ("The database path must be absolute, e.g. "
                      "D:\\AssetManager\\assets.db - a relative path would "
                      "resolve against whatever directory started the process, "
                      "which is not the same one for the Service, IIS and the "
                      "GUI.")
    # Tested before normpath, which strips a trailing separator and would turn
    # "D:\AssetManager\" into something that reads like a filename.
    if p.endswith("\\") or p.endswith("/"):
        return None, "The database path must name a file, not a folder."
    p = os.path.normpath(p)
    if os.path.isdir(p):
        return None, "The database path must name a file, not a folder."
    try:
        drive = os.path.splitdrive(p)[0]
        if drive and ctypes.windll.kernel32.GetDriveTypeW(
                drive + os.sep) == DRIVE_REMOTE:
            return None, ("%s is a mapped network drive. SQLite cannot lock a "
                          "file over SMB, so two writers would corrupt it. Use "
                          "a local drive." % drive)
    except Exception:
        # Not Windows, or the drive cannot be queried. The textual UNC check
        # above still stands; this one is the part that cannot be spotted by
        # reading the path.
        pass
    return p, None


# Resolved here rather than beside the other paths because it needs both
# _SERVER_CFG and the validator above. A configured path that does not validate
# does NOT fall back to the default: that would give a server quietly writing
# to a different file than the one the admin configured. The error is kept and
# _require_db refuses to start.
DB_PATH, _DB_CFG_VALUE, _DB_CFG_ERROR = DB_DEFAULT_PATH, "", None
_DB_CFG_VALUE = str(_SERVER_CFG.get("db_path", "") or "").strip()
if _DB_CFG_VALUE:
    _db_resolved, _DB_CFG_ERROR = _validate_db_path(_DB_CFG_VALUE)
    if _db_resolved:
        DB_PATH = _db_resolved


def _require_db():
    """Return a message explaining why the server must not start, else None.

    Called explicitly at each of the three entry points rather than from inside
    init_db(), so there is no bypass clause to get wrong: init_db() also runs
    against a fresh install and from the checker, where creating the file is
    exactly right.

    A configured database that is not there prevents startup, naming the path.
    Creating an empty one instead would give a server that starts cleanly,
    reports healthy, shows no records and takes a day's work into a file nobody
    opens again - while the real database, wherever it went, is the one
    everybody believes they are looking at.

    The default path is exempt: nothing is configured, so a missing file is a
    first run and init_db() makes it, exactly as it always has.
    """
    if _DB_CFG_ERROR:
        return ("server_config.json names a database that cannot be used.\n\n"
                "    db_path:  %s\n\n%s\n\n"
                "Fix db_path in server_config.json, or remove it to use\n"
                "    %s"
                % (_DB_CFG_VALUE, _DB_CFG_ERROR, DB_DEFAULT_PATH))
    if DB_PATH != DB_DEFAULT_PATH and not os.path.exists(DB_PATH):
        return ("The configured database does not exist.\n\n"
                "    %s\n\n"
                "server_config.json points here through db_path. The server "
                "will not create a database at a configured path: it would "
                "start, report healthy, show no records, and take a day's work "
                "into a file nobody opens again.\n\n"
                "Move the database to that path, or remove db_path from "
                "server_config.json to use\n    %s"
                % (DB_PATH, DB_DEFAULT_PATH))
    return None


# The non-GET endpoints that stay open while writes are held, and the one
# property they share: none of them writes anything a backup or a restore is
# about. `admin_verify` and `auth_verify` check a password - the second's
# in-place hash upgrade is best effort already and never turns a correct
# password into a refusal - and `preview_import` answers what a file would
# become without writing a row of it.
#
# Written as the set that stays **open** rather than the set that is refused,
# because the two are not symmetrical: a new endpoint nobody thought about must
# default to being held, not to being let through. `tools/server-checks.py`
# fails a non-GET route that is in neither.
MAINTENANCE_OPEN = frozenset((
    "admin_verify",
    "auth_verify",
    "preview_import",
))

# One `write.held` row per client per endpoint per window, keyed on the window
# the state was entered at. Two failures rather than one behind this: a held
# `POST /clients/log` answered with a log row is a refusal that writes what it
# refused, and every client retries on its own tick, so a ten-minute restore
# would fill the table it is restoring. The first refusal is what an Admin
# needs to see; the hundredth says nothing the first did not.
_HELD_SEEN = set()


def _maintenance_state():
    """What is holding writes right now, or None.

    Read from disk on every request, the way `_storekeeper_can_cancel` is and
    for a sharper version of its reason: what enters this state is an operation
    running on a worker in this same process, and a request arriving a moment
    later has to see it rather than a snapshot taken at import.

    An absent, unreadable or shapeless file means **no maintenance**, which is
    the behaviour before this existed. That is deliberately the opposite answer
    from `admin_config.json`'s raise: a stray byte in this file must not be a
    server that refuses every write with nothing able to say why, and the state
    it describes is a few minutes long where a credential is permanent.
    """
    try:
        with io.open(MAINTENANCE_PATH, encoding="utf-8-sig") as f:
            got = json.load(f)
    except Exception:
        return None
    if not isinstance(got, dict) or not got.get("what"):
        return None
    return got


def _maintenance_enter(what, actor="Admin (Server GUI)"):
    """Hold every write while `what` runs.

    On disk rather than in a module global, and that is the half worth saying
    why about: a crash in the middle of a backup then leaves something an Admin
    can look at and a next start can report, where an in-memory flag would
    leave a half-copied file and no record that anything had been running. What
    stops that record becoming a server nobody can write to again is
    `_maintenance_clear_stale` below.
    """
    state = {"what": what, "since": datetime.now().isoformat(),
             "pid": os.getpid(), "actor": actor}
    with io.open(MAINTENANCE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    _log_event("maintenance.entered", what, actor=actor, level="warn")
    return state


def _maintenance_leave(actor="Admin (Server GUI)"):
    """Take the hold off. Safe to call when there is none."""
    state = _maintenance_state()
    try:
        os.remove(MAINTENANCE_PATH)
    except OSError:
        pass
    if state:
        _HELD_SEEN.discard(state.get("since"))
        _log_event("maintenance.left", state.get("what") or "", actor=actor)
    return state


@contextlib.contextmanager
def _maintenance(what, actor="Admin (Server GUI)"):
    """Hold writes for the length of a block, whatever happens inside it.

    A context manager rather than two calls at each site, because the failure
    it removes is the one that matters: an operation that raises half way
    through and leaves the server refusing writes until somebody restarts it.
    """
    _maintenance_enter(what, actor)
    try:
        yield
    finally:
        _maintenance_leave(actor)


def _maintenance_clear_stale():
    """A server that has just started is not in the middle of a backup.

    The state is on disk so a crash mid-operation is visible rather than
    silent - and the price of that is a file outliving the process that wrote
    it, which would be a server refusing every write for ever with nothing
    saying why. This is the one moment such a file is **known** to be stale, so
    it is cleared here and the clearing is written down rather than being done
    quietly.

    Called from `_start_background_jobs`, which is the one thing all three
    serving modes go through and the monitor-only GUI deliberately does not: a
    window watching somebody else's listener has no business clearing that
    process's state while the operation is still running.
    """
    state = _maintenance_state()
    if not state:
        return None
    try:
        os.remove(MAINTENANCE_PATH)
    except OSError:
        pass
    _log_event("maintenance.left",
               "%s - left behind by a process that is no longer running, "
               "cleared at start" % (state.get("what") or "?"),
               actor=str(state.get("actor") or ""), level="warn")
    return state


def _storekeeper_can_cancel():
    """May a caller with no admin password cancel a Transaction?

    Read from disk on every call rather than from _SERVER_CFG, because the whole
    point of the switch is that turning it off takes effect on the next request
    - an admin who has to restart the server to withdraw a permission will not
    reach for it in the situation that made them want it.

    A missing key means allowed, which is the behaviour before this existed.
    Anything already deployed therefore keeps working unchanged, and an
    admin_config-style raise is wrong here: a server_config.json that predates
    the key is normal, not corrupt.
    """
    return bool(_load_server_cfg().get("storekeeper_can_cancel", True))


def _storekeeper_can_add_engineer():
    """May a caller with no admin password create an Engineer? (ADR-0017)

    The shape `_storekeeper_can_cancel` has and for its reasons: read from disk
    on every call, so withdrawing it takes effect on the next request rather
    than on the next restart; and a missing key means allowed, a
    server_config.json that predates it being normal rather than corrupt.

    **Creating only.** What this hands over is the ability to create a name
    that Transactions are then recorded against, which is a smaller thing than
    it sounds beside `POST /transactions` being unauthenticated on purpose
    (ADR-0002) - the Storekeeper can already record a movement without any
    credential, and this stops them having to go and find an Admin to be able
    to name the person it was for. Editing one is a different act: the Access
    Profile decides what an Engineer's own client shows them and an Own
    Password is a credential somebody can then be that Engineer with, so both
    stay where 013 put them, at the console, behind the admin password.
    """
    return bool(_load_server_cfg().get("storekeeper_can_add_engineer", True))


def _storekeeper_cancel_window_mins():
    """How long after it was created may an auto-approved Transaction be
    cancelled with no password at all? (#198)

    Read from disk on every call, the two switches above being the precedent
    and the reason theirs: an Admin who has to restart the server to withdraw a
    window will not reach for the setting in the situation that made them want
    to.

    **An absent key means zero**, which is deliberately the other answer from
    the two beside it, and the difference is what the setting is. A switch that
    is not written down means the freedom that was there before it existed; a
    *duration* that is not written down is no window at all - there is no
    length a server that has never been told one could be said to have meant.
    Zero is also how it is switched off, so the file and the form say the same
    thing by one number rather than by a number and a flag.

    Anything that is not a whole number of minutes, and anything below zero,
    reads as off: this opens a door, so the answer to a value nobody can make
    sense of is the closed one.
    """
    try:
        mins = int(_load_server_cfg().get("storekeeper_cancel_window_mins", 0)
                   or 0)
    except (TypeError, ValueError):
        return 0
    return mins if mins > 0 else 0


# The name every Transaction recorded before this setting existed carries, and
# the column default in the schema below. The two have to agree: a row written
# by an old client and a row written by a server with no name configured are
# the same fact, and reading them as two different storekeepers would split one
# person's history in half.
STOREKEEPER_DEFAULT = "Storekeeper User"


def _storekeeper_name():
    """Who the Storekeeper is, as this server states it.

    Read from disk on every call for the reason _storekeeper_can_cancel gives:
    a name corrected on the console has to reach the next request, not the next
    restart. It is a setting rather than a row in team_members - the Storekeeper
    is never the recipient of a Transaction, so a row would put them in every
    Engineer dropdown and every one of the seven readers of that table would
    need to learn to skip it (see the Manage Users note in CLAUDE.md).

    An empty or missing value means STOREKEEPER_DEFAULT, so a server_config.json
    written before this key existed is normal rather than corrupt - the same
    answer storekeeper_can_cancel gives.
    """
    return ((_load_server_cfg().get("storekeeper_name") or "").strip()
            or STOREKEEPER_DEFAULT)


def _storekeeper_actor(name=None):
    """The System Log label for an act by the Storekeeper.

    The suffix is a log label and never a stored column: `storekeeper` and
    `cancelled_by` both record the name alone, and the role in brackets is what
    makes an entry read as an act by the person who holds the store rather than
    as a bare name beside an Engineer's. One function so the acts a Storekeeper
    takes on a row - creating one and cancelling one - cannot word it
    differently. The Storekeeper client words it a third time, in `sk_actor()`:
    the server does not import `common.py` (rule 10), so there is nowhere for
    one copy to live, and `cascade-audit.py` holds the two spellings to
    matching instead.

    `name` is optional because `_cancel_transaction` can arrive with an empty
    one - a row written before anything populated its `storekeeper` column has
    nothing to attribute a cancel to - and this server's own name is the
    truthful answer there, the unauthenticated cancel path being the
    Storekeeper's alone.
    """
    return "%s (Storekeeper)" % (name or _storekeeper_name())


def _validate_range(value, lo, hi, label):
    """Return (int, error_message). Exactly one of the two is None.

    Same contract as _validate_port, so both read the same way at the call
    site and neither can be mistaken for returning a bare value.
    """
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return None, "%s must be a number between %d and %d." % (label, lo, hi)
    if not (lo <= n <= hi):
        return None, "%s must be between %d and %d." % (label, lo, hi)
    return n, None


def _save_server_cfg(_actor=None, **changes):
    """Merge changes into server_config.json, keeping every other key.

    `_actor` is who the entry below is attributed to and is **not** written to
    the file: the leading underscore is what keeps it out of the arbitrary keys
    this takes, since every other name here becomes a setting. Left None it is
    the Admin, which is what every caller but the two delegable dialogs is.

    Overwriting the whole file drops ssl_enabled, which silently turns HTTPS off
    on the next restart. The cert files stay on disk so nothing looks wrong until
    a client fails to verify.

    Takes arbitrary keys rather than a fixed host/port pair. The two SSL paths in
    the GUI used to read-modify-write this file themselves, which survived only
    because _load_server_cfg merges over a two-key default - so the first setting
    added beyond those two would have been erased by whichever writer saved next.
    Every writer goes through here.
    """
    cfg = _load_server_cfg()
    cfg.update(changes)
    with open(SERVER_CFG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    # Every writer of this file comes through here, so this one line covers the
    # endpoint, the Server Settings window, the Database Location dialog and
    # the Storekeeper Cancel switch. Only the keys that change what the server
    # *does*: feed_limit, refresh_secs and theme change what this window shows,
    # and a line every time somebody drags the refresh slider is how a log stops
    # being read.
    told = {k: v for k, v in changes.items()
            if k in ("host", "port", "db_path", "ssl_enabled",
                     "storekeeper_can_cancel", "storekeeper_can_add_engineer",
                     "storekeeper_cancel_window_mins", "storekeeper_name",
                     "clear_age_threshold_days")}
    if told:
        _log_event("server.config_changed",
                   ", ".join("%s=%s" % (k, told[k]) for k in sorted(told)),
                   actor=_actor or "Admin (Server GUI)", level="warn",
                   data=dict(told, changed=", ".join(sorted(told))))
    return cfg


def _port_in_use(port):
    """Return True if another process already owns the port.

    Uses an exclusive *bind* test (SO_EXCLUSIVEADDRUSE on Windows) rather than a
    connect probe. A connect probe fails when the owning server is listening but
    wedged/slow — which previously let a second instance conclude the port was
    free and start a duplicate listener. A bind test checks OS-level ownership
    regardless of whether the owner is responsive."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        s.bind(("", port))
        return False          # bind succeeded → nobody owns the port
    except OSError:
        return True           # bind failed → port already owned
    finally:
        s.close()


def _acquire_single_instance_mutex():
    """
    Create a Global Named Mutex so only one interactive GUI process runs.
    Returns True if this process is the first (mutex created fresh).
    Returns False if another GUI instance already holds it.
    Only meaningful on Windows; always returns True on other platforms.
    """
    if sys.platform != "win32":
        return True
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, True,
                                                      "Global\\AssetManagerServer_GUI")
        err = ctypes.windll.kernel32.GetLastError()
        # ERROR_ALREADY_EXISTS == 183
        return err != 183
    except Exception:
        return True  # can't check → allow


ASSET_TYPES = ["Laptop", "Desktop", "Mobile", "Tablet", "Screen", "UPS", "Server",
               "Cisco Phone", "Printer", "Scanner", "Switch"]

# ─── Embedded default lookup (asset_lookup.xlsx shipped with the app) ─────────
DEFAULT_LOOKUP_B64 = (
    "UEsDBBQAAAAIADCJSV1Gx01IlQAAAM0AAAAQAAAAZG9jUHJvcHMvYXBwLnhtbE3PTQvCMAwG4L9S"
    "dreZih6kDkQ9ip68zy51hbYpbYT67+0EP255ecgboi6JIia2mEXxLuRtMzLHDUDWI/o+y8qhiqHk"
    "e64x3YGMsRoPpB8eA8OibdeAhTEMOMzit7Dp1C5GZ3XPlkJ3sjpRJsPiWDQ6sScfq9wcChDneiU+"
    "ixNLOZcrBf+LU8sVU57mym/8ZAW/B7oXUEsDBBQAAAAIADCJSV1P4EZ37wAAACsCAAARAAAAZG9j"
    "UHJvcHMvY29yZS54bWzNksFqwzAMhl9l+J7ISUahJvVlpacNBits7GZstTWLY2NrJH37OVmbMrYH"
    "2NHS70+fQK0OQvuIz9EHjGQx3Y2u65PQYcNOREEAJH1Cp1KZE31uHnx0ivIzHiEo/aGOCDXnK3BI"
    "yihSMAGLsBCZbI0WOqIiHy94oxd8+IzdDDMasEOHPSWoygqYnCaG89i1cANMMMLo0ncBzUKcq39i"
    "5w6wS3JMdkkNw1AOzZzLO1Tw9vT4Mq9b2D6R6jXmX8kKOgfcsOvk1+Zhu98xWfN6VVS84Ot9dS/4"
    "WjT1++T6w+8m7LyxB/uPja+CsoVfdyG/AFBLAwQUAAAACAAwiUldmVycIxAGAACcJwAAEwAAAHhs"
    "L3RoZW1lL3RoZW1lMS54bWztWltz2jgUfu+v0Hhn9m0LxjaBtrQTc2l227SZhO1OH4URWI1seWSR"
    "hH+/RzYQy5YN7ZJNups8BCzp+85FR+foOHnz7i5i6IaIlPJ4YNkv29a7ty/e4FcyJBFBMBmnr/DA"
    "CqVMXrVaaQDDOH3JExLD3IKLCEt4FMvWXOBbGi8j1uq0291WhGlsoRhHZGB9XixoQNBUUVpvXyC0"
    "5R8z+BXLVI1lowETV0EmuYi08vlsxfza3j5lz+k6HTKBbjAbWCB/zm+n5E5aiOFUwsTAamc/VmvH"
    "0dJIgILJfZQFukn2o9MVCDINOzqdWM52fPbE7Z+Mytp0NG0a4OPxeDi2y9KLcBwE4FG7nsKd9Gy/"
    "pEEJtKNp0GTY9tqukaaqjVNP0/d93+ubaJwKjVtP02t33dOOicat0HgNvvFPh8Ouicar0HTraSYn"
    "/a5rpOkWaEJG4+t6EhW15UDTIABYcHbWzNIDll4p+nWUGtkdu91BXPBY7jmJEf7GxQTWadIZljRG"
    "cp2QBQ4AN8TRTFB8r0G2iuDCktJckNbPKbVQGgiayIH1R4Ihxdyv/fWXu8mkM3qdfTrOa5R/aasB"
    "p+27m8+T/HPo5J+nk9dNQs5wvCwJ8fsjW2GHJ247E3I6HGdCfM/29pGlJTLP7/kK6048Zx9WlrBd"
    "z8/knoxyI7vd9lh99k9HbiPXqcCzIteURiRFn8gtuuQROLVJDTITPwidhphqUBwCpAkxlqGG+LTG"
    "rBHgE323vgjI342I96tvmj1XoVhJ2oT4EEYa4pxz5nPRbPsHpUbR9lW83KOXWBUBlxjfNKo1LMXW"
    "eJXA8a2cPB0TEs2UCwZBhpckJhKpOX5NSBP+K6Xa/pzTQPCULyT6SpGPabMjp3QmzegzGsFGrxt1"
    "h2jSPHr+BfmcNQockRsdAmcbs0YhhGm78B6vJI6arcIRK0I+Yhk2GnK1FoG2camEYFoSxtF4TtK0"
    "EfxZrDWTPmDI7M2Rdc7WkQ4Rkl43Qj5izouQEb8ehjhKmu2icVgE/Z5ew0nB6ILLZv24fobVM2ws"
    "jvdH1BdK5A8mpz/pMjQHo5pZCb2EVmqfqoc0PqgeMgoF8bkePuV6eAo3lsa8UK6CewH/0do3wqv4"
    "gsA5fy59z6XvufQ9odK3NyN9Z8HTi1veRm5bxPuuMdrXNC4oY1dyzcjHVK+TKdg5n8Ds/Wg+nvHt"
    "+tkkhK+aWS0jFpBLgbNBJLj8i8rwKsQJ6GRbJQnLVNNlN4oSnkIbbulT9UqV1+WvuSi4PFvk6a+h"
    "dD4sz/k8X+e0zQszQ7dyS+q2lL61JjhK9LHMcE4eyww7ZzySHbZ3oB01+/ZdduQjpTBTl0O4GkK+"
    "A226ndw6OJ6YkbkK01KQb8P56cV4GuI52QS5fZhXbefY0dH758FRsKPvPJYdx4jyoiHuoYaYz8ND"
    "h3l7X5hnlcZQNBRtbKwkLEa3YLjX8SwU4GRgLaAHg69RAvJSVWAxW8YDK5CifEyMRehw55dcX+PR"
    "kuPbpmW1bq8pdxltIlI5wmmYE2eryt5lscFVHc9VW/Kwvmo9tBVOz/5ZrcifDBFOFgsSSGOUF6ZK"
    "ovMZU77nK0nEVTi/RTO2EpcYvOPmx3FOU7gSdrYPAjK5uzmpemUxZ6by3y0MCSxbiFkS4k1d7dXn"
    "m5yueiJ2+pd3wWDy/XDJRw/lO+df9F1Drn723eP6bpM7SEycecURAXRFAiOVHAYWFzLkUO6SkAYT"
    "Ac2UyUTwAoJkphyAmPoLvfIMuSkVzq0+OX9FLIOGTl7SJRIUirAMBSEXcuPv75Nqd4zX+iyBbYRU"
    "MmTVF8pDicE9M3JD2FQl867aJguF2+JUzbsaviZgS8N6bp0tJ//bXtQ9tBc9RvOjmeAes4dzm3q4"
    "wkWs/1jWHvky3zlw2zreA17mEyxDpH7BfYqKgBGrYr66r0/5JZw7tHvxgSCb/NbbpPbd4Ax81Kta"
    "pWQrET9LB3wfkgZjjFv0NF+PFGKtprGtxtoxDHmAWPMMoWY434dFmhoz1YusOY0Kb0HVQOU/29QN"
    "aPYNNByRBV4xmbY2o+ROCjzc/u8NsMLEjuHti78BUEsDBBQAAAAIADCJSV1dUGUdgAMAAHgOAAAY"
    "AAAAeGwvd29ya3NoZWV0cy9zaGVldDEueG1sjZfbc5s4FIf/FQ1P24eUi/ElHdszDm6b7iRdJm53"
    "+yrDsdFGIFaS6+S/r4QI8bY6TF9sLuc78InbT8uzkI+qAtDkqeaNWgWV1u27MFRFBTVVb0ULjdlz"
    "ELKm2qzKY6haCbTsoJqHSRTNwpqyJlgvu225XC/FSXPWQC6JOtU1lc83wMV5FcTBy4YHdqy03RCu"
    "ly09wg701zaXZi0cupSshkYx0RAJh1Wwid9t44kFuoq/GZzVxTKxKnshHu3Kp3IVRPaMgEOhbQtq"
    "/r5DBpzbTuY8/uubBsMxLXi5/NL9QydvZPZUQSb4P6zU1SpYBKSEAz1x/SDOt9ALTW2/QnDV/ZKz"
    "q02igBQnpUXdw+YMata4f/rUD8QlkCBA0gPJT0CcIsCkByY/H2GGAGkPpN3IOJVuHLZU0/VSijOR"
    "ttp0swvdYHa00WeNve47Lc1eZji93ihlbq7Pp3oPchlq09FuD4uevhmndyAZ5Tie/c7Bvzy34GG3"
    "v8PeixL4/+HQjMAwDMkwDAnSJ46i2CeO1e8+XyFIhiF3tNWi9SlixNY8B+SOaqZPJZDpNI1GHCeD"
    "4wR3THyOWL1z9CEZhuCOGHGbk/ecabgx7wSySCPyMR6zTAfLFLec+CyxemfpQzIM2YJ6RDRxxFzK"
    "v1rNcg5PZB6NSk4HySkumfoksXon6UMyFCkkQONzxIjOMU/SJLkdkZsNcjNcbuqTw+qdnA/JMORe"
    "7Bn3vm7Qg9BanZoj+Ug5fXomm2k64jgfHOe448zniNU7Rx+SYcgXuuegfY4YsWlbDoTltCR/xJGu"
    "yBGaNyOai0FzgWvOfZpYvdP0IRmGfM13PkesfJNn5IYWj1eGI7Pp2GN4Pehd43oLnx5W7/R8SIYi"
    "IL97P6pbjHCPoTiDfF8egTzMRyXj6DUiRLjmtTcVYIDz9DEZymRMFYLklWj8MWCc+5Q7lMwXaTym"
    "e5GIsEwR//J27nXR/GN1vUyGMrlkjfZfWJQx38o7E27lnyby5FKQ+zRKy2bM9jX4xHjyib3JBwWc"
    "rTf64ExBmwaxxZgPp3+ZVidi2V1DW8K+xbNo9F5+zUAxHoJibwhCAafrTUE4c2a6qLy2GOJu48yE"
    "d/6sNEmuZ9HVN59reJHy7ZzsnsojaxThcDCNo7dz83mWbprjVkxS6fLzXmgzjegWKzM1BGkLzP6D"
    "EPplxc4lhsnm+gdQSwMEFAAAAAgAMIlJXfLpLjqyAgAANAsAAA0AAAB4bC9zdHlsZXMueG1s3Vbb"
    "jpswEP0VxAcUEloaqiRSSxVppbZaKVupr04wxJIv1JhVsl9fj00gF89q28eCIuw5PmcuHkOWnTlx"
    "uj1QaqKj4LJbxQdj2k9J0u0PVJDunWqptEittCDGTnWTdK2mpOqAJHgyT9M8EYTJeL2UvdgI00V7"
    "1UuzitM4WS9rJSfLPPYGu5QIGj0TvopLwtlOM7eWCMZP3jwHw15xpSNjQ6GreAaW7sXDMz+DKAcd"
    "waTSYEy8h1s/W9ooGv18gCW7QWTyoZudDTjduOvKUXqh6R6d1Wacj0llsTesly0xhmq5sRPHccY7"
    "KBrGT6fWZtVocprNP8RvJnSKswpcNuVl5Gn6cfH1vZO5oI6i7mEj3yldUT3GPovPpvWS09pYumbN"
    "AZ5GtVApZYwSdlAx0ihJXGJnxjCwsnvK+RZ66Vd9pX2sI98UDxX0QwT1Ow9tQMPQy/gJ6F+qee0L"
    "2fk/yUYte1bmS2+zkW7+u1eGPmpas6ObH+vRP6Y+m9TnN+qkbfnpM2eNFNTn/maH6yU586KD0uzF"
    "eoPG21sD9Q19rIeijPVw1bmq9GiNoOVX8Q84sXxyE+16xg2Tw+zAqorKu4JbeUN29pVwpW/XV7Qm"
    "PTdPI7iKp/F3WrFeFOOqR0h9WDWNv0FjzfLxzFlfTFb0SKtymNpWvulpuIBwi0zn9B7BOB4LI4Bh"
    "frAIMI5nYX7+p3wWaD4ew2JbBJEFylmgHM8KIaW7MT9hTmGvcKZFkWV5jlW0LIMRlFjd8hx+YTUs"
    "NmBgfsDT39Ua3228Q17vA2xPX+sQLFO8E7FM8VoDEq4bMIoivNuYH2Bgu4D1DvgP+4GeCnOyDHYV"
    "iw07wThSFBgCvRju0TxHqpPDHd4f7JRkWVGEEcDCEWQZhsBpxBEsAogBQ7LMfQdvvkfJ+TuVTP+T"
    "138AUEsDBBQAAAAIADCJSV2XirscwAAAABMCAAALAAAAX3JlbHMvLnJlbHOdkrluwzAMQH/F0J4w"
    "B9AhiDNl8RYE+QFWog/YEgWKRZ2/r9qlcZALGXk9PBLcHmlA7TiktoupGP0QUmla1bgBSLYlj2nO"
    "kUKu1CweNYfSQETbY0OwWiw+QC4ZZre9ZBanc6RXiFzXnaU92y9PQW+ArzpMcUJpSEszDvDN0n8y"
    "9/MMNUXlSiOVWxp40+X+duBJ0aEiWBaaRcnToh2lfx3H9pDT6a9jIrR6W+j5cWhUCo7cYyWMcWK0"
    "/jWCyQ/sfgBQSwMEFAAAAAgAMIlJXdv5o+o4AQAAKQIAAA8AAAB4bC93b3JrYm9vay54bWyNUdFK"
    "w0AQ/JVwH2DSogVLI4hFLRQtVvp+TTbN0rvbsLdptV/vJiFY8MWnvZ1dZmfmFmfi457omHx5F2Ju"
    "apFmnqaxqMHbeEMNBJ1UxN6KtnxIY8Ngy1gDiHfpNMtmqbcYzMNi5Npwet2QQCFIQcEO2CGc4++8"
    "a5MTRtyjQ/nOTf92YBKPAT1eoMxNZpJY0/mVGC8UxLptweRcbibDYAcsWPyBt53IT7uPPSJ2/2FV"
    "SG5mmRJWyFH6jZ7fqsYT6PLQtULP6AR4aQVemNoGw6GjURfplY0+h7EOIc75PzFSVWEBSypaD0GG"
    "HBlcJzDEGptokmA95OYxRmVe68m26WzpnVU5WBTVdhUYz1EHvCoHlaO0EioMUL4pW1RcYyo2nHSl"
    "55ne3k3uNY7WuSfF3sOabDk6HX/p4QdQSwMEFAAAAAgAMIlJXSQem6KtAAAA+AEAABoAAAB4bC9f"
    "cmVscy93b3JrYm9vay54bWwucmVsc7WRPQ6DMAyFrxLlADVQqUMFTF1YKy4QBfMjEhLFrgq3L4UB"
    "kDp0YbKeLX/vyU6faBR3bqC28yRGawbKZMvs7wCkW7SKLs7jME9qF6ziWYYGvNK9ahCSKLpB2DNk"
    "nu6Zopw8/kN0dd1pfDj9sjjwDzC8XeipRWQpShUa5EzCaLY2wVLiy0yWoqgyGYoqlnBaIOLJIG1p"
    "Vn2wT06053kXN/dFrs3jCa7fDHB4dP4BUEsDBBQAAAAIADCJSV1lkHmSGQEAAM8DAAATAAAAW0Nv"
    "bnRlbnRfVHlwZXNdLnhtbK2TTU7DMBCFrxJlWyUuLFigphtgC11wAWNPGqv+k2da0tszTtpKoBIV"
    "hU2seN68z56XrN6PEbDonfXYlB1RfBQCVQdOYh0ieK60ITlJ/Jq2Ikq1k1sQ98vlg1DBE3iqKHuU"
    "69UztHJvqXjpeRtN8E2ZwGJZPI3CzGpKGaM1ShLXxcHrH5TqRKi5c9BgZyIuWFCKq4Rc+R1w6ns7"
    "QEpGQ7GRiV6lY5XorUA6WsB62uLKGUPbGgU6qL3jlhpjAqmxAyBn69F0MU0mnjCMz7vZ/MFmCsjK"
    "TQoRObEEf8edI8ndVWQjSGSmr3ghsvXs+0FOW4O+kc3j/QxpN+SBYljmz/h7xhf/G87xEcLuvz+x"
    "vNZOGn/mi+E/Xn8BUEsBAhQAFAAAAAgAMIlJXUbHTUiVAAAAzQAAABAAAAAAAAAAAAAAAIABAAAA"
    "AGRvY1Byb3BzL2FwcC54bWxQSwECFAAUAAAACAAwiUldT+BGd+8AAAArAgAAEQAAAAAAAAAAAAAA"
    "gAHDAAAAZG9jUHJvcHMvY29yZS54bWxQSwECFAAUAAAACAAwiUldmVycIxAGAACcJwAAEwAAAAAA"
    "AAAAAAAAgAHhAQAAeGwvdGhlbWUvdGhlbWUxLnhtbFBLAQIUABQAAAAIADCJSV1dUGUdgAMAAHgO"
    "AAAYAAAAAAAAAAAAAAC2gSIIAAB4bC93b3Jrc2hlZXRzL3NoZWV0MS54bWxQSwECFAAUAAAACAAw"
    "iUld8ukuOrICAAA0CwAADQAAAAAAAAAAAAAAgAHYCwAAeGwvc3R5bGVzLnhtbFBLAQIUABQAAAAI"
    "ADCJSV2XirscwAAAABMCAAALAAAAAAAAAAAAAACAAbUOAABfcmVscy8ucmVsc1BLAQIUABQAAAAI"
    "ADCJSV3b+aPqOAEAACkCAAAPAAAAAAAAAAAAAACAAZ4PAAB4bC93b3JrYm9vay54bWxQSwECFAAU"
    "AAAACAAwiUldJB6boq0AAAD4AQAAGgAAAAAAAAAAAAAAgAEDEQAAeGwvX3JlbHMvd29ya2Jvb2su"
    "eG1sLnJlbHNQSwECFAAUAAAACAAwiUldZZB5khkBAADPAwAAEwAAAAAAAAAAAAAAgAHoEQAAW0Nv"
    "bnRlbnRfVHlwZXNdLnhtbFBLBQYAAAAACQAJAD4CAAAyEwAAAAA="
)

# ─── Passwords ────────────────────────────────────────────────────────────────

# Every password this server stores - the admin password, each capability
# password, each Engineer's Own Password - goes through the pair below and
# nowhere else. They used to be bare unsalted SHA-256, which is one rainbow
# table for every machine this app has ever been installed on: no salt, no work
# factor, and passwords a human chose. See ADR-0008.
#
# The stored value is self-describing - "pbkdf2_sha256$<iterations>$<salt>$<hash>"
# - so the format can be changed again without renaming a JSON key or a DB
# column, and so a value read off disk says how to check it rather than being
# guessed at. pbkdf2_hmac is standard library: nothing here may add a dependency,
# because requirements-server.txt feeds a vendored lib\ pinned to one Python
# minor version (rule 13).
PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 200_000
PBKDF2_SALT_BYTES = 16

# The shortest password this server will store: the admin password and an
# Engineer's Own Password are held to the same bound. One constant rather than
# the literal 4 it was in two endpoints, now that a third asks the same
# question - an Own Password the Engineer chooses themselves must not end up
# held to a looser bound than the admin password by an edit nobody noticed.
# CAPABILITY_MIN stays its own number: a delegation bound is a different rule,
# and ADR-0006 argues it separately.
PASSWORD_MIN = 4


def hash_password(password: str) -> str:
    """The stored form of a new password. The only place a new hash is made."""
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", (password or "").encode(), salt,
                                 PBKDF2_ITERATIONS)
    return "%s$%d$%s$%s" % (PBKDF2_ALGO, PBKDF2_ITERATIONS, salt.hex(),
                            digest.hex())


def password_matches(password: str, stored: str) -> bool:
    """True when `password` is the password `stored` was made from.

    Two formats are accepted, deliberately: the salted one above and a bare
    64-character hex SHA-256, which is what every install written before
    ADR-0008 holds. An install cannot be asked to reset the admin password to
    take an update, and there is no migration step for a hash the server only
    ever sees one password at a time for - so the verifier reads both and the
    callers below rewrite a legacy value on the verification that proved it.

    An empty stored value is "no password set" and matches nothing, whatever
    was sent: `has_password` false on an Engineer must not mean the empty
    string opens their Settings. A stored value in neither format matches
    nothing either - a corrupt hash is not a password anyone can be asked for.
    """
    stored = stored or ""
    candidate = (password or "").encode()
    if stored.startswith(PBKDF2_ALGO + "$"):
        # Compared as bytes rather than hex text: compare_digest refuses a
        # non-ASCII str, and every field here comes off disk, where a corrupt
        # value must be a refusal rather than a 500.
        try:
            _, iterations, salt, digest = stored.split("$")
            calc = hashlib.pbkdf2_hmac("sha256", candidate,
                                       bytes.fromhex(salt), int(iterations))
            want = bytes.fromhex(digest)
        except ValueError:
            return False
        return hmac.compare_digest(calc, want)
    if _is_legacy_hash(stored):
        # Lowercased because _is_legacy_hash accepts either case while
        # hexdigest() only ever produces one: without this, an upper-case
        # legacy value would be recognised as legacy and then never match,
        # which is a lockout dressed up as a wrong password.
        return hmac.compare_digest(hashlib.sha256(candidate).hexdigest(),
                                   stored.lower())
    return False


_HEX = set("0123456789abcdefABCDEF")


def _is_legacy_hash(stored: str) -> bool:
    """A bare unsalted SHA-256 hex digest, the pre-ADR-0008 stored form.

    The charset is spelled out rather than left to int(stored, 16), which
    accepts non-ASCII digits - and a non-ASCII stored value would then reach
    compare_digest, which raises on one.
    """
    stored = stored or ""
    return len(stored) == 64 and all(c in _HEX for c in stored)


def _upgrade_stored_hash(stored, password, rewrite):
    """Rewrite a legacy hash in the salted format, on the use that proved it.

    This is what drains an install of legacy hashes with nobody being asked to
    do anything: each password is rehashed the first time it is used, because
    that is the only moment the server knows the plaintext.

    It is called from a *verify* path, so it must never turn a correct password
    into a refusal: a failed write - a read-only config file, a locked database
    - leaves the legacy hash in place to be upgraded on the next use, and that
    is strictly better than refusing an admin who typed their password
    correctly. Hence the bare except, which is the point of this helper
    existing rather than the three callers each holding one.
    """
    if not _is_legacy_hash(stored):
        return
    try:
        rewrite(hash_password(password))
    except Exception:
        pass

# ─── Admin config ─────────────────────────────────────────────────────────────

# What admin_config.json looked like the last time this process read it,
# so _sync_admin_cfg below can tell a file somebody else wrote from the
# one this process is already holding. A list rather than a bare global
# so the two writers below can set it without declaring it.
_ADMIN_CFG_STAMP = [None]


def _admin_cfg_stamp():
    """(mtime, size) of admin_config.json, or None where there is no file."""
    try:
        st = os.stat(ADMIN_CFG_PATH)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def load_admin_cfg():
    """Load admin_config.json, merged over the defaults.

    The merge is what lets a later build add a key without every install that
    already exists failing on it: the file on disk was written before that key
    existed, and this used to hand it back verbatim.

    A malformed file still raises, deliberately. Falling back to the defaults on
    a bad read would silently reset the admin password to its install-time value
    - the only credential this server has, quietly downgraded by a corrupt file.
    """
    cfg = {"first_run": True, "capability_hashes": {},
           "capability_holders": {}}
    existed = os.path.exists(ADMIN_CFG_PATH)
    if existed:
        with open(ADMIN_CFG_PATH) as f:
            cfg.update(json.load(f))
        # A file from before capability passwords has no key at all, which the
        # merge above handles. One with a key of the wrong shape is malformed,
        # and this file raises on malformed rather than falling back: silently
        # reading {} out of a corrupt map would drop every delegation the Admin
        # had made without saying so.
        if not isinstance(cfg.get("capability_hashes"), dict):
            raise ValueError("admin_config.json: capability_hashes must be an "
                             "object of capability -> hash")
        # The holder names beside them (R1), read the same way and for a
        # weaker version of the same reason: a corrupt map here costs the
        # names in every `remote.action` entry written afterwards, which is
        # the whole of what ADR-0015's identity half buys. A file written
        # before this existed has no key and the merge above answers for it.
        if not isinstance(cfg.get("capability_holders"), dict):
            raise ValueError("admin_config.json: capability_holders must be "
                             "an object of capability -> name")
    # The install-time default is hashed here rather than in the literal above
    # because hashing is deliberately slow now (ADR-0008) and this function
    # runs at import: a normal file has its own hash, and paying 200,000
    # rounds to build a value that is then thrown away is work for nothing.
    # Keyed on the key being *absent*, not falsy - a file that says
    # "password_hash": "" is saying nothing opens this server, and turning
    # that into the default would hand it back to the word "admin".
    if "password_hash" not in cfg:
        cfg["password_hash"] = hash_password("admin")
    if not existed:
        save_admin_cfg(cfg)
    _ADMIN_CFG_STAMP[0] = _admin_cfg_stamp()
    return cfg

def save_admin_cfg(cfg):
    with open(ADMIN_CFG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    # This process wrote it, so what is on disk is what is in memory:
    # stamping here is what stops _sync_admin_cfg reading this process's
    # own write back in on the next request.
    _ADMIN_CFG_STAMP[0] = _admin_cfg_stamp()


def _update_admin_cfg(**changes):
    """Write `changes` into admin_config.json, and into ADMIN_CFG once it lands.

    The order is the whole of this function. Every caller used to set the key
    on ADMIN_CFG and then save, so a write that failed left the credential
    changed in memory and unchanged on disk, with nothing said at the time -
    and an install directory the console account cannot write to is exactly
    how that happens. The admin then typed their correct current password into
    Change Admin Password, was told it was incorrect - because the in-memory
    hash was by then the one nobody had been told about - and found the old
    password working again after a restart, which is the disk copy coming
    back. Saving first means a failed write changes nothing anywhere: the
    exception reaches the caller with the credential still what it was.

    ADMIN_CFG is updated in place rather than rebound, because every endpoint
    and every dialog reads it through the module global.
    """
    # So the read-modify-write is over what is on disk now. Two processes
    # hold this file across the supported deployments, and a console
    # writing a capability password out of a stale copy would put back the
    # admin password hash it was still holding.
    _sync_admin_cfg()
    cfg = dict(ADMIN_CFG)
    cfg.update(changes)
    save_admin_cfg(cfg)
    ADMIN_CFG.update(changes)

ADMIN_CFG = load_admin_cfg()


def _sync_admin_cfg():
    """Re-read admin_config.json where something else has written it.

    The credential was a snapshot taken at import, which is right for the
    one deployment where the console *is* the server and wrong for both
    supported ones. Under IIS (ADR-0001) and under the Windows Service the
    Server GUI is a second process and monitor-only, so Change Admin
    Password wrote the new hash to disk and into the console's own memory
    while the process actually serving went on checking every request
    against the hash it read at start: the console accepted the new
    password, the network went on accepting the old one, and it stayed
    that way until the app pool was recycled. What sees that is every door
    on the wire - `POST /admin/verify` above all, which is what the
    installer asks before it will stand up a Storekeeper, so an install
    done after the password was changed was still let in by the
    install-time "admin" and refused the password the Admin had set. The
    same gap points the other way, a legacy hash the serving process
    rewrote on use (ADR-0008) being invisible to the console.

    It is `storekeeper_can_cancel`'s rule applied to the credential - a
    thing an Admin changes must not need a restart to take effect - and it
    is a **stat** rather than a re-read, so the ordinary request pays one
    stat against a file that has not moved and the read happens on the
    change alone. Re-reading outright would put a file open and a JSON
    parse behind every door in this file for an answer that is the same
    one for months at a time.

    A file that has gone unreadable or malformed **leaves the in-memory
    copy exactly as it was**, which is not load_admin_cfg's raise pointing
    the other way: that one refuses to fall back to the install-time
    default, and this one refuses to fall back to anything at all. The
    stamp is taken before the read, so a bad file is read once rather than
    on every request behind it.
    """
    stamp = _admin_cfg_stamp()
    if stamp is None or stamp == _ADMIN_CFG_STAMP[0]:
        return
    _ADMIN_CFG_STAMP[0] = stamp
    try:
        fresh = load_admin_cfg()
    except Exception:
        return
    # In place rather than rebound, for _update_admin_cfg's reason: every
    # endpoint and every dialog reads this through the module global. An
    # update rather than a clear and an update, because this runs on a
    # request thread and app.run(threaded=True) means another one can be
    # reading the map between the two: what the loader hands back always
    # carries all four keys, having merged over the defaults, so there is
    # nothing a clear removes and a moment with no password_hash in it is
    # a KeyError at a door that should have answered.
    ADMIN_CFG.update(fresh)


def _admin_password_ok(candidate) -> bool:
    """True when `candidate` is the admin password. The one door to it.

    Every site that used to compare sha256(candidate) against
    ADMIN_CFG['password_hash'] by hand comes through here, so the legacy
    upgrade happens on every admin verification rather than on whichever ones
    somebody remembered - and there is one place to read when the question is
    what opens this server.

    An empty or missing password is refused before anything is hashed: every
    caller is a dialog or an endpoint whose field can arrive untouched, and
    hashing "" against 200,000 iterations to learn that is work for nothing.
    """
    if not candidate:
        return False
    _sync_admin_cfg()
    stored = ADMIN_CFG['password_hash']
    if not password_matches(candidate, stored):
        # The one place a wrong admin password is known, so the one place it is
        # recorded. Never the password itself, in any form - not the attempt,
        # not its length, not a hash of it. _authorise below asks the capability
        # first precisely so a legitimate capability password does not arrive
        # here and leave a refusal that never happened.
        _log_event("auth.refused", "the admin password was wrong",
                   level="warn")
        return False
    _upgrade_stored_hash(stored, candidate, _rehash_admin_password)
    return True


def _rehash_admin_password(new_hash):
    """Store an already-computed hash of the admin password. Not a change.

    It takes a hash rather than a password precisely so it cannot be a second
    way to *set* the admin password: that is /admin/change_password and the
    dialog behind it, both of which ask for the current one first.
    """
    _update_admin_cfg(password_hash=new_hash)

# ─── Capability passwords ─────────────────────────────────────────────────────

# Four actions can be delegated one at a time, so somebody can be given SSL
# Certificate without also being given Delete Every Record. These are **not**
# PERMISSIONS (rule 8): those decide what an Engineer's client shows, and no
# client has ever heard of these. Changing the admin password is not in the
# list and is not delegable.
#
# **They no longer gate this console.** Server Administration is one door with
# the admin password on it (_console_unlock below), so a second credential at
# each action was answering a question nobody was asking here - and it was
# never what these were for: they are the credential an Admin manages this
# server *remotely* with, from a Notifier, which is what ADR-0006's own "When
# to revisit" said would have to be argued against the network. ADR-0015 is
# that argument, and R1 built the channel it argued for: _authorise is what
# _remote_authorise asks, _console_actor's sibling _remote_actor words the
# actor, and _pw_caption still captions the window. Four of the five reach an
# endpoint, over HTTPS only - CAPABILITY_REMOTE below is that set. ssl_cert is
# deliberately not in it and never will be: installing a certificate means
# uploading ssl_key.pem, the one file that must never travel (rule 1), so that
# capability stays console-only and the window says so.
#
# **server_settings is the fifth and is one capability rather than four**
# (#170). Four areas are administered behind it - the Engineer list, the mail
# server, Asset Proposals and the Client registry - and four capabilities would
# be four passwords an Admin hands out, four rows on that window and four
# entries in the delegation map, for four panels that in practice go to the
# same person: whoever is administering this server from somewhere other than
# the console. What that costs is that one password reaches all four, which is
# stated on its row rather than left to be discovered.
CAPABILITIES = ("server_config", "ssl_cert", "manage_records",
                "import_archive", "server_settings")
CAPABILITY_LABELS = {
    "server_config":  "Change Host / Port",
    "ssl_cert":       "SSL Certificate",
    "manage_records": "Manage Transaction History",
    "import_archive": "Import Transaction Archive",
    "server_settings": "Server Settings",
}
# What each one actually reaches, in one line, for the row on the Capability
# Passwords window (#170). A label names an action and that was enough while
# every label said what it did - "Change Host / Port" is its own description -
# but "Server Settings" beside it is not, and the two sit a click apart on one
# window. So what a password opens is written down here, once, rather than
# worded into that window's loop where it could not be held to anything.
CAPABILITY_REACH = {
    "server_config":  "the host and port this server binds on its next start",
    "ssl_cert":       "installing and removing this server's certificate",
    "manage_records": "deleting, correcting and cancelling Transactions",
    "import_archive": "restoring Transactions from an archive file",
    "server_settings": "the Engineer list and their Own Passwords, the mail "
                       "server, Asset Proposals, and the Client registry with "
                       "its commands - four areas behind one password",
}
CAPABILITY_MIN = 4
# Which of the five are reachable over the network (R1, ADR-0015). Four, and
# the absence is the decision: **`ssl_cert` is not here and must not be**, since
# installing a certificate means uploading `ssl_key.pem`, which is the one file
# that must never travel - anybody holding it impersonates this server to every
# client that pinned it (rule 1). Delegating the console action would be
# delegating the ability to become the server, over HTTP, to whoever the
# password reached. It stays a console action, where physical access is what
# stands behind it.
#
# Written as the set that **is** remote rather than the one that is not, for
# MAINTENANCE_OPEN's reason: a capability added later must default to
# console-only rather than to the network.
CAPABILITY_REMOTE = frozenset(("server_config", "manage_records",
                               "import_archive", "server_settings"))
# How long a holder name may be. A label, the way `cancelled_by` is, and capped
# where that is capped: it is copied into the `actor` column of every entry the
# credential writes, and an Admin who pastes a paragraph into the field would
# be choosing the width of that column for ever.
CAPABILITY_HOLDER_MAX = 120


def _authorise(capability, password, address=""):
    """Which credential opened `capability`, "" for neither.

    "admin" or "capability", both truthy, so a caller that only wants to know
    whether the dialog opens reads exactly as it did. What the answer is for is
    the System Log: the server is the only thing that knows which of the two
    passwords was typed, and _console_actor below is what turns that into the
    `actor` column. A bare bool threw it away, so a delegate's act was recorded
    as the Admin's - sharpest on a deletion, where the rows are gone and the
    entry is the entire record that it happened.

    The admin password opens everything, always - setting a capability password
    can never lock the Admin out of their own server, and there is no capability
    the Admin cannot reach with the one password they already have.  A
    capability password opens only its own capability, which is the whole point:
    handing somebody Import Archive must not hand them Delete.

    An empty or missing password never authorises anything, whatever is set -
    every caller is a dialog that can be submitted with the field untouched.

    An unknown capability name **raises** rather than returning False. Every
    name passed here is a literal in this file, so a wrong one is a bug at the
    callsite; returning False would read as "wrong password" and hide it in the
    one place somebody would look. The setter below reports a bad name through
    its payload instead, because there the name comes from a form.

    Read from the in-memory ADMIN_CFG, which is where the admin password is read
    from too.

    `address` is the source address for the refusal entry, and is empty for the
    console, which is what `_log_event` already means by an empty one - a row
    written in process. Since R1 three of these are reachable over the network
    through `_remote_authorise`, which is the only caller that passes one, so a
    refused capability password is visibly a refusal from somewhere rather than
    one from the keyboard.
    """
    if capability not in CAPABILITIES:
        raise ValueError("Unknown capability: %s" % (capability,))
    if not password:
        return ""
    # Before the capability hashes are read, and not only before the admin
    # password is: _admin_password_ok syncs too, but it is asked second, so
    # a capability password set or cleared at the console would be answered
    # out of the stale map first.
    _sync_admin_cfg()
    # The capability first, the admin password second. The answer is the same
    # either way - a capability password may not be the admin password, which
    # _set_capability_password refuses outright - but the order decides what the
    # System Log says: _admin_password_ok records a wrong admin password, and
    # asking it first would write that line every time a delegate used the
    # password they were given.
    stored = (ADMIN_CFG.get('capability_hashes') or {}).get(capability) or ""
    if stored and password_matches(password, stored):
        _upgrade_stored_hash(stored, password,
                             lambda h: _rehash_capability_password(capability,
                                                                   h))
        return "capability"
    if _admin_password_ok(password):
        return "admin"
    _log_event("auth.refused",
               "neither password opened %s"
               % CAPABILITY_LABELS.get(capability, capability), level="warn",
               address=address)
    return ""


def _capability_holder(capability):
    """What the Admin called the holder of this capability's password. R1.

    "" where none was given, which is a **state rather than an error**: a
    password set before this existed has no name beside it, and so does one an
    Admin deliberately left unnamed. What it must never do is fall back to the
    Admin, which is #74's defect pointing the other way - an act recorded as
    the Admin's that the Admin did not do.

    It is the name of a **credential and not an authentication of a person**.
    An Admin typed it when they set the password; a shared secret proves
    nothing about whose fingers are on the keyboard, so every sentence built
    out of it says which credential was used and what the Admin called it,
    and none of them says who did it.
    """
    return ((ADMIN_CFG.get('capability_holders') or {}).get(capability)
            or "").strip()


# The loopback addresses a request may arrive from when something in front of
# this process forwarded it. IPv6 loopback and the IPv4-mapped spelling of
# 127.0.0.1 are the same peer as 127.0.0.1 and have to read as one, a stack
# that answers "::ffff:127.0.0.1" being a machine where the header would
# otherwise be thrown away over a spelling.
_LOOPBACK_PEERS = ("127.0.0.1", "::1", "::ffff:127.0.0.1")

# What an address may be, before anything stores it. Both columns that take one
# cap their own field already - _log_event at _LOG_FIELD_MAX, the check-in at
# _CHECKIN_MAX - and this is the cap on the value itself, because the string
# comes off a header rather than off a socket and one caller keys a set on it.
_ADDR_MAX = 120


def _client_addr():
    """Where this request actually came from. #187.

    `request.remote_addr` is the peer of the TCP connection this process is
    reading, which off IIS is the client and under IIS is never the client at
    all: HttpPlatformHandler owns the port, starts this process on
    `%HTTP_PLATFORM_PORT%` and proxies each request to it over loopback
    (ADR-0001), so every row in the Client registry and every shipped System
    Log entry recorded `127.0.0.1` - the two columns whose entire job is to say
    where something came from, on the one deployment that is supported.
    Machines reach this server over a VPN, so that is a diagnostic thrown away
    rather than a cosmetic one, and `remote.action` beside it recorded a
    delegated capability password as having been used by the server on itself.

    So the forwarded address is read **only when the peer is loopback**, and
    that condition is the whole security of this function rather than a
    tidiness about proxies. `X-Forwarded-For` is a header any caller sets, and
    the endpoints that write these columns are unauthenticated by design
    (ADR-0002, ADR-0005) - so trusting it from an arbitrary peer would let
    anybody on the network write any address they liked into the System Log,
    which is worse than the honest `127.0.0.1` it replaces: a wrong address is
    read as a fact where a loopback one is visibly one hop's worth of nothing.
    A peer that is not loopback is talking to this process directly, so its own
    address is the answer and no header can displace it.

    The **leftmost** entry, which is the originating client where a chain of
    proxies each appended itself. There is one hop here and there is meant to
    be one, so a chain at all is either somebody else's proxy or a caller
    padding the header; the leftmost is the honest reading of the convention
    either way, and what stands behind it is that only a loopback peer was
    believed in the first place.

    **Nothing in IIS sets this header on its own**, which is the fact this
    rests on and the one worth writing down: HttpPlatformHandler's
    configuration reference documents exactly one header it adds to the proxied
    request - `X-IIS-WindowsAuthToken`, under `forwardWindowsAuthToken`, which
    this deployment has off - so the header is put there by the `web.config`
    `tools\\install-iis.ps1` writes, out of IIS's own `REMOTE_ADDR`, and that is
    the other half of this fix rather than an assumption about the module.
    Where that rule is not there - an install whose `web.config` predates it,
    or a machine without the URL Rewrite module it needs - no header arrives,
    the `or` below answers with the peer, and the behaviour is exactly what it
    was.
    """
    try:
        peer = (request.remote_addr or "").strip()
    except Exception:
        return ""
    if peer not in _LOOPBACK_PEERS:
        return peer[:_ADDR_MAX]
    try:
        fwd = request.headers.get("X-Forwarded-For", "")
    except Exception:
        fwd = ""
    first = (fwd or "").split(",")[0].strip()
    return (first or peer)[:_ADDR_MAX]


def _remote_actor(capability, opened_by, holder=""):
    """Who the System Log says did a delegated action over the network. R1.

    `_console_actor`'s sibling, and deliberately not the same sentence: that
    one says `(Server GUI)`, which is a claim about physical access, and this
    one cannot make it. Both keep the `Delegate: ` prefix, because a filter over
    it must match every delegated act rather than half of them.

    **The capability comes first and the holder second**, which is the whole
    wording decision: what this server actually proved is that the password for
    one named action was given, and the holder is a label an Admin typed beside
    it. `Delegate: Brian Dawson` read as an identity - `Delegate: Manage
    Transaction History held by "Brian Dawson"` reads as what it is. An unnamed
    credential says so rather than borrowing anybody's name.
    """
    if opened_by != "capability":
        return "Admin (remote)"
    label = CAPABILITY_LABELS[capability]
    if holder:
        return 'Delegate: %s held by "%s" (remote)' % (label, holder)
    return "Delegate: %s, unnamed holder (remote)" % (label,)


def _remote_authorise(capability, password, address=""):
    """The network door onto one delegable action. R1, ADR-0015.

    Returns (actor, payload, status). Exactly one of `actor` and `payload` is
    set: an actor is the string every entry this request goes on to write is
    attributed to, and a payload is the refusal to return as it stands.

    This is the function ADR-0006 said would have to exist before a capability
    password meant anything, and the three things it holds are the three that
    argument turned on:

    * **HTTPS only.** `_remote_tls_ok` above, and a refusal rather than a
      downgrade - there is no smaller version of sending a replayable
      credential in the clear.
    * **The capability is one of the three.** An unknown name, or `ssl_cert`,
      **raises**: every name passed here is a literal at a route in this file,
      so a wrong one is a bug at the call site, and answering 401 would hide it
      behind what reads as a wrong password. `_authorise` raises for the same
      reason.
    * **Every use is written down.** One `remote.action` at `warn` carrying the
      capability, the holder as the Admin named them, and the source address
      this server saw - before the action runs, so a call that then fails is
      still on the record as having been made. The name is **copied into the
      row**, never looked up when the log is read: a password is rotated by
      replacing it and the holder beside it changes, so a join would
      re-attribute every past act to whoever holds the credential today. That
      is what `_rename_member` refuses to do to `system_log`, for the same
      reason - an audit trail edited to agree with a later decision is not one.

    The admin password opens all three, as it opens everything, so a delegation
    can never lock the Admin out of their own server.

    The body is `_remote_admit` below, which answers with the credential as
    well. This is the shape every door but one wants: three of them and the
    archive importer care only that somebody got in and what to attribute the
    entry to.
    """
    _opened_by, actor, refusal, status = _remote_admit(capability, password,
                                                       address=address)
    return actor, refusal, status


def _remote_admit(capability, password, address="", admin_is_native=False):
    """`_remote_authorise`'s body, answering with the credential as well. #169.

    Returns (opened_by, actor, payload, status) - `opened_by` being
    `_authorise`'s own answer, "admin" or "capability", and "" where nothing
    opened it.

    **`admin_is_native` is the one door this exists for.** At the four R1
    endpoints the admin password is a remote-channel credential like the
    capability password beside it, so both are refused over plain HTTP and both
    are written down as a `remote.action`. `POST /transactions/cancel` is the
    exception, and was one long before this channel existed: the admin password
    has been that endpoint's own credential since ADR-0003, it is what the
    Storekeeper's Cancel pill sends to retract a **Confirmed** row, and HTTP is
    the default deployment (rule 1). Refusing it here would break the ordinary
    store on the ordinary install. So where this is set the admin password is
    left exactly as it was - no transport gate, and no `remote.action` entry,
    the `transaction.cancelled` beside it already recording the act as the
    Admin's - while the **capability** password is held to both.

    That costs one documented property, and it is worth saying which: at the
    four R1 doors a capability password is refused **before it is examined**,
    which cannot hold here because only examining it says which of the two
    credentials arrived. The refusal is still the same refusal, with the same
    `insecure` code and the same entry, and nothing about the password reaches
    the answer - what moved is the order, not what is told. ADR-0015 carries
    the exception.
    """
    if capability not in CAPABILITY_REMOTE:
        raise ValueError("Not a remote capability: %s" % (capability,))
    if not admin_is_native and not _remote_tls_ok():
        return None, None, _remote_insecure(capability, address), 403
    opened_by = _authorise(capability, password, address=address)
    if not opened_by:
        return "", None, {"error": "Wrong password",
                          "code": "bad_password"}, 401
    if opened_by == "capability" and not _remote_tls_ok():
        # The late gate, reached only from the door above. A capability
        # password is replayed rather than compared, so it is refused over a
        # connection this server cannot see encrypted wherever it arrives.
        return opened_by, None, _remote_insecure(capability, address), 403
    holder = _capability_holder(capability) if opened_by == "capability" else ""
    actor = _remote_actor(capability, opened_by, holder)
    if not (admin_is_native and opened_by == "admin"):
        _log_event("remote.action",
                   "%s  ·  %s" % (CAPABILITY_LABELS[capability],
                                      "the admin password"
                                      if opened_by == "admin" else
                                      ('the capability password, holder named by '
                                       'the Admin as "%s"' % holder if holder else
                                       "the capability password, no holder "
                                       "named")),
                   actor=actor, level="warn", address=address)
    return opened_by, actor, None, 200


def _remote_insecure(capability, address=""):
    """The HTTPS refusal, worded once. #169.

    Two callers since the cancel door has a gate before the password and one
    after it, and a delegate told two different things about one rule is a
    delegate who reads the second as a different fault.
    """
    _log_event("remote.refused",
               "%s over a connection this server cannot see encrypted"
               % CAPABILITY_LABELS[capability],
               level="warn", address=address)
    return {"error": "This action is only accepted over HTTPS.",
            "code": "insecure"}


def _rehash_capability_password(capability, new_hash):
    """Store an already-computed hash of one capability password.

    The counterpart of _rehash_admin_password, and a hash rather than a
    password for the same reason: _set_capability_password below is the only
    way to *delegate* an action, and it asks for the admin password first.
    """
    have = dict(ADMIN_CFG.get('capability_hashes') or {})
    have[capability] = new_hash
    _update_admin_cfg(capability_hashes=have)


def _pw_caption(capability):
    """The caption for a password field on a delegable action.

    One place, because a field captioned "Admin password" is a lie to whoever
    holds the other password that opens it, and four dialogs wording that
    independently is four chances to get it wrong.
    """
    return "Admin password  ·  or the %s password" % \
        (CAPABILITY_LABELS[capability],)


def _console_actor(capability, opened_by):
    """Who the System Log says did a delegable action.

    `opened_by` is what _authorise answered. The admin password opens every
    capability, so most of these entries still read Admin (Server GUI); one a
    delegate opened names them as one, and names the action they were handed.
    ADR-0006's whole point is that a capability password is **not** the admin
    password, and `actor` - "who, as far as anything knows" - is the one place
    that distinction is visible after the fact.

    One place for the same reason _pw_caption is one place: five actions
    wording this independently is five chances to write a different sentence,
    and the column is filtered on.

    Still carries "(Server GUI)". A capability password reaches no endpoint at
    all, so a delegate is always at this console and it reads as redundant -
    but the Admin's own rows say it, and a filter over that suffix must not
    stop matching the console's entries halfway down the table.
    """
    if opened_by == "capability":
        return "Delegate: %s (Server GUI)" % (CAPABILITY_LABELS[capability],)
    return "Admin (Server GUI)"



def _set_capability_password(capability, new_password, admin_password,
                            holder=None, authorised_as=None):
    """Set or clear one capability's password and holder. The admin password
    only.

    Delegating is the Admin's decision, so a capability password can never
    change or clear itself: otherwise whoever held Import Archive could keep it
    after the Admin meant to take it back, and the Admin's own password would no
    longer be the whole story about who can do what.

    An empty `new_password` clears it. Anything else is held to the four
    characters the admin password is held to, and refused when it *is* the admin
    password - that would hand the delegate everything while looking like a
    delegation, and clearing it afterwards would take nothing away.

    `holder` is what the Admin calls whoever they are handing the password to
    (R1), copied into the `actor` column of every `remote.action` that password
    writes. It takes the **admin password** like the password beside it, and
    for the stronger reason: a delegate who could rename themselves could
    rename themselves to somebody else in the log. None leaves whatever name is
    there alone, "" clears it, and clearing the **password** clears the name
    with it - a name for a credential that no longer exists is a row in a file
    that means nothing.

    `authorised_as` is the console saying its door already asked (096): the
    Capability Passwords entry is gated on the admin password, so the window
    asks nothing again and hands its actor here instead. `_delete_member`'s
    convention, and still never a capability password - nothing that holds
    one can reach this.

    Returns (payload, status) like the other enforcement helpers here, so the
    dialog renders a refusal it did not have to word itself.
    """
    if authorised_as is None and not _admin_password_ok(admin_password):
        return {"error": "Wrong admin password.", "code": "bad_password"}, 401
    if capability not in CAPABILITIES:
        return {"error": "Unknown capability: %s" % (capability,),
                "code": "bad_capability"}, 400
    new = new_password or ""
    have = dict(ADMIN_CFG.get('capability_hashes') or {})
    named = dict(ADMIN_CFG.get('capability_holders') or {})
    if holder is not None:
        who = str(holder).strip()[:CAPABILITY_HOLDER_MAX]
        if who:
            named[capability] = who
        else:
            named.pop(capability, None)
    if new == "":
        was_set = bool(have.pop(capability, ""))
        named.pop(capability, None)
        _update_admin_cfg(capability_hashes=have,
                          capability_holders=named)
        _log_event("capability.password_cleared",
                   CAPABILITY_LABELS.get(capability, capability),
                   actor="Admin (Server GUI)", level="warn")
        return {"status": "cleared", "capability": capability,
                "was_set": was_set}, 200
    if len(new) < CAPABILITY_MIN:
        return {"error": "A capability password must be at least %d "
                         "characters." % CAPABILITY_MIN,
                "code": "too_short"}, 400
    if password_matches(new, ADMIN_CFG['password_hash']):
        return {"error": "That is the admin password, so it would not be a "
                         "delegation - and clearing it later would take "
                         "nothing away.", "code": "same_as_admin"}, 400
    have[capability] = hash_password(new)
    _update_admin_cfg(capability_hashes=have, capability_holders=named)
    # That a delegation was made and who it was made to, never what it was made
    # with. The holder is a name an Admin typed, which is exactly what this
    # entry records it as.
    _log_event("capability.password_set",
               "%s  ·  %s"
               % (CAPABILITY_LABELS.get(capability, capability),
                  'holder named as "%s"' % named[capability]
                  if named.get(capability) else "no holder named"),
               actor="Admin (Server GUI)", level="warn")
    return {"status": "set", "capability": capability,
            "holder": named.get(capability, "")}, 200


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# The Engineer list, as it stands once every column above has been added.
# Written out in full because changing a column's collation in SQLite means
# rebuilding the table - there is no ALTER for it - and migration
# 008_member_name_nocase carries the same DDL for the same reason
# `001_baseline` is a no-op against what init_db already does.
_MEMBERS_NOCASE_SCHEMA = """
CREATE TABLE team_members_new (
    name                 TEXT PRIMARY KEY COLLATE NOCASE,
    auto_approve         INTEGER DEFAULT 0,
    profile              TEXT    DEFAULT 'default',
    permissions          TEXT    DEFAULT '',
    password_hash        TEXT    DEFAULT '',
    must_change_password INTEGER DEFAULT 0
)
"""

_MEMBERS_COLS = ("name", "auto_approve", "profile", "permissions",
                 "password_hash", "must_change_password")


def _ensure_member_name_nocase(c):
    """Give `team_members.name` the NOCASE collation, if it has not got it.

    An Engineer is a person, and a person typed in a different case is the same
    person. The declared collation is what `=` uses, so this one line is what
    makes every `WHERE name=?` in this file case-insensitive - and what stops
    the next one, written later, from being the one that forgot.

    Returns the name pairs that stopped it, empty when there were none. A
    database holding two names differing only in case cannot take the
    collation, and **this path does not refuse to start over it**: init_db runs
    on every boot, and turning a running install into a dead one over data that
    was already there is the worse failure. The pairs are logged instead, and
    `migrate` - the deliberate act, run by somebody who is watching - refuses
    loudly and names them.
    """
    row = c.execute("SELECT sql FROM sqlite_master WHERE type='table'"
                    " AND name='team_members'").fetchone()
    if row and "COLLATE NOCASE" in (row[0] or "").upper():
        return []
    dupes = c.execute(
        "SELECT a.name, b.name FROM team_members a JOIN team_members b"
        " ON a.rowid < b.rowid AND a.name = b.name COLLATE NOCASE"
        " ORDER BY a.rowid").fetchall()
    if dupes:
        return [(a, b) for a, b in dupes]
    cols = ", ".join(_MEMBERS_COLS)
    c.execute(_MEMBERS_NOCASE_SCHEMA)
    c.execute("INSERT INTO team_members_new(%s) SELECT %s FROM team_members"
              % (cols, cols))
    c.execute("DROP TABLE team_members")
    c.execute("ALTER TABLE team_members_new RENAME TO team_members")
    return []


# The Engineer list once the name has stopped being the key. Written out in
# full for the reason the schema above is: SQLite has no ALTER for a primary
# key either, so this is a rebuild, and migration 012_member_identity carries
# the same DDL for the same reason `001_baseline` is a no-op against init_db.
_MEMBERS_IDENTITY_SCHEMA = """
CREATE TABLE team_members_new (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT    UNIQUE COLLATE NOCASE,
    auto_approve         INTEGER DEFAULT 0,
    profile              TEXT    DEFAULT 'default',
    permissions          TEXT    DEFAULT '',
    password_hash        TEXT    DEFAULT '',
    must_change_password INTEGER DEFAULT 0
)
"""


def _ensure_member_identity(c):
    """Give `team_members` an id, if it has not got one.

    A name as the primary key made a rename a delete and an insert, which took
    the Engineer's Own Password, their Access Profile and their permissions
    with it - so the safe thing to do about a misspelt name was to leave it
    wrong. An id makes it an UPDATE.

    The name keeps `UNIQUE COLLATE NOCASE`, so everything
    `_ensure_member_name_nocase` above bought is intact: two spellings
    differing only in case are still one Engineer, every `WHERE name=?` in this
    file still matches without regard to case, and `_save_member`'s
    `ON CONFLICT(name)` still fires - on the constraint now rather than on the
    key, which is the same clause and the same row.

    Returns the name pairs that stopped it, empty when there were none, and
    **does not refuse to start over them** - init_db runs on every boot, and
    the reasoning is `_ensure_member_name_nocase`'s in full. In practice a
    database reaching here cannot collide unless that function was the one that
    stood aside, which is exactly the case this has to survive.
    """
    cols = [row[1] for row in
            c.execute("PRAGMA table_info(team_members)").fetchall()]
    if "id" in cols:
        return []
    dupes = c.execute(
        "SELECT a.name, b.name FROM team_members a JOIN team_members b"
        " ON a.rowid < b.rowid AND a.name = b.name COLLATE NOCASE"
        " ORDER BY a.rowid").fetchall()
    if dupes:
        return [(a, b) for a, b in dupes]
    carried = ", ".join(_MEMBERS_COLS)
    c.execute(_MEMBERS_IDENTITY_SCHEMA)
    c.execute("INSERT INTO team_members_new(%s) SELECT %s FROM team_members"
              " ORDER BY rowid" % (carried, carried))
    c.execute("DROP TABLE team_members")
    c.execute("ALTER TABLE team_members_new RENAME TO team_members")
    return []


_ASSETS_NOCASE_SCHEMA = """
CREATE TABLE assets_new (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_number  TEXT DEFAULT '' COLLATE NOCASE,
    serial_number TEXT DEFAULT '' COLLATE NOCASE,
    asset_type    TEXT NOT NULL,
    asset_model   TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    created_by    TEXT DEFAULT '',
    updated_at    TEXT DEFAULT ''
)
"""

_ASSETS_COLS = ("id", "asset_number", "serial_number", "asset_type",
                "asset_model", "created_at", "created_by", "updated_at")

_ASSET_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_number ON assets"
    " (asset_number) WHERE asset_number <> ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_serial ON assets"
    " (serial_number) WHERE serial_number <> ''",
)


def _asset_identity_clashes(c):
    """[(column, one spelling, the other)] for identifiers naming two assets.

    Empty is not an identifier, so two assets with no Serial Number are not a
    collision - which is what the partial indexes below say in SQL, and what
    lets an asset carry only one of the two (rule 5's shape).
    """
    found = []
    for col in ("asset_number", "serial_number"):
        found.extend(
            (col, a, b) for a, b in c.execute(
                "SELECT x.{0}, y.{0} FROM assets x JOIN assets y"
                " ON x.id < y.id AND x.{0} = y.{0} COLLATE NOCASE"
                " WHERE x.{0} <> '' ORDER BY x.id".format(col)).fetchall())
    return found


def _resolve_asset_identity(c):
    """Make each identifier name one asset. Returns (cleared, unresolved).

    **A value that names two assets names neither**, so where an identifier is
    held by more than one row it is cleared from all but the lowest id - which
    keeps one answer for whoever scans it, and is deterministic. The assets are
    kept: each still carries its other identifier, which is the whole of what
    makes this safe, and rule 5's shape is what says an asset needs only one of
    the two.

    It is not always safe, and the unsafe case is reported rather than done: a
    row whose *other* identifier is empty would be left with none at all, which
    is not an asset any more. Those pairs come back in `unresolved` for the
    caller to decide about - the migration refuses over them, `init_db` warns
    and starts. Which of two rows describing one asset is the real one is not a
    decision either of them gets to make.

    The real shipped Lookup Sheet is why this exists rather than a blanket
    refusal: 6 of its 3462 rows share a Serial Number with another row, each
    pair carrying two distinct Asset Numbers. Refusing would have meant no
    install could start and no existing install could upgrade, over a
    manufacturer's number that identified nothing to begin with.
    """
    cleared, unresolved = [], []
    for col, other in (("asset_number", "serial_number"),
                       ("serial_number", "asset_number")):
        dupes = c.execute(
            "SELECT {0} FROM assets WHERE {0} <> '' GROUP BY {0} COLLATE NOCASE"
            " HAVING COUNT(*) > 1".format(col)).fetchall()
        for (value,) in dupes:
            rows = c.execute(
                "SELECT id, {1} FROM assets WHERE {0} = ? COLLATE NOCASE"
                " ORDER BY id".format(col, other), (value,)).fetchall()
            if any(not r[1] for r in rows[1:]):
                unresolved.append((col, value, len(rows)))
                continue
            c.execute("UPDATE assets SET {0} = '' WHERE id IN ({1})".format(
                col, ",".join(str(r[0]) for r in rows[1:])))
            cleared.append((col, value, len(rows) - 1))
    return cleared, unresolved


def _ensure_asset_identity(c):
    """Give the identifiers their collation and their unique indexes.

    The same shape as `_ensure_member_name_nocase`, and for the same reason: a
    column's collation cannot be ALTERed, so an older table is rebuilt. What
    differs is what a pre-existing collision means here: `_resolve_asset_identity`
    clears an identifier two assets share, keeping both, and what it cannot
    clear without leaving a row with no identifier at all this **warns and
    carries on** over - because it runs on every boot and a server that will not
    start over a duplicate somebody created months ago is a store that cannot
    record a movement today. Migration 010 refuses over exactly those, being a
    deliberate act with somebody watching.

    Returns (cleared, unresolved) for the caller to log. Where anything is
    unresolved the table is left as it was found, indexes included: they are
    what those rows cannot be created over.
    """
    cleared, unresolved = _resolve_asset_identity(c)
    if unresolved:
        return cleared, unresolved
    row = c.execute("SELECT sql FROM sqlite_master WHERE type='table'"
                    " AND name='assets'").fetchone()
    if not (row and "COLLATE NOCASE" in (row[0] or "").upper()):
        cols = ", ".join(_ASSETS_COLS)
        c.execute(_ASSETS_NOCASE_SCHEMA)
        c.execute("INSERT INTO assets_new(%s) SELECT %s FROM assets"
                  % (cols, cols))
        c.execute("DROP TABLE assets")
        c.execute("ALTER TABLE assets_new RENAME TO assets")
    for sql in _ASSET_INDEXES:
        c.execute(sql)
    return cleared, unresolved


def init_db():
    conn = get_db()
    c = conn.cursor()
    # A fresh database has no tables at all before the CREATEs below run - the
    # file did not exist, or existed with nothing in it. Only that database is
    # stamped with this build's latest schema version once it is built: one
    # that predates migrations (a v2.0.0 install, `user_version` 0 with tables
    # already present) has to stay at 0, so `001_baseline` onward still runs
    # on it (#275). Checked here, before anything is created, rather than as
    # `os.path.exists(DB_PATH)`, because connecting already creates an empty
    # file and either test answers the same question.
    _is_fresh_db = not c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_type       TEXT    NOT NULL,
        serial_number    TEXT    DEFAULT '',
        asset_number     TEXT    DEFAULT '',
        team_member      TEXT    NOT NULL,
        direction        TEXT    NOT NULL,
        timestamp        TEXT    NOT NULL,
        confirmed        INTEGER DEFAULT 0,
        rejected         INTEGER DEFAULT 0,
        confirmed_at     TEXT    DEFAULT '',
        rejection_reason TEXT    DEFAULT '',
        notes            TEXT    DEFAULT '',
        storekeeper      TEXT    DEFAULT 'Storekeeper User'
    )''')
    cols = [row[1] for row in c.execute("PRAGMA table_info(transactions)").fetchall()]
    if 'rejection_reason' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN rejection_reason TEXT DEFAULT ''")
    if 'asset_number' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN asset_number TEXT DEFAULT ''")
    if 'asset_model' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN asset_model TEXT DEFAULT ''")
    # Cancelled: the movement never happened, so the Transaction is retracted
    # rather than deleted. Migration 003 adds these too - init_db is what makes
    # a fresh database and an upgraded one identical without running migrate.
    if 'cancelled' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN cancelled INTEGER DEFAULT 0")
    if 'cancelled_at' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN cancelled_at TEXT DEFAULT ''")
    if 'cancelled_by' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN cancelled_by TEXT DEFAULT ''")
    if 'cancel_reason' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN cancel_reason TEXT DEFAULT ''")
    # Which kind of Confirmed this row is (#198). An Engineer who confirmed a
    # movement and an Auto-Approve Engineer who was never asked leave the same
    # `confirmed=1` behind, and the cancel window below may open one and must
    # never open the other - a confirmation is the evidence the verification
    # step produces. Migration 014 adds it too, init_db being what makes a
    # fresh database and an upgraded one identical without running migrate.
    if 'auto_approved' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN auto_approved INTEGER DEFAULT 0")
    # Where the answer came from (#282): desktop or auto,
    # decided by the server from the route and never read from a body. NULL is
    # "decided before Origin existed" and is never guessed at; the one thing
    # an old row does say is auto_approved, which is what the backfill reads.
    # Migration 017 adds it too, init_db being what makes a fresh database and
    # an upgraded one identical without running migrate.
    if 'origin' not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN origin TEXT")
        c.execute("UPDATE transactions SET origin='auto' WHERE auto_approved=1")
    # Engineers — name + auto-approve flag
    # The id is here rather than only in _ensure_member_identity below, so a
    # database created by this line is already the shape that function would
    # rebuild it into and there is nothing for it to do - the same reason the
    # collation is written here rather than left to _ensure_member_name_nocase.
    # Both stand aside on a table that already has what they are for, so a
    # fresh install is never rebuilt on its first boot (ADR-0016).
    c.execute('''CREATE TABLE IF NOT EXISTS team_members (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT UNIQUE COLLATE NOCASE,
        auto_approve INTEGER DEFAULT 0
    )''')
    mcols = [row[1] for row in c.execute("PRAGMA table_info(team_members)").fetchall()]
    if 'profile' not in mcols:
        c.execute("ALTER TABLE team_members ADD COLUMN profile TEXT DEFAULT 'default'")
    if 'permissions' not in mcols:
        c.execute("ALTER TABLE team_members ADD COLUMN permissions TEXT DEFAULT ''")
    if 'password_hash' not in mcols:
        c.execute("ALTER TABLE team_members ADD COLUMN password_hash TEXT DEFAULT ''")
    # An Own Password an Admin set is temporary until the Engineer replaces it,
    # and that is a state of its own: an Engineer with no Own Password at all
    # and one holding a password they are about to be made to replace are not
    # the same thing, and password_hash cannot tell them apart. Migration 006
    # adds this too - init_db is what makes a fresh database and an upgraded
    # one identical without anybody running migrate.
    if 'must_change_password' not in mcols:
        c.execute("ALTER TABLE team_members ADD COLUMN must_change_password"
                  " INTEGER DEFAULT 0")
    # Case stops being significant in a name, once every column above
    # exists to be carried across. Migration 008 does this too - init_db is
    # what makes a fresh database and an upgraded one identical without
    # anybody running migrate, the same as the columns above.
    _name_collisions = _ensure_member_name_nocase(c)
    # Then the name stops being the key at all, so it can be corrected without
    # the row being deleted and written again under the new spelling - which
    # took the Own Password, the profile and the permissions with it. Migration
    # 012 does this too, the both-ways pattern above; it is second because it
    # carries the collation across rather than setting it, and a table that is
    # still BINARY has not been rebuilt yet.
    _name_collisions = _name_collisions or _ensure_member_identity(c)
    if c.execute("SELECT COUNT(*) FROM team_members").fetchone()[0] == 0:
        for nm in ["Alice Carter", "Brian Dawson", "Carol Evans", "David Foster"]:
            c.execute("INSERT OR IGNORE INTO team_members(name, auto_approve) VALUES (?,0)", (nm,))
    # Client installations. Migration 004 creates this too - init_db is what
    # makes a fresh database and an upgraded one identical without anybody
    # running migrate, the same as the columns above.
    c.execute('''CREATE TABLE IF NOT EXISTS clients (
        client_id        TEXT PRIMARY KEY,
        hostname         TEXT    DEFAULT '',
        os_user          TEXT    DEFAULT '',
        app              TEXT    DEFAULT '',
        version          TEXT    DEFAULT '',
        member           TEXT    DEFAULT '',
        cert_fingerprint TEXT    DEFAULT '',
        reported_address TEXT    DEFAULT '',
        address          TEXT    DEFAULT '',
        first_seen       TEXT    DEFAULT '',
        last_seen        TEXT    DEFAULT ''
    )''')
    # Which certificate each installation trusts, so the question "who would
    # break if I replaced it today" is answerable before anything is replaced:
    # every client pins `ssl_cert.pem` and fails closed against anything else
    # (rule 1). Migration 013 adds this too - init_db is what makes a fresh
    # database and an upgraded one identical without anybody running migrate,
    # the same as the columns above.
    ccols = [row[1] for row in c.execute("PRAGMA table_info(clients)").fetchall()]
    if 'cert_fingerprint' not in ccols:
        c.execute("ALTER TABLE clients ADD COLUMN cert_fingerprint TEXT"
                  " DEFAULT ''")
    # The address the Client says it has, beside the one this server saw -
    # behind NAT the second is the gateway. Migration 016 adds this too.
    if 'reported_address' not in ccols:
        c.execute("ALTER TABLE clients ADD COLUMN reported_address TEXT"
                  " DEFAULT ''")
    # Commands waiting for a Client to collect. Migration 005 creates these too
    # - same both-ways pattern. The index is on the hot path: every check-in
    # runs the pending query, and every Client calls that on a timer.
    c.execute('''CREATE TABLE IF NOT EXISTS client_commands (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id    TEXT    NOT NULL,
        command      TEXT    NOT NULL,
        issued_at    TEXT    NOT NULL,
        issued_by    TEXT    DEFAULT 'Admin',
        expires_at   TEXT    NOT NULL,
        collected_at TEXT    DEFAULT ''
    )''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_client_commands_pending"
              " ON client_commands (client_id, collected_at)")
    # The System Log - what was done, as opposed to what was moved. Migration
    # 007 creates this too, the same both-ways pattern as the tables above, and
    # the index is what the Server GUI's window filters and orders on and what
    # the hourly retention pass deletes by.
    c.execute('''CREATE TABLE IF NOT EXISTS system_log (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ts        TEXT    NOT NULL,
        component TEXT    NOT NULL,
        event     TEXT    NOT NULL,
        level     TEXT    DEFAULT 'info',
        actor     TEXT    DEFAULT '',
        detail    TEXT    DEFAULT '',
        client_id TEXT    DEFAULT '',
        address   TEXT    DEFAULT '',
        client_ts TEXT    DEFAULT '',
        data      TEXT
    )''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_system_log_ts"
              " ON system_log (ts)")
    # A fact beside a row's sentence (#246/071), nullable and additive: a
    # call site that names none leaves this NULL, which an older build's own
    # absence of the column already reads as. Migration 015 adds this too -
    # init_db is what makes a fresh database and an upgraded one identical
    # without anybody running migrate, the same as the columns above.
    lcols = [row[1] for row in c.execute("PRAGMA table_info(system_log)").fetchall()]
    if 'data' not in lcols:
        c.execute("ALTER TABLE system_log ADD COLUMN data TEXT")
    # The assets themselves, which lived in asset_lookup.xlsx until 024.
    # Migration 009 creates this too - the same both-ways pattern as the tables
    # above - and seeds it from the sheet beside the database. This is the
    # other way in: a fresh install has no sheet to migrate from, only the one
    # embedded in this exe, and an install whose database has been moved away
    # from the server is seeded here rather than by the migration, which cannot
    # see a sheet that is not beside the file it was handed.
    c.execute('''CREATE TABLE IF NOT EXISTS assets (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_number  TEXT    DEFAULT '' COLLATE NOCASE,
        serial_number TEXT    DEFAULT '' COLLATE NOCASE,
        asset_type    TEXT    NOT NULL,
        asset_model   TEXT    DEFAULT '',
        created_at    TEXT    NOT NULL,
        created_by    TEXT    DEFAULT '',
        updated_at    TEXT    DEFAULT ''
    )''')
    _seeded, _seed_cleared = _seed_assets_if_empty(c)
    # An identifier names one asset, in whichever case it was typed.
    # Migration 010 does this too - init_db is what makes a fresh database and
    # an upgraded one identical without anybody running migrate, the same as
    # the columns and the collation above. It runs **after** the seed, so a
    # first boot indexes the rows it just wrote rather than an empty table.
    _asset_cleared, _asset_clashes = _ensure_asset_identity(c)
    _asset_cleared = _seed_cleared + _asset_cleared
    # An asset the Storekeeper is holding and the Admin has not seen yet.
    # Migration 011 creates this too, the same both-ways pattern as the tables
    # above. The identifiers are NOCASE for the reason `assets` has them
    # (010): a proposal that differs from a pending one only in case is the
    # same proposal, and telling the Storekeeper that on the spot is the point
    # of this row existing. No unique index, though - two people proposing one
    # serial is a thing that happens and is answered with a sentence, not with
    # a constraint that would also stop a rejected proposal being made again
    # after the hardware turned out to be real.
    c.execute('''CREATE TABLE IF NOT EXISTS asset_proposals (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_number  TEXT    DEFAULT '' COLLATE NOCASE,
        serial_number TEXT    DEFAULT '' COLLATE NOCASE,
        asset_type    TEXT    NOT NULL,
        asset_model   TEXT    DEFAULT '',
        proposed_by   TEXT    NOT NULL,
        proposed_at   TEXT    NOT NULL,
        client_id     TEXT    DEFAULT '',
        status        TEXT    NOT NULL,
        decided_at    TEXT    DEFAULT '',
        decided_by    TEXT    DEFAULT '',
        reason        TEXT    DEFAULT ''
    )''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_asset_proposals_status"
              " ON asset_proposals (status, id)")
    if _is_fresh_db:
        # The latest number this build ships, the same count a restore checks
        # a backup's manifest against - no second way of counting migrations.
        # A package with no migrations/ beside it answers 0, which leaves this
        # database exactly where it already was.
        c.execute("PRAGMA user_version = %d" % _latest_schema_version())
    conn.commit()
    conn.close()

    # After the close, because _log_event opens its own connection and the
    # table it writes to is one of the ones created above. A warning rather
    # than a refusal: see _ensure_member_name_nocase.
    if _asset_cleared:
        # Not a failure and not silent: an Admin looking for an asset by a
        # serial that has stopped answering needs to find this line.
        _log_event(
            "assets.ambiguous_identifier",
            "%d identifier(s) named more than one asset and have been cleared "
            "from all but the first, every asset kept and still carrying its "
            "other identifier: %s. Correct them in the Lookup Sheet window - "
            "a value naming two assets names neither."
            % (len(_asset_cleared),
               "; ".join("%s %r on %d row(s)" % (col, v, n)
                         for col, v, n in _asset_cleared)),
            level="warn")
    if _asset_clashes:
        _log_event(
            "assets.duplicate_identifier",
            "%d identifier(s) name more than one asset and cannot be cleared - "
            "a row would be left with no identifier at all - so an identifier "
            "is not unique yet and the later row is shadowed by the first in "
            "every lookup: %s. Correct them in the Lookup Sheet window."
            % (len(_asset_clashes),
               "; ".join("%s %r on %d row(s)" % (col, v, n)
                         for col, v, n in _asset_clashes)),
            level="warn")
    if _seeded:
        _log_event("assets.seeded",
                   "%d asset(s) read in from asset_lookup.xlsx" % _seeded)
    if _name_collisions:
        _log_event(
            "members.name_collision",
            "%d Engineer name(s) differ only in case, so names are still "
            "matched byte for byte: %s. Remove one of each pair from Manage "
            "Users." % (len(_name_collisions),
                        "; ".join("%r / %r" % (x, y) for x, y in _name_collisions)),
            level="warn")

# ─── Routes ───────────────────────────────────────────────────────────────────

# ─── Every route declares the credential it wants ─────────────────────────────

# Three functions actually judge a credential here - `_admin_password_ok`
# above, `_authorise` beside it, and `_remote_admit` built on the pair - and
# each is already the one place its own question is answered. What no route had
# was any way to say **which** of them it asks. That was whatever the body
# happened to call, so in the source a route left open on purpose (ADR-0002), a
# route whose author forgot, and a route guarded by hand all read the same: an
# absent line. #209.
#
# So every route below carries a `door(...)` line naming its credential, and
# `tools/server-checks.py` refuses a route that carries none. Unauthenticated
# becomes a stated fact rather than a missing one, and the reason is written
# where the route is rather than only in an ADR somebody has to know to go and
# read.
#
# **The declaration does not perform the check**, and that is the decision
# worth recording rather than the shape of it. Each check already sits at one
# place, and one of them deliberately does not sit at the endpoint at all:
# `_cancel_transaction` holds the admin password with the rule, so the Server
# GUI calling that function directly is held to exactly what a curl is - which
# is `check_authorisation_is_in_the_one_enforcement_point`'s whole assertion. A
# decorator that short-circuited the request could not follow the check in
# there. Nor could it stand in front of the three routes that decide *between*
# credentials inside their own bodies: `POST /members` has the Storekeeper's
# create-only path beside the admin one (ADR-0017), `POST /transactions/cancel`
# has the unauthenticated Pending path beside it (ADR-0002), and
# `POST /auth/verify` answers differently depending on which of the two
# passwords opened it. A decorator that enforced some of these forms and merely
# declared the rest would be the absent line again, one level up.
#
# What makes the declaration load-bearing is that the gate holds it against the
# body: a route declaring a capability whose body never reaches `_remote_admit`
# fails, and so does a body that checks a credential its declaration never
# named. Drift is caught where every other cascade in this repo is caught, by a
# check that reads both sides rather than by a comment nobody is held to.
#
# **Delegation is a declaration now rather than a wiring job.** A route that
# should be reachable with a capability password names the capability and goes
# through `_remote_admit`; there is no second list to add it to, which is what
# R1 and #170-#174 each had to do by hand for three routes at a time. Only a
# capability in `CAPABILITY_REMOTE` may be named, so ADR-0015's one refusal -
# `ssl_cert` never reaches an endpoint, because installing a certificate means
# uploading `ssl_key.pem`, the one file that must never travel (rule 1) - is
# kept by construction here rather than by memory at each new route.

DOOR_OPEN  = "open"    # no credential, on purpose; `why` says whose purpose
DOOR_ADMIN = "admin"   # the admin password and nothing else (rule 7, rule 11)
DOOR_OWN   = "own"     # the Engineer's own password (ADR-0009), admin over it

# view function name -> (credential, why, optional). Nothing in this process
# reads it, which is the honest thing to say about it: the gates read it, and
# the gates are what hold it against the bodies and against the API table.
ROUTE_DOORS = {}


def door(credential, why="", optional=False):
    """Declare which credential the route under this line asks for. #209.

    `credential` is DOOR_OPEN, DOOR_ADMIN, DOOR_OWN,
    or the name of a capability in CAPABILITY_REMOTE - the same string `_remote_admit` is
    passed, so a declaration and a call cannot name two different capabilities
    without the gate seeing it.

    `why` is required on DOOR_OPEN and refused on everything else: an open
    route is the one kind that has to argue for itself, and "the admin
    password" is not an argument anybody needs to read. `optional` marks the
    two routes that are open **until** a password is offered - `POST /members`'
    create-only path (ADR-0017) and `POST /transactions/cancel`'s Pending path
    (ADR-0002) - so neither the gate nor a reader takes them for a guarded
    route with a hole in it.

    It returns the function untouched. This registers a fact; it does not wrap.
    """
    fixed = (DOOR_OPEN, DOOR_ADMIN, DOOR_OWN)
    if credential not in fixed and credential not in CAPABILITY_REMOTE:
        raise ValueError("Not a credential a route may ask for: %s"
                         % (credential,))
    if (credential == DOOR_OPEN) != bool(why):
        raise ValueError("%s: an open route states why, and nothing else does"
                         % (credential,))
    if optional and credential in fixed:
        raise ValueError("%s: optional is for a capability door that stays "
                         "open until a password is offered" % (credential,))

    def declare(fn):
        if fn.__name__ in ROUTE_DOORS:
            raise ValueError("Two doors declared for %s" % (fn.__name__,))
        ROUTE_DOORS[fn.__name__] = (credential, why, optional)
        return fn
    return declare


@app.before_request
def _hold_writes_during_maintenance():
    """Refuse a write while a backup or a restore is running (G3, ADR-0018).

    **The server does not queue it instead.** A server that accepts a write it
    cannot commit has told the client something untrue, and every client here
    already knows how to hold one: the Storekeeper has an offline buffer for
    exactly this and the Notifier gained one for its answers. So the honest
    answer is a refusal shaped so the client can recognise it - 503 with
    `code: "maintenance"` - rather than an acknowledgement nothing can rely on.

    **503 and not 409**, because that is what a client already treats as the
    server rather than the row: the Storekeeper's flush keeps a 5xx queued and
    drops a 4xx as permanent, so a client built before this reads the refusal
    correctly without knowing the code at all. The code is what lets a client
    that *does* know it stop the flush after the first one, since this answer
    is about the server and will be the same for every row behind it.

    A GET is untouched: reads carry on for the length of the operation, which
    is what makes it a maintenance state rather than an outage.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if request.endpoint is None or request.endpoint in MAINTENANCE_OPEN:
        return None
    state = _maintenance_state()
    if not state:
        return None
    where = _client_addr()
    seen = (state.get("since"), request.endpoint, where)
    if seen not in _HELD_SEEN:
        _HELD_SEEN.add(seen)
        _log_event("write.held",
                   "%s %s held by %s" % (request.method, request.path,
                                         state.get("what") or "maintenance"),
                   level="warn", address=where)
    return jsonify({
        "error": "The server is busy with %s and is not taking writes just "
                 "now. This will be sent again when it is done."
                 % (state.get("what") or "maintenance"),
        "code":  "maintenance",
        "since": state.get("since", ""),
    }), 503


@app.route('/health')
@door(DOOR_OPEN, why="every Client resolves this server through it and the "
                     "port-change cascade runs over it (ADR-0003)")
def health():
    conn  = get_db()
    count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    conn.close()
    # port is what this process is actually listening on; next_port is what the
    # admin has saved but not restarted into yet. A client records next_port
    # while it can still reach the old one, then falls back to it once the old
    # listener goes away - that is the whole port-change cascade, and it is
    # exactly how 069's bind-port.ps1 moves a binding when iis.json is
    # present: bind the new port beside the old one, let next_port carry it
    # to every online client, then remove the old one. Only the undetected
    # case - HttpPlatformHandler launched this process (ADR-0001) but
    # install-iis.ps1 never ran, so nothing recorded which site owns the
    # binding - has no way to move the port at all; never advertise
    # next_port there.
    saved = _load_server_cfg()
    locked = _iis_served_undetected()
    if locked:
        next_port = None
    else:
        next_port = saved.get("port")
    return jsonify({
        "status":    "ok",
        "timestamp": datetime.now().isoformat(),
        "total":     count,
        "port":      PORT,
        "next_port": next_port if next_port != PORT else None,
        # The console's Server Settings window (gui_settings.py) is its own
        # process - interactive GUI mode, not the process HttpPlatformHandler
        # launched - so its own _iis_served_undetected() answers for itself,
        # not for whichever process actually holds PORT. It probes this
        # loopback endpoint instead, the way refresh_stats already does for
        # liveness, and reads this key rather than re-deriving it.
        "port_locked": locked,
        # What is in front of this port, not what this process was
        # configured to do. Under IIS the two are different questions with
        # different answers: TLS ends at the site (ADR-0001), `ssl_enabled` is
        # written by the console's own certificate install and by nothing
        # else, and `ssl_cert.pem` may correctly not be there at all where
        # install-iis.ps1 bound from -PfxPath or -CertThumbprint. So an
        # install whose certificate IIS holds answered `false` over a site
        # serving https, which is the one wrong answer this key can give -
        # every Client resolves the server through here. `_iis_tls_bound()`
        # already knew, and was not being asked: it is the banner's answer and
        # the Remote Admin door's, so this is now the third caller of one
        # function rather than a fourth spelling of the question. It and not
        # `_port_serves_tls()` directly, which it is the single caller of by
        # design - a probe is a handshake against this machine's own port, and
        # a second caller is a second handshake on a schedule nobody wrote
        # down. Off IIS nothing moves: this process binds the listener out of
        # those two files, so the flag and their presence are the whole of the
        # answer.
        "ssl":       (_iis_tls_bound() if _iis_host() is not None else
                      bool(_SERVER_CFG.get("ssl_enabled")
                           and os.path.exists(SSL_CERT_PATH)
                           and os.path.exists(SSL_KEY_PATH))),
        # Additive, so a Client of any version still finds the server here and
        # still follows a port change. A client that knows the field can hide
        # its Cancel control rather than offer one that only ever fails; a
        # client that does not is unaffected, because the rule is enforced at
        # the endpoint either way.
        "storekeeper_can_cancel": _storekeeper_can_cancel(),
        # Additive for the same reason (ADR-0017): the Storekeeper hides its
        # Add Engineer control rather than offering one the server will refuse,
        # and a client built before the key reads allowed, which is what it was.
        "storekeeper_can_add_engineer": _storekeeper_can_add_engineer(),
        # Additive for the same reason (#198), and read on the tick that
        # already reads the switch above: what it buys the Storekeeper is
        # knowing that an auto-approved Transaction it has just recorded is
        # still retractable without a password, so the Cancel pill can offer
        # itself on a row that reads Confirmed. 0 is no window, which is what a
        # server built before the key means and what one with the setting off
        # means - the same answer by one number, as the setting itself is.
        "storekeeper_cancel_window_mins": _storekeeper_cancel_window_mins(),
        # Additive for the same reason, and read by the Storekeeper on the tick
        # that already reads the switch above. It is sent as the bare name: the
        # "(Storekeeper)" a log entry carries is a label, and wording it here
        # would put it in the `storekeeper` column of every row that client
        # submits.
        "storekeeper_name": _storekeeper_name(),
        # Additive, and unread by any client on purpose (#242): what
        # _client_addr() resolved this very request to, so deploy-checks.ps1
        # and an operator can both tell, from a machine that is not the
        # server, whether URL Rewrite is actually forwarding a caller's
        # address rather than every row quietly reading the loopback hop
        # HttpPlatformHandler proxies every request through.
        "seen_from": _client_addr(),
    })

# What each client app's release zip is called in dist\. The name is written
# down here and in tools/bundle-client.ps1, which is what builds the zip, and
# the two have to agree or this server hands out 404s for a package sitting
# beside it; cascade-audit.py holds them to each other.
CLIENT_PACKAGES = {
    "notifier":    "NotifierApp",
    "storekeeper": "StorekeeperApp",
}

_CLIENT_PKG_DIGESTS = {}


def _client_package(key):
    """Path to the client zip for `key` at the published version, or None.

    Looked for in dist\\ under the install directory - the one place on this
    machine that holds every shippable artifact, and since 062 the same
    directory tools/update.ps1 reads this server's own releases from. It is
    looked at twice, <dist>\\<version>\\ first and then <dist> itself, because
    package.ps1 writes dist\\<version>\\ and that whole directory is what gets
    carried to a machine, while a zip carried on its own lands beside it.

    Only the published version resolves. /version answers APP_VERSION as
    `latest` and a client asks for what it was told about, so a zip left in
    dist\\ by an older release is not something to hand out.
    """
    name = CLIENT_PACKAGES.get(key)
    if not name:
        return None
    filename = "%s-%s.zip" % (name, APP_VERSION)
    dist = os.path.join(BASE_DIR, "dist")
    for cand in (os.path.join(dist, APP_VERSION, filename),
                 os.path.join(dist, filename)):
        if os.path.exists(cand):
            return cand
    return None


def _client_package_sha256(path):
    """SHA-256 of a client zip, remembered against its mtime and size.

    Stated rather than implied, because it is what the client checks a
    finished download against before it stops the running app. Hashing eight
    megabytes on every /version would be paid by every client launch, and a
    replaced zip is a new mtime and a new size - two files that agree on both
    and differ in content would be a release overwritten in place, which is
    what package.ps1's <version>\\ directory exists to prevent.
    """
    try:
        st = os.stat(path)
    except OSError:
        return ""
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _CLIENT_PKG_DIGESTS.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    digest = h.hexdigest()
    _CLIENT_PKG_DIGESTS[path] = (stamp, digest)
    return digest


@app.route('/version')
@door(DOOR_OPEN, why="a client that had to authenticate to learn an update "
                     "exists is a client that never updates")
def get_version():
    """Latest published version + download link (if the installer is present next to
    AssetServer.exe). Clients compare this against their own APP_VERSION and prompt
    the user to update when behind. Drop a new AssetManager_Setup.exe beside the
    server exe and bump APP_VERSION to push an update."""
    installer = os.path.join(BASE_DIR, "AssetManager_Setup.exe")
    has_installer = os.path.exists(installer)

    # Additive, like every other key here: a client built before it reads what
    # it knows and goes on offering the installer. One entry per client zip
    # this server actually holds, so an app missing from the map is a package
    # nobody copied here rather than a client that may not update. The digest
    # is over the zip's own bytes and is checked by the updater BEFORE the
    # running app is stopped - a short download found afterwards leaves a
    # Notifier down, which is an engineer who stops being asked to confirm
    # anything.
    packages = {}
    for key in CLIENT_PACKAGES:
        path = _client_package(key)
        if path:
            packages[key] = {
                "filename": os.path.basename(path),
                "path":     "/download/client/%s" % key,
                "sha256":   _client_package_sha256(path),
                "size":     os.path.getsize(path),
            }

    return jsonify({
        "latest": APP_VERSION,
        "has_installer": has_installer,
        "download_path": "/download/installer" if has_installer else "",
        "client_packages": packages,
    })

@app.route('/download/installer')
@door(DOOR_OPEN, why="the update path is open or it is not a path - see "
                     "GET /version above")
def download_installer():
    installer = os.path.join(BASE_DIR, "AssetManager_Setup.exe")
    if not os.path.exists(installer):
        return jsonify({"error": "installer not available"}), 404
    return send_file(installer, as_attachment=True,
                     download_name="AssetManager_Setup.exe")

@app.route('/download/client/<key>')
@door(DOOR_OPEN, why="the update path is open or it is not a path - see "
                     "GET /version above")
def download_client_package(key):
    """One client app's release zip, out of dist\\ beside this server.

    No executable crosses this: the zip holds .py files, the launchers and the
    vendored lib\\, and what Windows starts afterwards is a signed pythonw.exe
    with a launcher as its argument (rule 12). That is what keeps the update
    path out of Defender ASR's way, and it is why this sits beside
    /download/installer rather than replacing it - a machine with no Python
    yet still needs the one exe we ship.

    `key` is looked up in CLIENT_PACKAGES rather than joined onto a path, so
    there is no name a caller can send that reaches a file this does not
    already know about.
    """
    path = _client_package(key)
    if not path:
        return jsonify({"error": "no package for that client",
                        "code": "no_package"}), 404
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path))

def _wants_cancelled():
    """True when the caller opted in to Cancelled Transactions on a list endpoint.

    Off by default on both /transactions and /export. Every client works out
    Pending as neither-confirmed-nor-rejected from what those two return, so a
    client built before cancelling existed would show every Cancelled
    Transaction as Pending for ever.
    """
    return str(request.args.get('include_cancelled', '')).strip().lower() \
        in ('1', 'true', 'yes')


@app.route('/transactions', methods=['GET'])
@door(DOOR_OPEN, why="ADR-0002 - the clients have no identity to "
                     "authenticate the read with either")
def get_transactions():
    member  = request.args.get('member', '')
    clauses, params = [], []
    if not _wants_cancelled():
        clauses.append('cancelled=0')
    if member:
        # COLLATE NOCASE, because this column is a label and not a key: it
        # holds the Engineer's name as it was at the time, deliberately
        # untouched when they are renamed or removed, so it carries whatever
        # spelling was written then. The Engineer asking is the same person
        # either way. `team_members.name` needs no such clause - its own
        # collation is NOCASE and that is what `=` uses.
        clauses.append('team_member=? COLLATE NOCASE')
        params.append(member)
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    conn  = get_db()
    rows  = conn.execute(
        'SELECT * FROM transactions' + where + ' ORDER BY timestamp DESC', params
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# How much text a caller may put in a Transaction's two free-text fields.
# Here for the reason _CHECKIN_MAX and the /clients/log caps further down are
# where they are: POST /transactions and POST /reject/<id> are unauthenticated
# by design (ADR-0002), so a caller on the network chooses both of these
# strings and chooses how long they are. `notes` is a note a storekeeper types
# and `reason` is a sentence an engineer gives for a rejection; neither has any
# business being a megabyte.
#
# `transactions` has no retention bound at all, which is what makes this
# different from the System Log rather than the same argument twice:
# LOG_MAX_ROWS bounds that table's row *count* and LOG_RETENTION_DAYS its age,
# so an unbounded value walks past both by being one enormous row - and nothing
# bounds this table by either measure.
#
# Truncated rather than refused. The movement a Transaction records has already
# happened, so a note that ran long must not be what stops it being recorded -
# the same argument the offline buffer rests on. A rejection is the Engineer
# answering, and the answer matters more than its length.
#
# 500 rather than the log's 400: a note is the thing being described where a
# System Log `detail` is one line summarising something else. The log's own
# copy of a rejection reason is still cut to _LOG_DETAIL_MAX by _log_event,
# which is that writer's rule about its own column and not this one.
_TXN_TEXT_MAX = 500

# And how much of a *name* may be written into one. `cancelled_by` is the
# fourth column on this table an unauthenticated caller chooses the length of -
# POST /transactions/cancel needs no password at all for a Pending Transaction
# while the Storekeeper switch is on, and absent means allowed - so the
# paragraph above applies to it unchanged.
#
# 120 rather than _TXN_TEXT_MAX, because it is a label and not prose: it holds
# a person's name, or "Admin", which is exactly the class _CHECKIN_MAX exists
# for one section down and is measured against the same thing - a hostname, an
# account name, a version string. A constant of its own rather than a second
# caller of that one: what a Client may claim about itself and what may be
# written into a Transaction are two facts that happen to share a number, and
# raising either for its own reasons must not move the other.
_TXN_NAME_MAX = 120


@app.route('/transactions', methods=['POST'])
@door(DOOR_OPEN, why="ADR-0002 - the transaction endpoints are open, and "
                     "the Lookup Sheet is what stands in front of this one")
def create_transaction():
    # No timestamp is read from the body. This endpoint is unauthenticated
    # (ADR-0002) and a caller who could set the timestamp could rewrite
    # history; backdating belongs to the Server GUI, behind the admin password.
    payload, status = _create_transaction(request.json or {})
    return jsonify(payload), status

@app.route('/pending/<path:member>')
@door(DOOR_OPEN, why="ADR-0002 - the Notifier asks what is waiting for "
                     "the Engineer it was installed for")
def get_pending(member):
    rows = _pending_rows(member)
    if not rows:
        # A Notifier still polling under a name that has since been corrected.
        # The rows moved with the rename (`_rename_member`), so this Notifier
        # is handed an empty queue - which is indistinguishable from having
        # nothing to confirm, and is the same silent failure the collation
        # above exists to prevent. The current spelling is resolved from the
        # act that changed it and the question asked again; the Client learns
        # the new name for itself on its next check-in, which is what makes
        # this a bridge rather than a second source of truth.
        #
        # Only where the first answer was empty, so a name nobody has renamed
        # costs nothing at all, and an Engineer with pending Transactions is
        # never answered from anywhere but their own name.
        current = _former_member_name(member)
        if current:
            rows = _pending_rows(current)
    return jsonify([dict(r) for r in rows])

def _txn_engineer(conn, trans_id):
    """The Engineer a Transaction names - the one who answered it, for a
    System Log entry that records an answer (#282)."""
    row = conn.execute("SELECT team_member FROM transactions WHERE id=?",
                       (trans_id,)).fetchone()
    return row["team_member"] if row else ""

def _decide_transaction(trans_id, verdict, origin, reason="", actor=""):
    """Confirm or reject one Pending Transaction. (payload, status).

    The one writer of an answer, so the desktop routes cannot record the
    same act differently (#286): `verdict` is "confirmed" or "rejected",
    `origin` is the route's own fact ("desktop", #282) and `actor` the
    System Log's name for who answered - empty where the caller is
    unauthenticated and the address is all there is.
    """
    rejecting = verdict == "rejected"
    conn = get_db()
    # Only a Pending Transaction may be confirmed, which is the same shape
    # GET /pending/<member> already filters on. Without it the popup queue
    # produces the failure on its own: a Transaction is queued, the Storekeeper
    # cancels it, and the engineer clicks Confirm on the popup still on screen -
    # leaving confirmed=1 beside cancelled=1, with confirmed_at overwritten so
    # the row no longer records when it was retracted. Against a Rejected row it
    # is worse than untidy: /stats counts Confirmed as confirmed=1 AND
    # cancelled=0, so a rejected-then-confirmed row inflates that tile.
    # Capped here rather than at the UPDATE below: the same value is put in
    # front of _log_event a few lines on, and one truncation is what keeps the
    # row and the System Log entry saying the same thing.
    reason = str(reason or '')[:_TXN_TEXT_MAX]
    if rejecting:
        cur = conn.execute(
            "UPDATE transactions SET rejected=1, confirmed_at=?, "
            "rejection_reason=?, origin=? "
            'WHERE id=? AND confirmed=0 AND rejected=0 AND cancelled=0',
            (datetime.now().isoformat(), reason, origin, trans_id))
    else:
        cur = conn.execute(
            "UPDATE transactions SET confirmed=1, confirmed_at=?, origin=? "
            'WHERE id=? AND confirmed=0 AND rejected=0 AND cancelled=0',
            (datetime.now().isoformat(), origin, trans_id))
    conn.commit()
    changed = cur.rowcount
    engineer = _txn_engineer(conn, trans_id) if changed else ""
    conn.close()
    if not changed:
        # Reported rather than answered "confirmed" over an update that changed
        # nothing. The clients ignore the body here (the Notifier's _confirm
        # swallows everything), so this is for whoever is reading afterwards.
        return {"error": "That transaction is not pending, so it cannot "
                         "be %s." % verdict,
                "code": "not_pending"}, 409
    # A desktop caller is unauthenticated (ADR-0002), so the address is the
    # only fact about who this actually was - which is exactly why it is
    # recorded.
    data = {"origin": origin, "engineer": engineer}
    if rejecting:
        _log_event("transaction.rejected",
                   "#%d  %s" % (trans_id, reason or "(no reason given)"),
                   actor=actor, level="warn", address=_client_addr(),
                   data=data)
    else:
        _log_event("transaction.confirmed", "#%d" % trans_id, actor=actor,
                   address=_client_addr(), data=data)
    return {"status": verdict}, 200


@app.route('/confirm/<int:trans_id>', methods=['POST'])
@door(DOOR_OPEN, why="ADR-0002 - a Notifier has no credential to confirm "
                     "with, and giving it one would ship the secret")
def confirm_transaction(trans_id):
    # Only a Pending Transaction may be confirmed, which is the same shape
    # GET /pending/<member> already filters on. Without it the popup queue
    # produces the failure on its own: a Transaction is queued, the Storekeeper
    # cancels it, and the engineer clicks Confirm on the popup still on screen -
    # leaving confirmed=1 beside cancelled=1, with confirmed_at overwritten so
    # the row no longer records when it was retracted. Against a Rejected row it
    # is worse than untidy: /stats counts Confirmed as confirmed=1 AND
    # cancelled=0, so a rejected-then-confirmed row inflates that tile.
    payload, status = _decide_transaction(trans_id, "confirmed", "desktop")
    return jsonify(payload), status

@app.route('/reject/<int:trans_id>', methods=['POST'])
@door(DOOR_OPEN, why="ADR-0002, as POST /confirm/<id> beside it")
def reject_transaction(trans_id):
    data = request.json or {}
    payload, status = _decide_transaction(trans_id, "rejected", "desktop",
                                          reason=data.get('reason'))
    return jsonify(payload), status

@app.route('/stats')
@door(DOOR_OPEN, why="four counts over the table GET /transactions "
                     "already answers in full (ADR-0002)")
def get_stats():
    conn      = get_db()
    total     = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    pending   = conn.execute('SELECT COUNT(*) FROM transactions '
                             'WHERE confirmed=0 AND rejected=0 AND cancelled=0').fetchone()[0]
    confirmed = conn.execute('SELECT COUNT(*) FROM transactions '
                             'WHERE confirmed=1 AND cancelled=0').fetchone()[0]
    # Assets currently held by an engineer: per asset, the newest confirmed
    # transaction must be 'Out Store'. Counting every confirmed 'Out Store' row
    # instead would never decrease when an asset is returned.
    out_now   = conn.execute(
        """WITH latest AS (
             SELECT direction,
                    ROW_NUMBER() OVER (
                      PARTITION BY %s
                      ORDER BY timestamp DESC, id DESC
                    ) AS rn
             FROM transactions
             WHERE confirmed = 1 AND cancelled = 0
           )
           SELECT COUNT(*) FROM latest WHERE rn = 1 AND direction = 'Out Store'"""
        % _asset_key_sql()
    ).fetchone()[0]
    conn.close()
    return jsonify({"total": total, "pending": pending, "confirmed": confirmed, "out_now": out_now})

@app.route('/export')
@door(DOOR_OPEN, why="the Storekeeper's Excel export, over the table "
                     "GET /transactions already answers (ADR-0002)")
def export_all():
    """Full table as JSON. Cancelled Transactions are left out unless the caller
    passes include_cancelled - see _wants_cancelled. The default shape is
    unchanged, which is what lets an un-updated Storekeeper keep working.
    """
    where = '' if _wants_cancelled() else ' WHERE cancelled=0'
    conn  = get_db()
    rows  = conn.execute(
        'SELECT * FROM transactions' + where + ' ORDER BY timestamp DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ─── Engineers ────────────────────────────────────────────────────────────────

# `open_settings` was here until 013. Ticket 012 made an Engineer's Own Password
# open Notifier Settings by itself - the same door that name stood for - so the
# permission gated nothing, and a permission that gates no real behaviour must
# not stay (rule 8): an Admin ticks it and believes something changed. Nothing
# read it when it went; the ticks already stored are read by nothing rather than
# read differently, since `_member_permissions` filters the column through this
# tuple and a name not in it drops out.
PERMISSIONS = (
    "view_all_history",   # Dashboard lists every engineer's records, not only own
)

DEFAULT_PROFILE_PERMISSIONS = ()   # the default profile grants nothing

#: What each Permission is called in front of an Admin, for the checkboxes the
#: Manage Users window draws. **Not a second list of names** - rule 8 keeps that
#: in PERMISSIONS above, and the window loops over PERMISSIONS and looks a label
#: up here, so a name with no label still appears as itself rather than dropping
#: out of the form. It lives here rather than being read from the Storekeeper's
#: PERMISSION_LABELS because the server imports no client module (rule 10);
#: 013 took that dialog out of the Storekeeper, so this is now the only caption
#: table there is, and cascade-audit.py holds it to PERMISSIONS in both
#: directions.
PERMISSION_LABELS = {
    "view_all_history": "See every Engineer's history, not only their own",
}


def _member_permissions(row):
    """Permissions in force for a team_members row.

    The stored list is only consulted on a custom profile, so switching an
    engineer back to default revokes everything at once without having to clear
    the checkboxes, and switching back to custom restores what was ticked."""
    if (row["profile"] or "default") != "custom":
        return list(DEFAULT_PROFILE_PERMISSIONS)
    stored = (row["permissions"] or "").split(",")
    return [p for p in PERMISSIONS if p in stored]


def _rehash_member_password(name, new_hash):
    """Store an already-computed hash of one Engineer's Own Password.

    A hash rather than a password, for the reason _rehash_admin_password gives:
    POST /members is the only way to *set* one, and it asks for the admin
    password first. The column is not renamed and the row is otherwise
    untouched, so a client that has never heard of this sees nothing change.
    """
    conn = get_db()
    try:
        conn.execute("UPDATE team_members SET password_hash=? WHERE name=?",
                     (new_hash, name))
        conn.commit()
    finally:
        conn.close()


def _set_member_password(name, new_password, admin_password,
                         authorised_as=None):
    """Set or clear one Engineer's Own Password. The admin password, or #171's.

    The enforcement point the two writers share: POST /members' member_password
    field, and the Engineer's card in the Server GUI's Manage Users window.
    Add Transaction and
    Cancel have the same shape for the same reason - a rule must not hold at
    the endpoint and quietly not in the window an Admin uses, which is exactly
    where somebody would reach for a way past it.

    /auth/change_password writes the same column and deliberately does not come
    through here: it takes the *Engineer's* own password, which this helper
    does not accept and must not, and a flag argument saying which credential
    opened it would put "may an own password do this?" at every call site -
    the decision common.py keeps as two doors rather than one function for
    exactly that reason. What the two of them have to agree on is not the
    write, it is what a password an Admin set means.

    **A password an Admin set is temporary.** Setting one arms
    must_change_password, so the Engineer is made to choose their own the first
    time they authenticate with it, and this is the whole of the reset path
    too: an Admin who is told a password has been forgotten sets another one
    here and the Engineer replaces that one in turn. Nothing else arms the
    flag, because nothing else sets a password on somebody else's behalf.

    An empty `new_password` clears the hash **and** the flag. An Engineer with
    no Own Password is asked for nothing, so a flag left armed beside an empty
    column would be a demand to replace a password that does not exist.

    **`authorised_as` is the Server Settings capability reaching this** (#171),
    and it is the same shape `_cancel_transaction` already carries: the
    endpoint has proved a credential through `_remote_authorise` and is naming
    who every entry is to be attributed to, because a capability password is
    replayed rather than compared and this helper has no way to check one. When
    it is set the admin password is not examined at all, and a caller that
    passes both is the endpoint's bug rather than a second door.

    **What that delegates is written down rather than waved past.** This is the
    argument that kept it out of ADR-0006's set: whoever can set an Engineer's
    Own Password can then open that Engineer's Settings as them - a second
    Admin, not one delegated action. #171 delegates it anyway, deliberately, and
    pays for it in visibility: `CAPABILITY_REACH` says so on the Capability
    Passwords row, the panel says so on its face, and every act here is
    attributed to the delegate rather than to the Admin. See ADR-0009 and
    ADR-0015.

    Returns (payload, status) like the other enforcement helpers here, so a
    caller renders a refusal it did not have to word itself.
    """
    if authorised_as is None and not _admin_password_ok(admin_password):
        return {"error": "Wrong admin password.", "code": "bad_password"}, 401
    name = (name or "").strip()
    row = _member_row(name) if name else None
    if row is None:
        return {"error": "No such Engineer: %s" % (name or "(none)"),
                "code": "no_member"}, 404
    new = new_password or ""
    if new and len(new) < PASSWORD_MIN:
        return {"error": "An Own Password must be at least %d characters."
                         % PASSWORD_MIN, "code": "too_short"}, 400
    conn = get_db()
    try:
        conn.execute("UPDATE team_members SET password_hash=?,"
                     " must_change_password=? WHERE name=?",
                     (hash_password(new) if new else "", 1 if new else 0,
                      name))
        conn.commit()
    finally:
        conn.close()
    # Through the one helper POST /members and the console share, so the log
    # cannot say one thing about a password set over the wire and another about
    # the same password set at this window.
    _log_event("member.password_set" if new else "member.password_cleared",
               "%s%s" % (name, "  (temporary)" if new else ""),
               actor=authorised_as or "Admin", level="warn")
    return {"status": "set" if new else "cleared", "name": name,
            "has_password": bool(new),
            "must_change_password": bool(new)}, 200


#: What separates the two spellings in a `member.renamed` detail. One string,
#: because `_rename_member` writes it and `_parse_renamed` reads it, and a log
#: line nothing can parse is a Notifier that stays deaf.
_RENAMED_SEP = "  ->  "


def _parse_renamed(detail):
    """(id, old name, new name) out of a `member.renamed` detail, or None.

    The detail is written as `#<id>  <old>  ->  <new>`. A name carrying the
    separator itself would be read short, which is a misparse rather than a
    wrong answer: the id is what the caller acts on and it is read from the
    front.
    """
    d = (detail or "").strip()
    if not d.startswith("#") or _RENAMED_SEP not in d:
        return None
    head, new = d.split(_RENAMED_SEP, 1)
    ident, sep, old = head.partition("  ")
    if not sep or not ident[1:].isdigit():
        return None
    return int(ident[1:]), old.strip(), new.strip()


def _former_member_name(name):
    """The Engineer's current name, given a name that used to be theirs.

    Empty where the name was never renamed away, which is every name on a
    server nobody has renamed anybody on.

    **Derived from the `member.renamed` entries rather than from a table of
    former names.** The System Log is already the record of the act and already
    carries both spellings and the id; a second copy of that fact is what the
    cascade rule exists to prevent, and it would be the copy that goes stale.
    What it costs is that table's own retention (LOG_RETENTION_DAYS): a
    Notifier that has not run since the rename fell out of the log has no
    former name left to be found by. That is bounded by how long a laptop can
    be switched off rather than by how long ago somebody was renamed, and it is
    not the only answer either - the check-in hands every Client the current
    spelling for the id it holds, which is the fix that does not expire.

    Newest first, so a name renamed away twice resolves through the most recent
    act rather than the first one.
    """
    name = (name or "").strip()
    if not name:
        return ""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT detail FROM system_log WHERE event='member.renamed'"
            " ORDER BY id DESC").fetchall()
    except Exception:
        # The log is not what this server is for. A query that cannot run
        # answers "no former name", which is what it answers on a server where
        # nobody has been renamed - never an exception into a poll.
        return ""
    finally:
        conn.close()
    for r in rows:
        parsed = _parse_renamed(r["detail"])
        if not parsed or parsed[1].lower() != name.lower():
            continue
        row = _member_row_by_id(parsed[0])
        if row is not None and str(row["name"]).lower() != name.lower():
            return str(row["name"])
        return ""
    return ""


@app.route('/members', methods=['GET'])
@door(DOOR_OPEN, why="the list every client offers an Engineer from; no "
                     "Own Password hash is in it")
def list_members():
    conn = get_db()
    rows = conn.execute('SELECT * FROM team_members ORDER BY name').fetchall()
    conn.close()
    # has_password, never the hash: this endpoint needs no password to call, so
    # anything derived from one must not leave the server.
    #
    # must_change_password is added beside it rather than folded into it,
    # because there are three states and not two: no Own Password at all, one
    # waiting to be replaced, and one the Engineer chose. A client built before
    # this reads the keys it knows and behaves exactly as it did - additive
    # only, which is what lets the server go first in a rollout - and the flag
    # says nothing that trying the password would not.
    #
    # `id` is beside the name rather than instead of it, and every caller here
    # still asks by name: what it is for is a Client that wants to survive the
    # name changing under it (the check-in answers with both), and an Admin
    # window that has to name the row it is renaming.
    return jsonify([{
        "id":           r["id"],
        "name":         r["name"],
        "auto_approve": bool(r["auto_approve"]),
        "profile":      r["profile"] or "default",
        "permissions":  _member_permissions(r),
        "has_password": bool(r["password_hash"]),
        "must_change_password": bool(r["must_change_password"]),
    } for r in rows])

@app.route('/permissions', methods=['GET'])
@door(DOOR_OPEN, why="a fact about this build - what a Permission is "
                     "called (rule 8) - and about no install")
def list_permissions():
    """The Permission names and what each is called in front of an Admin. #171.

    **No credential**, for `GET /members`' reason one step further on: every
    `/members` answer already carries the names in each Engineer's
    `permissions` list, so what this adds is the caption beside the name and
    nothing that was not already visible.

    It exists because rule 8 says the names live in `server.py` and no client
    carries a copy, and #171's Remote Admin users panel has to draw a tick per
    Permission with a caption on it. Without this the panel would either ship a
    second copy of `PERMISSION_LABELS` - the drift `cascade-audit.py` fails an
    app for - or show an Admin a row of bare `view_all_history` strings.

    A name with no caption is served as itself rather than dropped, which is
    what the Manage Users window already does with the same two tables: a
    Permission that has lost its caption is still a Permission, and an Admin
    who cannot see it cannot grant or revoke it.
    """
    return jsonify([{"name": p, "label": PERMISSION_LABELS.get(p, p)}
                    for p in PERMISSIONS])


def _member_door(data):
    """Who a `/members` body is authorised as, or the refusal. #171.

    Returns `(authorised_as, refusal, status)` - `authorised_as` being the
    sentence every System Log entry behind this call is attributed to.

    **The admin password is this door's own credential and not a remote-channel
    one**, which is `_remote_admit`'s `admin_is_native` and the second endpoint
    to use it after `POST /transactions/cancel` (ADR-0015). These routes have
    taken the admin password over plain HTTP since they existed, HTTP is the
    default deployment (rule 1), and the Storekeeper's own Add Engineer sits on
    the create-only path beside them - so a transport gate in front of the
    password would refuse the ordinary install for a channel #171 added. It is
    recorded as `Admin` for that reason too: nothing about where the caller was
    standing changed, and the `member.saved` entry already says it was the
    Admin's doing.

    The **capability** password is held to both halves, as it is everywhere: it
    is replayed rather than compared, so it is refused `insecure` over a
    connection this server cannot see encrypted, and every use of it is a
    `remote.action` before the call runs. The one documented cost is the same
    one the cancel door carries - the capability password is examined before
    the transport is judged, because only examining it says which of the two
    credentials arrived.
    """
    opened_by, actor, refusal, status = _remote_admit(
        "server_settings", data.get('password', ''),
        address=_client_addr(), admin_is_native=True)
    if refusal:
        return None, refusal, status
    return (actor if opened_by == "capability" else "Admin"), None, 200


@app.route('/members', methods=['POST'])
@door("server_settings", optional=True)
def add_member():
    """Add or update one Engineer.

    Three doors in one, and which one a body opened is decided by the
    `password` key alone. **No key at all** is the Storekeeper's create-only
    path (ADR-0017). A key carrying the **admin password**, or the **Server
    Settings** capability password over HTTPS (#171), is the full path -
    the profile, the permissions and the Own Password included. The admin
    password is this door's own credential and is accepted over plain HTTP
    exactly as it always was (`_member_door`); the capability password is not.
    `password: ""`
    is an attempt at the second and is refused as wrong rather than treated as
    absent, `_cancel_transaction`'s convention and for its reason: a typo must
    not silently downgrade an Admin into a create-only caller and produce a
    refusal naming the wrong rule.

    The rules themselves live in `_save_member`, where the Server GUI's Manage
    Users window reaches them too.
    """
    data = request.json or {}
    who = None
    if 'password' in data:
        who, refusal, status = _member_door(data)
        if refusal:
            return jsonify(refusal), status
    payload, status = _save_member(
        data.get('name', ''),
        None,
        data.get('auto_approve'),
        profile=data['profile'] if 'profile' in data else _KEEP,
        permissions=data['permissions'] if 'permissions' in data else _KEEP,
        member_password=(data['member_password'] if 'member_password' in data
                         else _KEEP),
        authorised_as=who)
    return jsonify(payload), status

@app.route('/members/delete', methods=['POST'])
@door("server_settings")
def delete_member():
    """Remove an engineer. The admin password, or Server Settings over HTTPS.

    Existing transaction history is unaffected - `team_member` is stored as
    text on each record, so what shrinks is the list an Engineer is offered
    from and nothing that was already recorded against them. There is no
    unauthenticated path here and #171 did not add one: `POST /members`'
    create-only door delegates *creation*, which leaves a row with no
    credential of any kind on it, where this takes an Own Password down with
    the row.
    """
    data = request.json or {}
    who, refusal, status = _member_door(data)
    if refusal:
        return jsonify(refusal), status
    payload, status = _delete_member(data.get('name', ''), None,
                                     authorised_as=who)
    return jsonify(payload), status


@app.route('/members/rename', methods=['POST'])
@door("server_settings")
def rename_member():
    """Correct one Engineer's name. #171.

    Body: `{password, id, name}`. The admin password, or the **Server
    Settings** capability password over HTTPS. Forwards to `_rename_member`,
    the one writer of a rename, which the Server GUI's Manage Users window also
    calls - so ADR-0016's rules cannot hold at the console and quietly not here.

    **It authorises before it reads the body**, which is not incidental: this
    is the door `notifier_app.py`'s Remote Admin knocks on to learn whether a
    password opens the users panel, and the knock is this call with no `id` at
    all. A 400 is the door having opened and a 401 is the credential being
    turned away, which is the same shape the other three panels learn by - and
    it is the reason there is no endpoint anywhere that answers "what does this
    password open", that being a way to read the delegation map over the wire.

    Keyed on the id rather than the name, because the name is the thing being
    changed (ADR-0016).
    """
    data = request.json or {}
    who, refusal, status = _member_door(data)
    if refusal:
        return jsonify(refusal), status
    if 'id' not in data:
        return jsonify({"error": "No Engineer id provided",
                        "code": "no_id"}), 400
    try:
        member_id = int(data.get('id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid Engineer id", "code": "no_id"}), 400
    payload, status = _rename_member(member_id, data.get('name', ''), None,
                                     authorised_as=who)
    return jsonify(payload), status

def _within_auto_approve_cancel_window(row):
    """Is this an auto-approved Transaction still inside the window? (#198)

    Two questions and both are answered off the row. **How it came to be
    Confirmed** is `auto_approved`, written by `_create_transaction` at the
    moment it was written, rather than the Engineer's flag as it stands now: a
    row an Engineer really confirmed must never start reading as auto-approved
    because somebody ticked a box afterwards, which is what asking
    `team_members` here would do. **When it was created** is `confirmed_at`,
    which for an auto-approved row is exactly that moment - `timestamp` is the
    movement's own time and may be backdated by an admin, so it is the wrong
    clock for a window measured from the record being made.

    A `confirmed_at` that cannot be read as a time answers False, the way a
    setting nobody can make sense of does: this opens a door.
    """
    mins = _storekeeper_cancel_window_mins()
    if not mins or not row["auto_approved"]:
        return False
    try:
        made = datetime.fromisoformat(str(row["confirmed_at"]))
    except (TypeError, ValueError):
        return False
    return datetime.now() - made <= timedelta(minutes=mins)


@app.route('/transactions/cancel', methods=['POST'])
@door("manage_records", optional=True)
def cancel_transaction():
    """Body: {id, reason, cancelled_by?, password?}. **No auth** for a pending
    transaction while the storekeeper switch is on - ADR-0002 already leaves
    transaction endpoints open, and undoing a mis-scan has to be as quick as
    making one.

    The admin password is what opens a **confirmed** transaction: once the
    engineer has confirmed, they and the storekeeper are asserting different
    things about the physical world, and clearing that disagreement should not be
    one person's button. It also overrides the switch.

    Since #169 the **Manage Transaction History** capability password opens it
    too, over HTTPS, beside the admin password it already took - so a delegate
    administering this server remotely can retract a Confirmed row rather than
    being sent to the console for the one thing in that window they could not
    do. It overrides the switch and opens a Confirmed Transaction exactly as
    the admin password does, and it is recorded as the delegate it is.

    The password is examined **here** rather than at `_cancel_transaction`
    because which of the two arrived decides whether the transport matters:
    the admin password is this endpoint's own credential and is accepted over
    plain HTTP as it always was, while a capability password is refused over
    one. That is `_remote_admit`'s `admin_is_native`, and the ordering it costs
    is written down there and in ADR-0015. The **admin** password still goes to
    `_cancel_transaction` to be checked, so the one enforcement point is
    unmoved for it.

    A body with no `password` key is the unauthenticated path; `password: ""` is
    an attempt at a credential with an empty password and is refused as wrong,
    not treated as absent.
    """
    data = request.json or {}
    try:
        tid = int(data.get('id'))
    except (TypeError, ValueError):
        return jsonify({"error": "A transaction id is required.",
                        "code": "bad_id"}), 400
    reason = data.get('reason', '')
    named = (data.get('cancelled_by') or '').strip()
    pw = data.get('password')
    if pw is None:
        payload, status = _cancel_transaction(tid, reason, named)
        return jsonify(payload), status
    opened_by, actor, refusal, status = _remote_admit(
        "manage_records", pw, address=_client_addr(),
        admin_is_native=True)
    if refusal:
        return jsonify(refusal), status
    if opened_by == "admin":
        payload, status = _cancel_transaction(tid, reason, named, password=pw)
    else:
        payload, status = _cancel_transaction(tid, reason, named,
                                              authorised_as=actor)
    return jsonify(payload), status


# What an admin may correct. asset_model is not in the list on purpose: it
# comes from the lookup sheet's 4th column and no caller has ever typed it.
MODIFIABLE   = ("asset_number", "serial_number", "asset_type", "team_member",
                "direction", "notes", "timestamp")
_MODIFY_COLS = MODIFIABLE + ("asset_model",)


# How much of one value a correction's diff may write down (#200). A note is
# _TXN_TEXT_MAX (500) long and _LOG_DETAIL_MAX is 400, so one long note would
# fill the entry on its own and every field named after it would be lost to the
# cut _log_event makes at the end of the string. 60 is enough to read an
# identifier, an engineer's name, a direction or a timestamp whole - those being
# what a dispute is actually reconstructed from - and enough of a note to
# recognise which note it was.
_DIFF_VALUE_MAX = 60


def _modify_detail(tid, row, new):
    """What a correction changed, in one line, for the System Log (#200).

    The entry said who corrected which Transaction and what the row read
    afterwards, which is the half an Admin reading the log months later already
    has - the row is in front of them. What it could not say is what the row
    read *before*, and that is the half a dispute turns on. It is
    `transaction.deleted`'s argument applied one act earlier: for something
    whose evidence is the row itself, this entry is the record.

    Only fields that actually moved. A caller sends the whole form, so a
    correction of one field arrives carrying six that are unchanged, and
    writing those down would mean every entry carries the whole row and the
    diff stops being a diff.

    `_MODIFY_COLS` rather than `MODIFIABLE`, so the two fields rule 6 corrects
    from the Lookup Sheet - the Asset Type and the Asset Model - are recorded
    as changes when they move, which they do without any caller having asked.

    **Truncated deliberately, and it says so.** Each value is cut to
    `_DIFF_VALUE_MAX` on its own, so the last field named keeps both of its
    values rather than the first field's note eating the budget and the rest
    falling off the end of `_log_event`'s own cut; and where the fields
    themselves do not fit, whole fields are dropped from the end and the count
    of them is written down. A diff silently cut in half reads as a complete
    record of a smaller change, which is the one thing it must not do.

    It is deliberately not a shared helper. `_save_member`, `_save_asset` and
    `_save_server_cfg` all change existing values and all log without a diff,
    and each would want different fields, different redaction (a member row
    holds `password_hash`) and a different sentence - so they were considered
    and left, and a helper shaped by this one call site would be the wrong
    shape for the first of them to take it.

    **Returns `(detail, changes, dropped)`** since #071: the printed line
    exactly as before, the `(field, old, new)` triples it was built from - cut
    to `_DIFF_VALUE_MAX` the same way, kept in step with `detail`'s own
    truncation so the two never disagree about which fields made it in - and
    how many did not fit. The one call site turns the last two into
    `_log_event`'s `data`, so `_log_diff` reads them back structurally instead
    of re-parsing the first.
    """
    def show(v):
        s = "" if v is None else str(v)
        return ('"%s..."' % s[:_DIFF_VALUE_MAX] if len(s) > _DIFF_VALUE_MAX
                else '"%s"' % s)

    def trimmed(v):
        s = "" if v is None else str(v)
        return s[:_DIFF_VALUE_MAX] + "..." if len(s) > _DIFF_VALUE_MAX else s

    fields = [k for k in _MODIFY_COLS if str(row[k] or "") != str(new[k] or "")]
    if not fields:
        return "#%d  no field changed" % tid, [], 0

    parts = [f"{k}: {show(row[k])} -> {show(new[k])}" for k in fields]
    head, kept, used = "#%d  " % tid, [], 0
    for part in parts:
        left = len(parts) - len(kept)
        tail = 0 if left == 1 else len("  (+%d more not shown)" % (left - 1))
        cost = len(part) + (2 if kept else 0)
        if len(head) + used + cost + tail > _LOG_DETAIL_MAX:
            break
        kept.append(part)
        used += cost
    if not kept:                       # one field, on its own, still too long
        kept, n_kept = [parts[0][:_LOG_DETAIL_MAX - len(head)]], 1
    else:
        n_kept = len(kept)
    dropped = len(parts) - n_kept
    line = head + ";  ".join(kept)
    line += "  (+%d more not shown)" % dropped if dropped else ""
    changes = [(k, trimmed(row[k]), trimmed(new[k])) for k in fields[:n_kept]]
    return line, changes, dropped


@app.route('/transactions/delete', methods=['POST'])
@door("manage_records")
def delete_transactions():
    """Delete one or more transaction records by id.

    The admin password, or the **Manage Transaction History** capability
    password over HTTPS (R1, ADR-0015). This is the sharpest of the three
    remote actions and is why the holder name exists at all: the rows are what
    stops existing, so the `transaction.deleted` entry is the entire record
    that the act happened, and it named `Admin` whoever had asked for it until
    R1. It says which credential now.
    """
    data = request.json or {}
    who, refusal, status = _remote_authorise(
        "manage_records", data.get('password', ''),
        address=_client_addr())
    if refusal:
        return jsonify(refusal), status
    ids = data.get('ids', [])
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "No record ids provided"}), 400
    try:
        ids = [int(i) for i in ids]
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid ids"}), 400
    conn = get_db()
    qmarks = ",".join("?" * len(ids))
    cur = conn.execute(f"DELETE FROM transactions WHERE id IN ({qmarks})", ids)
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    # The one write here that leaves nothing behind to read, so the log entry is
    # the whole record that it happened. The ids, not the rows: a deleted row's
    # contents belong in the archive the dialog offers, not in here.
    _log_event("transaction.deleted",
               "%d record(s): %s" % (deleted, ", ".join(str(i) for i in ids)),
               actor=who, level="warn",
               address=_client_addr())
    return jsonify({"status": "ok", "deleted": deleted})

@app.route('/transactions/modify', methods=['POST'])
@door("manage_records")
def modify_transaction():
    """Correct one Pending Transaction. R1.

    Body: {password, id, <any of MODIFIABLE>}. The admin password, or the
    **Manage Transaction History** capability password over HTTPS.

    There was deliberately no endpoint for this until R1, and what changed is
    not the rule but where the Admin is standing: a capability that can delete
    a row outright and cannot correct a typo in one is a capability whose
    holder reaches for the deletion. The console's Modify Selected is the other
    door and both forward to `_modify_transaction`, the one enforcement point,
    so the Pending-only rule and rule 6's re-check cannot hold here and quietly
    not there.

    There is still **no unauthenticated path at all**, unlike
    `POST /transactions/cancel`: undoing a mis-scan has to be as quick as
    making one, and editing somebody else's record is not that.
    """
    data = request.json or {}
    who, refusal, status = _remote_authorise(
        "manage_records", data.get('password', ''),
        address=_client_addr())
    if refusal:
        return jsonify(refusal), status
    try:
        tid = int(data.get('id'))
    except (TypeError, ValueError):
        return jsonify({"error": "No record id provided",
                        "code": "no_id"}), 400
    fields = {k: data[k] for k in MODIFIABLE if k in data}
    if not fields:
        return jsonify({"error": "Nothing to correct",
                        "code": "no_fields"}), 400
    payload, code = _modify_transaction(
        tid, fields, actor=who, address=_client_addr())
    return jsonify(payload), code


@app.route('/records/import', methods=['POST'])
@door("import_archive")
def import_records():
    """Restore records from an .xlsx archive. R1.

    Body: {password, file_data: <base64 xlsx>, filename?}. The admin password,
    or the **Import Transaction Archive** capability password over HTTPS.

    The bytes are read straight through `openpyxl` rather than written to disk
    first, which is `POST /lookup/upload`'s shape and for its reason: an
    archive that turns out to be unreadable leaves nothing behind. `filename`
    is a label for the System Log and nothing else - it is never joined onto a
    path, so there is no name a caller can send that reaches a file.

    It **appends** with new ids, which is what the helper has always done: an
    archive is rows that were deleted from here, and a restore that could
    overwrite by id would let a caller rewrite a Transaction still in the
    table.
    """
    data = request.json or {}
    who, refusal, status = _remote_authorise(
        "import_archive", data.get('password', ''),
        address=_client_addr())
    if refusal:
        return jsonify(refusal), status
    file_b64 = data.get('file_data', '')
    if not file_b64:
        return jsonify({"error": "No file data provided",
                        "code": "no_file"}), 400
    name = str(data.get('filename') or "an uploaded archive")[:_TXN_NAME_MAX]
    try:
        raw = base64.b64decode(file_b64)
        n, refusal = _import_records_xlsx(io.BytesIO(raw), actor=who,
                                          source=name, address=_client_addr())
    except Exception as e:
        return jsonify({"error": "Invalid archive file: %s" % e,
                        "code": "bad_archive"}), 400
    if refusal:
        return jsonify({"error": refusal, "code": "bad_header"}), 400
    return jsonify({"status": "ok", "imported": n})


@app.route('/clients/checkin', methods=['POST'])
@door(DOOR_OPEN, why="a Client announces itself before it holds any "
                     "credential at all (ADR-0005)")
def client_checkin():
    # A POST of its own rather than anything hung off /health: an identifier and
    # a Windows account name have no business in a URL, where a reverse proxy
    # writes them verbatim into a log nobody prunes, the heartbeat has to stay
    # answerable with nothing attached, and the queue is handed back in the
    # response body, which a GET of a heartbeat has nowhere to put. See
    # ADR-0005.
    payload, status = _record_checkin(request.json or {},
                                      _client_addr())
    return jsonify(payload), status


@app.route('/clients', methods=['GET'])
@door("server_settings")
def list_clients():
    """The Client registry. The **admin password**, or the **Server Settings**
    capability password over HTTPS (#174) - a GET carrying a body, like
    `GET /admin/server_config` and `GET /admin/mail` above and for their reason.

    **Never open**, unlike every other credential-less read in this file. What
    those answer is a fact about this build - what a Permission is called, what
    models the sheet holds - where this is a map of the hostnames, Windows
    account names and source addresses of the machines on the internal network,
    which is the sentence `POST /clients/checkin` has always carried about why
    no such route existed. #174 creates it behind a credential rather than
    weakening that sentence.

    It answers what the console's Connected Clients window shows, in one round
    trip: the row, the certificate it says it pins, how long ago it was heard
    from, and the commands queued against it with each one's derived state. The
    commands come with the row because that window reads them for the selected
    Client and a remote panel would otherwise ask per press of an arrow key.

    `served` and `staged` are this server's own two fingerprints, so a panel
    can say what the certificate column means and whether there is anything to
    push at all - both public (`GET /cert` serves the first to anybody), and
    the **key** beside them is served from nowhere (rule 1).
    """
    data = request.json if request.is_json else {}
    who, refusal, status = _remote_authorise(
        "server_settings", (data or {}).get('password', ''),
        address=_client_addr())
    if refusal:
        return jsonify(refusal), status
    out = []
    for r in _client_rows():
        cid = r["client_id"]
        out.append({
            "client_id": cid, "hostname": r["hostname"],
            "os_user": r["os_user"], "app": r["app"], "version": r["version"],
            "member": r["member"], "address": r["address"],
            "reported_address": r["reported_address"],
            "cert_fingerprint": r["cert_fingerprint"],
            "first_seen": r["first_seen"], "last_seen": r["last_seen"],
            "age_secs": _since_ts(r["last_seen"]),
            "commands": [{"id": c["id"], "command": c["command"],
                          "issued_at": c["issued_at"],
                          "issued_by": c["issued_by"],
                          "expires_at": c["expires_at"],
                          "state": _command_status(c)}
                         for c in _command_rows(cid)],
        })
    return jsonify({"clients": out, "served": _cert_fingerprint(),
                    "staged": _cert_fingerprint(SSL_CERT_NEXT_PATH)})


@app.route('/clients/command', methods=['POST'])
@door("server_settings")
def queue_client_command():
    """Queue one command for one Client. The **admin password**, or the
    **Server Settings** capability password over HTTPS (#174).

    Forwards to `_queue_command`, the one writer of the queue, which the
    console's Connected Clients window also calls - so the duplicate guard, the
    refusal for a Client that has never checked in and the seven-day expiry
    written at issue time cannot hold at the console and quietly not here.
    There was deliberately no endpoint until #174 and what changed is where the
    Admin is standing, the same thing that changed for
    `POST /transactions/modify` at R1 and `POST /members/rename` at #171.

    **None of the three commands ends a Windows session** - `COMMAND_LABELS`
    says so and this route adds nothing to `COMMANDS`.

    It is a credential and not a person, so nothing the caller sends names the
    issuer: the row's `issued_by` and the `client.command_issued` entry beside
    it both carry `_remote_actor`'s sentence, the way
    `POST /transactions/cancel` ignores a `cancelled_by`.

    Refused with a `code`: `insecure` (403), `bad_password` (401), `no_client`
    (400), plus whatever `_queue_command` itself refuses - `bad_command` (400),
    `unknown_client` (404), `already_queued` (409).
    """
    data = request.json or {}
    who, refusal, status = _remote_authorise(
        "server_settings", data.get('password', ''),
        address=_client_addr())
    if refusal:
        return jsonify(refusal), status
    cid = str(data.get('client_id', '') or '').strip()
    if not cid:
        return jsonify({"error": "A client_id is required.",
                        "code": "no_client"}), 400
    payload, status = _queue_command(
        cid, str(data.get('command', '') or '').strip(), issued_by=who)
    return jsonify(payload), status


@app.route('/clients/push_cert', methods=['POST'])
@door("server_settings")
def push_staged_cert():
    """Queue `trust_cert` for every installation. The **admin password**, or
    the **Server Settings** capability password over HTTPS (#174).

    Phase two of a rotation (C3, ADR-0020), and the one act behind this
    capability that reaches the **whole fleet** from one call - which is why it
    is a route of its own rather than a `client_id` of `*` on the one above: a
    command for one machine and a command for every machine are different acts,
    and the second must not be reachable by leaving a field out of the first.

    Forwards to `_push_next_cert`, which refuses outright where nothing is
    staged, queues through `_queue_command` per Client so the duplicate guard
    holds, and writes one `cert.pushed` naming the fingerprint - the thing a
    command name alone cannot say months later.

    Refused with `insecure` (403), `bad_password` (401) or `no_staged_cert`
    (409).
    """
    data = request.json or {}
    who, refusal, status = _remote_authorise(
        "server_settings", data.get('password', ''),
        address=_client_addr())
    if refusal:
        return jsonify(refusal), status
    payload, status = _push_next_cert(issued_by=who)
    return jsonify(payload), status


@app.route('/clients/clear', methods=['POST'])
@door("server_settings")
def clear_client_registry():
    """Remove every installation not heard from for more than `days` (#203).
    The **admin password**, or the **Server Settings** capability password
    over HTTPS.

    A sixth route under `/clients`, which `tools/server-checks.py` holds to an
    allow-list precisely so that one has to be argued for rather than waved
    through. The argument is the one #174 made for the three above it: this
    registry is read and acted on from the Notifier's Remote Admin panel as
    well as at the console, and an Admin who may log a machine off remotely and
    must walk to the server to tidy up after a machine that no longer exists is
    being sent on an errand by the shape of the API rather than by the size of
    the act. It is not a `client_id` on a delete of one row, for
    `POST /clients/push_cert`'s reason: what this does is a statement about the
    fleet, and it is the only shape offered.

    Forwards to `_clear_stale_clients`, the one writer, which the console's
    Connected Clients window also calls - so the floor under the threshold, the
    row kept because its `last_seen` cannot be read, the `client_commands` rows
    left orphaned and the single `clients.cleared` entry cannot hold at the
    console and quietly not here.

    Body carries either `days`, a number, or `threshold`, the "d:h:m" string
    the Clear Old dialog's field takes since #268 - `_parse_age_threshold`
    reads the same string here that the console parses before calling
    `_clear_stale_clients` directly, so a caller over the wire is not left a
    year behind what the console can now say. `threshold` wins where both are
    sent.

    Refused with a `code`: `insecure` (403), `bad_password` (401) or `bad_age`
    (400, a threshold under `CLEAR_AGE_MIN_DAYS`, or a `threshold` string
    `_parse_age_threshold` cannot read).
    """
    data = request.json or {}
    who, refusal, status = _remote_authorise(
        "server_settings", data.get('password', ''),
        address=_client_addr())
    if refusal:
        return jsonify(refusal), status
    days = data.get('days')
    if data.get('threshold') is not None:
        try:
            days = _parse_age_threshold(data.get('threshold'))
        except (ValueError, TypeError):
            return jsonify({"error": "Could not read that threshold.",
                            "code": "bad_age"}), 400
    payload, status = _clear_stale_clients(days, actor=who)
    return jsonify(payload), status



# The System Log's own module since #227, and the one `bind()` call that has
# to run before the block below it: `server_cert`, the three registers and
# `server_gui` are each handed `_log_event`, so the writer has to be a live
# object by the time that block runs. Neither of the three names it hands
# over sits below this line - `get_db` is a long way above it and
# `_notify_of` came off `server_mail`'s flat import at the top of the file -
# so there is nothing keeping this call down here with them.
#
# `db_path` is handed over as a **reader** rather than as the path, for the
# reason `server_sync.bind()` takes it that way: `DB_PATH` is resolved once
# at this file's import and re-pointed by `tools/server-checks.py` between
# check groups, so a copy taken here would be the path as it was at import.
server_log.bind(
    db_path=lambda: DB_PATH,
    get_db=get_db,
    notify_of=_notify_of)
# Backup, restore, the migrations and the archive since #228. Nothing orders
# this call against the five below it: no other module is handed anything
# that file defines, and `_maintenance`, `get_db` and the paths it wants are
# all a long way above here. `db_path` is a reader rather than the path for
# the reason the call above takes one.
server_archive.bind(
    app_version=APP_VERSION,
    base_dir=BASE_DIR,
    migrations_dir=MIGRATIONS_DIR,
    restore_aside_dir=RESTORE_ASIDE_DIR,
    admin_cfg_path=ADMIN_CFG_PATH,
    server_cfg_path=SERVER_CFG_PATH,
    lookup_path=LOOKUP_PATH,
    db_path=lambda: DB_PATH,
    get_db=get_db,
    log_event=_log_event,
    maintenance=_maintenance,
    event_phrase=event_phrase)
# The asset lookup's write path and the proposals since #229. Five names,
# and nothing orders this call against the others: what
# `register_transactions.bind()` and `server_sync.bind()` are handed out of
# that module are function objects off the flat import at the top of this
# file, not anything this call sets. `DEFAULT_LOOKUP_B64` goes over rather
# than moving, rule 11 keeping the workbook embedded here.
server_lookup.bind(
    asset_types=ASSET_TYPES,
    default_lookup_b64=DEFAULT_LOOKUP_B64,
    lookup_path=LOOKUP_PATH,
    get_db=get_db,
    log_event=_log_event)


# Everything server_cert reads out of this module, handed over once. It sits
# here rather than beside the import because _admin_password_ok and _iis_host
# do not exist yet at the top of the file. The four queue and client readers
# beside them do - #226 moved them into server_clients.py - and so does
# _log_event since #227 moved it into server_log.py, this file importing both
# sets back flat at the top, so they are the same objects those modules hold
# and this call's shape did not change with their source. Nothing calls into
# server_cert before a request or a window does, both of which are long after
# import.
server_cert.bind(
    base_dir=BASE_DIR,
    ssl_cert_path=SSL_CERT_PATH,
    ssl_key_path=SSL_KEY_PATH,
    ssl_cert_next_path=SSL_CERT_NEXT_PATH,
    ssl_key_next_path=SSL_KEY_NEXT_PATH,
    cert_rollback_dir=CERT_ROLLBACK_DIR,
    admin_password_ok=_admin_password_ok,
    client_rows=_client_rows,
    command_rows=_command_rows,
    command_status=_command_status,
    iis_host=_iis_host,
    log_event=_log_event,
    queue_command=_queue_command,
    save_server_cfg=_save_server_cfg)

# The same hand-over for the Assets register, and here for the same reason:
# `get_db` is defined above this line and does not exist yet at the import.
# `_log_event` does, since #227 - it is `server_log.py`'s now and comes off
# the flat import at the top - and this call is below `server_log.bind()` so
# that the writer it hands over is a bound one. Nothing in that module runs
# before a request or a window calls into it.
register_assets.bind(get_db=get_db, log_event=_log_event)

# And the same hand-over for the Transactions register. Thirteen rather than
# two, and here for the same reason: every name on the list but `_log_event`
# is defined above this line and none of those exists yet at the import.
# `_asset_key_sql` is not on it - that one the module takes from
# `register_assets` itself, which is the whole reason this ticket waited for
# that one.
register_transactions.bind(
    get_db=get_db,
    log_event=_log_event,
    load_lookup_table=_load_lookup_table,
    storekeeper_name=_storekeeper_name,
    storekeeper_actor=_storekeeper_actor,
    admin_password_ok=_admin_password_ok,
    storekeeper_can_cancel=_storekeeper_can_cancel,
    within_auto_approve_cancel_window=_within_auto_approve_cancel_window,
    modify_detail=_modify_detail,
    txn_text_max=_TXN_TEXT_MAX,
    txn_name_max=_TXN_NAME_MAX,
    modifiable=MODIFIABLE,
    modify_cols=_MODIFY_COLS)


# And the same hand-over for the Engineers register. Ten, and here for the
# reason the two above are here: every name on the list but `_log_event` is
# defined above this line and none of those exists yet at the import. `_KEEP`
# is not on it - that one goes the other way, and is imported from the module
# rather than handed to it.
register_engineers.bind(
    get_db=get_db,
    log_event=_log_event,
    admin_password_ok=_admin_password_ok,
    member_permissions=_member_permissions,
    set_member_password=_set_member_password,
    storekeeper_actor=_storekeeper_actor,
    storekeeper_can_add_engineer=_storekeeper_can_add_engineer,
    renamed_sep=_RENAMED_SEP,
    password_min=PASSWORD_MIN,
    permissions=PERMISSIONS)

import server_gui
server_gui.bind(sys.modules[__name__])
from server_gui import (asset_proposals, asset_sync, backup_restore,
                        capability_passwords, client_list, mail_settings,
                        manage_assets, manage_records, manage_users,
                        notification_rules, run_gui, system_log, THEME,
                        DANGER, INPUT_BG, SUCCESS,
                        _CONSOLE_UNLOCKED, _CONSOLE_UNSAVED, _ago_ts,
                        _capability_state, _client_colour, _status_of,
                        _transaction_client, _transaction_log_rows)


# The System Log's one route. It stayed here when #227 moved the cluster it
# belongs to into `server_log.py`, which is the shape #226 gave the
# `/clients*` routes and 041-043 gave the three registers - a module of what
# the routes call, not of the routes - and it is what leaves `@app`, `@door`,
# `DOOR_OPEN`, `request` and `jsonify` out of that file entirely.
@app.route('/clients/log', methods=['POST'])
@door(DOOR_OPEN, why="POST /clients/checkin's reason - a Client holds no "
                     "credential - and a log nothing can post to is none")
def client_log():
    # Its own endpoint rather than more fields on /clients/checkin, for the
    # reason ADR-0005 gave for not widening /health: the check-in is a Client's
    # whole statement about itself and the response is a command queue, while
    # this is a batch of somebody else's history and a Client with nothing to
    # say must not have to check in to say it.
    payload, status = _record_log(request.json or {}, _client_addr())
    return jsonify(payload), status


# ─── Mail ─────────────────────────────────────────────────────────────────────
# What this server can store of a secret it has to be able to read back, and
# nothing else: the mail this heading used to carry is `server_mail.py` since
# #224.
#
# Every password this system has stored until now is a one-way salted hash
# (ADR-0008): nothing on this machine can recover one, which is why a stolen
# admin_config.json is not a stolen password. An SMTP password is *replayed* at
# every send, so it has to be recoverable, and it is the first secret of that
# kind here. It is encrypted with Windows DPAPI at machine scope and kept in
# smtp_secret.dat; where DPAPI is not there it is refused rather than written
# in plaintext. ADR-0013 records all three of those decisions.
#
# The pair below stayed when the mail went, and stayed here rather than moving
# into `server_mail.py`, because mail is not its only caller: the external
# asset system's credential (ADR-0014) is the other, and that cluster is 051's.
# A shared helper living in one of the two modules that use it would leave the
# other importing a mail module for something neither owns.

# CRYPTPROTECT_LOCAL_MACHINE. Machine scope rather than user scope because one
# install is opened by three different accounts - the interactive Admin at this
# console, LocalSystem under the Windows Service, and the app pool identity
# under IIS - and a secret written by one that the other two cannot read is a
# mail feature that works only while somebody is logged in.
_DPAPI_LOCAL_MACHINE = 0x04



def _secret_set(path, label, secret, unavailable):
    """Encrypt one replayable secret for this machine, or remove it.

    Returns "" or a refusal sentence. The refusal where DPAPI is unavailable is
    the whole of the fallback story: there is not one. A recoverable password
    written in plaintext into an install directory that gets zipped into
    rollback copies and carried around in backups is a worse thing to have than
    the feature it belongs to not working on that machine.

    It takes the path rather than naming one because there are **two** of these
    now - the mail relay's password (ADR-0013) and the external asset system's
    credential (ADR-0014) - and ADR-0013 said in as many words that a second
    one is the moment to stop writing the DPAPI calls out again. What it is
    *not* is a store: each secret keeps a file of its own, so clearing one
    cannot take the other with it, and each has its own three-line wrapper
    below naming its own file. `unavailable` is the caller's sentence, because
    the advice differs - a relay that asks for no password is a real answer for
    mail, and an external system that needs none is a different one.
    """
    secret = secret or ""
    if not secret:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as ex:
            return "The stored password could not be removed: %s" % ex
        return ""
    if not HAS_DPAPI:
        return unavailable
    try:
        blob = win32crypt.CryptProtectData(secret.encode("utf-8"), label, None,
                                           None, None, _DPAPI_LOCAL_MACHINE)
        with open(path, "wb") as f:
            f.write(blob)
    except Exception as ex:
        return "The password could not be encrypted: %s" % ex
    return ""


def _secret_get(path):
    """One stored secret, or "". Never raises.

    Read at the moment it is replayed rather than held in a module-level
    variable for the life of the process: what is in memory for a second is
    not what a crash dump or a hung worker's stack has in it for a day.
    """
    if not HAS_DPAPI or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            blob = f.read()
        return win32crypt.CryptUnprotectData(blob, None, None, None,
                                             _DPAPI_LOCAL_MACHINE)[1].decode(
                                                 "utf-8")
    except Exception:
        return ""


# Everything server_mail reads out of this module, handed over once. It sits
# here rather than in the block above that binds the three registers, for that
# block's own reason turned one file further down: `_secret_set` and
# `_secret_get` are defined *here*, below it, and a name handed over before it
# exists is the one real failure mode of this pattern. Nothing in that module
# runs before a request, a window or a log write reaches it.
server_mail.bind(
    log_levels=LOG_LEVELS,
    smtp_secret_path=SMTP_SECRET_PATH,
    load_server_cfg=_load_server_cfg,
    log_event=_log_event,
    save_server_cfg=_save_server_cfg,
    secret_get=_secret_get,
    secret_set=_secret_set,
    validate_port=_validate_port,
    event_sentence=event_sentence)


# Everything server_sync reads out of this module, handed over once. It
# sits here beside the call above and for that call's reason: `_secret_set`
# and `_secret_get` are two of the fifteen and are defined just above,
# below the block that binds the three registers. Nothing in that module
# runs before a window, a background tick or a log write reaches it.
#
# `db_path` is handed over as a **reader** rather than as the path. `DB_PATH`
# is resolved once at this file's import and re-pointed by
# `tools/server-checks.py` between check groups, so a copy taken here would
# be the path as it was at import - the same failure this pattern's own rule
# is about, one step along.
server_sync.bind(
    app_version=APP_VERSION,
    check_import_mapping=_check_import_mapping,
    db_path=lambda: DB_PATH,
    get_db=get_db,
    import_fields=_IMPORT_FIELDS,
    import_labels=_IMPORT_LABELS,
    load_assets=_load_assets,
    load_server_cfg=_load_server_cfg,
    log_db_timeout=_LOG_DB_TIMEOUT,
    log_event=_log_event,
    map_import_columns=_map_import_columns,
    save_asset=_save_asset,
    secret_get=_secret_get,
    secret_set=_secret_set,
    sync_secret_path=SYNC_SECRET_PATH)


# ─── Lookup routes ────────────────────────────────────────────────────────────

@app.route('/lookup')
@door(DOOR_OPEN, why="rule 6 validates every submission against this, "
                     "and POST /transactions is open (ADR-0002)")
def lookup_asset():
    """
    GET /lookup?q=<asset_number_or_serial>
    Returns {"found": true, "asset_type": "...", "asset_number": "...", "serial_number": "..."}
    or      {"found": false}
    """
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({"found": False, "error": "No query provided"}), 400
    table = _load_lookup_table()
    entry = table.get(q.lower())
    if entry:
        return jsonify({"found": True, **entry})
    return jsonify({"found": False})

@app.route('/asset_types')
@door(DOOR_OPEN, why="rule 2 - every client reads its type list from "
                     "here before it can draw a form")
def asset_types():
    """GET /asset_types — the valid asset types, derived from the lookup sheet
    (falls back to the baked-in list). Clients load this at startup so new types
    added to asset_lookup.xlsx appear without a rebuild."""
    return jsonify({"asset_types": _lookup_asset_types()})

@app.route('/asset_models')
@door(DOOR_OPEN, why="rule 2's neighbour, read by the same forms for the "
                     "same reason (026)")
def asset_models():
    """GET /asset_models[?type=<asset_type>] - the models the register holds.

    The wire form of what the Lookup Sheet window's Asset Model combobox has
    offered since 026, through the one helper both read, so a client's list
    and the console's cannot be two spellings of one query. No credential: it
    answers nothing `GET /lookup` does not already answer one asset at a time.
    An unknown type is an **empty list** rather than a 400 - a type with no
    model recorded yet is an ordinary state, not a bad request.
    """
    return jsonify({"asset_models": _asset_models(request.args.get("type", ""))})

@app.route('/lookup/file')
@door(DOOR_OPEN, why="the register as a workbook, which GET /lookup and "
                     "GET /asset_types already answer row by row")
def lookup_file():
    """GET /lookup/file — the Lookup Sheet as an xlsx.

    Generated from the `assets` table rather than served off disk: since 024
    the workbook is the interchange format and the table is the store, so the
    file beside the server is the seed this install started from and is not
    what anybody asking this question means. The shape on the wire is
    unchanged - the same four columns in the same order - so no client moves.
    """
    try:
        data = _lookup_xlsx_bytes([(a["asset_number"], a["serial_number"],
                                    a["asset_type"], a["asset_model"])
                                   for a in _load_assets()])
    except Exception as e:
        return jsonify({"error": "Could not build the workbook: %s" % e}), 500
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name="asset_lookup.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route('/lookup/upload', methods=['POST'])
@door(DOOR_ADMIN)
def lookup_upload():
    """
    POST /lookup/upload
    Body: {"password": "...", "file_data": "<base64-encoded xlsx>"}
    Replaces the Lookup Sheet with what the workbook holds.

    Admin password only (rule 11), and its shape on the wire is exactly what it
    was before 024 - a base64 xlsx in, a count back - so a Storekeeper built
    against the old server still replaces it. What changed is where the rows
    land: the table, in one transaction, rather than a workbook written over
    the old one.
    """
    data = request.json or {}
    if not _admin_password_ok(data.get('password', '')):
        return jsonify({"error": "Wrong admin password"}), 401
    file_b64 = data.get('file_data', '')
    if not file_b64:
        return jsonify({"error": "No file data provided"}), 400
    try:
        raw = base64.b64decode(file_b64)
        # Read by the same function the seed reads a sheet with, so an
        # uploaded workbook and an installed one cannot be read two different
        # ways - and read out of the bytes, so nothing is written to disk
        # before the assets are known to be readable.
        rows = _xlsx_asset_rows(io.BytesIO(raw))
    except Exception as e:
        return jsonify({"error": f"Invalid Excel file: {e}"}), 400
    try:
        loaded = _replace_assets(rows, actor="Admin",
                                 address=_client_addr())
    except ValueError as e:
        # The workbook read perfectly well; what it holds is what cannot be
        # kept, so calling it invalid would send the Admin looking at the wrong
        # thing. Nothing was written - the replacement is one transaction - and
        # the message names the row and the identifier, which is what the
        # caller needs to correct the sheet rather than guess at it. A sheet
        # with rows that are not assets is `bad_rows`, with every one of them
        # in `refusals` (103); a collision is still `duplicate_identifier`.
        body = {"error": str(e),
                "code": getattr(e, "code", "") or "duplicate_identifier"}
        if getattr(e, "refusals", None):
            body["refusals"] = e.refusals
        return jsonify(body), 400
    return jsonify({"status": "ok", "assets_loaded": loaded})

@app.route('/assets/propose', methods=['POST'])
@door(DOOR_OPEN, why="the Storekeeper proposes and the Admin decides "
                     "(028); a proposal writes nothing into the register")
def propose_asset():
    """
    POST /assets/propose
    Body: {"client_id", "asset_number", "serial_number", "asset_type",
           "asset_model", "proposed_by"}
    Records an asset the Storekeeper is holding, for an Admin to approve.

    **No auth**, the same reason ADR-0002 gives for the Transaction endpoints:
    a Client holds no credential. It is safe to leave open for a reason of its
    own, which ADR-0012 sets out - a proposal changes nothing until an Admin
    approves it at the console, so the register keeps being changed by exactly
    one credential.

    Refused with a `code`: `bad_asset` (400) for a row that is not an asset,
    `duplicate_identifier` (409) where the register already holds it - which is
    the answer the caller wanted, the asset can be transacted now - and
    `already_proposed` (409) where a pending proposal does.

    A body carrying **`rows`** is a whole file instead of one asset (029), each
    row the same four fields. It is **all or nothing**: one refusal refuses the
    file and `refusals` names every line that is wrong with it, because a
    delivery half recorded is worse than one refused - nothing says which half.
    Refused additionally with `no_rows` (400), `too_many` (400, naming the
    count and the bound) and `bad_rows` (409).
    """
    data = request.json or {}
    if isinstance(data.get('rows'), list):
        try:
            ids, stamp = _propose_batch(
                data['rows'],
                proposed_by=(data.get('proposed_by') or '')[:120],
                client_id=data.get('client_id', ''),
                address=_client_addr(),
                source=(data.get('source') or '')[:120])
        except _AssetRefused as e:
            return jsonify({"error": str(e), "code": e.code,
                            "refusals": e.refusals}), (
                400 if e.code in ("no_rows", "too_many", "bad_asset") else 409)
        return jsonify({"status": "ok", "proposal_ids": ids,
                        "proposed": len(ids), "proposed_at": stamp,
                        "proposal_status": "pending"})
    try:
        pid = _propose_asset(data.get('asset_number', ''),
                             data.get('serial_number', ''),
                             data.get('asset_type', ''),
                             data.get('asset_model', ''),
                             proposed_by=(data.get('proposed_by') or '')[:120],
                             client_id=data.get('client_id', ''),
                             address=_client_addr())
    except _AssetRefused as e:
        return jsonify({"error": str(e), "code": e.code}), (
            400 if e.code == "bad_asset" else 409)
    return jsonify({"status": "ok", "proposal_id": pid,
                    "proposal_status": "pending"})


@app.route('/assets/import/preview', methods=['POST'])
@door(DOOR_OPEN, why="it writes nothing - it answers what a file would "
                     "become (029)")
def preview_import():
    """
    POST /assets/import/preview
    Body: {"headers": [...], "rows": [[...]], "mapping": {field: index|null}}
    What a file would become, and what is wrong with it. **Writes nothing.**

    This is how a client reads a file it cannot judge. The Storekeeper parses
    the workbook - which is a mechanism, and the one thing about an import that
    is copied - and sends the header row here for the guess, then the rows and
    the mapping the operator confirmed for the verdicts. The **rules** stay
    here, in `_map_import_columns`, `_check_import_mapping` and
    `_validate_import_rows`, which is the same set the Server GUI's Import
    Assets shows the Admin: a client carrying its own would drift into a file
    one door accepts and the other refuses (rule 10).

    No auth, for ADR-0012's reason and more simply because it writes nothing
    and answers nothing `GET /lookup` does not already answer. With no
    `mapping` it answers the guess alone, which is the first stage; with one it
    answers the verdicts. A mapping that cannot describe an asset is refused
    (`bad_mapping`, 400) rather than validated against, and a file longer than
    one batch is refused with the count (`too_many`, 400).
    """
    data    = request.json or {}
    headers = [str(h if h is not None else "")
               for h in (data.get('headers') or [])][:_IMPORT_COLUMNS_MAX]
    rows    = data.get('rows')
    rows    = rows if isinstance(rows, list) else []
    if len(rows) > _PROPOSAL_BATCH_MAX:
        return jsonify({
            "error": "This file carries %d rows and one batch may carry %d."
                     % (len(rows), _PROPOSAL_BATCH_MAX),
            "code": "too_many"}), 400
    sent    = data.get('mapping')
    guessed = not isinstance(sent, dict)
    if guessed:
        mapping = _map_import_columns(headers)
    else:
        mapping = {}
        for f in _IMPORT_FIELDS:
            i = sent.get(f)
            mapping[f] = (i if isinstance(i, int) and not isinstance(i, bool)
                          and 0 <= i < len(headers) else None)
        refusal = _check_import_mapping(mapping)
        if refusal:
            return jsonify({"error": refusal, "code": "bad_mapping",
                            "mapping": mapping}), 400
    verdicts = []
    warning = ""
    if rows and not guessed:
        grid = [[str(c if c is not None else "").strip()
                 for c in (r if isinstance(r, list) else [])] for r in rows]
        assets = _load_assets()
        verdicts = _validate_import_rows(grid, mapping, assets,
                                         _load_proposals("pending"))
        warning = _check_swapped_columns(grid, mapping, assets)
    return jsonify({"fields": list(_IMPORT_FIELDS), "labels": _IMPORT_LABELS,
                    "mapping": mapping, "guessed": guessed,
                    "verdicts": verdicts, "warning": warning})


@app.route('/assets/proposals')
@door(DOOR_OPEN, why="nothing in it is more sensitive than the register "
                     "GET /lookup/file already serves whole")
def list_proposals():
    """
    GET /assets/proposals?status=pending
    What has been proposed, and what the Admin said about it.

    No auth, and nothing in it is more sensitive than the register it is
    waiting to become - these are asset numbers and types, which `GET /lookup`
    already answers for. It is what lets the Storekeeper see the answer to what
    it asked, since a Client has no other way to be told.
    """
    status = (request.args.get('status') or '').strip().lower()
    if status and status not in PROPOSAL_STATUSES:
        return jsonify({"error": "Unknown status %r" % status,
                        "code": "bad_status"}), 400
    return jsonify(_load_proposals(status))


@app.route('/assets/proposals/decide', methods=['POST'])
@door("server_settings")
def decide_asset_proposal():
    """Answer one proposal. The **admin password**, or the **Server Settings**
    capability password over HTTPS (#173).

    Body: ``{id, decision, reason, password}``, where `decision` is `approve`
    or `reject`. Forwards to `_decide_proposal`, which is what the Server GUI's
    Asset Proposals window calls, so an approval goes through `_save_asset` -
    the one writer of an asset - either way, and the rules cannot hold at the
    console and quietly not on the wire.

    **What this delegates is the largest thing behind this capability, and it
    is said here rather than left to be worked out**: approving writes the
    register, and the register is what rule 6's refusal and rule 2's Asset
    Types rest on, so this password can add an asset that can then be
    transacted and a type every client afterwards offers. That is why it was a
    console act until now. What has **not** moved is replacing the sheet:
    `POST /lookup/upload` and the Lookup Sheet window are still the admin
    password and nothing else (rule 11), because answering a question the
    Storekeeper asked and overwriting every asset this server holds are not
    the same size of act.

    `_save_asset`'s refusals are untouched, which matters most on the one race
    this has: an identifier that reached the register while the proposal waited
    refuses in that function's own words and **the proposal stays pending**,
    which is the state it is actually in (025).

    A `decided_by` is not taken from the caller - this is a credential rather
    than a person, so the row and both System Log entries carry
    `_remote_authorise`'s own sentence, the way `POST /transactions/cancel`
    ignores one.

    Refused with a `code`: `insecure` (403), `bad_password` (401), `no_id`
    (400), `bad_decision` (400), `no_reason` (400, a rejection with no reason),
    `no_proposal` (404), `already_decided` (409), plus whatever `_save_asset`
    itself refuses an approval with - `duplicate_identifier` (409) above all.
    """
    data = request.json or {}
    who, refusal, status = _remote_authorise(
        "server_settings", data.get('password', ''),
        address=_client_addr())
    if refusal:
        return jsonify(refusal), status
    try:
        pid = int(data.get('id') or 0)
    except (TypeError, ValueError):
        pid = 0
    if not pid:
        return jsonify({"error": "A proposal id is required.",
                        "code": "no_id"}), 400
    decision = str(data.get('decision', '') or '').strip().lower()
    if decision not in ("approve", "reject"):
        return jsonify({"error": "decision has to be approve or reject.",
                        "code": "bad_decision"}), 400
    try:
        row = _decide_proposal(pid, decision == "approve", decided_by=who,
                               reason=data.get('reason', ''))
    except _AssetRefused as e:
        return jsonify({"error": str(e), "code": e.code}), (
            400 if e.code in ("no_reason", "bad_asset") else
            404 if e.code == "no_proposal" else 409)
    except ValueError as e:
        # `_save_asset` is the one writer of an asset and words its own
        # refusals without a code (025). For a **stored** proposal there is
        # one it can raise: `_propose_asset` already refused a row with no
        # identifier and no type, so what is left is an identifier that
        # reached the register while this proposal waited - which is the race,
        # and the proposal stays pending, that being the state it is in.
        return jsonify({"error": str(e),
                        "code": "duplicate_identifier"}), 409
    return jsonify({"status": "ok", "proposal_id": row["id"],
                    "proposal_status": ("approved" if decision == "approve"
                                        else "rejected")})


# ─── Admin routes ─────────────────────────────────────────────────────────────

@app.route('/admin/verify', methods=['POST'])
@door(DOOR_ADMIN)
def admin_verify():
    data = request.json or {}
    if _admin_password_ok(data.get('password', '')):
        return jsonify({"valid": True})
    return jsonify({"valid": False}), 401

@app.route('/auth/verify', methods=['POST'])
@door(DOOR_OWN)
def auth_verify():
    """Authenticate an engineer and report what their profile allows.

    Accepts either that engineer's own password or the admin password, so an
    admin can always get into a client's Settings and an engineer with no
    password of their own is unaffected. admin=True in the reply is what lets a
    client show the admin-only parts of a screen.

    must_change_password is reported here because this is the moment it is
    about: an Own Password an Admin set is temporary, and the first time the
    Engineer authenticates with it they are made to replace it before anything
    else proceeds (ADR-0009). Answering it on the round-trip that proved the
    password is what lets the client decide without asking a second question.
    It is the row's flag either way, including when the admin password is what
    opened the door - it is a fact about the Engineer's password, not about who
    just typed something - so the client forces a replacement only on the
    Engineer's own path. Additive, like every other key here.
    """
    data = request.json or {}
    name = (data.get('name', '') or '').strip()
    pw   = data.get('password', '') or ''

    if _admin_password_ok(pw):
        row = _member_row(name) if name else None
        return jsonify({
            "valid":       True,
            "admin":       True,
            "profile":     (row["profile"] or "default") if row else "default",
            # An admin is not limited by the engineer's profile.
            "permissions": list(PERMISSIONS),
            "must_change_password": bool(row["must_change_password"])
                                    if row else False,
        })

    row = _member_row(name) if name else None
    if row is None or not password_matches(pw, row["password_hash"]):
        # The admin leg above already recorded its own refusal through
        # _admin_password_ok; this is the Engineer's. Which Engineer was
        # claimed, and the address it was claimed from - never the password.
        _log_event("auth.refused",
                   "an Own Password was wrong for %s" % (name or "(no name)"),
                   level="warn", address=_client_addr())
        return jsonify({"valid": False}), 401
    # The one place an Own Password is checked and then kept, so the one place
    # an upgrade is worth making: /auth/change_password checks one too, but
    # replaces it in the same request, so rehashing what it is about to
    # overwrite would be work for nothing.
    _upgrade_stored_hash(row["password_hash"], pw,
                         lambda h: _rehash_member_password(name, h))
    return jsonify({
        "valid":       True,
        "admin":       False,
        "profile":     row["profile"] or "default",
        "permissions": _member_permissions(row),
        "must_change_password": bool(row["must_change_password"]),
    })


@app.route('/auth/change_password', methods=['POST'])
@door(DOOR_OWN)
def auth_change_password():
    """An Engineer replaces their own Own Password.

    The Engineer's pair to /auth/verify, the way /admin/change_password is the
    Admin's pair to /admin/verify. `current_password` is either that Engineer's
    **current** Own Password or the admin password: the second is what makes an
    Admin-driven reset possible for an Engineer who has forgotten theirs.

    **Which of the two was proved decides the mark.** Their own clears
    must_change_password: the Engineer proved the password they already had, so
    the new one is theirs. The admin password arms it, because this endpoint is
    on the network and the admin password proves an Admin and nothing about
    whose fingers typed the new password - so what it leaves behind is a
    Temporary Own Password, the same thing an Admin setting one at the console
    leaves behind. Without that, this was the one route around ADR-0009: an
    Admin could replace an existing Own Password from anywhere and the result
    was never flagged. It costs the Admin standing at the Engineer's desk one
    further replacement, which is the price of the server not having to guess
    which of them was at the keyboard.

    **A capability password opens nothing here**, and nothing had to be written
    to make that so: this checks the admin hash through _admin_password_ok and
    the Engineer's own through password_matches, and never calls _authorise.
    Since R1 a capability password does reach three endpoints (ADR-0015), and
    this is not one of them - an Own Password is an Engineer's credential and
    no delegation of an administrative action has any business setting one.

    It **changes** an Own Password and never creates one. An Engineer who has
    none is refused with `no_password` - otherwise an Admin standing at a
    Notifier could set a first Own Password through here and it would not be
    temporary, which is the one thing ADR-0009 rests on. An Engineer with no
    Own Password is untouched by all of this, and their Transactions are
    unaffected whatever happens here: /confirm and /reject are unauthenticated
    on purpose (ADR-0002).

    That refusal fires **before** either password is examined, which is what
    makes its wording load-bearing rather than decorative. It is the answer an
    Admin gets when they type the admin password here for an Engineer who has
    no Own Password yet, and the Notifier shows the server's words verbatim -
    so a message that only said there was nothing to change read as "your
    password was wrong", and the Admin retyped a password that was never the
    problem. It says so, and names the remedy in the terms of the window
    that holds it: the Engineer's card in the Server GUI's Manage Users
    window. Naming POST /members instead would be true and useless - the
    person reading this is at a Notifier, and cannot call an endpoint.

    `name` is not proof of anything and is not meant to be. What stops an
    Engineer changing somebody else's is that the current password is checked
    against *that* Engineer's row - one Engineer's password does not open
    another's - and only the admin password opens every row, as it always has.
    """
    data    = request.json or {}
    name    = (data.get('name', '') or '').strip()
    current = data.get('current_password', '') or ''
    new_pw  = data.get('new_password', '') or ''
    if not name:
        return jsonify({"error": "Name required", "code": "no_name"}), 400
    row = _member_row(name)
    if row is None:
        return jsonify({"error": "No such Engineer: %s" % name,
                        "code": "no_member"}), 404
    if not row["password_hash"]:
        # Reached before either password is looked at, so it must not read as a
        # refusal of the one that was typed - see the docstring above.
        return jsonify({"error": "%s has no Own Password yet, so there is none "
                                 "to change - whichever password you typed. An "
                                 "Admin sets the first one on your card in the "
                                 "Server GUI's Manage Users window." % name,
                        "code": "no_password"}), 409
    # Their own first, the admin password second: the Engineer's own password is
    # the ordinary case, and each check costs a tenth of a second (ADR-0008).
    # Which one opened it is kept rather than re-derived, both because it
    # decides the mark below and because deriving it would hash twice.
    own = password_matches(current, row["password_hash"])
    if not (own or _admin_password_ok(current)):
        _log_event("auth.refused",
                   "neither password opened %s's Own Password" % name,
                   level="warn", address=_client_addr())
        return jsonify({"error": "Wrong password", "code": "bad_password"}), 401
    if len(new_pw) < PASSWORD_MIN:
        return jsonify({"error": "Password too short (min %d chars)"
                                 % PASSWORD_MIN, "code": "too_short"}), 400
    conn = get_db()
    try:
        # Cleared where the Engineer proved their own password, because that
        # is the whole difference between a temporary Own Password and an
        # ordinary one; armed where only the admin password was proved, since
        # an Admin-set password is temporary wherever it is set from. The only
        # other way the mark comes down is the Own Password being removed
        # altogether, in _set_member_password.
        conn.execute("UPDATE team_members SET password_hash=?,"
                     " must_change_password=? WHERE name=?",
                     (hash_password(new_pw), 0 if own else 1, name))
        conn.commit()
        # Which door opened it is the fact worth keeping: the Engineer's own
        # leaves a password only they know, the admin password leaves a
        # temporary one somebody else chose.
        _log_event("member.password_changed",
                   "%s  (%s)" % (name, "by the Engineer" if own
                                 else "by an Admin - temporary"),
                   actor=name if own else "Admin",
                   address=_client_addr())
    finally:
        conn.close()
    return jsonify({"status": "ok", "name": name,
                    "must_change_password": not own})



@app.route('/admin/change_password', methods=['POST'])
@door(DOOR_ADMIN)
def admin_change_password():
    data    = request.json or {}
    current = data.get('current_password', '')
    new_pw  = data.get('new_password', '')
    if not _admin_password_ok(current):
        return jsonify({"error": "Wrong current password"}), 401
    if len(new_pw) < PASSWORD_MIN:
        return jsonify({"error": "Password too short (min %d chars)"
                                 % PASSWORD_MIN}), 400
    _update_admin_cfg(password_hash=hash_password(new_pw), first_run=False)
    _log_event("admin.password_changed", "over POST /admin/change_password",
               actor="Admin", level="warn",
               address=_client_addr())
    return jsonify({"status": "ok"})

@app.route('/admin/server_config', methods=['GET'])
@door("server_config")
def get_server_config():
    """What is configured. The admin password, or the **Change Host / Port**
    capability password over HTTPS (R1).

    Widened beside the POST rather than left admin-only: a delegate who may set
    the port and may not read it is filling a form on a guess, and what this
    answers - a bind address and a port - is the pair they are being handed.
    Every read is a `remote.action` entry like every write, since who has been
    asking is as much a fact about a delegation as what they changed.
    """
    data = request.json or {}
    who, refusal, status = _remote_authorise(
        "server_config", data.get('password', ''),
        address=_client_addr())
    if refusal:
        return jsonify(refusal), status
    return jsonify({"host": HOST, "port": PORT})

@app.route('/admin/server_config', methods=['POST'])
@door("server_config")
def set_server_config():
    """Save the host and port for the next start. The admin password, or the
    **Change Host / Port** capability password over HTTPS (R1).

    The running server is unchanged until it is restarted, which is what makes
    this the mildest of the three remote actions: nothing that is serving now
    moves, and an Admin at the console sees the saved value in the same window.

    **Under IIS a restart applies nothing** and the note says so instead: the
    port is the site binding, and what moves it is the elevated half the
    console spawns (`tools\\bind-port.ps1`, ADR-0021). This route does not
    spawn it and cannot - it runs as the app pool identity, which is not an
    administrator - so what is saved here is the number that half will be
    told, and a delegate who saves it remotely still needs somebody at the
    console to apply it.
    """
    data = request.json or {}
    who, refusal, status = _remote_authorise(
        "server_config", data.get('password', ''),
        address=_client_addr())
    if refusal:
        return jsonify(refusal), status
    new_host = str(data.get('host', '0.0.0.0')).strip()
    if not new_host:
        return jsonify({"error": "Host cannot be empty"}), 400
    new_port, err = _validate_port(data.get('port', PORT))
    if err:
        return jsonify({"error": err}), 400
    if _iis_served_undetected() and new_port != PORT:
        return jsonify({"error": "The port cannot be changed: IIS is serving "
                                   "this process through HttpPlatformHandler but "
                                   "install-iis.ps1 never ran, so no site is on "
                                   "record to move. Run install-iis.ps1, or change "
                                   "the binding directly in IIS Manager."}), 400
    _save_server_cfg(host=new_host, port=new_port)
    if _iis_host() is not None:
        return jsonify({"status": "ok",
                        "note": "IIS serves the port, so restarting this "
                                "process applies nothing. The binding moves "
                                "when an Admin applies it from the Server "
                                "GUI's Server Settings."})
    return jsonify({"status": "ok", "note": "Restart the server to apply changes."})


def _mail_door():
    """The network door onto the mail settings. #172.

    Returns ``(actor, refusal, status)`` - `_remote_authorise`'s own answer,
    named here because five routes ask the same question and one of them is a
    GET carrying a body.

    `_remote_authorise` rather than `_member_door`'s `_remote_admit(...,
    admin_is_native=True)`: these five routes are new, so no shipped client
    sends the admin password to any of them and there is no install to break by
    holding both credentials to HTTPS. The `/members` doors are the exception
    because they predate the channel (ADR-0015), which is an argument about
    wire compatibility rather than about mail.
    """
    data = request.json or {}
    return _remote_authorise("server_settings", data.get('password', ''),
                             address=_client_addr())


@app.route('/admin/mail', methods=['GET'])
@door("server_settings")
def get_mail_settings():
    """The mail settings. The **admin password**, or the **Server Settings**
    capability password over HTTPS (#172).

    **The stored password is not in here and cannot be**: it is the one
    replayable secret this server holds (ADR-0013), and a route that answered
    with it would be a way to read it back off the network, which is the
    property `smtp_secret.dat` exists to have. What is answered instead is
    whether one is stored, which is the same thing the console's own window is
    told and all a form needs in order to say "type a new one to replace it".

    `can_store` beside it is whether DPAPI is available at all, because the
    remote form has to be able to say **why** the password field is refused -
    a machine that cannot encrypt one is a different situation from a relay
    that asks for none, and "failed" is the answer nobody can act on.
    """
    who, refusal, status = _mail_door()
    if refusal:
        return jsonify(refusal), status
    cfg = _smtp_cfg()
    return jsonify({"host": cfg["host"], "port": cfg["port"],
                    "from": cfg["from"], "username": cfg["username"],
                    "starttls": cfg["starttls"],
                    "password_stored": _smtp_secret_stored(),
                    "can_store": bool(HAS_DPAPI)})


@app.route('/admin/mail', methods=['POST'])
@door("server_settings")
def set_mail_settings():
    """Save the mail settings. The **admin password**, or the **Server
    Settings** capability password over HTTPS (#172).

    Forwards to `_save_mail_settings`, the one writer, which the console's Mail
    Settings window also calls - so the order the three steps happen in, and
    the DPAPI refusal in the middle of them, cannot hold here and quietly not
    at the console.

    The SMTP password is **`smtp_password`** and never `password`: `password`
    is the credential at every door in this file, and one key meaning the
    caller's own credential on one route and a secret to be stored on another
    is the kind of thing a client gets wrong once and logs for ever. Omitting
    it keeps whatever is stored, `""` clears it - `_save_member`'s convention,
    and for its reason: a form that is never shown the password cannot tell
    "leave it" from "clear it" any other way.

    Refused with a `code`: `insecure` (403), `bad_password` (401), `bad_port`
    (400) or `no_secret_store` (400, DPAPI is unavailable on that machine and
    there is deliberately no plaintext fallback - ADR-0013).
    """
    who, refusal, status = _mail_door()
    if refusal:
        return jsonify(refusal), status
    data = request.json or {}
    code, err = _save_mail_settings(
        data.get('host', ''), data.get('port', _SMTP_PORT_DEFAULT),
        data.get('from', ''), data.get('username', ''),
        data.get('starttls', False),
        password=(data['smtp_password'] if 'smtp_password' in data else _KEEP))
    if code:
        return jsonify({"error": err, "code": code}), 400
    return jsonify({"status": "ok",
                    "password_stored": _smtp_secret_stored()})


@app.route('/admin/mail/test', methods=['POST'])
@door("server_settings")
def send_mail_test():
    """Send one test mail and answer with what the relay said. The **admin
    password**, or the **Server Settings** capability password over HTTPS
    (#172).

    It sends against what is **on disk** rather than against anything in the
    body, which is why the window that calls it saves first: a test that passes
    against a form and fails against the file is worse than no test.

    The relay's own words are the answer, for the console's reason - a wrong
    password, a refused sender and a host that is not there each need a
    different thing done about them, and "failed" is the one answer nobody can
    act on. So a refused send is **200 with an `error`**, not a 5xx: the
    request did what it was asked, and the failure is the mail server's rather
    than this one's.
    """
    who, refusal, status = _mail_door()
    if refusal:
        return jsonify(refusal), status
    to = str((request.json or {}).get('to', '') or "").strip()
    if not to:
        return jsonify({"error": "An address to send the test to is required.",
                        "code": "no_recipient"}), 400
    err = _send_test_mail(to, who, address=_client_addr())
    if err:
        return jsonify({"status": "failed", "error": err}), 200
    return jsonify({"status": "ok"})


@app.route('/admin/notify_rules', methods=['GET'])
@door("server_settings")
def get_notify_rules():
    """The notification rules. The **admin password**, or the **Server
    Settings** capability password over HTTPS (#172).

    Behind a credential where `GET /permissions` beside it is not, and the
    difference is what is in it: a Permission's caption is a fact about this
    build, where a rule is a list of the department's mailboxes and which
    events somebody wanted to hear about.

    Answers the rules as `_notify_rules` reads them back - normalised, with the
    recipients already split - so a form draws what the server will actually
    act on rather than what somebody typed.
    """
    who, refusal, status = _mail_door()
    if refusal:
        return jsonify(refusal), status
    return jsonify({"rules": _notify_rules(),
                    "min_secs": _NOTIFY_MIN_SECS,
                    "hourly_max": _NOTIFY_HOURLY_MAX})


@app.route('/admin/notify_rules', methods=['POST'])
@door("server_settings")
def set_notify_rules():
    """Replace the notification rules. The **admin password**, or the **Server
    Settings** capability password over HTTPS (#172).

    The whole list, not one rule: that is what the window behind it holds and
    what `server_config.json` stores, and a per-rule door would need a key for
    a row that has never had one. Forwards to `_save_notify_rules`, the one
    writer, so which rows are dropped and which are refused is decided in one
    place.

    Applied at once and with no restart, because `_notify_rules` reads the file
    on every entry - which is the whole reason this is worth having on the
    network: an Admin who has to reach the console to stop a flood will not
    reach it in the situation that made them want to.

    Refused with a `code`: `insecure` (403), `bad_password` (401), `bad_rule`
    (400) or `bad_level` (400).
    """
    who, refusal, status = _mail_door()
    if refusal:
        return jsonify(refusal), status
    data = request.json or {}
    rules = data.get('rules')
    if not isinstance(rules, list):
        return jsonify({"error": "rules has to be a list.",
                        "code": "bad_rules"}), 400
    code, err, kept = _save_notify_rules(
        rules, who, address=_client_addr())
    if code:
        return jsonify({"error": err, "code": code}), 400
    return jsonify({"status": "ok", "rules": len(kept)})


@app.route('/cert')
@door(DOOR_OPEN, why="the server's public certificate - a client that has "
                     "to authenticate to get it cannot authenticate yet")
def serve_cert():
    if os.path.exists(SSL_CERT_PATH):
        return send_file(SSL_CERT_PATH, mimetype='application/x-pem-file',
                         download_name='ssl_cert.pem', as_attachment=False)
    return jsonify({"error": "No certificate installed on this server"}), 404


@app.route('/cert/next')
@door(DOOR_OPEN, why="GET /cert's reason, one certificate earlier "
                     "(ADR-0020)")
def serve_cert_next():
    """The staged certificate, or 404. C3, ADR-0020.

    Phase two of a rotation reads this: the certificate `_stage_new_cert` wrote
    and nothing is bound to. A client fetches it for itself on the `trust_cert`
    command and appends it to the file it already pins, so that when the
    binding does move there is nobody at any machine to confirm anything.

    A route of its own rather than a parameter on `/cert`, because the two
    answer different questions and only one of them is what a client should
    pin from scratch: `/cert` is what this server is actually serving and is
    what ADR-0010's first-contact bootstrap reads, where this is a certificate
    that has been minted and bound to nothing at all. A flag on one endpoint
    would put that distinction inside a caller's argument, which is the shape
    `common.py` refuses for its two password doors and for the same reason.

    404 is the ordinary state - most of the time nothing is staged - so it is
    not a failure and no client treats it as one.

    No credential, for `/cert`'s reason: a certificate is public, and a staged
    one is a certificate nothing trusts yet, which is less than public. The
    **key** beside it never leaves this machine and is not served from
    anywhere (rule 1).
    """
    if os.path.exists(SSL_CERT_NEXT_PATH):
        return send_file(SSL_CERT_NEXT_PATH,
                         mimetype='application/x-pem-file',
                         download_name='ssl_cert_next.pem',
                         as_attachment=False)
    return jsonify({"error": "No certificate is staged on this server",
                    "code": "no_staged_cert"}), 404


def _since_ts(ts):
    """Seconds since an ISO timestamp, or None when it cannot be read."""
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
    except (ValueError, TypeError):
        return None


# Everything server_clients reads out of this module, handed over once. It
# sits here rather than beside the other five bind() calls for one reason:
# `_since_ts` is directly above and is the last of the seven to be defined,
# and a name handed over before it exists is the one real failure mode of
# this pattern. Nothing in that module runs before a request, a window or a
# background tick reaches it - `server_cert.bind()` further up is handed
# four of its function objects rather than calling them, so it is unaffected
# by this call being later than that one.
#
# No name here is handed over as a callable the way `server_sync.bind()`
# takes `db_path`: nothing on this list is re-pointed after import.
# `DB_PATH` is not on it at all, `get_db()` resolving it at call time in
# this file.
server_clients.bind(
    app_version=APP_VERSION,
    client_package=_client_package,
    get_db=get_db,
    load_server_cfg=_load_server_cfg,
    log_event=_log_event,
    member_row=_member_row,
    member_row_by_id=_member_row_by_id,
    since_ts=_since_ts)


def _gui_snapshot(limit=18):
    """The activity feed, who is holding what, and the oldest pending rows -
    read straight out of assets.db rather than over HTTP.

    The counts in the header still come from GET /stats, because that call is
    also the liveness probe. These three do not: in monitor mode the GUI is a
    different process from the server, but the database file is the same one,
    and a file read cannot be blocked by a wedged listener - which is exactly
    the state this window has to stay readable in.

    The fourth return value is a cheap change signature. Repainting the feed
    every 5s would reset the scroll position and flicker; repainting only when
    the table actually moved does not.
    """
    conn = get_db()
    try:
        recent = conn.execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        # Same rule as /stats' out_now - per asset, the newest confirmed
        # transaction being 'Out Store' - counted per engineer instead of in
        # total. Counting confirmed 'Out Store' rows would never decrease.
        held = conn.execute(
            """WITH latest AS (
                 SELECT team_member, direction,
                        ROW_NUMBER() OVER (
                          PARTITION BY %s
                          ORDER BY timestamp DESC, id DESC
                        ) AS rn
                 FROM transactions
                 WHERE confirmed = 1 AND cancelled = 0
               )
               SELECT team_member, COUNT(*) AS n FROM latest
               WHERE rn = 1 AND direction = 'Out Store'
               GROUP BY team_member ORDER BY n DESC, team_member"""
            % _asset_key_sql()).fetchall()
        oldest = conn.execute(
            "SELECT * FROM transactions WHERE confirmed=0 AND rejected=0 "
            "AND cancelled=0 ORDER BY timestamp ASC, id ASC LIMIT 4").fetchall()
        # SUM(cancelled) is in the signature because cancelling moves no other
        # term in it: the row count, the max id, and both other sums stay put,
        # so without it the feed would keep showing a cancelled Transaction as
        # pending until something unrelated happened.
        sig = tuple(conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(SUM(confirmed),0), "
            "COALESCE(SUM(rejected),0), COALESCE(SUM(cancelled),0) "
            "FROM transactions").fetchone())
    finally:
        conn.close()
    return recent, held, oldest, sig


# ─── Flask runner (shared by interactive mode and Windows Service) ────────────

_AUTO_JOBS_STARTED = [False]

def _auto_accept_pass(now=None):
    """One Auto-Accept pass: confirm every Transaction pending for over 24h.

    Returns the number of rows confirmed.

    Split out of the loop below so that it can be called at all. The 24h rule is
    otherwise only observable a day after a change ships, which makes it the one
    rule here whose breakage cannot be caught while anyone is still looking.

    Auto-Accept, not Auto-Approve: this is the deadline that applies to every
    Engineer, not the per-Engineer flag that skips verification entirely.
    """
    now    = now or datetime.now()
    cutoff = (now - timedelta(hours=24)).isoformat()
    conn   = get_db()
    try:
        cur = conn.execute(
            "UPDATE transactions SET confirmed=1, confirmed_at=?, origin='auto' "
            "WHERE confirmed=0 AND rejected=0 AND cancelled=0 "
            "AND timestamp < ?",
            (now.isoformat(), cutoff)
        )
        conn.commit()
        if cur.rowcount:
            engineers = sorted(r[0] for r in conn.execute(
                "SELECT DISTINCT team_member FROM transactions "
                "WHERE origin='auto' AND confirmed_at=?", (now.isoformat(),)))
            # Only when it did something. An hourly line saying nothing
            # happened is how a log stops being read.
            _log_event("transaction.auto_accepted",
                       "%d Transaction(s) pending over 24h" % cur.rowcount,
                       actor="Auto-Accept",
                       data={"origin": "auto", "engineers": engineers})
        return cur.rowcount
    finally:
        conn.close()


def _auto_accept_stale_pending():
    """Background job: run the Auto-Accept pass hourly."""
    while True:
        try:
            _auto_accept_pass()
        except Exception:
            pass
        time.sleep(3600)  # re-check hourly


def _start_background_jobs():
    if _AUTO_JOBS_STARTED[0]:
        return
    _AUTO_JOBS_STARTED[0] = True
    # Before anything else: a process that is only now starting cannot be in
    # the middle of the backup whose state is on disk, and a hold nothing will
    # ever lift is worse than the crash that left it. See the function.
    _maintenance_clear_stale()
    threading.Thread(target=_auto_accept_stale_pending, daemon=True).start()
    # The System Log's retention, on its own loop rather than folded into the
    # Auto-Accept one: that job is named for the rule it applies, and a second
    # rule hiding inside it is how one of them comes to be removed with the
    # other.
    threading.Thread(target=_log_retention_loop, daemon=True).start()
    # And the external asset system, on a loop of its own for the same reason.
    # It is started whatever the configuration says: the loop re-reads the
    # interval every tick and does nothing while there is none, so an Admin who
    # configures a sync gets one without restarting the server - which is the
    # rule every other setting read from that file follows (032).
    threading.Thread(target=_sync_loop, daemon=True).start()
    # And the stale-Client sweep (#268), on its own loop for the same reason
    # the System Log's retention is not folded into Auto-Accept: a job named
    # for the rule it applies is one a later change can remove without
    # touching a rule it was never about. It re-reads the saved threshold
    # every tick, the same rule the sync loop above follows for its own
    # setting.
    threading.Thread(target=_client_sweep_loop, daemon=True).start()
    # And the live certificate's expiry, on a daily loop of its own for the
    # same reason (#273): it only warns, so nothing here stages or cuts
    # over a certificate by itself (ADR-0020).
    threading.Thread(target=_cert_expiry_loop, daemon=True).start()
    # atexit rather than a line in each of the three exit paths, so the GUI's
    # quit, the service's stop and IIS recycling a worker all leave the same
    # mark. It does not fire on a kill, which is the honest outcome: a start
    # line with no stop line before the next start is the record that the
    # process died, and that is worth being able to see.
    atexit.register(lambda: _log_event(
        "server.stopped", "AssetServer %s" % APP_VERSION))
    _log_event("server.started", "AssetServer %s  ·  pid %d"
                                 % (APP_VERSION, os.getpid()))


def _run_flask(host=None, port=None, use_ssl=True):
    """Start the Flask server (blocking). Chooses HTTP or HTTPS automatically.

    host/port/use_ssl are overridden only by the headless 'serve' entry point,
    where IIS assigns the port and terminates TLS itself. Every other caller
    passes nothing and gets the configured HOST/PORT with TLS as configured."""
    _start_background_jobs()
    ssl_ctx = None
    if (use_ssl and _SERVER_CFG.get('ssl_enabled') and
            os.path.exists(SSL_CERT_PATH) and os.path.exists(SSL_KEY_PATH)):
        ssl_ctx = (SSL_CERT_PATH, SSL_KEY_PATH)
    # NOTE: the listener keeps Werkzeug's default SO_REUSEADDR so the server can
    # rebind immediately on restart even while old client connections linger in
    # TIME_WAIT. Duplicate-instance protection is handled at the detection layer
    # (_port_in_use exclusive-bind test used by the GUI before it starts Flask),
    # NOT by binding the live listener exclusively — an exclusive live bind fails
    # to rebind over TIME_WAIT and turns a routine restart into an outage.
    app.run(
        host=host or HOST,
        port=port or PORT,
        debug=False,
        use_reloader=False,
        threaded=True,          # serve clients concurrently — one stuck/slow
                                # connection can't freeze the whole server
        ssl_context=ssl_ctx
    )


# ─── Windows Service definition ───────────────────────────────────────────────

if HAS_WIN32SVC:
    class AssetManagerService(win32serviceutil.ServiceFramework):
        """
        Windows Service wrapper for the Asset Manager Flask backend.
        Install : AssetServer.exe install
        Remove  : AssetServer.exe remove
        Start   : net start AssetManagerServer   (or via Services MMC)
        Stop    : net stop  AssetManagerServer
        Debug   : AssetServer.exe debug          (runs in console, Ctrl-C to stop)
        """
        # The window calls this the Asset Server and this block does not, on
        # purpose. Both of these are what an installed machine is registered
        # under: `update.ps1` stops the service by name, `net start` takes it,
        # and Services.MMC shows the display name next to it. Renaming them is
        # a cutover on the server machine rather than an edit here, so it waits
        # for its own ticket - and until then this is the one place in this
        # file where the words a person reads and the identifier behind them
        # are allowed to disagree.
        _svc_name_         = "AssetManagerServer"
        _svc_display_name_ = "Asset Manager Server"
        _svc_description_  = (
            "Runs the Asset Manager REST API (Flask/SQLite) as a background service, "
            "independent of any logged-on user session."
        )

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_evt = win32event.CreateEvent(None, 0, 0, None)

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self._stop_evt)

        def SvcDoRun(self):
            # Tell the SCM the service is now running — must be called before
            # any slow initialisation, otherwise net start times out (30 s default)
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            # Returning from SvcDoRun is what stops the service: the
            # framework reports SERVICE_STOPPED itself once this returns, so
            # doing it here as well would report it twice. The event log is the
            # only place a session-0 process can say why.
            _db_err = _require_db()
            if _db_err:
                servicemanager.LogErrorMsg(
                    "Asset Manager Server did not start.\n\n" + _db_err)
                return
            init_db()
            _ensure_sample_lookup()
            threading.Thread(target=_run_flask, daemon=True).start()
            # Block until SvcStop sets the event
            win32event.WaitForSingleObject(self._stop_evt, win32event.INFINITE)
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_name_, ""),
            )


def _launched_by_scm():
    """True if this process was started by the Windows Service Control Manager.
    Services run in session 0; an interactive double-click runs in session >= 1.
    Lets one exe be both the SCM-run service and the double-click GUI."""
    try:
        sid = ctypes.c_ulong()
        ctypes.windll.kernel32.ProcessIdToSessionId(
            ctypes.windll.kernel32.GetCurrentProcessId(), ctypes.byref(sid))
        return sid.value == 0
    except Exception:
        return False


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # ── Service management commands (install / remove / start / stop / debug) ──
    _svc_cmds = {"install", "remove", "start", "stop", "restart", "debug",
                 "update", "--startup", "querycontrol"}
    _first_arg = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    if _first_arg == "migrate":
        # Schema migrations, driven by tools/migrate.ps1 and tools/update.ps1.
        sys.exit(_migrate_cli(sys.argv[2:]))

    elif _first_arg in ("serve", "--headless"):
        # Headless foreground mode, for IIS HttpPlatformHandler (see ADR-0001).
        # IIS launches this process, assigns it a port via %HTTP_PLATFORM_PORT%
        # and terminates TLS itself, so bind plain HTTP on loopback and skip the
        # Tkinter GUI entirely. Run without that variable (e.g. by hand for
        # debugging) and it serves the configured HOST/PORT with TLS as usual.
        _iis_port = os.environ.get("HTTP_PLATFORM_PORT")
        # Each host handles this in its own idiom, because each has a different
        # way of being heard: stderr is what HttpPlatformHandler captures into
        # the stdout log, and exit 2 is what makes IIS report the process as
        # failed instead of retrying it into a loop.
        _db_err = _require_db()
        if _db_err:
            sys.stderr.write("Asset Server: " + _db_err + "\n")
            sys.stderr.flush()
            sys.exit(2)
        init_db()
        _ensure_sample_lookup()
        _run_flask(host="127.0.0.1" if _iis_port else None,
                   port=int(_iis_port) if _iis_port else None,
                   use_ssl=not _iis_port)

    elif _first_arg in _svc_cmds:
        if HAS_WIN32SVC:
            win32serviceutil.HandleCommandLine(AssetManagerService)
        else:
            print("pywin32 is not installed — Windows Service mode unavailable.")
            sys.exit(1)
    elif HAS_WIN32SVC and len(sys.argv) == 1 and _launched_by_scm():
        # Started by the Windows Service Control Manager (session 0) — hand off to
        # the service dispatcher so the SCM tracks it as Running. Without this the
        # exe would fall through to GUI mode and the SCM would mark it Stopped.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(AssetManagerService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # ── Interactive GUI mode ──────────────────────────────────────────────
        # Hide the console window that appears when built without --windowed
        if sys.platform == "win32" and getattr(sys, 'frozen', False):
            try:
                ctypes.windll.user32.ShowWindow(
                    ctypes.windll.kernel32.GetConsoleWindow(), 0  # SW_HIDE
                )
            except Exception:
                pass

        if not _acquire_single_instance_mutex():
            # Another GUI window is already open — bring it to the foreground
            ctypes.windll.user32.MessageBoxW(
                0,
                "Asset Server is already running.\n\nCheck the system tray.",
                "Already Running",
                0x40,   # MB_ICONINFORMATION
            )
            sys.exit(0)

        # The GUI reads the database directly for its feed and its counts
        # (see _gui_snapshot), so it is refused for the same reason the server
        # is - including in monitor-only mode, where it would otherwise open a
        # window captioned LIVE over an empty table.
        _db_err = _require_db()
        if _db_err:
            ctypes.windll.user32.MessageBoxW(
                0, _db_err, "Asset Server", 0x10)   # MB_ICONERROR
            sys.exit(2)

        init_db()
        _ensure_sample_lookup()

        if _port_in_use(PORT):
            # Something is already serving on the port (the Windows Service or
            # another instance) — run as a monitor-only front-end instead of
            # starting a second Flask that would double-bind and wedge the server.
            # _port_in_use uses an exclusive-bind probe, so it detects a
            # wedged-but-listening server too; if the listener is genuinely dead
            # the port reads free and the GUI can self-heal by starting Flask.
            pass
        else:
            threading.Thread(target=_run_flask, daemon=True).start()
            time.sleep(1.5)  # give Flask enough time to bind before the GUI polls it

        run_gui()
