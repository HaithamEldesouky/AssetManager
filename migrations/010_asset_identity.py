"""An identifier names one asset, whatever case it is typed in.

Rebuilds `assets` with both identifiers declared `COLLATE NOCASE` and adds a
unique index on each, over the rows where that identifier is non-empty:

    idx_assets_number    UNIQUE (asset_number)    WHERE asset_number  <> ''
    idx_assets_serial    UNIQUE (serial_number)   WHERE serial_number <> ''

The refusal existed before this, inside the Lookup Sheet window, and nothing
else ran it: `POST /lookup/upload` replaced the whole sheet with whatever
arrived and `_load_lookup_table` then silently kept the last of two rows
claiming one Asset Number - the earlier one shadowed, not reported. The
importer (027) and the external sync (032) would each arrive at that same gap.
So the rule moves to where every writer already goes, `_save_asset`, and to the
schema underneath it.

The partial indexes are what make an asset with only a serial legal: an empty
identifier is not an identifier, and two of them are not a collision. Nothing
about the shape of an asset changed - rule 5's "at least one of the two" is
still what `_save_asset` holds a row to.

Case is the other half of the same rule, and retrieval had it already:
`_load_lookup_table` has always keyed the sheet on both identifiers lowercased,
so `GET /lookup` and rule 6 are case-insensitive today. 024 moved that store
into SQLite; declaring the columns `COLLATE NOCASE` is what stops it being lost
on the way, and it puts the fold in the schema rather than in each caller's
memory. The **stored spelling is the one that was typed**, exactly as it is for
an Engineer's name (008): what stops being significant is only whether two
spellings differ by case. `NOCASE` folds ASCII only.

**A database already holding two rows for one identifier** is the case worth
reading carefully, because the real Lookup Sheet is one: 6 of its 3462 rows
share a Serial Number with another row, each pair carrying two distinct Asset
Numbers. A value that names two assets names neither, so it is **cleared from
all but the lowest id** - both assets kept, each still carrying its other
identifier, one deterministic answer left for whoever scans it. What this will
not do is clear an identifier off a row that has no other one: that row would
stop being an asset, and which of two rows describing one asset is the real one
is not a decision a migration gets to make. Those it **refuses** over, naming
them. `init_db()` meets the same database and warns instead, because it runs on
every boot.
"""

NAME = "asset_identity"

SCHEMA = """CREATE TABLE assets_new (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_number  TEXT DEFAULT '' COLLATE NOCASE,
    serial_number TEXT DEFAULT '' COLLATE NOCASE,
    asset_type    TEXT NOT NULL,
    asset_model   TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    created_by    TEXT DEFAULT '',
    updated_at    TEXT DEFAULT ''
)"""

COLS = ("id", "asset_number", "serial_number", "asset_type", "asset_model",
        "created_at", "created_by", "updated_at")

INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_number ON assets"
    " (asset_number) WHERE asset_number <> ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_serial ON assets"
    " (serial_number) WHERE serial_number <> ''",
)


def resolve(conn):
    """Clear an identifier two assets share. Returns (cleared, unresolved).

    Each is a list of (column, the value, how many rows). `cleared` is what was
    blanked - every row holding that value but the lowest id, each of which
    still carries its other identifier. `unresolved` is what could not be,
    because blanking would leave a row with no identifier at all.

    The same rule `server.py`'s `_resolve_asset_identity` applies, written here
    rather than imported: a migration takes a connection and nothing else, the
    way `008` and `009` carry their own DDL rather than reaching into the server
    they have to keep running without.
    """
    cleared, unresolved = [], []
    for col, other in (("asset_number", "serial_number"),
                       ("serial_number", "asset_number")):
        dupes = conn.execute(
            "SELECT {0} FROM assets WHERE {0} <> '' GROUP BY {0} COLLATE NOCASE"
            " HAVING COUNT(*) > 1".format(col)).fetchall()
        for (value,) in dupes:
            rows = conn.execute(
                "SELECT id, {1} FROM assets WHERE {0} = ? COLLATE NOCASE"
                " ORDER BY id".format(col, other), (value,)).fetchall()
            if any(not r[1] for r in rows[1:]):
                unresolved.append((col, value, len(rows)))
                continue
            conn.execute("UPDATE assets SET {0} = '' WHERE id IN ({1})".format(
                col, ",".join(str(r[0]) for r in rows[1:])))
            cleared.append((col, value, len(rows) - 1))
    return cleared, unresolved


def _rebuild(conn, schema):
    cols = ", ".join(COLS)
    conn.execute(schema)
    conn.execute("INSERT INTO assets_new(%s) SELECT %s FROM assets"
                 % (cols, cols))
    conn.execute("DROP TABLE assets")
    conn.execute("ALTER TABLE assets_new RENAME TO assets")


def up(conn):
    cleared, unresolved = resolve(conn)
    if unresolved:
        raise RuntimeError(
            "%d identifier(s) name more than one asset and cannot be cleared - "
            "a row would be left with no identifier at all, which is not an "
            "asset any more: %s. Correct them in the Server GUI's Lookup Sheet "
            "window; which of two rows describing one asset is the real one is "
            "not a decision this migration gets to make."
            % (len(unresolved),
               "; ".join("%s %r on %d row(s)" % (c, v, n)
                         for c, v, n in unresolved)))
    _rebuild(conn, SCHEMA)
    for sql in INDEXES:
        conn.execute(sql)
    return cleared


def down(conn):
    """Drops the indexes and puts the collation back. Every row is kept.

    The indexes are a constraint with no data in it, which is what a `down()`
    is for. The collation goes back with them because an older build compares
    these columns byte for byte and would otherwise see `AM-1` and `am-1` as
    two assets in the table and one in `_load_lookup_table`, which keys on the
    lowercased identifiers - the mismatch this migration exists to remove.

    An identifier `up()` cleared is **not** put back. It named two assets and
    so named neither, the row it was cleared from still carries its other
    identifier, and the sheet it came from is still on disk: restoring it would
    recreate the ambiguity this removed, in a build with no index to catch it.
    """
    for name in ("idx_assets_number", "idx_assets_serial"):
        conn.execute("DROP INDEX IF EXISTS %s" % name)
    _rebuild(conn, SCHEMA.replace(" COLLATE NOCASE", ""))
