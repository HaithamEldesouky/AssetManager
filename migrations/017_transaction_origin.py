"""Where a decided Transaction's answer came from.

Adds one column to transactions:

    origin  'desktop' or 'auto' - the route an answer came through,
            NULL where the row was decided before this existed

Chosen by the Asset Server from the route (`POST /confirm/<id>` and
`POST /reject/<id>` write 'desktop', `_create_transaction` and
`_auto_accept_pass` write 'auto') and never read from a request body, which
is the whole point of recording it (#282).

**Backfill: 'auto' where `auto_approved = 1`, otherwise NULL.** An
auto-approved row is the one fact an old row holds about how it was decided.
Every other old row is NULL, which means "decided before Origin existed" and
shows no label. 'desktop' is never guessed: the 24h Auto-Accept pass left no
mark on the rows it confirmed, so a confirmed row without `auto_approved` may
have been answered by an Engineer or by that pass, and a guess would put a
false label on a confirmation.

The backfill only touches rows whose origin is still NULL, so running up()
again, or after init_db() added the column, changes nothing it should not.
"""

NAME = "transaction_origin"

COLUMNS = (
    ("origin", "TEXT"),
)


def _existing(conn):
    return [row[1] for row in
            conn.execute("PRAGMA table_info(transactions)").fetchall()]


def up(conn):
    cols = _existing(conn)
    for name, decl in COLUMNS:
        if name not in cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN %s %s"
                         % (name, decl))
    conn.execute("UPDATE transactions SET origin='auto' "
                 "WHERE auto_approved=1 AND origin IS NULL")


def down(conn):
    """No-op: a downgrade never drops a column.

    Every insert in `_create_transaction` names its columns, so an older build
    ignores this one. Dropping it would throw away where each answer came
    from, which nothing can reconstruct afterwards.
    """
    return
