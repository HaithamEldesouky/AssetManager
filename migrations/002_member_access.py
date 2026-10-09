"""Per-engineer access profile and password.

Adds three columns to team_members:

    profile        'default' or 'custom'
    permissions    comma-separated permission names, only read when custom
    password_hash  SHA-256 of the engineer's own password, '' when unset

profile is kept alongside permissions rather than inferred from it so that
clearing every checkbox on a custom profile stays distinguishable from being on
the default profile - the two mean different things the moment the default set
changes.
"""

NAME = "member_access"

COLUMNS = (
    ("profile",       "TEXT DEFAULT 'default'"),
    ("permissions",   "TEXT DEFAULT ''"),
    ("password_hash", "TEXT DEFAULT ''"),
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

    Every insert in server.py names its columns and the xlsx archive is keyed on
    names, so an older build simply ignores these three. Dropping them would
    destroy an admin's access configuration and every engineer's password to
    satisfy a version number nothing reads.
    """
    return
