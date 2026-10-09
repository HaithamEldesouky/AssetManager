"""The System Log - what was done, across all three components.

Creates one table:

    system_log   one row per action, written by the Server in process or
                 shipped to it by a Client over POST /clients/log

Nothing recorded any of this before. The `transactions` table says what was
moved and `client_commands` says what an Admin asked a machine to do; neither
says who typed a wrong password, when the lookup sheet was replaced, which
Engineer's Own Password was reset, or that a Notifier started at all. The only
other record was `dev-run.ps1`'s redirected stdout and `applaunch.py`'s
`launch.err.log`, and neither of those exists on an installed machine.

A table in the database rather than a rolling file beside the server, because
every question asked of it is a filter over a column - which component, which
day - because it then travels inside the backup `update.ps1` takes and the copy
a migration leaves behind, rather than being a second thing somebody has to
remember to collect, and because the Server GUI window that reads it is a table
already. What that costs is contention with the Transaction writes, which is
answered where it has to be: `_log_event` in server.py never raises and never
waits long, so a locked or full log cannot turn a recorded Transaction into a
refused one.

`ts` is always the Server's own clock - when the row was written here. A
shipped entry carries the Client's claim about its own clock in `client_ts`
beside it, rather than in place of it, because a laptop that was offline for a
day ships a batch that all lands at one server time and because a clock is one
more thing an unauthenticated caller chooses. `address` is the same shape of
fact: the source address the Server actually saw, empty for exactly the rows
the Server wrote in process, so a caller claiming `component: "Server"` from
the network reads as the mismatch it is rather than being believed.

Retention is a bound, applied hourly by the job in server.py: entries older
than LOG_RETENTION_DAYS go, and so does anything beyond LOG_MAX_ROWS. Two
bounds rather than one because the endpoint is unauthenticated (ADR-0002,
ADR-0005) - an age bound alone cannot bound a table anybody on the network can
write to as fast as they like.
"""

NAME = "system_log"

SCHEMA = """CREATE TABLE IF NOT EXISTS system_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    component TEXT NOT NULL,
    event     TEXT NOT NULL,
    level     TEXT DEFAULT 'info',
    actor     TEXT DEFAULT '',
    detail    TEXT DEFAULT '',
    client_id TEXT DEFAULT '',
    address   TEXT DEFAULT '',
    client_ts TEXT DEFAULT ''
)"""

INDEX = "CREATE INDEX IF NOT EXISTS idx_system_log_ts ON system_log (ts)"


def up(conn):
    conn.execute(SCHEMA)
    # Both readers order and filter on ts: the Server GUI's window, and the
    # hourly retention pass that deletes by age.
    conn.execute(INDEX)


def down(conn):
    """Drops the index only. The table is kept.

    A downgrade never drops a column, and dropping a whole table is that rule
    written larger - the same answer `004_client_registry` and
    `005_client_commands` give. An older build never queries `system_log`, so
    keeping it costs that build nothing, while dropping it would throw away the
    only record of what was done to this server: who was refused, what an Admin
    changed, which machines were running. That is the half of the history the
    `transactions` table cannot reconstruct, and a downgrade is exactly the
    moment somebody wants to read it. The index is a pure performance artefact
    with no data in it, so reversing that is what a `down()` is for.
    """
    conn.execute("DROP INDEX IF EXISTS idx_system_log_ts")
