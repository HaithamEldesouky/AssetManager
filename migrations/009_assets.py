"""The assets themselves move into the database; the sheet becomes a format.

Creates one table:

    assets       one row per asset the department owns, keyed by the two
                 identifiers a Transaction is recorded against

`asset_lookup.xlsx` was the store until now. It is read on *every*
`_load_lookup_table()` call - every Transaction submitted, every keystroke in a
lookup field - and written by rewriting the whole workbook, which is why
correcting one asset rewrote every row beside it. Three things asked for in
this batch cannot be built on that: a uniqueness rule the store enforces rather
than one window happening to check, an import that writes a validated subset
without touching rows nobody named, and row-level updates arriving from an
external system while live reads are going on. See ADR-0011.

The sheet does not go away: it is still the interchange format, still what
`GET /lookup/file` serves and what `POST /lookup/upload` accepts, and it is
still embedded in the exe as the Lookup Sheet a brand-new install starts from. What
changed is which of the two is the copy.

**This migration seeds the table from whatever `asset_lookup.xlsx` sits beside
the database**, so no deployment loses its Lookup Sheet on the way up. Where it
finds no sheet - `db_path` has moved the database away from the server, or
openpyxl is not importable here - it creates an empty table and says so, and
`init_db()` seeds it on the next boot from the sheet beside the server, which
is the path it takes on a fresh install anyway. Both ways, the same pattern
every table here uses.
"""

import os

NAME = "assets"

SCHEMA = """CREATE TABLE IF NOT EXISTS assets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_number  TEXT DEFAULT '',
    serial_number TEXT DEFAULT '',
    asset_type    TEXT NOT NULL,
    asset_model   TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    created_by    TEXT DEFAULT '',
    updated_at    TEXT DEFAULT ''
)"""


def _db_dir(conn):
    row = conn.execute("PRAGMA database_list").fetchone()
    path = row[2] if row else ""
    return os.path.dirname(os.path.abspath(path)) if path else ""


def _sheet_rows(path):
    """(asset_number, serial_number, asset_type, asset_model) from the workbook.

    A copy of what `server.py` reads a sheet with rather than an import of it:
    a migration runs inside whatever build is on the machine and must not be
    able to fail because a helper moved.
    """
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()
    out = []
    for row in rows:
        if not row or len(row) < 3:
            continue
        an = str(row[0]).strip() if row[0] else ""
        sn = str(row[1]).strip() if row[1] else ""
        at = str(row[2]).strip() if row[2] else ""
        am = str(row[3]).strip() if len(row) > 3 and row[3] else ""
        if am.upper() in ("N/A", "N\\A", "NA", "N.A", "-"):
            am = ""
        if not at or (not an and not sn):
            continue
        out.append((an, sn, at, am))
    return out


def up(conn):
    from datetime import datetime
    conn.execute(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]:
        return
    path = os.path.join(_db_dir(conn), "asset_lookup.xlsx")
    if not os.path.exists(path):
        return
    try:
        rows = _sheet_rows(path)
    except Exception:
        return   # init_db() seeds it on the next boot
    now = datetime.now().isoformat()
    conn.executemany(
        "INSERT INTO assets(asset_number, serial_number, asset_type,"
        " asset_model, created_at, created_by)"
        " VALUES (?, ?, ?, ?, ?, 'asset_lookup.xlsx')",
        [(an, sn, at, am, now) for an, sn, at, am in rows])


def down(conn):
    """No-op: the table is kept.

    A downgrade never drops a column, and dropping a whole table is the same
    rule written larger - the answer `004`, `005` and `007` all give. An older
    build reads the sheet and never queries `assets`, so keeping it costs that
    build nothing. Dropping it would throw away every asset added, corrected or
    imported since the upgrade: the sheet on disk is a copy from before the
    move, so there would be nothing to reconstruct them from, and a downgrade
    is exactly the moment somebody wants the Lookup Sheet intact.
    """
    return
