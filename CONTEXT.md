# Asset Manager

Tracking of who is holding which piece of IT equipment in the IT department. Every movement of an asset between the store and an engineer is recorded by the storekeeper and then verified by the engineer who received it.

## Language

### Assets

**Asset**:
A single piece of IT equipment owned by the department. Identified only by its Asset Number and Serial Number; assets have no name.
_Avoid_: item, device, equipment, machine

**Asset Number**:
The department's own identifier for an asset. It **names one asset**, in
whichever case it was typed: two spellings differing only by case are one Asset
Number. It is **digits only**, and every asset carries one (103); an asset
written before 103 may still carry none so long as it carries a Serial Number
(025).
_Avoid_: asset ID, asset tag, barcode

**Serial Number**:
The manufacturer's identifier for an asset, held to the same rule as the Asset
Number beside it: one asset, case not significant, and carried by every asset
since 103 - absent only on one written before it.
_Avoid_: serial, SN, S/N

**Proposal**:
An asset the Storekeeper is holding that the Lookup Sheet does not have yet,
recorded so an Admin can approve it. It is **not** an asset and cannot be
transacted until it is approved - which is what makes recording one safe without
a password (028, ADR-0012). It is `pending`, `approved` or `rejected`, and a
rejected one is kept with the reason on it.
_Avoid_: request, submission, draft asset

**Batch**:
The proposals that arrived in one file - a delivery's spreadsheet, proposed at
once (029). It is not a record of its own: what makes a batch a batch is that
every row of it carries the same `proposed_at`, which is what the Server GUI
groups them under. A batch is taken whole or not at all. _Delivery_ is the
plain word for what physically arrived and is fine in front of a storekeeper;
_batch_ is what the rows are called here.
_Avoid_: import job, upload, submission

**Asset Model**:
What the asset is, as the manufacturer calls it - `ThinkPad T14`, `Dell U2419H`.
A column on an asset and not an entity: nothing references a model and nothing is
recorded against one. It is optional, filled into a Transaction whose caller sent
none, and picked from the models the Lookup Sheet already has for that Asset Type
rather than typed fresh each time (026) - which is what stopped one laptop being
held as `ThinkPad T14`, `Thinkpad T14` and `T14`.
_Avoid_: model number, part number, make

**Asset Type**:
The category an asset falls into, such as Laptop or Screen. The set of valid types is whatever appears in the Lookup Sheet.
_Avoid_: category, kind, device type, class

**Lookup Sheet**:
Every asset the department owns, maintained by the Admin. It is the sole authority on which assets and which Asset Types exist; an asset absent from it cannot be transacted. It is **kept in the database** and exchanged as a spreadsheet of the same name - `GET /lookup/file` writes one out, an upload replaces every asset from one - so the name belongs to the list rather than to the file it travels in (024, ADR-0011).
_Avoid_: master list, inventory, catalogue, asset register

**Asset Sync**:
One run of the scheduled read from the **external asset system** - another
department system that already knows what hardware it owns, which this server
pulls an asset list from and folds into the Lookup Sheet (032, ADR-0014). It
only ever **adds** an asset the register lacks or fills a field the register
left empty; a disagreement is reported as a **conflict** and left alone, and an
asset the external system no longer lists is reported and **never deleted**.
The register is authoritative, so this is a read and never a write-back. An
asset matched by its identifiers, never by the external system's own id.
_Avoid_: integration, CMDB sync, two-way sync, replication, mirror, feed

### People

**Engineer**:
A member of the IT team who takes assets out of the store and returns them. An Engineer is the recipient of a Transaction and the only person who can Confirm or Reject it. The **identity is an id and the name is a label** (ADR-0016), which is what makes a Rename possible at all; the name is still unique and still case-insensitive, so two spellings differing only in case are one Engineer wherever the system looks the row up, and the spelling the Admin entered is the one shown back. Their password is neither: case matters there, being what they know rather than who they are.
_Avoid_: team member, assignee, user, employee, recipient

