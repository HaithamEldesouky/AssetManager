"""The Storekeeper proposes an asset; the Admin approves it.

Creates `asset_proposals`, one row per asset somebody is holding that the
register does not have yet:

    id  asset_number  serial_number  asset_type  asset_model
    proposed_by  proposed_at  client_id
    status  decided_at  decided_by  reason

An asset the register does not hold cannot be transacted at all (rule 6), and
the register is changed only by the Admin at the console (rule 11). The
Storekeeper is the person standing where new hardware physically arrives, and
their only move before this was to stop, find an Admin and wait - which is
precisely the situation that makes somebody want a way past rule 6. A proposal
is the way that is answered without loosening it: the Storekeeper records what
they are holding, and it becomes an asset when an Admin says so. See ADR-0012.

`status` is **stored** here, unlike `client_commands`' derived one, because it
is not a function of two dates: a rejection is a decision somebody made and a
reason they gave, and there is nothing else on the row that says it.

The identifiers are `COLLATE NOCASE` for the reason `assets` has them (010) -
a proposal differing from a pending one only in case is the same proposal - but
there is **no unique index**. Two people proposing one serial is a thing that
happens and is answered with a sentence rather than a constraint; and a
rejected proposal must be re-proposable, because the hardware may have turned
up after all and that is how the Storekeeper says so.

`down()` **keeps the table**, the answer 004, 005 and 007 give: an older build
never reads it, while dropping it would throw away every pending proposal - the
assets somebody is holding and nobody has approved - along with the record of
what was refused and why. The index is a performance artefact with no data in
it, so that is what a downgrade reverses.
"""

NAME = "asset_proposals"

SCHEMA = """
CREATE TABLE IF NOT EXISTS asset_proposals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_number  TEXT    DEFAULT '' COLLATE NOCASE,
    serial_number TEXT    DEFAULT '' COLLATE NOCASE,
    asset_type    TEXT    NOT NULL,
    asset_model   TEXT    DEFAULT '',
    proposed_by   TEXT    NOT NULL,
    proposed_at   TEXT    NOT NULL,
    client_id     TEXT    DEFAULT '',
    status        TEXT    NOT NULL,
    decided_at    TEXT    DEFAULT '',
    decided_by    TEXT    DEFAULT '',
    reason        TEXT    DEFAULT ''
)
"""

INDEX = ("CREATE INDEX IF NOT EXISTS idx_asset_proposals_status"
         " ON asset_proposals (status, id)")


def up(conn):
    conn.execute(SCHEMA)
    conn.execute(INDEX)


def down(conn):
    conn.execute("DROP INDEX IF EXISTS idx_asset_proposals_status")
