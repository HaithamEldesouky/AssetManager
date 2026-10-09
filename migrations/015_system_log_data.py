"""Which act carries a fact beside its sentence.

Adds one column to system_log:

    data  TEXT, nullable - a JSON object, or NULL where a call site names
          none.

`EVENT_SENTENCES` (server_log.py) already gives every event a phrase, and
that phrase is all a reader could get back out of a row without parsing
`detail`'s free text - which asset, which client, which port, is a question
every new ticket answers with a new regex over it. This column is the other
half: a call site that has a fact worth keeping hands it to `_log_event` as a
dict, and `event_phrase` reads it back into the phrase's own `{keys}` where
the phrase has any.

**Additive and optional, on purpose.** `detail` goes on being written at
every call site exactly as it is today - `_log_event`'s caller loses nothing
by not passing `data`, and the ~100 call sites #071 leaves untouched carry
NULL here for ever, which is answered the same way an event with no phrase
at all is: the reader falls back to what it already had. A row this build
writes with no `data` and a row a build before this one ever ran reads back
identically, which is the one thing this migration must not get wrong.

Every row that already exists reads NULL, which is the same answer a call
site that chooses not to pass `data` gets going forward - there is no closed
default here the way `auto_approved`'s 0 is one: NULL is not a narrower
answer than "no data", it is that answer.
"""

NAME = "system_log_data"

COLUMNS = (
    ("data", "TEXT"),
)


def _existing(conn):
    return [row[1] for row in
            conn.execute("PRAGMA table_info(system_log)").fetchall()]


def up(conn):
    cols = _existing(conn)
    for name, decl in COLUMNS:
        if name not in cols:
            conn.execute("ALTER TABLE system_log ADD COLUMN %s %s"
                         % (name, decl))


def down(conn):
    """No-op: a downgrade never drops a column.

    An older build never reads `system_log.data` - it was never in its own
    schema - so it ignores the column exactly as it ignores any other row
    shape it does not recognise. Dropping it would throw away the one fact a
    reader could pull off a row without parsing `detail`, for the five events
    that write it, and re-upgrading would leave every row written while
    downgraded with no `data` at all - which reads as "this call site chose
    not to" rather than the truth, that nothing here could keep it. Kept, the
    column is exactly what it was: a row `event_phrase` reads if it can and
    falls back past if it cannot, the same answer it gives for NULL.
    """
    return
