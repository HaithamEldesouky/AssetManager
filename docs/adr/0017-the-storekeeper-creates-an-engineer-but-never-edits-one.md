---
status: accepted
---

# The Storekeeper creates an Engineer but never edits one

A Transaction is recorded against an Engineer by name, and `POST /transactions`
takes no credential at all (ADR-0002) because the Storekeeper's client holds
none and the movement has already happened. The one thing that client could not
do was name somebody the list did not already hold: a new starter arrives, the
store has their laptop in its hands, and the Add New Engineer dialog asked for
the admin password - the same password that opens Clear All Records.

That is ADR-0007's argument one door further on. An installation asks for the
credential that fits it, and the credential that fitted this door fitted every
other door on the server as well. The practical answer was that the store held
the admin password, which is the outcome ADR-0007 exists to prevent, or that
the Storekeeper waited for an Admin while somebody's laptop sat unrecorded.

## Decision

Creating an Engineer is delegated to the Storekeeper by default. Editing one is
not, and never becomes so.

`POST /members` takes a **create-only unauthenticated path**: a body carrying no
`password` key at all. It is gated by `storekeeper_can_add_engineer` in
`server_config.json`, which has `storekeeper_can_cancel`'s shape and its
behaviour - read from disk on every request, so withdrawing it takes effect on
the next request rather than the next restart; absent meaning allowed, so a file
written before the key is normal rather than corrupt; toggled at the console
with the admin password in **both** directions, switching it back on being as
much a change as switching it off; and carried on `GET /health`, so the client
hides the control rather than offering one the server will refuse.

Three things bound that path, and each is a different rule:

- **The switch** says whether it is open at all.
- **A name that already exists is refused** (`already_exists`, 409). An update
  is an edit. Without this, "create" would reach every field on an Engineer who
  is already on the list, which is the whole of what is being withheld. The name
  is matched `COLLATE NOCASE`, so a second spelling of somebody already here is
  the same refusal.
- **A `profile`, a `permissions` list or a `member_password` sent without a
  password is refused outright** (`create_only`, 403) rather than ignored. The
  row is created on the Default profile with no credential of any kind, and
  silently dropping a field the caller sent would let them believe it applied.

A wrong password never falls back to this path: `password: ""` is an attempt at
the admin path and is refused as wrong. That is `_cancel_transaction`'s
convention exactly, and for its reason - a typo that silently downgraded an
Admin would produce a refusal naming the wrong reason.

The act is attributed to `<name> (Storekeeper)` in the System Log, through
`_storekeeper_actor`, the same label a Transaction and a cancel from that client
carry. An Admin reading the log sees who added the row.

## What this actually hands over

The ability to **create a name that Transactions are then recorded against** -
and a Transaction against that name already needs no credential. So what the
delegation buys is that the store stops waiting; what it costs is a row in
`team_members` that somebody at the store chose, which an Admin can see, rename
(ADR-0016) or delete.

**Auto-Approve stays the one flag settable here.** It is neither a permission
nor a credential: it says this Engineer has no Notifier, so nothing will ever be
asked to confirm for them. It is also the one fact the person adding the
Engineer knows at that moment, standing where those Transactions are recorded.

What stays at the console, behind the admin password, is everything that is
**about** an Engineer rather than the fact of one: the name (a rename rewrites
their history, ADR-0016), the Access Profile and the permissions (what that
Engineer's own client shows them), the Own Password (a credential somebody can
then *be* that Engineer with, ADR-0009), and deleting the row (which takes the
Own Password with it). 013 moved all of those out of this client; this does not
move them back.

**#171 moves where an Admin may stand, and nothing else.** Those same acts are
reachable over the network on the **Server Settings** capability password
(ADR-0015), through the Notifier's Remote Admin window - which is not this
client, is not a credential the store is handed, and is still not the admin
password typed into a client (rule 7). The create-only path is untouched and is
asserted as untouched: a body with no `password` key is still that path, still
refuses a `profile`, a `permissions` list or a `member_password`, and is still
accepted over plain HTTP, there being no credential on it for a transport rule
to protect.

## What was rejected

**A capability password on it.** A capability password is what an Admin
administers this server *remotely* with (ADR-0015) - since #171 that does reach
these endpoints, but from an Admin's machine rather than from this client, and
a password the store would have to be handed and would then keep is the thing
ADR-0007 is about. A switch an Admin flips once is a smaller object than a
fourth credential in circulation.

**Missing key means denied.** The safer default, and the less consistent one:
`storekeeper_can_cancel` beside it reads a missing key as allowed, and two
switches of one shape answering an absent key two different ways is exactly the
kind of fact that gets remembered wrong. The behaviour before this key existed
was that the Storekeeper could add an Engineer - with a password it had to be
given - so allowed is also the honest reading of what a file that predates the
key was describing.

**Create-and-edit, with the profile fields simply ignored.** Ignoring a field a
caller sent is how an Admin comes to believe a permission was granted. The
refusal names where those fields are set instead.

**A second endpoint.** `POST /members/create` would be a second door to
`_save_member` with its own rules to keep in step - the thing rule 10 exists to
prevent. One enforcement point, with the credential deciding which of its two
paths was taken, is the shape `_cancel_transaction` already has.
