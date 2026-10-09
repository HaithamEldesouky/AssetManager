# Database

## Database Schema

Table `transactions`:

```
id               INTEGER PRIMARY KEY AUTOINCREMENT
asset_type       TEXT NOT NULL
serial_number    TEXT DEFAULT ''
asset_number     TEXT DEFAULT ''
asset_model      TEXT DEFAULT ''  -- from the lookup sheet's 4th column, '' when N/A
team_member      TEXT NOT NULL
direction        TEXT NOT NULL    -- 'Out Store' or 'In Store'
timestamp        TEXT NOT NULL    -- ISO format
confirmed        INTEGER DEFAULT 0
rejected         INTEGER DEFAULT 0
confirmed_at     TEXT DEFAULT ''
rejection_reason TEXT DEFAULT ''
notes            TEXT DEFAULT ''
storekeeper      TEXT DEFAULT 'Storekeeper User'
cancelled        INTEGER DEFAULT 0   -- 1 = the movement never happened, retracted
cancelled_at     TEXT DEFAULT ''
cancelled_by     TEXT DEFAULT ''
cancel_reason    TEXT DEFAULT ''
auto_approved    INTEGER DEFAULT 0   -- 1 = Confirmed at creation, nobody was asked
origin           TEXT                -- 'desktop' | 'auto', NULL = decided before this existed
```

`init_db()` runs `ALTER TABLE` if older databases are missing `rejection_reason`, `asset_number`, `asset_model`, the four cancel columns, `auto_approved` or `origin` — preserve this auto-migration logic when touching the schema.

