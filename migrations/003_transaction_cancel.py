"""Cancellation of a Transaction.

Adds four columns to transactions:

    cancelled      1 when the Transaction was retracted, 0 otherwise
    cancelled_at   ISO timestamp of the cancellation, '' when never cancelled
    cancelled_by   who cancelled it, '' when never cancelled
    cancel_reason  why, '' when never cancelled

Cancelled is not Rejected. Rejected is the Engineer denying a movement recorded
against them, and the reason is theirs. Cancelled is the movement never having
happened at all - a mis-scan withdrawn - and the reason belongs to whoever
withdrew it. Merging the two would erase the distinction the whole system exists
to record, so they are separate columns and a row can carry either.

A state rather than a delete: deleting the row leaves no trace that anything was
recorded or why it was withdrawn, and the archive-then-delete path in the Server
GUI is the only other way to remove one. See docs/adr/0003.
"""

NAME = "transaction_cancel"

COLUMNS = (
    ("cancelled",     "INTEGER DEFAULT 0"),
    ("cancelled_at",  "TEXT DEFAULT ''"),
    ("cancelled_by",  "TEXT DEFAULT ''"),
    ("cancel_reason", "TEXT DEFAULT ''"),
)


def _existing(conn):
    return [row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()]


def up(conn):
    cols = _existing(conn)
    for name, decl in COLUMNS:
        if name not in cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN %s %s" % (name, decl))


def down(conn):
    """No-op: a downgrade never drops a column.

    Every insert in server.py names its columns and the xlsx archive is keyed on
    names, so an older build simply ignores these four. Dropping them would
    silently un-cancel every retracted Transaction - each one would go back to
    Pending, and Auto-Accept would confirm the lot within a day.
    """
    return
