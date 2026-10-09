"""An Own Password that is waiting to be replaced.

Adds one column to team_members:

    must_change_password  1 while the Own Password in the row beside it is one
                          an Admin set and the Engineer has not yet replaced

Stored rather than derived, for the reason `profile` is stored beside
`permissions` rather than inferred from it: an Engineer with no Own Password at
all and an Engineer holding one they are about to be made to replace are
different states, and nothing in `password_hash` can tell them apart - a hash
is a hash whoever chose the password behind it.

An Admin setting an Own Password arms it, the Engineer replacing that password
clears it, and an Admin setting another one arms it again, which is how a
forgotten password is reset. See docs/adr/0009-an-own-password-has-a-lifecycle.md.

Every row that already exists reads 0, which is the honest answer for an
install written before this: the Own Passwords in it were set by an Admin, but
nobody was ever told they were temporary, and arming the flag on all of them
would make every Engineer with a password replace it because of an upgrade.
"""

NAME = "own_password_lifecycle"

COLUMNS = (
    ("must_change_password", "INTEGER DEFAULT 0"),
)


def _existing(conn):
    return [row[1] for row in conn.execute("PRAGMA table_info(team_members)").fetchall()]


def up(conn):
    cols = _existing(conn)
    for name, decl in COLUMNS:
        if name not in cols:
            conn.execute("ALTER TABLE team_members ADD COLUMN %s %s" % (name, decl))


def down(conn):
    """No-op: a downgrade never drops a column.

    Every insert in server.py names its columns, so an older build simply
    ignores this one. Dropping it would throw away which Own Passwords are
    still waiting to be replaced - and re-upgrading would then read 0 for all
    of them, quietly turning every temporary password into a permanent one.
    """
    return