**`auto_approved` is which kind of Confirmed a row is** (#198). An Engineer who
answered a popup and an Auto-Approve Engineer who was never asked leave the same
`confirmed=1` behind, and the cancel window below may open one and must never
open the other: a confirmation is the evidence the verification step produces.
It is **stored rather than derived**, which is the other side of the rule
`client_commands` states — derive a state that is a function of what you already
hold, store one that is not — because neither of the two ways of working it out
afterwards holds. `team_members.auto_approve` answers about the Engineer **as
they are now**, so an Admin ticking that box an hour from now would make every
row that Engineer really confirmed start reading as auto-approved and open the
window over their confirmation; and the `transaction.created` entry in
`system_log` already says `(auto-approved)`, but `POST /clients/log` is
unauthenticated (ADR-0002, ADR-0005), so a caller on the network could write that
sentence about a row an Engineer really answered. So it is written by
`_create_transaction`, the one writer of a Transaction, at the moment the row is
written, from the same `auto_approve` the `confirmed` and `confirmed_at` beside
it come from. Every row that already exists reads 0, which fails closed. The
clock the window is measured from needs no column of its own: for an
auto-approved row `confirmed_at` **is** the creation instant, where `timestamp`
is the movement's own time and may be backdated by an admin. Migration
`014_transaction_auto_approved` adds it and `init_db()` adds it idempotently as
well, and **a downgrade keeps it**.

**`origin` is where a decided Transaction's answer came from** (#282):
`desktop` or `auto`. The Asset Server decides it from the route the
answer came through and never reads it from a request body: `POST /confirm/<id>`
and `POST /reject/<id>` write `desktop`, `_create_transaction` writes `auto` for
an Auto-Approve Engineer, and `_auto_accept_pass` writes `auto` for each row it
Auto-Accepts. A Pending
row has no Origin (NULL). **NULL also means "decided before Origin existed"** and
shows no label: the backfill sets `auto` where `auto_approved = 1` and nothing
else, because the Auto-Accept pass left no mark on the rows it confirmed, so
`desktop` is never guessed for an old row. Migration `017_transaction_origin`
adds the column and runs that backfill, `init_db()` adds it idempotently as well
(with the same backfill when it is the one that adds it), and **a downgrade keeps
it**.

**Cancelled is not Rejected.** Rejected is the Engineer denying a movement
recorded against them; Cancelled is whoever recorded it saying the movement never
happened. Both carry a reason and the two reasons belong to different people, so
they are separate columns and one row can hold either. Migration
`003_transaction_cancel` adds the four and `init_db()` adds them idempotently as
well. **Every predicate that means Pending or Confirmed must exclude
`cancelled`** — there were eight when this landed, and the one that matters is
Auto-Accept: a Cancelled Transaction left in that query confirms itself a day
later, with nobody watching the change that caused it. See ADR-0003 for why this
is a state rather than a delete.

Table `assets` (the Lookup Sheet, since 024):

```
id            INTEGER PRIMARY KEY AUTOINCREMENT
asset_number  TEXT DEFAULT '' COLLATE NOCASE   -- unique where non-empty
serial_number TEXT DEFAULT '' COLLATE NOCASE   -- unique where non-empty
asset_type    TEXT NOT NULL    -- what GET /asset_types serves (rule 2)
asset_model   TEXT DEFAULT ''  -- '' where the sheet said N/A
created_at    TEXT NOT NULL
created_by    TEXT DEFAULT ''  -- 'asset_lookup.xlsx' for a seeded row, else who wrote it
updated_at    TEXT DEFAULT ''  -- '' until the asset is corrected
```

The assets lived in `asset_lookup.xlsx` until 024 moved them here; ADR-0011
says why, and the short version is that the workbook was read on every
`_load_lookup_table()` call and written by rewriting the whole file, so
correcting one asset rewrote every row beside it. The workbook is still the
**interchange format** — `GET /lookup/file` writes one out of this table and
`POST /lookup/upload` replaces every row from one — and it is still what ships
embedded in the exe as the list a brand-new install starts from.

**There is one writer, `_save_asset`**, the way `_create_transaction` is the
one writer of a Transaction: the Lookup Sheet window and the upload endpoint
both go through it, and it is where an asset is held to having an Asset Type
and both identifiers, the Asset Number digits only - `_asset_shape_error`, which
the proposal, import and sync doors ask as well (103). `_delete_asset` is the one remover. The table is
keyed on `id` rather than on an identifier, so correcting a mistyped Asset
Number is an update rather than a delete and an insert.

**An identifier names one asset** (025), which is two partial unique indexes
and a refusal in that one writer:

```
idx_assets_number  UNIQUE (asset_number)   WHERE asset_number  <> ''
idx_assets_serial  UNIQUE (serial_number)  WHERE serial_number <> ''
```

**Partial**, because an empty identifier is not an identifier: an asset may
carry only a serial where it was written before 103, and two of those are not a collision.
**`COLLATE NOCASE`**, because `_load_lookup_table()` has always keyed the sheet
on both identifiers lowercased — `AM-1` and `am-1` were already one entry there
and two rows in the table, and the second silently shadowed the first. The
**stored spelling is the one that was typed**, exactly as it is for an
Engineer's name; what stops being significant is only whether two spellings
differ by case, and `NOCASE` folds ASCII only. The indexes are the backstop;
`_save_asset` is what turns the constraint into a sentence naming the asset in
the way, so every caller can report it rather than say "failed" — the Lookup
Sheet window shows those words rather than computing its own, and
`POST /lookup/upload` names the row of the sheet it was found at. That refusal
lived in the window alone until 025, and the upload endpoint walked straight
past it.

The `id` is **not** on the wire and no Transaction references it: a Transaction
records the identifiers as they were at the time, so removing an asset leaves
every Transaction already recorded against it untouched and only stops it being
transacted again (rule 6).

Migration `010_asset_identity` adds the collation and the two indexes.
**A database already holding two rows for one identifier is the normal case,
not the exception** — 6 of the shipped sheet's 3462 rows share a Serial Number
with another row, each pair carrying two distinct Asset Numbers — so a blanket
refusal would have meant no install could start and no existing install could
upgrade, over a manufacturer's number that identified nothing to begin with.
A value that names two assets **names neither**, so it is **cleared from all but
the lowest id**: both assets are kept, each still carrying its other identifier
(rule 5's shape is what makes that an asset still), and one deterministic answer
is left for whoever scans it. `assets.ambiguous_identifier` in the System Log
says which, because an Admin looking for an asset by a serial that has stopped
answering needs to find that line.

What it will **not** do is clear an identifier off a row that has no other one:
that row would stop being an asset, and which of two rows describing one asset
is the real one is not a decision a migration gets to make. Over those the
migration **refuses**, naming them. `init_db()` meets the same database and
**warns and starts**, logging `assets.duplicate_identifier`: it runs on every
boot, and a store that cannot record a movement today because of a duplicate
created months ago is the worse failure — the same split `_resolve_asset_identity`
is called from both sides of. The seed applies the rule row by row as it reads
the sheet in, for the same reason: an `IntegrityError` on the first `init_db()`
of a fresh install is a server that never starts. A downgrade drops the indexes
and puts the byte-matching back, keeping every row — and does **not** put a
cleared identifier back, since restoring the ambiguity into a build with no
index to catch it is not a reversal of anything.

Migration `009_assets` creates the table and seeds it from the
`asset_lookup.xlsx` beside the database; `init_db()` creates it idempotently as
well and seeds it when it is empty, which is the path a fresh install takes and
the fallback for an install whose `db_path` moved the database away from the
sheet. **A downgrade keeps the table** — an older build reads the workbook and
never queries this, while dropping it would throw away every asset added or
corrected since the upgrade. Seeding happens once: an Admin who removed an
asset does not find it back after a restart.

Table `team_members` (engineers, dynamic):

```
id            INTEGER PRIMARY KEY AUTOINCREMENT
name          TEXT UNIQUE COLLATE NOCASE   -- an Engineer typed in another case is the same Engineer
auto_approve  INTEGER DEFAULT 0   -- 1 = no Notifier, transactions auto-confirmed
profile       TEXT DEFAULT 'default'  -- 'default' or 'custom'
permissions   TEXT DEFAULT ''         -- comma-separated names, only read when custom
password_hash TEXT DEFAULT ''         -- salted hash of the engineer's own password (ADR-0008), '' = unset
must_change_password INTEGER DEFAULT 0  -- 1 = the Own Password beside it is Temporary
```

`id` is the key and **`name` is a label** (ADR-0016). It was the other way
round until `012_member_identity`, which made a rename a delete and an insert —
and a delete takes the Engineer's Own Password, their Access Profile and their
permissions with it, so the safe thing to do about a misspelt name was to leave
it wrong. An id makes it an `UPDATE`. **The one writer of a rename is
`_rename_member`**, the way `_save_member` is the one writer of a row and
`_delete_member` the one remover, and there is deliberately no endpoint — the
Admin at this console is the only actor. It rewrites `transactions.team_member`
and `clients.member` in the same transaction, because every one of those rows is
about the same person and an Engineer whose past movements are filed under a
name they no longer have has had their history cut in half. It **never** rewrites
`system_log`: that table records what was done, by whom, at the time, and an
audit trail edited to agree with a later decision is not one — the act is
recorded instead, as `member.renamed` naming the id and both spellings, which is
also what `_former_member_name` reads. A rebuild rather than an `ALTER` for the
reason the collation below is one, and `init_db()` does it idempotently through
`_ensure_member_identity` as well, the both-ways pattern every table here uses.

**A renamed Engineer's Notifier must not go deaf**, which is the sharpest
consequence and has two answers because one of them expires. The Notifier holds
its Engineer's *name* in `config.json`; after a rename that name resolves to
nobody, `GET /pending/<name>` answers with an empty list, and an empty list is
indistinguishable from having nothing to confirm — so the engineer is never told
and simply stops being asked, with the 24h Auto-Accept resolving everything
behind them. So the **check-in carries the id** (`member_id` in and out, with
the Engineer's current `member` name beside it) and `common._adopt_member`
writes both into the config, which is the answer that does not expire; and
`GET /pending/<name>` **resolves a former name**, but only where the first answer
was empty, so a name nobody has renamed costs nothing. That former name is read
out of the `member.renamed` entries rather than out of a table of former names —
the log already holds both spellings and the id, and a second copy of a fact is
what the cascade rule exists to prevent — which costs the log's own retention:
a Notifier that has not run since the rename fell out of the log has no former
name left to be found by, which is why it is the second answer rather than the
only one. **An id that names a different living Engineer loses to the name**,
since a renamed-away name names nobody: that pairing is an id from a database
restored from a backup, and following it would silently re-point a Notifier at
somebody else.

`profile` is stored alongside `permissions` rather than inferred from it: an empty
custom profile and the default profile mean different things the moment the
default set changes, and switching an engineer to `default` and back must not
lose the ticks. Migration `002_member_access` adds the three columns, and
`init_db()` adds them idempotently as well — same pattern as the `transactions`
columns.

`name` carries **`COLLATE NOCASE`**, so `Brian Dawson` and `brian dawson` are one
Engineer everywhere the row is looked up: `_save_member` updates the
row instead of inserting a second beside it, `/auth/verify` answers for the
person who exists, `/pending/<member>` fills a Notifier configured in another
case — an Engineer who stops being asked to confirm anything is the one failure
that system exists to prevent — and the auto-approve read finds the row. A
collation cannot be `ALTER`ed onto a column, so migration
`008_member_name_nocase` **rebuilds the table** (create, copy, drop, rename) and
`init_db()` does the same idempotently, the both-ways pattern the columns above
use — and `012_member_identity` carries the collation across when it rebuilds
again for the id, so the clause is on the `UNIQUE` constraint now rather than on
the key and every query is unchanged. Two rows already differing only in case
cannot both survive that constraint, so the migration **refuses**, naming each
pair, while `init_db()` — which
runs on every boot — leaves the table alone and writes a `members.name_collision`
warning to the System Log rather than refusing to start. `down()` rebuilds it
back with the default collation and keeps every row. **`transactions.team_member`
is not a key but a label**, recorded as it was typed at the time, so the two
queries that match against it say `COLLATE NOCASE` explicitly and
`_create_transaction` writes the Engineer's own stored spelling when the name
names one. **Every password stays case-sensitive** — this is about who somebody
is, not about what they know. `NOCASE` folds ASCII only, which is the whole of
what these names are.

`must_change_password` is stored for exactly that reason and not derived from
`password_hash`: an Engineer with **no** Own Password and an Engineer holding a
**Temporary Own Password** are different states, and a hash is a hash whoever
chose the password behind it. An Admin setting one arms it, the Engineer
replacing it clears it, and an Admin setting another arms it again — which is
the whole of the reset path. Migration `006_own_password_lifecycle` adds the
column and `init_db()` adds it idempotently as well, and **a downgrade keeps
it**: reading 0 for every row on the way back up would turn every Temporary Own
Password into a permanent one without saying so. Every row that already existed
reads 0, because nobody was ever told those passwords were temporary. See
ADR-0009.

`password_hash` holds the salted, self-describing value ADR-0008 defines. It is
the one column a **verify** path writes: `POST /auth/verify` rewrites a hash
still in the pre-ADR-0008 format on the verification that proved it, because
that is the only moment the server holds the plaintext. The write is best
effort — a locked database leaves the old hash to be upgraded next time rather
than refusing a correct password.

`init_db()` creates `team_members` and seeds the default engineers if empty. Managed via `GET/POST /members`.

Table `clients` (one row per Client installation):

```
client_id        TEXT PRIMARY KEY   -- generated once by the Client, kept in its own config
hostname         TEXT DEFAULT ''
os_user          TEXT DEFAULT ''    -- the Windows account the app is running under
app              TEXT DEFAULT ''    -- 'Notifier' or 'Storekeeper'
version          TEXT DEFAULT ''
member           TEXT DEFAULT ''    -- the Engineer a Notifier is configured as, '' for the Storekeeper
cert_fingerprint TEXT DEFAULT ''    -- the ssl_cert.pem it says it pins, '' = it reported none
reported_address TEXT DEFAULT ''    -- the address the Client says it has, '' = it reported none
address          TEXT DEFAULT ''    -- source address of the last check-in, as the server saw it
first_seen       TEXT DEFAULT ''
last_seen        TEXT DEFAULT ''
```

The key is the Client's own identifier rather than the hostname or the address,
because both of those move — a machine is renamed, a DHCP lease changes — and
either as a key would fill this table with duplicates of one installation while
the Admin is trying to work out how many there are. Both are recorded as facts
*about* the installation instead: the hostname is the label a human recognises,
and the address is what the Admin needs when they have to go and find the
machine. **Behind a NAT or VPN gateway it no longer says that** (#281): the peer
is the gateway, one address for every Client behind it, so `reported_address`
beside it is the Client's own - the interface it would route to the server
through - and is what finds the machine there. A reinstall that clears the Client's config appears as a new row,
because it is a new installation. **A row leaves this table one way only** (#203):
the Server GUI's Connected Clients ⌦ Clear Old, or `POST /clients/clear` behind it, removes
every installation not heard from for longer than a chosen age — an age and
never one row somebody pointed at, since how long ago is the only question this
table answers. `client_commands` is keyed on `client_id` and is not a foreign
key, so those rows are left behind deliberately: an uncollected command is the
evidence that machine was not running, and an installation that comes back under
the identifier it has always had is still handed whatever is still waiting for
it. **What the server saw is what it was told
it saw, where something is in front of it** (#187): under IIS every request
reaches this process over a loopback hop (ADR-0001), so the peer of the
connection is `127.0.0.1` for every Client there has ever been, and that is what
this column recorded on the one deployment that is supported. `_client_addr()`
answers it now, reading `X-Forwarded-For` **only where the peer is loopback** -
this endpoint needs no credential at all (ADR-0002, ADR-0005), so a header
believed from an arbitrary peer would let anybody on the network write any
address they liked into the column an Admin reads to go and find a machine, which
is worse than the honest `127.0.0.1` it replaces. The header is set by the
`web.config` `tools/install-iis.ps1` writes, out of IIS's own `REMOTE_ADDR`;
nothing in HttpPlatformHandler sets one of its own, its configuration reference
documenting exactly one header it adds and that being `X-IIS-WindowsAuthToken`,
which this deployment has off. An install whose `web.config` predates that rule,
or a machine without the URL Rewrite module it needs, sends no header and records
the peer exactly as it did. Migration `004_client_registry` creates the
table and `init_db()` creates it idempotently as well — the same both-ways
pattern as the columns above — and **a downgrade keeps it**. See ADR-0005 for
why the check-in is its own channel and not a widening of `/health`.

`cert_fingerprint` is the certificate that installation says it trusts, and
what it is for is a question none of the other columns answer: **whether this
Client can still reach the server after the certificate is replaced.** Every
client pins `ssl_cert.pem` and fails closed against anything else (rule 1), so
a replacement strands each one holding the outgoing certificate — the hourly
`GET /cert` refresh included — until somebody at that machine confirms the new
fingerprint (ADR-0010), and before this there was no way to know from the
console which machines those were. `version` is a different question: what
build a Client is on, not what it would present a pinned copy against.

It is a **claim by the Client**, like the hostname and the app name beside it,
recorded with the source address the server saw as always (ADR-0005): only
that installation can say what it holds, and a server measuring its own file
instead would be answering the question with itself. The value is the digest
over the DER bytes between the PEM markers — the same number
`cert_fingerprint` in `common.py`, `_cert_fingerprint` in `server.py` and
`Get-CertFingerprint` in `tools/_deploy.ps1` all produce, because it is read
against one of them by a human. Capped at 120 characters like every other field
here, a colon-separated SHA-256 being 95. **A Client that stops sending it
clears the column**, which is the existing overwrite-not-merge contract and
matters most here: a stale fingerprint left behind would read as current, and
this is the column a certificate replacement is decided on. '' is also what a
Client holding no certificate reports, which is the honest answer — nothing
pinned is nothing to strand. Migration `013_client_cert` adds the column and
`init_db()` adds it idempotently as well, and **a downgrade keeps it**: a
downgrade is routinely what happens when a certificate change has gone wrong,
which is the one moment this column is the thing being read.

`reported_address` is the same kind of **claim by the Client**, sent on every
check-in for `cert_fingerprint`'s reason - a DHCP lease or a VPN reconnect
moves it - and read by `common.own_address` off a UDP socket connected to the
server, which sends nothing. It sits beside `address` and never replaces it:
`address` is the one fact here the server observed, and the System Log keeps
that one. Displayed, and trusted for nothing. An older Client sends none and its
row reads ''; an older server ignores the key. Migration
`016_client_reported_address` adds the column, `init_db()` adds it idempotently
as well, and **a downgrade keeps it**.

Table `client_commands` (one row per command issued to one Client):

```
id           INTEGER PRIMARY KEY AUTOINCREMENT
client_id    TEXT NOT NULL      -- the Client the command is for, not a foreign key
command      TEXT NOT NULL      -- one of `COMMANDS`: 'logoff', 'reset_identity',
                                  -- 'trust_cert' or 'update_now'
issued_at    TEXT NOT NULL
issued_by    TEXT DEFAULT 'Admin'
expires_at   TEXT NOT NULL      -- written at issue time, not computed on read
collected_at TEXT DEFAULT ''    -- '' = never handed over
```

There is **no status column**: `queued`, `collected` and `expired` are derived
from those two dates by `_command_status`, because a stored status is a second
copy of what they already say and it is the copy that goes stale. `expires_at`
is written at issue time so changing `COMMAND_TTL_DAYS` later cannot move the
deadline of a command already waiting. A command is handed over **at most
once** — collected in the same transaction as the check-in that took it — since
no acknowledgement channel exists, so one left queued would be re-handed on
every check-in and a laptop that crashed mid-logoff would be logged off for
ever. Nothing is ever deleted here: a command that was never collected is the
evidence that the machine has not been running, and a collected one is the only
record that a machine was ever told to do something. Migration
`005_client_commands` creates the table and its `(client_id, collected_at)`
index, `init_db()` creates both idempotently as well, and **a downgrade keeps
the table** and drops only the index.

Table `asset_proposals` (one row per asset somebody is holding that the
register does not have yet):

```
id             INTEGER PRIMARY KEY AUTOINCREMENT
asset_number   TEXT DEFAULT '' COLLATE NOCASE
serial_number  TEXT DEFAULT '' COLLATE NOCASE
asset_type     TEXT NOT NULL
asset_model    TEXT DEFAULT ''
proposed_by    TEXT NOT NULL     -- the Storekeeper's name, as /health gave it
proposed_at    TEXT NOT NULL
client_id      TEXT DEFAULT ''   -- which installation asked
status         TEXT NOT NULL     -- 'pending', 'approved', 'rejected'
decided_at     TEXT DEFAULT ''
decided_by     TEXT DEFAULT ''
reason         TEXT DEFAULT ''   -- why it was rejected
```

**A proposal is not an asset.** It is not in `assets`, `GET /lookup` does not
find it, `GET /asset_types` does not serve its type, and `_create_transaction`
refuses a movement against it exactly as before — which is the whole of what
makes `POST /assets/propose` safe to leave unauthenticated (ADR-0012). The
Storekeeper is the person standing where new hardware arrives and their only
move before 028 was to stop, find an Admin and wait, which is precisely the
situation that makes somebody want a way past rule 6; a proposal answers it
without spending the property rule 6 rests on, which is that **one credential
changes the register**.

`status` is **stored**, unlike `client_commands`' derived one, because it is not
a function of facts already on the row: a rejection is a decision somebody made
and a reason they gave, and `decided_at` alone cannot tell approved from
rejected. The two rules together are the actual rule — derive a state that is a
function of what you already hold, store one that is not.

A rejected proposal is **kept**, for the reason ADR-0003 keeps a cancelled
Transaction: the Storekeeper is owed the answer, and "this serial was refused
last month, for this reason" is the record that stops it being proposed weekly.
There is no delete in this feature at all. The identifiers are `COLLATE NOCASE`
for 010's reason, but there is **no unique index**: two people proposing one
serial is answered with a sentence, and a rejected proposal has to be
re-proposable, because the hardware may have turned up after all. Migration
`011_asset_proposals` creates the table and its `(status, id)` index, `init_db()`
creates both idempotently as well, and **a downgrade keeps the table** and drops
only the index — the answer 004, 005 and 007 give.

**A batch has no column of its own.** A delivery proposed as a file (029) is
every row of it carrying the one `proposed_at` that batch was stamped with, and
that is what the Server GUI groups on — the moment a batch arrived is a fact
those rows already hold, and `client_commands` above is the standing argument
for deriving such a thing rather than storing a second copy of it. `status` is
stored because it is *not* derivable; this is the same rule answering the other
way.

Table `system_log` (one row per action, from any of the three components):

```
id         INTEGER PRIMARY KEY AUTOINCREMENT
ts         TEXT NOT NULL      -- when the Server wrote it, the Server's own clock
component  TEXT NOT NULL      -- 'Server', 'Storekeeper' or 'Notifier'
event      TEXT NOT NULL      -- a short stable name: 'transaction.created', 'auth.refused'
level      TEXT DEFAULT 'info'   -- 'info', 'warn' or 'error'
actor      TEXT DEFAULT ''    -- who, as far as anything knows: an Engineer, 'Admin (Server GUI)',
                              -- 'Delegate: <capability label> (Server GUI)'
detail     TEXT DEFAULT ''    -- one line of context, and never a password in any form
client_id  TEXT DEFAULT ''    -- the shipping Client's identifier, '' for the Server's own
address    TEXT DEFAULT ''    -- the source address the Server saw; '' = written in process
client_ts  TEXT DEFAULT ''    -- what the Client claimed its own clock read
data       TEXT                  -- nullable JSON object, or NULL; a fact a call site
                              -- names beside its own `detail`, for `event_phrase` to
                              -- read back into a template rather than a regex over prose
```

**The System Log is what was *done*; `transactions` is what was moved.** Nothing
here copies a row that exists elsewhere - it records the act and points at the
row - and it records the acts that had no row at all: a refused password, a
replaced lookup sheet, a server starting, a Notifier stopping. It is a table
rather than a file beside the server because every question asked of it is a
filter over a column (which component, which day), because it then travels
inside the backup `update.ps1` takes and the copy a migration leaves behind
rather than being a second thing to collect, and because the Server GUI window
that reads it is a table already. What that costs is contention with the
Transaction writes, which is answered in `_log_event`: **a log write never
raises and never waits long**, so a locked or full log cannot turn a recorded
Transaction into a refused one. There is **one writer**, `_log_event`, the way
`_create_transaction` is the one writer of a Transaction - `POST /clients/log`
goes through it too, so a shipped entry and one the Server wrote itself cannot
mean different things by the same column.

`ts` is always the Server's clock and `address` is always what the Server saw.
Both are stored **beside** the Client's claims rather than being taken from
them, because `POST /clients/log` is unauthenticated (ADR-0002, ADR-0005) and a
component name, an actor and a clock are all things a caller on the network
chooses. `address` is empty for exactly the rows the Server wrote in process, so
a row claiming `component: Server` with an address beside it reads as the
mismatch it is instead of being believed. **And what the Server saw is what it
was told it saw where something is in front of it** (#187), which is
`clients.address` above and the same one helper: `_client_addr()` answers for
both columns, reads `X-Forwarded-For` only from a loopback peer, and is why an
entry shipped by a Client names that machine rather than the hop it arrived
over - `remote.action` beside it having recorded a delegated capability password
as used by the server on itself.

**Retention is two bounds, applied hourly** by `_log_retention_loop` and never
on a request: `LOG_RETENTION_DAYS` (90) drops anything older, and `LOG_MAX_ROWS`
(50000) drops anything beyond that many. Two rather than one because the
endpoint is unauthenticated - an age bound alone cannot bound a table anybody on
the network can write to as fast as they like. Migration `007_system_log`
creates the table and its `ts` index, `init_db()` creates both idempotently as
well, and **a downgrade keeps the table** and drops only the index - the same
answer `004` and `005` give.

**`data` is additive and every call site is free to leave it NULL** (#246/071).
`EVENT_SENTENCES` (`server_log.py`) still gives every event its one phrase,
unchanged; a second table beside it, `_EVENT_TEMPLATES`, gives five of those
events a second phrase with `{keys}` in it, and `event_phrase(event, data)`
reaches for that one and fills it where `data` has what it names. It falls
back to the plain `EVENT_SENTENCES` phrase - the one it always read - where
`data` is None, unreadable, or missing a key the template names, which is
what every row written before this column existed, and every row of the
roughly hundred call sites this ticket leaves unconverted, both read as. The
two phrases are kept apart rather than one column overwritten in place
because `EVENT_SENTENCES` is what a pre-#071 row of a converted event reads
as too - it carries no `data` any more than an unconverted one does - and
that row has to go on reading exactly the sentence it read before this
ticket, not that sentence with an unfilled `{key}` sitting in it.

`_log_event(..., data=None)` serialises the dict it is handed with
`sort_keys` and drops it to NULL rather
than truncating it where it does not fit in `_LOG_DETAIL_MAX` bytes - a cut
JSON document is not a smaller one, it is not JSON, and the row is never
refused for it. Five call sites carry it as of #071: `cert.installed`,
`cert.removed` and `cert.cutover` (`server_gui.py`, `server_cert.py`) name
the fingerprints involved; `server.config_changed` (`server.py`) names the
settings that changed; `transaction.modified` (`register_transactions.py`)
carries the same `(field, old, new)` triples `detail`'s line was already
built from, which is what lets `_log_diff` read a correction's diff back
structurally instead of re-parsing that line, falling back to the parse only
for a row `data` cannot answer for. Migration `015_system_log_data` adds the
column, `init_db()` adds it idempotently as well, and **a downgrade keeps
it** - the same answer `013` and `014` give, for the same reason: an older
build never reads it, and dropping it would throw away the one thing a
reader could pull off a converted row without parsing `detail`.

---

## Migration rules


- Migrations are `migrations/NNN_slug.py` with `up(conn)` and `down(conn)`. Numbers must be contiguous from `001`; a gap is rejected, since applying the rest would leave a schema no released build expects.
- **A downgrade never drops a column.** Every insert names its columns and the xlsx archive is keyed on names, so an older build ignores columns it does not know. Dropping them would destroy live data to satisfy a number nothing reads. A `down()` reverses indexes, constraints and data changes only. **Nor a whole table:** that is the same rule written larger, so `004_client_registry`'s `down()` keeps `clients` — an older build never reads it, while dropping it would throw away the hostname and address of every machine that is not in front of the Admin, and re-upgrading would present the whole fleet as brand new installations. `005_client_commands`'s `down()` keeps `client_commands` the same way and drops only its index, which is a pure performance artefact with no data in it — reversing that is what a `down()` is for. `007_system_log`'s `down()` is the same shape and for the sharpest version of the reason: an older build never queries `system_log`, while dropping it would throw away the only record of what was *done* to this server — who was refused, what an Admin changed, which machines were running — which is the half of the history the `transactions` table cannot reconstruct, and a downgrade is exactly the moment somebody wants to read it. `011_asset_proposals`'s `down()` is the same shape again: dropping it would throw away every **pending** proposal - the assets somebody is holding that nobody has answered about yet - and the reason each rejected one was refused, which is what stops the same asset being proposed weekly. `009_assets`'s `down()` keeps `assets` for the same reason with one more turn in it: an older build reads `asset_lookup.xlsx`, and that file is a copy from before the move, so every asset added, corrected or imported since would have nothing left to be reconstructed from. **`012_member_identity`'s `down()` does drop a column, and it is the one case the rule is not about:** `team_members.id` was added by that migration, nothing outside the table references it — no Transaction, no Client row, and `/members` answered by name on both sides of the change — so what goes is the key being reversed rather than anything anybody wrote down. Every row and every other column is kept. `013_client_cert`'s `down()` is the plain shape again and keeps the column it added: an older build never reads `clients.cert_fingerprint`, while dropping it would throw away which certificate every machine that is not in front of the Admin is holding — and a downgrade is routinely what a certificate change that has gone wrong ends in, which is the one moment that column is the thing being read. `014_transaction_auto_approved`'s `down()` is the plain shape once more: every insert in `_create_transaction` names its columns, so an older build ignores this one entirely, while dropping it would throw away which Transactions nobody was ever asked about — the one fact that tells a confirmation from a row that was never verified — and re-upgrading would read 0 for every row, which is the closed answer and so narrows nothing but also silently loses the record. `015_system_log_data`'s `down()` is the plain shape again: an older build never reads `system_log.data`, so it ignores every row that carries one exactly as it ignores any other shape it does not recognise, while dropping the column would throw away the one fact `event_phrase` and `_log_diff` can read off a converted row without parsing `detail`, and re-upgrading would leave every row written while downgraded with no `data` at all — read the same as a call site that chose not to pass it, which is the answer NULL already gives and not a narrower one.
- **Each step is one transaction, and the runner opens it.** `run_migrations`
  executes `BEGIN` before calling a migration and commits after stamping
  `user_version`, so a step that raises leaves nothing of itself behind.
  Explicit, because `sqlite3` opens a transaction only before `INSERT`, `UPDATE`
  and `DELETE` — never before DDL: the opening `CREATE TABLE` of a rebuild
  (`008`, `010`) therefore committed on its own and survived the rollback of the
  step it belonged to, leaving `assets_new` in the database with `user_version`
  unmoved, so the re-run died on `table assets_new already exists` — a name in
  no runbook, at the one moment `update.ps1` has deliberately restored
  everything except the database. SQLite's DDL is transactional, so this is what
  makes every rebuild written after it safe without a guard of its own, and a
  migration needs nothing but its own `up`/`down`. **Per step, not around the
  run**: a step that has been applied and stamped stays applied, so a run that
  fails at `010` leaves the database at v9 rather than back where it began.
  `tools/server-checks.py` holds all three halves of that — nothing of a failed
  step survives, everything of a finished one does, and a finished one is not
  undone by a later failure.
- Every migration run backs up the database first — wherever `db_path` puts it, since `_backup_db` writes alongside the file it opened — and that backup is the recovery path a migration run leaves behind — a migration that corrupts the database has nothing else of its own to restore from. An update is the one context with a second copy: `update.ps1` puts the database aside in `rollback/<old-version>/` before it migrates, so a failed migration there has both. `migrate.ps1 -NoBackup` (and `server.py migrate --no-backup`) skip it, deliberately, for throwaway databases: a test harness that migrates a scratch copy twenty times does not want twenty backups. **Never pass it against a real install.** If you are unsure which kind you are pointed at, you are pointed at a real one.
- **A rebuild is how a collation changes**, and how a key does. SQLite cannot `ALTER` either one, so `012_member_identity` rebuilds `team_members` a second time to give it an id and demote `name` to a `UNIQUE` constraint (ADR-0016), carrying the collation across untouched; it refuses a database whose names already collide, the way `008` does and naming the same pairs, because `init_db()` warns and carries on where that one refuses and such a database can therefore reach it. SQLite cannot `ALTER` a column's
  collation, so `008_member_name_nocase` and `010_asset_identity` create a new
  table, copy every row, drop the old one and rename — and their `down()` is the
  same rebuild in reverse rather than the no-op the column migrations use, since
  what it restores is the byte-matching an older build's queries assume. Neither
  loses a row. `008` **refuses** a database whose rows already collide, naming
  every pair rather than choosing a side. `010` has a fallback `008` does not,
  because an asset has two identifiers and an Engineer has one name: it clears
  the shared identifier from all but the first row, keeping every asset, and
  refuses only where that would leave a row with no identifier at all.
  `init_db()` is what makes a fresh database identical without anybody running
  `migrate`, and for `010` it warns and carries on where the migration refuses,
  because it runs on every boot.
- `init_db()` keeps its own idempotent `ALTER TABLE` column adds — they are what makes `001_baseline` a no-op. Don't move that logic into a migration.
- **A fresh database is stamped at creation.** Schema state is `PRAGMA user_version` alone, no bookkeeping table, and until #275 nothing wrote it outside `run_migrations` — a database `init_db()` had just built carried every column the latest migration adds and still read `user_version` 0, the same as a v2.0.0 install nothing has ever migrated. `init_db()` now checks `sqlite_master` for a table before it creates any: none there (the file did not exist, or existed empty) means it built this database itself, and it stamps `user_version` to `_latest_schema_version()` — the same count a restore checks a backup's manifest against, no second way of counting migrations. A table already there means the database predates this check or predates migrations altogether, and `init_db()` leaves `user_version` exactly where it found it, so `001_baseline` onward still applies. A package with no `migrations/` directory beside it answers a latest version of 0, which leaves a fresh database at 0 too — the same as before this ticket, rather than a guess.

Back to [CLAUDE.md](../../CLAUDE.md).
