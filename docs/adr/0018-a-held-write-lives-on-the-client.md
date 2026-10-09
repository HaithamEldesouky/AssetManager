---
status: accepted
---

# A held write lives on the client

A backup or a restore copies the database while the server is running. A write
that lands mid-copy is in neither file: not in the copy, which was taken before
it, and not reliably in the live one, which a restore is about to replace. The
window is seconds for a backup of a small store and minutes for a restore, and
it is exactly the window in which the Storekeeper is standing at the store
recording movements and an engineer is answering a popup.

So the server needs a state in which it is running, answering reads, and not
taking writes. The question this decides is what happens to a write that
arrives during it.

## Decision

**The server refuses it, and says so in a shape the client can recognise.**
While the state is in force every non-GET request that is not on a short open
list answers `503` with `{"code": "maintenance"}` and the server's own sentence
about what it is busy with. Reads carry on untouched, which is what makes this
a maintenance state rather than an outage.

**Both clients hold the write and send it again.** The Storekeeper buffers the
Transaction the way it already buffers one for a server that is not there; the
Notifier gains a buffer of its own for the Confirm and the Reject it had none
for.

**The state is a file beside the server**, `maintenance.json`, carrying what is
running, since when, which process id and who started it.

**What enters it is the next ticket.** The state, the guard and both clients'
halves land together here because they are one decision and half of it shipped
is a client that holds nothing against a server that refuses, or a server that
refuses against clients that drop the write. Backup and Restore from the console
is what calls `_maintenance(...)`, and it is the only thing that will: the
helpers are the mechanism and the operation is its one caller, the same shape
`_authorise` and `_console_actor` already sit in here.

## Why the server does not queue it instead

A server that accepts a write it cannot commit has told the client something
untrue. Every client here already knows how to hold one - the Storekeeper has
had an offline buffer since long before this, and the Notifier's is the smaller
half of this ticket - so the honest answer is a refusal shaped so the client can
recognise it, rather than an acknowledgement nothing can rely on.

A queue on the server would also be a second writer of every table it queued
for, which is the property this codebase spends the most effort keeping: one
`_create_transaction`, one `_save_asset`, one `_log_event`. A queued Transaction
replayed after a restore is a Transaction created by something that is not
`_create_transaction`, or it is that function called with a timestamp somebody
else chose, which is the thing `POST /transactions` refuses on purpose.

## Why 503 and not 409

503 is what a client already treats as the server rather than the row. The
Storekeeper's flush keeps a 5xx queued and drops a 4xx as permanent, so a client
built before this reads the refusal correctly without knowing the code at all -
the row stays buffered and is sent again on the next tick. The code is what lets
a client that *does* know it do better than that: this answer is about the
server, so it will be the same for every row behind this one, and the flush can
stop after the first rather than asking forty times.

**The code is the discriminator and not the status.** A 503 without it is
somebody's proxy answering about this request; an ordinary 5xx from the server
is about the one row and the row behind it may well go through. Both spellings
are one function in `common.py`, `held_for_maintenance`, because a client that
tested for the wrong string would treat a hold as an ordinary error and what
that costs is different in each of them - forty POSTs on the Tk thread in the
Storekeeper, an engineer's answer thrown away in the Notifier.

## The open list is the set that stays open

`MAINTENANCE_OPEN` names the non-GET endpoints that are not held, and it is
written as the set that is **open** rather than the set that is refused. The two
are not symmetrical: an endpoint added later by somebody who has not read this
must default to being held, not to being let through. `tools/server-checks.py`
fails a non-GET route that is in neither.

There are three on it, and they share one property - none writes anything a
backup or a restore is about. `admin_verify` and `auth_verify` check a password,
and the second's in-place hash upgrade (ADR-0008) is best effort already and
never turns a correct password into a refusal. `preview_import` answers what a
file would become without writing a row of it.

## A file rather than a key in `server_config.json`

`install-iis.ps1` and `installer.py` both read-modify-write that file from
outside this process. A server held shut by a value one of those could rewrite
is a server shut for a reason nobody typed, and the two scripts are run in
exactly the situation - a reinstall, a rebind - where somebody is already
trying to work out why the store cannot record anything.

On disk rather than in a module global because a crash in the middle of a backup
must leave something an Admin can look at. The price of that is a file outliving
the process that wrote it, which would be a server refusing every write for ever
with nothing saying why - so `_start_background_jobs` clears one it finds at
start and writes down that it did. A process that is only now starting cannot be
in the middle of the backup the file describes, and that is the one moment such
a file is **known** to be stale. The monitor-only GUI deliberately does not go
through that path: a window watching somebody else's listener has no business
clearing that process's state while the operation is still running.

## A shapeless file means no maintenance

An absent, unreadable or shapeless `maintenance.json` is read as no maintenance,
which is the behaviour before this existed. That is the opposite answer from
`admin_config.json`, which raises on a malformed file, and deliberately: a stray
byte there would silently reset the admin password, where a stray byte here
would be a server refusing every write with nothing able to say why. The state
this describes is a few minutes long; a credential is permanent.

## What the clients do with it

The **Storekeeper** buffers on submit and shows the server's own words, because
only the server knows what it is busy with and "the server is busy" with no idea
what with is the answer nobody can act on. Its flush breaks out of the loop the
way a transport failure does, for the reason above.

The **Notifier** holds the answer in `pending_answers.json` and flushes it at
the top of the poll tick, **before** the `GET /pending` - an answer already given
must be delivered before the server is asked what is still outstanding, or a
Transaction the engineer confirmed an hour ago comes back as pending and is put
in front of them a second time. One entry per Transaction, since a queue holding
a Confirm and a Reject for one id would be two answers taken in whatever order
the file happened to be written in.

A **409** is treated as sent on both sides: `not_pending` is the server saying
this Transaction is already resolved, and asking again would only ever get it
back. A **4xx** leaves the queue permanently and is written to the System Log,
for the reason a 4xx leaves the offline buffer - a payload the server will
always refuse, retried every fifteen seconds, is a queue that never empties and
never says so.

Nothing is shown to the engineer when a held answer is finally refused. They
answered that Transaction minutes or days ago and the window is long gone; the
System Log is where the Admin working out why a Transaction says one thing and
an engineer says another will look.

## What was rejected

**A lock on the database instead.** SQLite already has one, and what it produces
is `database is locked` at whichever caller happened to arrive - a refusal with
no code, no sentence and nothing a client can distinguish from a corrupt file.

**Holding reads as well.** The Storekeeper's history, the Notifier's pending
queue and the Server GUI's own tick are all reads, and stopping them for the
length of a restore turns a maintenance window into an outage for no gain: a
read of a database being copied is a read of the database.

**One `write.held` row per refusal.** Every client retries on its own tick and
`POST /clients/log` is itself held, so a ten-minute restore would fill the table
it is restoring - and a held log write answered with a log row is a refusal that
writes what it refused. The entry is deduplicated on the window, the endpoint
and the caller's address: the first refusal is what an Admin needs to see, and
the hundredth says nothing the first did not.