**Rename**:
Correcting the name an Engineer is recorded under, at the Server GUI and by the Admin alone. The row is the same row, so the Engineer keeps their Own Password, their Access Profile, their Permissions and their Auto-Approve setting — which is the whole point of the id being the identity. Every Transaction already recorded against them and every Client installation configured as them moves to the new spelling with it, because those rows are about that same person. The System Log does not move: it records what was done at the time, and the Rename is written into it as an act of its own naming both spellings.
_Avoid_: change name, edit name, update member, re-key

**Storekeeper**:
The single person who holds the store and records every Transaction on an Engineer's behalf. Never the recipient of a Transaction, which is why they are a named setting rather than a row in `team_members`: a row would put them in every Engineer dropdown. The Admin sets the name in the Server GUI's Manage Users window; it is recorded on every Transaction that installation submits, and the System Log attributes the act to `<name> (Storekeeper)`. There is no password on it — the Storekeeper app is known by the installation that checked in, not by a login.
_Avoid_: operator, clerk, admin

**Admin**:
Whoever holds the admin password. The only authority permitted to change the Lookup Sheet, add or remove Engineers, or delete Transactions. A capability, not a job title, and may be held by the Storekeeper.
_Avoid_: superuser, root, owner, manager

**Access Profile**:
What an Engineer is allowed to see and do. Either Default, which grants nothing beyond confirming and rejecting their own Transactions, or Custom, which grants exactly the Permissions an Admin has ticked. Set by the Admin, one profile per Engineer.
_Avoid_: role, group, access level, permission set

**Permission**:
One named capability a Custom Access Profile can grant. There is one: seeing every Engineer's history rather than only one's own. `open_settings` was the second until ticket 013 removed it — 012 had already made an Engineer's Own Password open Notifier Settings by itself, which is the door that name stood for, and a Permission that gates nothing must not stay. The names live in `PERMISSIONS` in `server.py` and are captioned there too; no client carries a copy.
_Avoid_: right, privilege, scope, claim

**Own Password**:
A password belonging to a single Engineer, separate from the admin password and optional. It unlocks only what that Engineer's Access Profile grants. The admin password always works and is never limited by a profile. An Admin sets the first one; after that the Engineer changes it themselves whenever the Asset Server is reachable.
_Avoid_: user password, personal PIN, credentials

**Temporary Own Password**:
An Own Password an Admin set, which the Engineer is made to replace the first time they authenticate with it. A property of the password rather than of the Engineer: it stops being Temporary the moment the Engineer chooses their own, and an Admin setting another one makes it Temporary again — which is how a forgotten Own Password is reset. Distinct from having no Own Password at all, which asks the Engineer for nothing.
_Avoid_: temp password, first-login password, must-change flag, expired password, one-time password, provisional password

**Capability Password**:
An optional password on one named action, held by whoever the Admin gave it to. It is the credential for administering this server **remotely**, from a Notifier, and it opens that one action and nothing else — not the other three, and not the admin password's own dialog (ADR-0015). It was a credential at the Server GUI until the console became one door with the admin password on it (see **Server Administration**), and since R1 it reaches an endpoint: **three of the four do**, over HTTPS only, and **SSL Certificate deliberately does not and never will**, since installing a certificate would mean uploading the private key. The admin password always opens all four, so setting one never takes anything away from the Admin. Not a Permission: a Permission gates an Engineer in their own client. Whoever holds one is a **Delegate** in the System Log: an action they opened is recorded as `Delegate: <label> held by "<holder>" (remote)`, or `Delegate: <label>, unnamed holder (remote)` where the Admin named nobody, rather than as the Admin — the server is the only thing that knows which of the two passwords was typed. The **holder's name** is a label the Admin typed on the credential and never an authentication of a person: it is set with the password, cleared with it, and copied into the row at write time rather than joined to afterwards.
_Avoid_: delegated password, action password, sub-password, second admin password, role

**Door**:
The credential one endpoint asks for, declared at the route in `server.py` and stated nowhere else. Every route has one - no credential at all, the admin password, an Engineer's Own Password, or one named Capability Password - and a route declaring none is refused by the gate rather than served, so an endpoint that is open on purpose reads differently in the source from one whose author forgot. The declaration does not perform the check; the checks stay where they are and the gate holds the two against each other.
_Avoid_: guard, auth check, middleware, decorator, gate, permission

