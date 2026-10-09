"""An Engineer gets an id, and a name that can change.

Rebuilds `team_members` with

    id   INTEGER PRIMARY KEY AUTOINCREMENT
    name TEXT UNIQUE COLLATE NOCASE

and nothing else changes: same other columns, same values, same spellings.

`name` was the primary key until here, which made a rename a delete and an
insert - and a delete takes the Engineer's Own Password, their Access Profile
and their permissions with it. An Admin correcting a misspelt name was
therefore correcting it by standing up a second Engineer and throwing the first
one away, so the safe answer was to leave the name wrong. An id makes the
rename an `UPDATE`, and everything hanging off the row stays on it.

The name keeps its `UNIQUE COLLATE NOCASE`, so everything migration `008` bought
is intact: two spellings differing only in case are still one Engineer, every
`WHERE name=?` in `server.py` still matches without regard to case, and
`ON CONFLICT(name)` in `_save_member` still fires on the constraint rather than
on the key. What stops being true is only that the name is the *identity*.

A rebuild rather than an `ALTER`, because SQLite cannot add or remove a primary
key in place - the pattern `008_member_name_nocase` and `010_asset_identity`
already use, and the runner opens the transaction around it (see the migration
rules in `CLAUDE.md`), so a failure here leaves nothing of itself behind.

**A database already holding two names that differ only in case cannot take
this either**, and the migration refuses, naming each pair - the same refusal
`008` makes and for the same reason: which of the two rows is the real Engineer
is not a decision a migration gets to make while nobody is looking. In practice
nothing reaching this step can collide, `008` having refused the same database
one version earlier; the check is here because `init_db()` warns and carries on
where this refuses, so a database that came up that way arrives here intact.

`down()` rebuilds back to `name TEXT PRIMARY KEY COLLATE NOCASE`, keeping every
row and every column. The id is dropped because it is the key being reversed
rather than data - no Transaction references it, `/members` answers by name on
both sides of the change, and an older build never selects it.

`init_db()` does this too, the both-ways pattern every table here uses, so a
fresh database and an upgraded one are identical without anybody running
migrate.
"""

NAME = "member_identity"

# The whole table as it stands at this version. Migrations 002, 006 and 008
# have already brought it to six columns, so every database reaching this step
# has all six and this adds the seventh.
SCHEMA = """
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

DOWN_SCHEMA = """
CREATE TABLE team_members_new (
    name                 TEXT    PRIMARY KEY COLLATE NOCASE,
    auto_approve         INTEGER DEFAULT 0,
    profile              TEXT    DEFAULT 'default',
    permissions          TEXT    DEFAULT '',
    password_hash        TEXT    DEFAULT '',
    must_change_password INTEGER DEFAULT 0
)
"""

#: The columns carried across, in both directions. `id` is deliberately not in
#: it: on the way up there is none to carry and AUTOINCREMENT assigns one, and
#: on the way down there is nowhere to put it.
COLS = ("name", "auto_approve", "profile", "permissions", "password_hash",
        "must_change_password")


def _collisions(conn):
    """Pairs of Engineers whose names differ only in case, oldest first."""
    return conn.execute(
        "SELECT a.name, b.name FROM team_members a JOIN team_members b"
        " ON a.rowid < b.rowid AND a.name = b.name COLLATE NOCASE"
        " ORDER BY a.rowid"
    ).fetchall()


def _rebuild(conn, schema):
    dupes = _collisions(conn)
    if dupes:
        raise RuntimeError(
            "team_members holds %d name(s) that differ only in case, so the "
            "name cannot be made unique: %s. Decide which row is the Engineer "
            "- its Own Password, its Access Profile and its Auto-Approve flag "
            "go with it - remove the other from the Server GUI's Manage Users "
            "window, and run this again."
            % (len(dupes), "; ".join("%r / %r" % (a, b) for a, b in dupes)))
    cols = ", ".join(COLS)
    conn.execute(schema)
    conn.execute("INSERT INTO team_members_new(%s) SELECT %s FROM team_members"
                 " ORDER BY rowid" % (cols, cols))
    conn.execute("DROP TABLE team_members")
    conn.execute("ALTER TABLE team_members_new RENAME TO team_members")


def up(conn):
    _rebuild(conn, SCHEMA)


def down(conn):
    """Back to a name-keyed table, with every row and every column kept.

    A downgrade never drops a column that holds data. The id is not one: it was
    added by this migration, nothing outside `team_members` references it, and
    `/members` answered by name before this and still does - so what goes is the
    key being reversed rather than anything anybody wrote down.

    It can always run: the names are unique under NOCASE on this side of the
    change, so there is nothing for the collision check to find on the way back.
    """
    _rebuild(conn, DOWN_SCHEMA)
