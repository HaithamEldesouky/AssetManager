"""An Engineer's name stops being case-sensitive.

Rebuilds `team_members` with

    name TEXT PRIMARY KEY COLLATE NOCASE

and nothing else changes: same columns, same values, same spellings.

An Engineer is a person, and a person typed in a different case is the same
person. SQLite's default collation is BINARY, so until this every `WHERE
name=?` in server.py matched bytes - `_save_member` missed the row and inserted
a second Engineer beside the first, `/auth/verify` answered `no_member` to
somebody who exists, and `GET /pending/<member>` returned nothing to a Notifier
whose configured name was cased differently, which is an Engineer who stops
being asked to confirm anything.

A rebuild rather than an ALTER, because SQLite cannot change a column's
collation in place. The declared collation is what `=` uses, so this is also
what makes those eleven queries case-insensitive without one of them being
edited - and what stops the twelfth, written later, from being the one that
forgot.

**A database already holding two names that differ only in case cannot take
this, and the migration refuses**, naming each pair. Which of the two rows is
the real Engineer - whose Own Password, whose Access Profile, whose
Transactions - is not a decision a migration gets to make while nobody is
looking.

The spelling stored is left exactly as it was: what stops being significant is
only whether two spellings differ by case. NOCASE folds ASCII only, so a name
outside A-Z is still compared as bytes - a limit worth writing down rather than
engineering around, since a Python-side fold would be one the database could
not enforce.

`init_db()` does this too, the both-ways pattern every table here uses, so a
fresh database and an upgraded one are identical without anybody running
migrate.
"""

NAME = "member_name_nocase"

# The whole table as it stands at this version. Migrations 002 and 006 have
# already added the four columns beyond the original pair, so every database
# reaching this step has all six.
SCHEMA = """
CREATE TABLE team_members_new (
    name                 TEXT PRIMARY KEY COLLATE NOCASE,
    auto_approve         INTEGER DEFAULT 0,
    profile              TEXT    DEFAULT 'default',
    permissions          TEXT    DEFAULT '',
    password_hash        TEXT    DEFAULT '',
    must_change_password INTEGER DEFAULT 0
)
"""

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
            "collation cannot be changed: %s. Decide which row is the Engineer "
            "- its Own Password, its Access Profile and its Auto-Approve flag "
            "go with it - remove the other from the Server GUI's Manage Users "
            "window, and run this again."
            % (len(dupes), "; ".join("%r / %r" % (a, b) for a, b in dupes)))
    cols = ", ".join(COLS)
    conn.execute(schema)
    conn.execute("INSERT INTO team_members_new(%s) SELECT %s FROM team_members"
                 % (cols, cols))
    conn.execute("DROP TABLE team_members")
    conn.execute("ALTER TABLE team_members_new RENAME TO team_members")


def up(conn):
    _rebuild(conn, SCHEMA)


def down(conn):
    """Back to BINARY, with every row and every column kept.

    A downgrade never drops data, so this is the same rebuild in reverse rather
    than a drop. It can always run: two names differing only in case cannot
    exist under NOCASE, so there is nothing here for the collision check to
    find on the way back.

    An older build reads the table exactly as it did - the collation is not a
    column and nothing selects it - so what this actually restores is the
    byte-matching that build's queries assume.
    """
    _rebuild(conn, SCHEMA.replace(" COLLATE NOCASE", ""))
