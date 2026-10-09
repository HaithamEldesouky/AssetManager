---
status: accepted
---

# A Cancelled Transaction is kept, not deleted

When a Transaction records a movement that never happened — the Storekeeper
scanned the wrong barcode, or logged an Out Store against the wrong Engineer —
the Transaction is marked **Cancelled** and stays in the table, carrying who
cancelled it, when, and why. It is not deleted.

## The alternative that was rejected

`POST /transactions/delete` already exists and already removes rows. It would
have needed no new column, no migration, and no changes to the eight places that
define Pending or Confirmed.

It was rejected because deleting the row destroys the only evidence that
anything was ever recorded. Afterwards there is no way to answer "was this asset
ever logged out to Brian Dawson?" — the answer looks identical whether it never happened
or happened and was undone. The Storekeeper's own mistake becomes unauditable at
exactly the moment somebody would want to audit it, and the Engineer who saw a
Notifier popup for it has no way to reconcile that memory with the history.

The delete path also requires the admin password, which makes correcting a
mis-scan slower than making one. In practice that means the mis-scan gets left
in place and confirmed, which is the outcome this feature exists to avoid.

## Cancelled is not Rejected

These are two different facts and are never merged:

- **Rejected** — the Engineer denies a movement recorded against them. The
  reason is the Engineer's.
- **Cancelled** — whoever recorded the Transaction says the movement never
  happened. The reason is the recorder's.

The difference is who says so, and recording who says so is what this system is
for. So they are separate columns, and a row can carry either. A Rejected
Transaction is refused for Cancellation: the Engineer has already answered it,
and that answer is the record.

## What being a state costs

Every predicate that means Pending or Confirmed has to exclude Cancelled, and
there were eight of them at the time this landed. The one that matters most is
Auto-Accept: a Cancelled Transaction left in that query confirms itself twenty
four hours later, and that defect is invisible while anyone is still looking at
the change that caused it. `tools/server-checks.py` covers each exclusion for
that reason.

The list endpoints pay the other cost. `GET /export` and `GET /transactions`
omit Cancelled Transactions unless the caller passes `include_cancelled`, and
the default is off because every client works out Pending as
neither-confirmed-nor-rejected from those responses. A Storekeeper built before
cancelling existed would otherwise show every Cancelled Transaction as Pending
for ever.

## Only the newest Transaction for an asset

The same newest-per-asset rule Out Now runs on. Cancelling an older Transaction
would leave the history asserting a return that preceded no departure. "Newest"
means newest **not already cancelled**, since a Cancelled Transaction never
happened — so repeated Cancellations unwind an asset's history one row at a
time, each needing its own reason.

## Who may Cancel

A **Pending** Transaction needs no password. Correcting a mis-scan has to be as
quick as making one, and ADR-0002 already leaves the transaction endpoints
unauthenticated, so requiring one here would buy nothing while making the wrong
outcome (leave the mis-scan in, let it confirm) the cheaper one.

A **Confirmed** Transaction needs the admin password. Once the Engineer has
Confirmed, they and the Storekeeper are asserting different things about the
physical world, and that disagreement is the one thing this system exists to
record. Clearing it should not be one person's button. This path is not optional
polish either: an Auto-Approve Engineer's Transactions are Confirmed the instant
they are recorded and are never Pending, so without it a mis-scan against one of
them cannot be retracted at all.

The **Manage Transaction History capability password** opens everything the
admin password opens here, over HTTPS (#169, ADR-0015). It was outside the
capability set for as long as the argument above was about the console: Cancel
is enforced in `_cancel_transaction` rather than at the endpoint, so a delegate
reaching it would have been reaching a rule written for a Storekeeper. What
changed is where the Admin is standing. That capability already deletes a row
outright and corrects a Pending one, and a delegate who may do both and may not
retract a Confirmed mis-scan either walks to the console or deletes the row —
which is the sharper version of the argument that put Correct on the network,
since a deletion is the one act whose evidence stops existing.

It is a **credential and not a person**, so what the row and the System Log
record is the credential: `cancelled_by` in the body is ignored on that path
rather than allowed to put a name in front of a delegated act. The transport
gate is the capability password's own (ADR-0015) and not this endpoint's — the
admin password is accepted here over plain HTTP exactly as it always was, that
being the default deployment (rule 1) and the path the Storekeeper's own Cancel
pill takes. Which of the two arrived is therefore examined before the transport
is judged, which is the one ordering exception ADR-0015 carries.

A wrong password is refused outright rather than falling back to the
unauthenticated path. Falling back would mean a typo silently downgrades an
admin to a Storekeeper and produces a refusal that names the wrong reason.

## The Storekeeper switch

`storekeeper_can_cancel` in `server_config.json` turns the unauthenticated path
off entirely, for a department where retraction should go through the Admin. Its
**absence means allowed**, so nothing already deployed changes behaviour.

It is published on `GET /health`, the heartbeat every Client already polls, so a
Client can hide its Cancel control rather than offer one that only ever fails.
That is a courtesy, not the control: it is **enforced at the endpoint regardless
of what any client shows**, because a client is a file on somebody's laptop and
an older one does not know the field exists. The admin password overrides the
switch — otherwise turning it off would lock the Admin out of the one path only
they have.

Authorisation lives in the same function as the newest-per-asset rule rather
than at the endpoint, because the Server GUI calls that function directly. A
check written at the endpoint would hold for a curl and not for the window an
admin actually uses. The capability password is the one credential checked at
the endpoint, and for a reason that cannot move: whether it may be accepted at
all is a question about the **transport**, which no helper can see. What
reaches the rule is the answer — `authorised_as`, the actor to attribute every
entry to — and the rule itself is unmoved: one Cancel, one newest-per-asset
check, one place a row is marked.

## When to revisit

- If Cancelled rows ever accumulate to the point of making the history
  unreadable. The archive-then-delete path in the Server GUI is still there for
  a deliberate purge, and it now carries the cancellation fields with it.
- If a Cancellation ever needs undoing. Nothing un-cancels a Transaction today,
  deliberately: recording the right Transaction afresh is the intended remedy,
  and a Cancelled row no longer blocks one for the same asset.
