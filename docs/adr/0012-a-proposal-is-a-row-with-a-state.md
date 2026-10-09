---
status: accepted
---

# A proposal is a row with a state, not a mail and not a trusted write

An asset the Lookup Sheet does not hold cannot be transacted at all (rule 6),
and the Lookup Sheet is changed only by the Admin at the Asset Server console,
with the admin password (rule 11). The Storekeeper is the person standing where
new hardware physically arrives, unpacking a box against a delivery note, and
their only move before 028 was to stop, find an Admin and wait.

That is precisely the situation that makes somebody want a way past rule 6 -
and the ways past it that suggest themselves are all worse than the wait.

## The decision

The Storekeeper records what they are holding as a **proposal**: a row in
`asset_proposals` carrying the four fields an asset has, who proposed it and
when, and a `status` of `pending`, `approved` or `rejected`. It becomes an
asset when an Admin approves it at the console, through `_save_asset` - the
same one writer a hand-typed asset goes through.

**Where that decision is made is two doors and one window** - three since
#173, the third being the Notifier's Remote Admin Asset Proposals panel over
`POST /assets/proposals/decide`, which is not a fourth decision path either:
it forwards to the same `_decide_proposal`. The Lookup Sheet
window's footer, because approving one writes the Lookup Sheet and that is the
window an Admin already thinking about assets is in; and Server Administration
since A10, whose entry carries the number still waiting. The second is not a
second decision path - both open `asset_proposals`, whose console entry asks
for the admin password on every open (096) and which writes through
`_decide_proposal` either way -
it is a way of being told there is something to answer. The first door alone
is three clicks deep, and a proposal nobody looks at is the stop this ADR
exists to remove, reached by a longer route.

A proposal is **not an asset**. It is not in `assets`, `GET /lookup` does not
find it, `GET /asset_types` does not serve its type, and `_create_transaction`
refuses a movement against it exactly as before. That is the whole of what
makes the rest of this safe.

## Why `POST /assets/propose` is unauthenticated

For the reason ADR-0002 gives for the Transaction endpoints: a Client holds no
credential, and inventing one for this endpoint alone would mean a secret on
the Storekeeper's machine that opens a door into the register - which is a
worse thing to have on that machine than the ability to ask a question.

What makes it safe here is narrower and stronger than the argument ADR-0002
makes. An unauthenticated `POST /transactions` can record a movement that never
happened; an unauthenticated `POST /assets/propose` can only **ask**. Nothing a
caller on the network can put in this table changes what any client is offered,
what any lookup answers, or what any Transaction is allowed to be recorded
against. The worst a flood of nonsense proposals achieves is a list an Admin
has to reject, which is visible, attributed and reversible - and every row of
it is a System Log entry naming the source address the server saw.

The register keeps being changed by exactly **one credential**. That is the
property rule 6 rests on, and this feature does not spend it.

## What was rejected

**Letting the Storekeeper write the register directly**, with the admin
password entered at that machine. This is the obvious shortcut and it ends rule
11: the admin password would then live wherever the store is, be typed in front
of whoever is standing there, and open Clear All Records and the capability
passwords with it. ADR-0007 already refused this shape for installs.

**A capability password for it.** A capability opens one console action and
reaches no endpoint (ADR-0006). Whoever could approve an asset could add one,
and an added asset is transactable - so this would be the admin password with
an extra step, which is the exact thing ADR-0006 says a capability must not be.

**That refusal was against ADR-0006's shape and #173 reverses it under
ADR-0015's** - which supersedes ADR-0006 and is the reason the answer changes
rather than the reasoning being abandoned. A capability password is no longer a
console credential that opens a control beside the admin password on the same
machine; it is what an Admin administers this server *remotely* with, over
HTTPS only. So the objection above - the admin password with an extra step,
sitting at the console next to the doors it is not allowed to open - is about a
thing that no longer exists. What `POST /assets/proposals/decide` delegates is
the act, not the console: the **Server Settings** capability answers a proposal
from somewhere other than the server room, `_decide_proposal` and `_save_asset`
are unchanged and are still the one path, and a delegate's decision is
attributed to the delegate rather than to the Admin. The half of the objection
that still holds is the half that did not move: **replacing** the sheet is not
delegable and is not delegated (rule 11), because approving one asset in answer
to a question and overwriting every asset this server holds are not the same
size of act.

**Mailing the Admin instead of storing a row.** A mail is not a state: it
cannot be listed, cannot say whether it was answered, and cannot stop the same
asset being proposed every week. 031 will mail the Admin *that a proposal is
waiting* - a notification about a row, which is the right order of the two.

**A pending proposal in the `assets` table with a flag.** Every predicate that
reads that table - `_load_lookup_table`, `GET /asset_types`, rule 6's check,
the Lookup Sheet window, the exporter - would have to learn to skip a row, and
the one that forgot would be the one that made an unapproved asset
transactable. The same argument the Manage Users window makes about not
inventing a `team_members` row for the Admin and the Storekeeper.

**Deleting a rejected proposal.** ADR-0003's argument, one table over: the
Storekeeper is owed the answer, and "this serial was refused last month, for
this reason" is the record that stops it being proposed weekly. A rejection
carries who decided it, when, and why, and the row is kept. There is no delete
in this feature at all.

## What a stored `status` costs, and why it is stored anyway

`client_commands` deliberately has **no** status column - `queued`, `collected`
and `expired` are derived from two dates, because a stored copy of what the
dates already say is the copy that goes stale (ADR-0005's table).

This is not that case. A rejection is a decision somebody made and a reason
they gave; there is nothing else on the row that says it, and no pair of dates
it can be computed from. `decided_at` alone cannot tell approved from rejected.
So the state is stored, and the two rules together are the actual rule: derive
a state that is a function of facts you already hold, store one that is not.

## Consequences

- The Storekeeper gains an answer to "this box is not in the system" that is
  not "go and find somebody", and the Admin gains a list to work through rather
  than an interruption.
- Approval is a second door to `_save_asset` rather than a second way of
  writing an asset, so 025's uniqueness rule applies to it untouched - an
  approval racing an identifier that reached the register while the proposal
  waited is refused, and the proposal stays pending, which is what it is.
- A proposal made with no server is **refused, not buffered**. A Transaction is
  buffered because the movement already happened and the record is owed; a
  proposal is a question, and a queued question is one the Storekeeper believes
  was asked.
- 029 imports a file as proposals, which is this state applied to 027's helpers,
  and 031 mails the Admin that one is waiting. Both rest on the row existing.