**Server Administration**:
The Server GUI's console, and the window every other administrative window is reached from. The admin password is asked for once at the door and every control behind it opens without asking again, for as long as the server window is running. It was called Change Admin Password until the door was added; that dialog is now one of its entries and is the one that still asks, because a door that could change the credential it was opened with would be that credential with an extra step (rule 7).
_Avoid_: admin menu, settings, control panel, admin console, admin panel

### Transactions

**Transaction**:
One record of one asset moving between the store and one Engineer, in one Direction, at one point in time.
_Avoid_: record, entry, movement, log, transfer

**Direction**:
Which way an asset moved in a Transaction. There are exactly two: Out Store and In Store.
_Avoid_: action, type, flow, in/out

**Out Store**:
The Direction meaning the asset left the store and is now held by the Engineer.
_Avoid_: checkout, issued, taken, borrowed

**In Store**:
The Direction meaning the asset came back from the Engineer and is now held by the store.
_Avoid_: checkin, returned, received

**Pending**:
The state of a Transaction that its Engineer has neither Confirmed nor Rejected.
_Avoid_: unconfirmed, open, awaiting, unresolved

**Confirmed**:
The state of a Transaction whose Engineer agrees it happened as recorded.
_Avoid_: approved, accepted, acknowledged, verified

**Rejected**:
The state of a Transaction whose Engineer denies it happened as recorded. Always carries a reason given by the Engineer.
_Avoid_: denied, disputed, refused, declined

**Cancelled**:
The state of a Transaction retracted because the movement it records never happened — an asset that never left the store and never came back. Always carries a reason, given by whoever cancelled it. Distinct from Rejected: Rejected is the Engineer denying a movement recorded against them, Cancelled is the recorder withdrawing the record itself. A Cancelled Transaction is kept and marked, never deleted, and counts towards nothing.
_Avoid_: deleted, removed, voided, reversed, undone, retracted

**Correction**:
A change to a Pending Transaction's own fields — which asset, which Engineer, which Direction, when, the notes — made by the Admin before the Engineer answers it. Only while Pending: a Confirmed Transaction is never corrected, because the Engineer's confirmation is the evidence and correcting the record underneath it would destroy that; that case is Cancelled and recorded again. A corrected Transaction stays Pending, and the Engineer is asked about the corrected version.
_Avoid_: edit, amend, update, revise, fix, adjust

**Backdated**:
Recorded with a Transaction time earlier than the moment it was recorded — a movement that happened while nothing was there to take it down. Only the Admin can backdate, from the Server GUI and behind the admin password; a Transaction from a Client is always stamped by the Asset Server as it arrives. A Backdated Transaction is Pending like any other, and one dated more than a day ago is Auto-Accepted on the next pass.
_Avoid_: retroactive, historical, manual entry, after the fact, post-dated

**Auto-Approve**:
A setting on an individual Engineer meaning their Transactions are Confirmed the instant they are recorded, and they are never asked. Set by the Admin, for engineers who do not take part in verification at all.
_Avoid_: trusted, pre-approved, bypass, whitelisted

**Auto-Accept**:
Confirmation applied by the system to any Transaction that has stayed Pending for more than 24 hours. Distinct from Auto-Approve: Auto-Accept is a deadline that applies to everyone, Auto-Approve is a property of one Engineer.
_Avoid_: timeout, expiry, auto-confirm, lapse

**Out Now**:
The number of assets currently held by Engineers rather than by the store. An asset counts once, based on the Direction of the most recent Confirmed Transaction against it.
_Avoid_: total out, outstanding, checked out, issued count

### Installations

**Asset Server**:
The one installation that holds the database, the Lookup Sheet and the REST API, and the only one any Client talks to. Its console is the Server GUI - that window keeps its name, being a proper name for one window rather than a word for the component. The exe and the Windows Service are still called `AssetServer.exe` and `AssetManagerServer`: renaming those is a cutover on the server machine, not a wording decision.
_Avoid_: the server, the backend, the API server, the host, master

