"""
Asset Manager - the Assets register.

The four functions that read and write the `assets` table: every asset in the
Lookup Sheet (`_load_assets`), the one writer of a row (`_save_asset`), the
removal (`_delete_asset`), and the identity rule the other two tables lean on
(`_asset_key_sql`) - and the shape an asset must have (`_asset_shape_error`),
which every door into the table asks (103).

Lifted out of `server.py` by #215 unchanged. They were never the routes' and
never the window's: `server.py`'s lookup endpoints and `server_gui.py`'s
Manage Assets, Asset Proposals and Asset Sync call the same three writers, and
`tools/server-checks.py` calls all four directly rather than over HTTP. A
cluster two adapters and a gate already reach the same way is one a module can
name, which is what 039 (#210) asked for and what this ticket is the Assets
third of.

Headless-safe: nothing here draws, so `server.py` imports it at module level.

**It opens no connection of its own.** `get_db` is `server.py`'s, and comes
over through `bind()` at import the way `server_cert.py` takes its paths -
`from server import get_db` would execute the whole server a second time
rather than reach the one running, because `server.py` runs as `__main__`
under `applaunch`'s `runpy.run_path`. `_log_event` comes the same way, for the
same reason. Which database a call reads is therefore still decided once, in
`server.py`, by whoever bound it.
"""

import re
import sqlite3
from datetime import datetime

# Handed over by server.py's bind() below, before anything here is called.
# Named exactly as server.py names them, so the code moved in reads there and
# here as one thing.
get_db = None
_log_event = None


def bind(*, get_db, log_event):
    """Give this module the server's connection and its logger. Called once.

    Keyword-only and exhaustive: every name the moved code reads out of
    `server.py` is on this list, so what the two modules share is one
    signature to read rather than a search of the file.

    What is bound here is module state, so a process holding **two** server
    modules leaves this one pointing at whichever imported it last. A real
    install has one; `tools/server-checks.py` is the only thing that imports
    a second, and it gives each staged copy a `register_assets` of its own.
    """
    # `global get_db` is a syntax error where `get_db` is also the parameter,
    # and the moved code calls it bare - so the module global is set the one
    # way left rather than the name being spelt differently on each side.
    globals()["get_db"] = get_db
    global _log_event
    _log_event = log_event


def _load_assets():
    """Every asset, oldest first, as dicts carrying the row id.

    The Lookup Sheet window reads this; `_load_lookup_table`, which stayed
    in `server.py`, is what every rule reads. Both come off the table now - 024 moved the sheet out
    of the workbook and into the database, and ADR-0011 says why.
    """
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, asset_number, serial_number, asset_type, asset_model"
            " FROM assets ORDER BY id")]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


# Worded once, because `_save_asset` raises it one asset at a time and the
# importer reports it for every row of a file before writing any of them. Two
# spellings of one refusal is two sentences an Admin has to work out are the
# same refusal.
_IDENTIFIER_TAKEN = ("%s %s is already in the Lookup Sheet (%s, %s). Correct "
                     "that asset instead - two rows with the same identifier "
                     "are one asset to every lookup.")


def _asset_shape_error(asset_number, serial_number, asset_type):
    """Empty where the three fields describe an asset, else the sentence why not.

    An asset carries an Asset Number, a Serial Number and an Asset Type (103).
    Rule 5's "at least one identifier" is a Transaction's rule, and it was held
    here too, so an asset could be proposed with no serial and an Asset Number
    of `P-1`. The embedded sheet already has this shape on every one of its
    rows; what was missing was a door holding the rest to it.

    Asked by every door rather than by `_save_asset` alone, because three of
    them answer before anything is written - a proposal, an import's verdicts,
    a sync's skip list - and each has to say the same sentence the writer would.
    Digits are ASCII `0-9`: `str.isdigit` also takes `²`.
    """
    if not asset_number:
        return "An asset needs an Asset Number."
    if not re.fullmatch("[0-9]+", asset_number):
        return ("Asset Number %s is not a number - an Asset Number is digits "
                "only." % asset_number)
    if not serial_number:
        return "An asset needs a Serial Number."
    if not asset_type:
        return "An asset needs an Asset Type."
    return ""


