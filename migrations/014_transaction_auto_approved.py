"""Which kind of Confirmed a Transaction is.

Adds one column to transactions:

    auto_approved  1 where the row was Confirmed at creation because the
                   Engineer it names has Auto-Approve set, 0 otherwise

An Engineer who answered a popup and an Auto-Approve Engineer who was never
asked leave the same `confirmed=1` behind, and the cancel window #198 adds may
open one and must never open the other: a confirmation is the evidence the
verification step produces, and a door that could not tell the two apart would
be a way past somebody's answer.

**Stored rather than derived**, which is the other side of the rule
`client_commands` states - derive a state that is a function of what you
already hold, store one that is not. Neither of the two ways of working it out
afterwards holds:

  * `team_members.auto_approve` answers about the Engineer **as they are now**,
    and an Admin may tick that box an hour from now, at which point every row
    that Engineer really confirmed starts reading as auto-approved and the
    window opens over their confirmation.

  * the `transaction.created` entry in `system_log` already says
    `(auto-approved)` - and `POST /clients/log` is unauthenticated (ADR-0002,
    ADR-0005), so a caller on the network could write that sentence about a row
    an Engineer really answered.

So it is written by `_create_transaction`, the one writer of a Transaction, at
the moment the row is written, from the same `auto_approve` the `confirmed` and
`confirmed_at` beside it come from.

Every row that already exists reads 0, which fails closed: an older Transaction
is outside any window measured in minutes regardless, and the answer a server
gives about a row it has no flag for is the refusal it gave before this
existed.
"""

NAME = "transaction_auto_approved"

COLUMNS = (
    ("auto_approved", "INTEGER DEFAULT 0"),
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


def down(conn):
    """No-op: a downgrade never drops a column.

    Every insert in `_create_transaction` names its columns, so an older build
    ignores this one entirely. Dropping it would throw away which Transactions
    nobody was ever asked about - the one fact that tells a confirmation from a
    row that was never verified - and re-upgrading would read 0 for every row,
    which is the closed answer and so silently narrows nothing but also
    silently loses the record.
    """
    return
