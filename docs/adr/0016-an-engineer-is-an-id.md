---
status: accepted
---

# An Engineer is an id, and their name is a label that can change

`team_members.name` was the primary key. Everything about an Engineer hung off
their name: their Own Password, their Access Profile, their permissions, their
Auto-Approve flag, and — by spelling rather than by reference — every
Transaction recorded against them and every Client installation configured as
them.

That made a rename a **delete and an insert**. An Admin correcting a misspelt
name would have stood up a second Engineer and thrown the first one away, Own
Password and profile with it, so the safe thing to do about a wrong name was to
leave it wrong. Migration `012_member_identity` gives the row an
`id INTEGER PRIMARY KEY AUTOINCREMENT` and demotes `name` to
`TEXT UNIQUE COLLATE NOCASE`, which makes a rename an `UPDATE`.

## What the name still is

A label, and one that is still unique and still case-insensitive. Migration
`008_member_name_nocase`'s whole argument survives — a person typed in a
different case is the same person, every `WHERE name=?` in `server.py` still
matches without regard to case, and `_save_member`'s `ON CONFLICT(name)` still
fires, on the constraint now rather than on the key. Every endpoint still
answers by name. What changed is only that the name is no longer the *identity*.

## What a rename rewrites

`transactions.team_member` and `clients.member`. Both hold a spelling rather
than a key, and both are rewritten by `_rename_member` in the same transaction
as the row itself.

That looks like a contradiction of the rule that a Transaction records the
identifiers as they were at the time, and it is not the same case. An asset
identifier records *what was scanned*, and correcting it later would be
rewriting an observation. A `team_member` records *who* — one person, whose name
is what this migration exists to let an Admin fix — and every one of those rows
is about that person. An Engineer whose past movements are filed under a name
they no longer have has had their history cut in half, at exactly the moment
somebody is reconstructing a dispute.

## What a rename never rewrites

**`system_log`.** It records what was done, by whom, at the time. An audit trail
edited to agree with a later decision is not an audit trail, and the one thing
this table is for is being the record when the others disagree. The rename is
recorded *as an act* instead: `member.renamed`, at `warn`, naming the id and
both spellings.

## The Notifier must not go deaf

This is the sharpest consequence and the reason the ticket is more than a
migration. A Notifier holds its Engineer's **name** in `config.json`. After a
rename that name resolves to nobody, `GET /pending/<name>` answers with an
empty list, and an empty list is indistinguishable from having nothing to
confirm. The engineer is never told; they simply stop being asked, and the
24-hour Auto-Accept resolves everything with nobody looking. That is the one
failure the Notifier exists to prevent.

Two answers, deliberately, because one of them expires and the other one costs
a poll interval:

- **The check-in carries the id.** `POST /clients/checkin` takes a `member_id`
  and answers with `member_id` and the Engineer's **current** `member` name.
  `common._adopt_member` writes both into the config and the Notifier takes the
  new name back into memory on the same tick. This is the fix that does not
  expire; what it costs is up to one poll interval of asking under the old
  name.
- **`GET /pending/<name>` resolves a former name.** Only where the first answer
  was empty, so a name nobody has renamed costs nothing. The former name is
  read out of the `member.renamed` entries rather than out of a table of former
  names: the log already holds both spellings and the id, and a second copy of
  a fact is what the cascade rule exists to prevent. What *that* costs is the
  log's own retention — a Notifier that has not run since the rename fell out
  of the log has no former name left to be found by, which is bounded by how
  long a laptop can be switched off rather than by how long ago somebody was
  renamed, and is why it is the second answer rather than the only one.

**An id that names a different living Engineer loses to the name.** A
renamed-away name names nobody, so a name that still names somebody beside an
id that names somebody else is not a rename — it is an id from another database,
one restored from a backup taken before these were handed out. Following it
would silently re-point a Notifier at a different Engineer, which is worse than
it going deaf, so the name wins there.

## Wire shape

Additive only. `id` appears beside `name` on `GET /members` and on
`_save_member`'s answer; `member_id` and `member` appear on the check-in's.
A client built before any of them reads the keys it knows and behaves exactly
as it did, which is what lets the server go first in a rollout.

## What was rejected

**A `member_former_names` table.** It would be a second copy of what
`member.renamed` already says, with no retention bound of its own and nothing
holding the two in step — the copy that goes stale. The log's retention is a
real limit and is written down rather than engineered around, the check-in
being the answer that does not expire.

**Renaming by name — `POST /members` taking a `new_name`.** A rename addressed
by the thing being renamed is ambiguous the moment two of them are in flight,
and it would put the rename in the same helper as every other edit, where an
older client sending a name it read a minute ago would rename somebody by
accident. `_rename_member` takes the id.

**An endpoint for it.** There was deliberately none: the Admin at this console
was the only actor, the same call Add Transaction, Modify, the Client commands
and the Lookup Sheet made. **#171 reverses that**, and what changed is where the
Admin is standing rather than the rule - the same thing that changed for Modify
at R1. `POST /members/rename` takes the admin password or the **Server Settings**
capability password over HTTPS (ADR-0015) and forwards to `_rename_member`, so
everything above holds on the wire exactly as it holds at the console: the id is
the key, `transactions.team_member` and `clients.member` move in the same
transaction, `system_log` never does, and the act is recorded as
`member.renamed` naming both spellings. The rejection beside this one stands
untouched and is what makes that safe - the endpoint is addressed **by id**, so
a caller holding a spelling it read a minute ago cannot rename somebody by
accident.

**Rewriting `system_log` too, for consistency.** Consistency between the record
of what happened and the record of what is true now is not a property worth
having — they answer different questions, and one of them is only worth reading
because it is not edited.

## When to revisit

- If an Engineer ever needs two names at once — a display name and a login. Then
  the label splits and this decision is the floor it splits from, not the thing
  in the way.
- If a Transaction ever needs to point at the Engineer by id. It does not today:
  the name is what an export, a workbook and a dispute are read in, and a join
  for every row would buy nothing an Admin can see. If it ever does, the rewrite
  above stops being needed and becomes a migration.
- If renames become common enough that the log's retention is what a Notifier
  actually hits. Then the former-name answer needs somewhere durable to live,
  and this is the paragraph that says so in advance.
