"""What address each Client installation says it has.

Adds one column to clients:

    reported_address  the address of the interface the Client would reach
                      this server through, as it reported it

`address` beside it is the peer this server saw, and behind a NAT or VPN
gateway that is the gateway - one address for every Client behind it, which
no longer tells the Admin where the machine is. Only the machine can say its
own.

It is a **claim by the Client**, like the hostname and the certificate
fingerprint beside it, recorded with the source address the server saw as
always (ADR-0005). Both are shown and neither replaces the other; the claim is
displayed and trusted for nothing.

Every row that already exists reads '', which is the honest answer for an
install written before this: nothing has reported one yet, and every current
Client will on its next check-in.
"""

NAME = "client_reported_address"

COLUMNS = (
    ("reported_address", "TEXT DEFAULT ''"),
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
    ignores this one. Dropping it would throw away the one address that says
    where a machine behind NAT actually is.
    """
    return