**Client**:
One installation of the Notifier or the Storekeeper on one machine, identified by an identifier it generates once and keeps in its own configuration. Not the machine and not the person: the same laptop reinstalled is a second Client, because nothing connects the two, and a renamed laptop is still the first one.
_Avoid_: installation, node, agent, endpoint, device, machine, instance

**Origin**:
Where a Transaction's Confirm or Reject was given: `desktop`, or `auto` for Auto-Approve and Auto-Accept. Decided by the Asset Server from the door the answer came through, never taken from what the caller says about itself, and shown beside the state wherever a decided Transaction is read.
_Avoid_: source, channel, decided via, platform

**Check-in**:
A Client telling the Asset Server it exists and where it is — its hostname, the Windows account it runs under, which app and version it is, which Engineer it is configured as, and its **Reported Address** - the address the Client says it has. The Asset Server adds the source address it saw and the time; behind NAT the two differ, and neither replaces the other. Not a heartbeat: the heartbeat is how a Client finds the Asset Server, carries nothing about the Client, and must stay answerable with nothing attached (ADR-0005).
_Avoid_: heartbeat, ping, registration, phone home, handshake, keepalive

**Command** — one instruction the Admin queues for one Client, collected on that
Client's next Check-in and handed over exactly once. It is queued, not sent:
nothing here opens a connection to a machine, and a Client that is switched off
collects nothing until it comes back. A Command that was never collected is
kept and shown as expired, because that is how the Admin learns the machine has
not been running.

_Avoid_: push, remote control, signal, instruction, job, task, order

**Mail Relay** — the mail server the Asset Server hands a message to. Not a
mail server of our own: nothing here queues, retries or stores mail, and a
message the relay would not take is a System Log entry rather than something
waiting somewhere. The Asset Server is configured with one relay, one address it
sends as, and at most one password — which is the only secret in this system
that is stored so it can be read back, because it has to be replayed at every
send (030, ADR-0013).

_Avoid_: mail server (ours), SMTP server, mailer, outbox, queue

**Event** — the short, stable name a System Log entry is filed under:
`transaction.created`, `auth.refused`, `update.rolled_back`. It names the act
rather than the thing acted on, and it does not change once it has been
written, because a Notification Rule subscribes to it and every entry already
in the table carries it. Beside it is a **level** — `info` for a thing that
happened, `warn` for a refusal or something an Admin has to act on, `error` for
something that did not work at all — which is what a rule's floor is set
against and is the difference between a mailbox worth reading and one nobody
does. **Every name this build can write, and the level each is written at, is
in `docs/system-log-events.md`**: the Notification Rules window offers only the
names this server's log has already seen, so a name that has never happened has
to be typed, and that is the list to type it from.

_Avoid_: event type, log type, message, code, tag, signal

**Notification Rule** — a standing instruction that one System Log event name,
at or above one level, is mailed to one or more addresses (031). It subscribes
to the name rather than to the thing that happened: the Asset Server has one
writer of that log and every act already passes through it, so a rule is how an
Admin says which of them is worth a mail. A rule on a name nothing has emitted
yet is allowed and mails nothing, which is visible; an act nobody wired would
mail nothing and look configured, which is the failure this shape avoids. The
names offered on the window are the ones this server's log has actually seen,
so writing a rule for something that has not happened yet — which is the
ordinary case for anything worth being told about — means typing the name:
`docs/system-log-events.md` is the list, with the level each is written at.

_Avoid_: alert, subscription, trigger, watch, hook, webhook

**System Log** — the record of what was *done*, across all three components, on
one timeline. A Transaction is what was moved; a System Log entry is the act:
who was refused, what an Admin changed, which machine started or stopped. Each
entry carries the component that claims it and, where it arrived over the
network, the source address the Asset Server actually saw beside that claim — the two
are separate facts and the second is not a guarantee about the first. A Client
keeps its own copy in a rolling file and ships the same entries to the Asset Server;
neither copy is trusted to be the other. Never holds a password, in any form.
Each entry is filed under an Event name at a level; `docs/system-log-events.md`
is every name this build can write.

_Avoid_: audit trail, audit log, event log, history, journal, telemetry, trace
