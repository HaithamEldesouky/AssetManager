---
status: accepted
---

# A backup is a copy of this install, and not of its secrets

There was no way to take a copy of this install from the console. What existed
was the copy `update.ps1` puts in `rollback\<old-version>\` before it writes,
and the `.bak-v*` a migration leaves behind - both of which are taken by
something else, for its own reasons, at a moment nobody chose. An Admin who
wanted a copy before a risky change, or who had to move this install to another
machine, had to know which files beside the server matter and stop the server by
hand before copying them.

So: **Backup / Restore**, an entry in Server Administration, behind the admin
password the console already asked for.

## Decision

**A backup is a directory, not an archive.** `AssetManagerBackup-<version>-<stamp>`
under a directory the Admin picks, holding each file beside the others and a
`manifest.json` describing them. A directory is what somebody can look inside
without a tool, copy onto a share, and hand to a restore that verifies it file by
file; a zip would be one more thing that can be half-written, and nothing here
needs the compression.

**It is taken inside the maintenance state** (ADR-0018). `_take_backup` copies
under `with _maintenance("a backup", actor):`, so the server answers reads
throughout and refuses writes with the code both clients already hold against.
A database copied while a Transaction is landing is a copy of neither state.

**The manifest carries a SHA-256 of what was written, not of what was read.**
The digest is taken over the copy, after the copy, because what a restore has to
be able to trust is the file it is about to put back - a digest of the source
would pass a backup whose write was truncated.

## What a backup does not hold, and says so by name

`BACKUP_EXCLUDED` names three files and the reason for each, and the manifest
carries that map, so a restore can tell the Admin what they have to set again
rather than leaving them to find out.

- **`smtp_secret.dat`** and **`sync_secret.dat`** are DPAPI at **machine scope**
  (ADR-0013, ADR-0014). They cannot be decrypted on another machine, so carrying
  them would be shipping a file that reads as a stored password and is not one -
  the worse failure, because the mail settings window would go on saying a
  password is set while every send fails. Excluded, named, and the restore says
  both have to be entered again.
- **`ssl_key.pem`** is excluded for the older reason: it is the one file that
  must never travel (rule 1's ground, and the reason `package.ps1` refuses any
  staged file that holds a `PRIVATE KEY`). A backup is copied to a share, onto a
  laptop, into somebody's Downloads; the key stays on the machine that generated
  it.

`ssl_cert.pem` is **not** excluded. It is public, `GET /cert` already serves it
to anybody who asks, and it is the file every client has pinned - so a restore
that put back everything except the certificate would be a server no client
could verify.

## What a restore does, in the order it does it

1. **Reads the manifest** and refuses one that is missing, unreadable, of the
   wrong `kind`, or whose `schema_version` is **newer** than this build knows
   how to open. A newer schema is the one case where restoring would succeed and
   then fail later, at a query, against a database this build cannot migrate
   down from on its own.
2. **Verifies every digest before a byte is written.** A restore that discovers
   a corrupt file halfway through has already replaced the database with half of
   another one. The verification also refuses a name that is not a bare
   basename - `os.path.join` with an absolute second argument throws the first
   away, which is `client_update.py`'s `_escapes_install` argument in a second
   place and for the same reason.
3. **Puts the current files aside**, into `restore_aside\<stamp>\`, one directory
   per run - `update.ps1`'s `rollback\` shape, and the only way back from a
   restore somebody pointed at the wrong backup. It is kept rather than cleared:
   a restore is rare, the files are small beside `lib\`, and the moment somebody
   wants the previous one is the moment after a second restore has been run.
4. **Writes**, inside `_maintenance("a restore", actor)`.
5. **Tells the Admin to restart**, and to set both secrets again.

## The database goes to this install's `db_path`, not the backup's

`_restore_target` maps the manifest's database name onto `DB_PATH` as this
server is configured now, with its `-wal` and `-shm` beside it. A backup records
where the database was; a restore is being run on a machine that has already
been told where it should be, which is `server_config.json`'s `db_path` - and
that configuration is itself one of the files being restored, so following the
backup's path would mean writing the database somewhere the very file landing
beside it says it is not. The other files land beside the server.

## Why there is no endpoint

The same call Add Transaction, Modify, the Client commands, the Lookup Sheet,
Mail Settings and Asset Sync all made: the Admin at this console is the only
actor. A restore replaces the database; an endpoint for it would be the largest
blast radius in this system reachable from the network, and there is nobody to
offer it to.

The four helpers take paths and touch no Tk - `_export_public_cert`'s precedent
(C5) - so every refusal here is reachable by `tools/server-checks.py`. The window
asks and reports and decides nothing.

## What was rejected

**Copying the database with SQLite's own backup API instead of the maintenance
state.** It would give a consistent database, and nothing else: `server_config.json`,
`admin_config.json` and the lookup workbook would still be copied while the
server was free to rewrite them, and a backup whose database and whose
`admin_config.json` are from different minutes is a restore that puts back a
password hash for a state that never existed. One mechanism for the whole set.

**Backing up into the install directory by default.** A backup on the same disk
as the thing it is a backup of answers none of the failures anybody takes one
for. The Admin picks the directory, and there is no default.

**A restore that restarts the server for itself.** Under IIS this process does
not own the listener (ADR-0001) and under the Service it is session 0; a window
that claimed to have restarted the server would be the tray's Quit before #125
made it say what it actually does. It says what to do instead.
