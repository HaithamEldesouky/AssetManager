"""The registry of Client installations.

Creates one table:

    clients   one row per installation, keyed on the identifier the Client
              generates once and keeps in its own configuration

Nothing on the wire carried any of this before. The server saw a source address
and nothing else, so the Admin could not tell which machine an Engineer's
Notifier was on, whether it was running at all, or that one had been set up as
the wrong Engineer, without walking to the laptop.

The key is the Client's own identifier rather than the hostname or the address,
because both of those move: a machine is renamed and a DHCP lease changes, and
either would fill this table with duplicates of one installation. Hostname is
the label a human recognises and the address is what the Admin needs when they
have to go and find the machine, so both are recorded - as facts about the
installation, not as its identity. A reinstall that clears the configuration
appears as a new row, because it is a new installation.

See docs/adr/0005 for why the check-in is its own channel and not a widening of
the heartbeat.
"""

NAME = "client_registry"

SCHEMA = """CREATE TABLE IF NOT EXISTS clients (
    client_id  TEXT PRIMARY KEY,
    hostname   TEXT DEFAULT '',
    os_user    TEXT DEFAULT '',
    app        TEXT DEFAULT '',
    version    TEXT DEFAULT '',
    member     TEXT DEFAULT '',
    address    TEXT DEFAULT '',
    first_seen TEXT DEFAULT '',
    last_seen  TEXT DEFAULT ''
)"""


def up(conn):
    conn.execute(SCHEMA)


def down(conn):
    """No-op: the table is kept.

    A downgrade never drops a column, and dropping a whole table is the same
    rule written larger. An older build never queries `clients`, so leaving it
    costs that build nothing; dropping it would throw away every installation
    record the Admin has - the hostnames and addresses of machines that are not
    in front of them - to satisfy a version number that does not read the table
    either way. Re-upgrading would then present a fleet of Clients as brand new
    installations until each one happened to check in again.
    """
    return