def _save_asset(asset_number, serial_number, asset_type, asset_model="",
                asset_id=None, actor="Admin (Server GUI)", conn=None):
    """The one writer of an asset row. Returns its id.

    The Lookup Sheet window and POST /lookup/upload both come through here, the
    way every Transaction comes through `_create_transaction` and every log
    entry through `_log_event`: a rule holding at one door and quietly not at
    the other is the shape of defect this project keeps finding.

    An asset needs the shape `_asset_shape_error` describes - both
    identifiers, the Asset Number digits only, and an Asset Type - and **an
    identifier names one asset**,
    matched without regard to case, which is refused here rather than left to
    whichever window happened to check. That refusal used to live in the Lookup
    Sheet window alone, where the upload endpoint walked straight past it and
    `_load_lookup_table` then kept the last of two rows claiming one Asset
    Number, shadowing the first without saying so. The unique indexes
    underneath are the backstop; this is what turns the constraint into a
    sentence naming the asset in the way.

    `conn` is for a caller writing many rows in one transaction, and it also
    decides the logging: a row written on its own is an Admin changing the
    Lookup Sheet and gets a line of its own, while one of five hundred in a
    wholesale replacement is covered by the entry that caller writes.
    """
    asset_number  = (asset_number or "").strip()
    serial_number = (serial_number or "").strip()
    asset_type    = (asset_type or "").strip()
    asset_model   = (asset_model or "").strip()
    refused = _asset_shape_error(asset_number, serial_number, asset_type)
    if refused:
        raise ValueError(refused)
    own  = conn is None
    conn = conn or get_db()
    now  = datetime.now().isoformat()
    try:
        for value, col, what in ((asset_number, "asset_number", "Asset Number"),
                                 (serial_number, "serial_number",
                                  "Serial Number")):
            if not value:
                continue
            held = conn.execute(
                "SELECT id, asset_number, serial_number, asset_type FROM assets"
                " WHERE %s = ? COLLATE NOCASE AND id IS NOT ?" % col,
                (value, asset_id)).fetchone()
            if held:
                raise ValueError(_IDENTIFIER_TAKEN % (
                    what, value,
                    held["asset_number"] or held["serial_number"],
                    held["asset_type"] or "no type"))
        if asset_id is None:
            cur = conn.execute(
                "INSERT INTO assets(asset_number, serial_number, asset_type,"
                " asset_model, created_at, created_by) VALUES (?,?,?,?,?,?)",
                (asset_number, serial_number, asset_type, asset_model, now,
                 actor))
            asset_id, said = cur.lastrowid, "added"
        else:
            conn.execute(
                "UPDATE assets SET asset_number=?, serial_number=?,"
                " asset_type=?, asset_model=?, updated_at=? WHERE id=?",
                (asset_number, serial_number, asset_type, asset_model, now,
                 asset_id))
            said = "corrected"
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()
    if own:
        _log_event("asset.saved", "%s %s (%s)"
                   % (asset_number or serial_number, said, asset_type),
                   actor=actor, level="warn")
    return asset_id


def _delete_asset(asset_id, actor="Admin (Server GUI)"):
    """Remove one asset. The Transactions recorded against it are untouched.

    Removing an asset stops it being transacted again (rule 6) and says nothing
    about the movements already recorded, which is why nothing else moves here.
    """
    conn = get_db()
    row = conn.execute("SELECT asset_number, serial_number FROM assets"
                       " WHERE id=?", (asset_id,)).fetchone()
    try:
        conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
        conn.commit()
    finally:
        conn.close()
    if row:
        _log_event("asset.removed",
                   row["asset_number"] or row["serial_number"],
                   actor=actor, level="warn")


# Which asset a Transaction is about. A Transaction carries no `assets.id`: it
# records the identifiers as they were typed, which is what leaves every
# Transaction untouched when the asset is removed from the Lookup Sheet - so
# the asset *is* whichever of the two the row actually holds, Asset Number
# first. That is a rule, and it is worded here once for the reason
# `_IDENTIFIER_TAKEN` is worded once: three queries ask it - Out Now, the per
# Engineer counts beside it and the newest-per-asset rule Cancel is held to -
# and a copy left behind is two numbers on one window disagreeing with nothing
# on the window saying which is right, and a Cancel refusing `not_newest`
# against an asset the count beside it thinks is a different one.
#
# The arguments are the two column expressions, so the same wording serves the
# placeholder side of a comparison: `_asset_key_sql("?", "?")` takes three
# parameters, the Asset Number twice and the Serial Number.
def _asset_key_sql(number="asset_number", serial="serial_number"):
    return ("CASE WHEN %s <> '' THEN 'A:' || %s ELSE 'S:' || %s END"
            % (number, number, serial))
