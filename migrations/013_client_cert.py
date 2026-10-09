"""Which certificate each Client installation trusts.

Adds one column to clients:

    cert_fingerprint  the SHA-256 fingerprint of the `ssl_cert.pem` that
                      installation currently pins, as it reported it

The question it answers is not what build a Client is on - `version` beside it
already says that - but whether it can still reach this server after the
certificate is replaced. Every client pins that file and fails closed against
anything else (rule 1), so a replacement strands each one holding the outgoing
certificate until somebody at that machine confirms the new fingerprint
(ADR-0010), and nothing on the check-in said which of them that would be.

It is a **claim by the Client**, like the hostname and the app name beside it,
recorded with the source address the server saw as always (ADR-0005). Only
that installation can say what it holds, and what is worth knowing is exactly
what it would present its pinned copy against.

Every row that already exists reads '', which is the honest answer for an
install written before this: nothing has reported a fingerprint yet, and every
one of them will on its next check-in.
"""

NAME = "client_cert"

COLUMNS = (
    ("cert_fingerprint", "TEXT DEFAULT ''"),
)


def _existing(conn):
    return [row[1] for row in conn.execute("PRAGMA table_info(clients)").fetchall()]


def up(conn):
    cols = _existing(conn)
    for name, decl in COLUMNS:
        if name not in cols:
            conn.execute("ALTER TABLE clients ADD COLUMN %s %s" % (name, decl))


def down(conn):
    """No-op: a downgrade never drops a column, and 004 keeps the table.

    The insert in `_record_checkin` names its columns, so an older build
    ignores this one. Dropping it would throw away which certificate every
    machine that is not in front of the Admin is holding - and a downgrade is
    routinely what happens when a certificate change has gone wrong, which is
    the one moment that column is the thing being read.
    """
    return
