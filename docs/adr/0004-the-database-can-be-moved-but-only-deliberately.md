---
status: accepted
---

# The database can be moved, but only deliberately

`db_path` in `server_config.json` names the SQLite file. Absent or empty, the
database is `assets.db` beside the server, exactly as it has always been. Set,
it must be an absolute path on a local drive, the file must already be there,
and the server refuses to start when it is not.

The department's server has a small system volume and a large data volume, and
the answer to "the disk is full" should not be "reinstall the server
somewhere else".

The dialog that writes it is behind the console's admin door since 066 - an
entry in Server Administration rather than a button on the action row, where it
asked for nothing. The decision here is unchanged; what changed is that a
setting this document calls deliberate is no longer editable by whoever is
standing at a console nobody has unlocked. Since 090 it asks for the admin
password on every open rather than once a sitting, so a console somebody
unlocked and walked away from is not one either.

## Only the database moves

The lookup sheet, both config files and the certificate stay beside the
server. They are part of the install, not of the data: a directory setting that
moved all of them would mean an install whose own configuration lives somewhere
else, and the first thing anybody does on a broken server is look next to the
exe.

This is why the setting names a **file** and not a folder. A folder setting
reads like an invitation to move the lot, and it also cannot express the one
thing an admin sometimes wants, which is a database whose filename says which
install it belongs to.

## It never moves the file

Saving the setting copies nothing. Copying a live SQLite database out from
under a running server can capture a half-written page, and a move would leave
the `-wal` and `-shm` files behind - the copy then looks complete, opens
cleanly, and is missing the last committed transactions.

So the order is the admin's: stop the server, move the file, set the path,
start it. The dialog says so, and saving a path with nothing at it yet is
allowed on purpose, because the setting can reasonably be written either before
or after the move.

## A configured path with nothing at it prevents startup

The alternative was to create an empty database, which is what the default path
does on a first run. It was rejected because the two situations are not alike.
At the default path, no file means a first run. At a configured path, no file
means either the move has not happened yet or something else went wrong - and
in both cases an empty database gives a server that starts cleanly, reports
healthy on `/health`, shows no records, and accepts a day's work into a file
nobody will open again. Meanwhile the real database, wherever it went, is the
one everybody believes they are looking at.

The refusal names the path and names `db_path`, because the person reading it is
looking at a server that used to work.

An **invalid** `db_path` does not fall back to the default either, for the same
reason in a sharper form: the server would come up healthy and write to a
different file than the one the admin configured. The validation error is kept
and reported instead.

The gate (`_require_db`) is called explicitly at each of the three hosts - the
`serve` verb, the Windows Service, the GUI - rather than from inside
`init_db()`. `init_db()` also runs against a fresh install and from
`tools/server-checks.py`, where creating the file is exactly right, so a gate
in there would have needed a bypass clause and the bypass is the bug. Each host
reports in the only way it can be heard: stderr and exit 2 for IIS, the event
log for session 0, a message box for the console.

The `migrate` verb is exempt. Its wrapper passes `--db` explicitly, and
migrating a copy is a legitimate thing to do.

## Local drives only

A UNC path is refused on its text and a mapped drive by asking Windows what
kind of drive it is, because the letter says nothing.

SQLite's locking rests on advisory locks that an SMB redirector emulates rather
than honours. Two writers on one share do not see each other's locks and
interleave the file instead of queueing; the corruption is silent, and the
migration backup is on the same share. There is no configuration that makes
this safe, so it is refused where it can still be explained - at the point the
path is entered - rather than at bind time, where there is nobody to explain it
to.

## The tooling has to agree

`update.ps1`, `migrate.ps1` and `install-iis.ps1` all resolve the same path
through `Resolve-DbPath` in `tools/_deploy.ps1`. This is not tidiness. Every one
of them backs the database up before touching it, and **a backup written where
the database no longer is, is worse than no backup**: it succeeds, it is roughly
the right size, and it is the wrong file. Pointed at the default path on an
install that had moved, `migrate.ps1` would create an empty database, migrate
that, and report success while the real one stayed at the old schema version.

`install-iis.ps1` also grants the app pool identity Modify on the database's
**folder**, not just the file. SQLite writes `-wal` and `-shm` beside the
database, so without directory write access every submission fails with
"attempt to write a readonly database" - long after the install script reported
success.

## When to revisit

- If anyone wants the database on a share anyway. The answer is not a flag; it
  is a real database server, and at that point this system needs a different
  storage decision rather than a looser check.
- If a second thing ever needs to move with it. Then the setting is the wrong
  shape and it should become a data directory, with every path derived from it
  in one place.
