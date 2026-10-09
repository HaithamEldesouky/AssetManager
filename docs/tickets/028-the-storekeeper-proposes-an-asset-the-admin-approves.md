# 028 - The Storekeeper proposes an asset; the Admin approves it

**Type:** feature · **Depends on:** 024, 025 · **Needs an ADR**

## The problem

An asset the register does not hold cannot be transacted at all (rule 6), and the register
is changed only by the Admin at the Asset Server console. The Storekeeper is the person
standing where new hardware physically arrives, and their only move today is to stop, find
an admin, and wait - which is precisely the situation that makes somebody want a way past
rule 6.

## What changes

A **proposal**: the Storekeeper records the asset they are holding, and it becomes a real
asset only when an Admin says so.

```
asset_proposals
  id             INTEGER PRIMARY KEY AUTOINCREMENT
  asset_number   TEXT DEFAULT ''
  serial_number  TEXT DEFAULT ''
  asset_type     TEXT NOT NULL
  asset_model    TEXT DEFAULT ''
  proposed_by    TEXT NOT NULL     -- the Storekeeper's name, as /health gave it
  proposed_at    TEXT NOT NULL
  client_id      TEXT DEFAULT ''
  status         TEXT NOT NULL     -- 'pending', 'approved', 'rejected'
  decided_at     TEXT DEFAULT ''
  decided_by     TEXT DEFAULT ''
  reason         TEXT DEFAULT ''   -- why it was rejected
```

`status` is **stored** here, unlike `client_commands`' derived one, because it is not a
function of two dates: a rejection is a decision somebody made and a reason they gave, and
there is nothing else on the row that says it. A rejected proposal is **kept**, for the
reason ADR-0003 keeps a cancelled Transaction - the Storekeeper is owed the answer, and
"this serial was refused last month" is the record that stops it being proposed weekly.

Migration `010_asset_proposals`, `init_db()` idempotently as well, `down()` keeps the table.

- `POST /assets/propose` - body `{client_id, asset_number, serial_number, asset_type, asset_model}`.
  **No auth**, the same reason ADR-0002 gives for the Transaction endpoints: a Client holds
  no credential. It is safe to leave open for the reason it is safe there - a proposal
  changes nothing until an Admin approves it, which is the whole point of the state. It is
  refused for the shape a proposal must have (an identifier, a type), for a duplicate of
  something already in the register (025's helper, so the Storekeeper is told on the spot),
  and for a duplicate of a proposal already pending.
- `GET /assets/proposals?status=pending` - so the Storekeeper can see what it asked for and
  what came back. Nothing in it is more sensitive than the register it will become.
- Approval has **no endpoint** - the same call Add Transaction, Modify, the Client commands
  and the Lookup Sheet made. The Admin is at the console.

**Storekeeper side:** an **＋ Add Asset** control beside the form, submitting a proposal and
showing the answer, plus the outcome of its own earlier proposals on the 15s tick it
already runs. Approved assets simply start resolving in the lookup field, which is the
answer the Storekeeper actually wanted.

**Server GUI side:** a proposals window reached from the Lookup Sheet, one card per pending
proposal, showing who proposed it and when, with Approve and Reject; a rejection takes a
reason. Every decision takes the **admin password** at the top of that window, checked with
`_admin_password_ok` directly - approving writes the register, which is rule 11's ground.
Approve writes through `_save_asset`, so a proposal and a hand-typed asset cannot mean
different things.

Every proposal, approval and rejection is a System Log entry, attributed the way 011
attributes everything - `<name> (Storekeeper)` on the way in, `Admin (Server GUI)` on the
decision.

## The ADR

Why a proposal is a row with a state rather than a mail to an admin or a direct write the
Storekeeper is trusted with: rule 6 is only worth anything while the register is trusted,
and the register is trusted because one credential changes it.

## Verification

`tools/server-checks.py`: the endpoint's refusals, that an approval writes exactly one
asset through the one writer, that a rejection writes none and keeps the row, that a
proposal duplicating the register is refused on the spot. `tools/client-checks.py`: the
Storekeeper's new window measured like the rest, and its offline path - a proposal made
with no server is **refused**, not buffered, since unlike a Transaction there is nothing
that already happened to record.

## Not in this ticket

Importing a file as a proposal - 029. Mailing the Admin that a proposal is waiting - 031.

## As built

Done as filed, with the migration numbered `011_asset_proposals` - 010 went to
025's asset identity - and ADR-0012 written for the argument the ticket asked
for. Four decisions the ticket left open, and one deliberate deviation.

- **The deviation: the Server GUI shows a table, not a card per proposal.** The
  facts on a proposal are the four an asset has plus who asked and when, which
  is a row, and this window opens from the Lookup Sheet window, which lists the
  same four in the same order (rule 4). What a card would buy is room for the
  rejection reason, and that is the one thing here that is written rather than
  read - it is asked for in its own prompt when Reject is pressed. Manage Users
  has cards because an Engineer carries a profile, a password state and a tick;
  a proposal carries none of those.
- **The refusals carry codes, through one small `_AssetRefused`.** Every other
  refusal on the wire here has a `code`, and a Storekeeper has to tell
  `duplicate_identifier` - the asset exists and can be transacted **now**, which
  is the answer they wanted - from `already_proposed`, where somebody has asked
  and the answer is coming. The exception is a `ValueError` subclass, so the
  windows show `str(...)` as they already do and nothing at the console had to
  learn a new shape.
- **An approval racing the register leaves the proposal pending.**
  `_decide_proposal` writes through `_save_asset` and does **not** catch its
  refusal, so an identifier that reached the register while the proposal waited
  refuses in 025's own words and the row stays in the state it is actually in.
  Approving it over an asset it did not write would be the lie.
- **A rejected proposal blocks nothing.** The identifiers are `COLLATE NOCASE`
  so a proposal differing only in case is the same proposal, but there is no
  unique index: the hardware may have turned up after all, and re-proposing it
  is how the Storekeeper says so. Only a **pending** proposal collides.
- **The Storekeeper offers it where the refusal happens.** ＋ Propose this asset
  is packed onto the lookup verdict line only while that line is saying the
  server will refuse what was typed, and unpacked the moment something
  resolves - a standing offer beside an asset that resolved perfectly well is
  an invitation to propose a duplicate. The Tools tab carries the same dialog
  for an asset that is not in front of the form.

`seen_proposals.json` beside that app is the one new file: the same shape as
`seen_rejections.json`, for the same reason - an answer arrives whenever the
Admin gets to it, routinely after the app has been closed and reopened.

## Verified

- `tools/server-checks.py` (124 groups), `tools/cascade-audit.py` (no drift) and
  `tools/client-checks.py` (12 groups) all exit 0.
- The real Server GUI window, driven end to end: the Lookup Sheet footer opens
  it, two pending proposals are listed with who proposed them and when, a
  decision with no admin password is refused on the window, an approval writes
  the asset and clears the row, a rejection keeps the row with the reason and
  its `decided_by`, and the table is left empty with the count reading what was
  decided.
- The endpoints through Flask's test client: every refusal and its code, the
  pending listing, an unknown status refused, and a proposal that is visibly not
  an asset - `GET /lookup` does not find it while it waits.

## Not done here

Mailing the Admin that a proposal is waiting stays 031's, and importing a file
as proposals stays 029's, as filed.
