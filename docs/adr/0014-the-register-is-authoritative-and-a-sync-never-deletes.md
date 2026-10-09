---
status: accepted
---

# The register is authoritative, and a sync never deletes

Another system in this department already knows what hardware it owns. 032
reads that system's asset list and folds it into the `assets` table. The
question this ADR answers is not how — that is `urllib.request` and 027's
mapper, and neither is interesting — but **what the sync is allowed to do to a
register that other things already depend on**.

Three decisions, each of which is a place somebody will reach for the opposite
and each of which is load-bearing for something outside this feature.

## The register wins over the external system for a field it already holds

An asset both systems hold, where they disagree about its Asset Type or its
Asset Model, is **left exactly as it is** and reported as a conflict. The
external system's value is taken only where this register's is **empty**.

This is not modesty about the external system's data quality. It is rule 6.
`_create_transaction` refuses a movement for an asset the Lookup Sheet does not
hold, and it *corrects* the asset number, serial number and type of every
Transaction it does accept to the sheet's values. The sheet is therefore not a
description of an asset; it is the thing every recorded movement was measured
against. A remote system that could rewrite an `asset_type` silently is how an
asset that has been transacted as a Laptop for a year becomes a Screen
overnight — with a year of Transactions behind it that were corrected to say
Laptop, and nothing anywhere saying that the two halves of that history are
about the same object.

Filling an **empty** field is the one case where that argument does not apply:
nothing was ever corrected to `""`, no Transaction was measured against it, and
an asset carrying a model where it had none is strictly more than it was. That
is the whole of the overlap where the external system is the better answer, so
that is the whole of what it is allowed to write.

The conflict is *reported* rather than swallowed. A disagreement between two
systems about one asset is a fact somebody has to settle, and the settling is
done by an Admin correcting one side or the other — from the Lookup Sheet
window, which is the door the sync's own button sits beside.

## Nothing is ever deleted by a sync

An asset this register holds and the external system's list does not carry is
**reported and left**. There is no configuration that makes it a delete.

A Transaction records the identifiers as they were at the time and references no
asset id (024). So the row in `assets` is not a foreign key that a Transaction
would be left dangling from — it is the **only description of the thing that was
moved** that this system has beyond the two identifiers. Deleting an asset
because a remote system stopped listing it would take the Asset Type and the
Model of every movement already recorded against it, and it would do so on the
strength of an absence: a filtered API call, a paginated answer whose second
page never arrived, a remote system mid-migration, a wrong path typed into this
window. **An absence is the single least trustworthy thing a remote system can
tell you**, because every failure mode of the connection looks exactly like one.

`_delete_asset` stays what it has been since 024: something an Admin does at the
console, one asset at a time, having looked.

## Identity is the identifiers, never a remote id

Matching is on Asset Number and Serial Number, folded for case the way 025 folds
them. The external system's own primary key is not stored and not consulted.

There is no column for one and adding one would be a **second identity** for a
thing rule 3 says has exactly two. Worse, it would be an identity this system
cannot verify: an Asset Number is printed on a label somebody scans, and a
remote id is a number in a database nobody here can see. The first time the
external system is rebuilt, restored or migrated, every remote id changes and
every asset here is suddenly new — while the labels on the hardware have not
moved at all.

What this costs is that a remote system which re-cuts its own identifiers looks
like additions and absences, which is exactly what it is from this side. That
is the honest reading, and nothing is deleted over it.

## And the credential is the second replayable secret

ADR-0013 said that the moment a second replayable secret appeared was the moment
to decide whether one file and one pair of helpers becomes a store. It has
appeared: a bearer token or a basic-auth password for the external system is
replayed on every run, exactly as the SMTP password is replayed on every send.

**It does not become a store.** It becomes one pair of helpers — `_secret_set`
and `_secret_get`, which take the path — and a **file per secret**:
`sync_secret.dat` beside `smtp_secret.dat`. DPAPI at machine scope, refused
rather than written in plaintext, for every reason ADR-0013 gives and with
nothing added to them.

A file each rather than a map in one file because the two secrets are unrelated
and have different lifetimes: the mail relay is set once and forgotten, and the
external system's token is rotated on whatever schedule that system's owners
keep. Clearing one must not be able to take the other with it, a corrupt file
must cost one feature rather than both, and `_smtp_secret_*` naming
`SMTP_SECRET_PATH` and nothing else is a property `tools/server-checks.py`
already asserts — one that survives this change unaltered, which it would not
if both values moved into one blob.

The generic pair exists so that the DPAPI calls, the machine-scope flag and the
refusal are written **once**. A second hand-copied `CryptProtectData` is the
shape of defect rule 10 exists to prevent, and a security primitive is the worst
thing in this repo to hold two copies of.

One thing is added rather than copied: **a credential is never sent over a plain
`http://` base URL**. The refusal names it instead of sending it with a warning
beside it. A token crossing an internal network in clear is not something a
warning undoes, and an internal network is precisely where somebody assumes
otherwise.

## What was rejected

- **A `last_sync` key in `server_config.json`, or a column beside each asset.**
  The run's outcome is derived from the `sync.finished` and `sync.failed` rows
  the run already wrote, the way `client_commands` derives `queued` and
  `collected` from two dates. A stored status is a second copy of what those
  rows say, and it is the copy that goes stale when a run dies between writing
  the row and updating the key.
- **A "trust the external system" switch.** It would be one checkbox and the
  argument above would stop applying the moment anybody ticked it. If the
  external system ever *is* authoritative for a field, that is a decision to
  make in a ticket, per field, with somebody's name on it.
- **Write-back.** Out of scope in 032 by name, and it is a different argument
  entirely: it asks which system is authoritative, and everything above is an
  answer to "neither, within its own half".
- **`requests`.** `server.py` imports no HTTP client and
  `requirements-server.txt` feeds a vendored `lib` pinned to one Python minor
  version (rule 13). The standard library answers this.
- **Relaxing TLS verification for the external system.** Rule 1 is worded for
  the clients, but this would be the first place in this repo to turn
  verification off, and a self-signed CMDB is a thing to fix on the CMDB.

## Consequences

- A sync can only ever grow the register or leave it alone. The worst a
  misconfigured one does is add assets that should not be there, which an Admin
  removes from the Lookup Sheet window one at a time, having looked.
- Every run is visible as System Log rows — `sync.started`, `sync.added`,
  `sync.conflict`, `sync.failed`, and `sync.finished` for the console — so
  mailing a run is a Notification Rule (031) rather than mail code in the sync.
- A conflict is permanent until somebody settles it: every run will report it
  again. That is the intended shape. A disagreement that stops being reported is
  a disagreement nobody will fix.
- Two records of one payload claiming one identifier are refused as a **pair**.
  Taking the first would be this code deciding which of two descriptions of one
  asset is real, which is the answer 027 already refuses to give a spreadsheet
  that collides with itself.

## When to revisit

If a **third** replayable secret appears, the per-file shape stops paying for
itself and the store question is worth asking properly. And if the external
system ever becomes the place assets are actually created — rather than a second
record of them — then "the register is authoritative" is the thing to revisit,
not the delete rule, which would still be wrong.
