"""The queue of commands waiting for a Client.

Creates one table:

    client_commands   one row per command issued to one Client, kept after it
                      is collected or expires

Knowing which Client is running the wrong thing does not help if correcting it
means walking to the laptop. The Admin queues a command and the Client collects
it on its next check-in.

Durable, not in memory: a command for a laptop that is closed for a week has to
still be there when it opens, and under IIS (ADR-0001) an application-pool
recycle would take an in-memory queue with it and leave no record it had ever
existed.

`expires_at` is written at issue time rather than computed on read, so changing
the default period later cannot silently move the deadline of a command already
waiting. There is no status column: collected and expired are derived from
`collected_at` and `expires_at`, because a stored status is a second copy of
what those two already say and it is the copy that goes stale.

See docs/adr/0005 for the check-in channel these are handed back through.
"""

NAME = "client_commands"

SCHEMA = """CREATE TABLE IF NOT EXISTS client_commands (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    TEXT NOT NULL,
    command      TEXT NOT NULL,
    issued_at    TEXT NOT NULL,
    issued_by    TEXT DEFAULT 'Admin',
    expires_at   TEXT NOT NULL,
    collected_at TEXT DEFAULT ''
)"""

INDEX = ("CREATE INDEX IF NOT EXISTS idx_client_commands_pending"
         " ON client_commands (client_id, collected_at)")


def up(conn):
    conn.execute(SCHEMA)
    # Every check-in runs the pending-commands query, so it is on the hot path
    # of the one endpoint every Client calls on a timer.
    conn.execute(INDEX)


def down(conn):
    """Drops the index only. The table is kept.

    A downgrade never drops a column, and dropping a whole table is that rule
    written larger: an older build never queries `client_commands`, so keeping
    it costs that build nothing, while dropping it would throw away the record
    of every command the Admin issued - including the ones that were collected,
    which is the only evidence that a machine was ever told to do something.
    The index is a pure performance artefact with no data in it, so reversing
    that is what a `down()` is for.
    """
    conn.execute("DROP INDEX IF EXISTS idx_client_commands_pending")
