---
status: accepted
supersedes: 0006
---

# A capability password is a remote credential, not a console delegation

ADR-0006 gave four Server GUI actions an optional password of their own, so one
of them could be handed to somebody without handing over the admin password.
That is not what capability passwords are for, and the Server GUI is not where
they belong.

They belong on the wire. An Admin who is not standing at `asset-server` has no
way to administer this server at all today — the Server GUI is the only console
there is, and every window in it that matters is reached by walking to the
machine. A capability password is the credential for doing a named subset of
that work from a Notifier, over HTTPS, against endpoints that accept it.

The console, meanwhile, gets **one** door. Server Administration asks for the
admin password once and everything behind it opens: the six windows that each
asked for it were one sitting of maintenance spent typing one password six
times, and four of those windows were also accepting a credential that ADR-0006
had put there for a different reason than the one it is now being kept for.

## What this changes

- `_authorise` is not a console gate. Nothing in the Server GUI calls it, and
  `_console_actor` is called from nowhere: a console entry reads
  `Admin (Server GUI)` again, because the console has one credential again.
- The four actions — Manage Transaction History, Import Transaction Archive,
  Change Host / Port, SSL Certificate — are behind `_console_unlock`, which
  asks at the first of them in a sitting and nothing after that. *Amended by
  096:* Change Host / Port and SSL Certificate are now inside Server Settings,
  whose entry asks the admin password on every open (`_admin_again`) as every
  window-opening entry does; the other two keep `_console_unlock`. The
  credential is still the admin password alone.
- `CAPABILITIES`, `CAPABILITY_LABELS`, `CAPABILITY_MIN`, `capability_hashes`,
  `_authorise`, `_pw_caption`, `_console_actor` and the Capability Passwords
  window are all kept, unchanged in shape. They are the store and the
  vocabulary the remote channel needs, and rebuilding them against the network
  would be rebuilding what is already correct.
- Two labels move with the actions they name, per the cascade rule:
  `Manage / Delete Records` becomes **Manage Transaction History** and
  `Import Archive` becomes **Import Transaction Archive**. The label is what
  the holder is told their password is for, so it cannot lag the action.

## What the channel turned out to be (R1)

Four of the five are reachable, and the fifth deliberately is not:

| capability | endpoints |
|---|---|
| Change Host / Port | `GET` and `POST /admin/server_config` |
| Manage Transaction History | `POST /transactions/delete`, `POST /transactions/modify`, `POST /transactions/cancel` (#169) |
| Import Transaction Archive | `POST /records/import` |
| Server Settings | `POST /members`, `POST /members/delete`, `POST /members/rename` (#171); `GET`/`POST /admin/mail`, `POST /admin/mail/test`, `GET`/`POST /admin/notify_rules` (#172); `POST /assets/proposals/decide` (#173); `GET /clients`, `POST /clients/command`, `POST /clients/push_cert` (#174) - complete, all four areas |
| SSL Certificate | **none, and none is coming** |

**Which routes are on the far side of it is a declaration now** (#209). Each
route carries a `door(...)` line under its `@app.route` naming the capability it
asks for, only a name in `CAPABILITY_REMOTE` may be declared, and
`tools/server-checks.py` holds the declaration against what the body reaches -
so a route that names a capability and never asks `_remote_admit` fails the
gate, and so does one that asks for a different capability than it declares.
Nothing about the channel widens: a route still goes through `_remote_admit` and
the scope rule below is unchanged. What goes away is the wiring - `ssl_cert` is
kept off the network by construction rather than by remembering, and adding a
route to a capability is one line at that route rather than a sweep of this
table.

`CAPABILITY_REMOTE` is written as the set that **is** remote rather than the one
that is not, for `MAINTENANCE_OPEN`'s reason: a capability added later should
default to console-only rather than to the network. **SSL Certificate is not in
it because installing a certificate means uploading `ssl_key.pem`**, the one
file that must never travel - anybody holding it impersonates this server to
every client that pinned it (rule 1). That is not a gap to be closed later; it
is the answer.

### Server Settings is a widening of this channel, not a second one (#170)

This ADR argued that a capability password is what an Admin administers this
server *remotely* with. The four areas behind **Server Settings** - the Engineer
list and their Own Passwords, the mail server, Asset Proposals, and the Client
registry with its commands - are that same argument reaching four more windows
that previously had no endpoint at all. The channel, the transport rule, the
`remote.action` entry and the holder's name are unchanged; what widens is the
set of doors on the far side of it. An amendment rather than a supersession.

**One capability rather than four**, which is the decision worth recording. Four
would be four passwords an Admin hands out, four rows on that window and four
entries in the delegation map, for four panels that in practice go to the same
person. What it costs is real and is not hidden: this one password reaches the
Engineer list - and therefore, through an Own Password, the ability to *be* an
Engineer at that Engineer's client - the relay the department's mail leaves by,
the register that rule 6 and rule 2 rest on, and every Client installation. So
`CAPABILITY_REACH` in `server.py` states what each capability opens in one line
and the Capability Passwords row shows it, because `Server Settings` is the one
label here that does not describe itself, and it sits a click under `Change Host
/ Port`.

**It is still not the admin password.** `POST /admin/change_password` is closed
to it like every other capability (rule 7), and so is `POST /lookup/upload` -
answering a proposal is delegated, replacing the Lookup Sheet is not (rule 11).

Three properties hold at every one of those doors.

**HTTPS only.** A capability password is the one credential this server checks
that is *replayed* rather than compared against a stored hash, so a plain
`http://` request carrying one is the credential itself on the wire. There is
no smaller version of that to degrade to, so it is a refusal - `insecure`, 403 -
made **before the password is examined**, which is why the code is not
`bad_password`: the credential was not the problem and an answer saying it was
would send whoever holds it looking for a typo.

**Two doors are the exception to that ordering, and only to the ordering** -
`POST /transactions/cancel` (#169) and the three `/members` doors behind one
`_member_door` (#171). That door takes the admin password as well, and has
since long before this channel existed - it is what the Storekeeper's Cancel
pill sends to retract a Confirmed row, over plain HTTP, which is the default
deployment (rule 1). Refusing on the transport before looking at the password
would therefore refuse the ordinary store on the ordinary install, and nothing
about the password can say which credential arrived without examining it. So
the two are told apart first and the transport is judged afterwards: the admin
password is accepted exactly as it always was, and a **capability** password
over plain HTTP is refused with the same `insecure` 403, the same
`remote.refused` entry and the same words. What moved is the order of two
checks inside this server, not what is refused and not what the holder is told
- and the credential was on the wire before either check ran regardless, which
is what the refusal was never able to undo. Under IIS the hop into this
process is loopback HTTP, TLS having ended at the site (ADR-0001), so
`request.is_secure` alone would refuse the whole supported deployment;
`iis.json`'s `cert_thumbprint` is the second signal, being the record
`install-iis.ps1` left of what it bound, and an `iis.json` naming no thumbprint
is a site nothing was bound to and is refused.

**Mail Settings is not that exception, and the difference is the whole of
why the flag exists** (#172). Its five routes - `GET`/`POST /admin/mail`,
`POST /admin/mail/test` and `GET`/`POST /admin/notify_rules` - go through one
`_mail_door`, which is plain `_remote_authorise`: strict HTTPS on **both**
credentials, the admin password included. They are **new**, so there is no
shipped client sending the admin password to any of them over plain HTTP and no
install to break by holding it to the transport rule. `admin_is_native` is a
wire-compatibility allowance for doors that predate this channel, not a
property of the admin password, and a route that never had those callers does
not get it - the default stays the stricter one, for the reason
`CAPABILITY_REMOTE` is written as the set that *is* remote.

What that channel widens at those five is a **setting** and never a secret that
can be read back. The SMTP password may be set over it - `_save_mail_settings`
is the same one writer the console's window calls, so the DPAPI refusal sits in
the same place either way - and is answered by none of the five: `GET
/admin/mail` says whether one is stored and never what it is, because it is the
one password this server holds rather than checks (ADR-0013). Notification
Rules is the half worth the most remotely and for the reason those rules are
read from disk on every log entry in the first place: an Admin who has to reach
this console to stop a flood of mail will not reach it in the situation that
made them want to.

**Asset Proposals is the same answer as the mail routes and gets no door of
its own** (#173). It is one route - `POST /assets/proposals/decide` - so it
calls `_remote_authorise` directly, which is what `POST /records/import` and
`POST /admin/server_config` already do: a named door exists where **several**
routes ask one question and the decision must not be made three ways, and a
helper wrapping a single call site would be a byte-identical copy of
`_mail_door` under another name, which is the duplication rule 10 exists to
prevent. It is new, so the strict reading holds on both credentials for the
mail routes' reason - there is no shipped client sending the admin password to
it over plain HTTP, and `admin_is_native` is a wire-compatibility allowance
rather than a property of the admin password.

What it widens is the **largest thing behind this capability**, and that is
stated rather than left to be worked out: approving writes the register through
`_save_asset`, so this password can add an asset that can then be transacted
and, where the type is new, a type every client afterwards offers. What it does
**not** widen is replacing the sheet - `POST /lookup/upload` and the Lookup
Sheet window stay the admin password and nothing else (rule 11). The line is
the size of the act rather than which helper runs: answering one question the
Storekeeper asked is not overwriting every asset this server holds. And
`GET /assets/proposals` beside it needs no credential at all, which is why the
Remote Admin window knocks on the decision route rather than on the read - an
open route answers for any password and says nothing about whether that one
may decide.

**The Client registry is the fourth and last of the four** (#174), and it is
Asset Proposals' answer again for Asset Proposals' reason: three routes -
`GET /clients`, `POST /clients/command` and `POST /clients/push_cert` - each
calling `_remote_authorise` directly rather than growing a `_client_door`.
Several routes asking one question is not on its own what a named door is for;
what it is for is a **decision** with a shape of its own that must not be made
several ways, which is what `_member_door`'s `admin_is_native` is. These three
share nothing but the capability name, so a helper here would be a
byte-identical copy of `_mail_door` (rule 10). They are new, so the strict
reading holds on both credentials, for the mail routes' reason.

What widened with them is not a door but a **helper's shape**. `_queue_command`
and `_push_next_cert` checked `_admin_password_ok` **inside** themselves, which
was correct while the console was their only caller and is the thing that
cannot survive a second one: a helper holding a password can only ever know
about one of two doors, and the one it knows about is the one that existed
first. So each takes an **actor** now and the endpoint and the console each ask
for their own credential - the split `_modify_transaction` made at R1, made
again one table over. It is the same rule the enforcement points here already
keep from the other side: `_save_asset`, `_decide_proposal` and
`_rename_member` take no password either.

`GET /clients` is the sharpest of the three and is worth stating on its own.
Every other credential-less read in this server answers a fact about **this
build** - what a Permission is called, what models the sheet holds, what
certificate is served. This answers a map of the hostnames, Windows account
names and source addresses of the machines on the internal network, which is
exactly the sentence ADR-0005 carried about why no such route existed. It is
created behind a credential rather than by weakening that sentence, and it is
**never open**: that is also what makes it usable as the Remote Admin window's
knock, where `GET /assets/proposals` one ticket earlier could not be, an open
route answering for any password and saying nothing about whether that one may
look.

`POST /clients/push_cert` is a **route of its own** rather than a `client_id`
of `*` on the command route, and that is a decision rather than a shape:
commanding one machine and commanding every machine are different acts (C3,
ADR-0020), and the second must not be reachable by leaving a field out of the
first.

The `/members` doors are the same argument one table over, and are the reason
the exception is `_remote_admit`'s `admin_is_native` flag rather than a branch
written twice. Those routes have taken the admin password over plain HTTP since
they existed; the Storekeeper's own Add Engineer sits on the create-only path
beside them (ADR-0017), and a pre-S3 Storekeeper mid-rollout still sends the
password. A transport gate in front of it would have made routes every install
already has HTTPS-only for a channel #171 added - a wire-compat break dressed
as a security tightening, which is the one shape the blast-radius rule exists
to catch. So the admin password stays this door's own credential: accepted over
plain HTTP, recorded as `Admin`, and writing **no** `remote.action`, because
nothing about where that caller was standing changed. The capability password
beside it is held to both halves as everywhere else.

**Never the admin password's own door.** No capability password reaches
`POST /admin/change_password` (rule 7), and none reaches any admin-only
endpoint - `/lookup/upload` above all (rule 11), which is the one that has
never moved. `/members` and `/members/delete` were on that list until #171 put
them behind **Server Settings**, #172 did the same to the mail routes and #174
to `_queue_command`, which this paragraph named as an example until then: what the
assertion in `tools/server-checks.py` holds is that each capability opens
exactly its own doors and no others, which is a rule about scope rather than a
fixed list of endpoints, and it is why widening one is a line in
`CAPABILITY_REACH` rather than a weakening of the check.
A capability that could change the admin password would be the admin password
with an extra step. The admin password meanwhile opens all three remote doors,
as it opens everything, so a delegation can never lock the Admin out.

**Every use is written down, with a name on it.** One `remote.action` entry at
`warn` per call, written **before** the action runs so a call that then fails is
still on the record as having been made, carrying the capability, the source
address this server saw, and **the holder** - the name the Admin wrote beside
that password in the Capability Passwords window. That name is a **label on the
credential, not an authentication of a person**: nobody proved they are the
holder, the Admin wrote down who they handed it to, and the actor string says
exactly that much - `Delegate: Manage Transaction History held by "Ops
on-call" (remote)`, or `Delegate: <label>, unnamed holder (remote)` where none
was written, which is the state "unnamed" rather than a fallback to `Admin`.
Capability first and holder second, with ADR-0006's `Delegate: ` prefix kept, so
a filter over it goes on matching. The name is **copied into the row at write
time and never joined to later**, the rule `_rename_member` keeps for
`system_log`: a password is rotated by replacing it and the name beside it
changes, so a join would re-attribute every past act to whoever holds the
credential today, and an audit trail edited to agree with a later decision is
not one.

Nothing is lost in the meantime. The admin password opened all four before and
opens all four now, so no act that could be performed yesterday cannot be
performed today — what changes is who else could perform it, and the answer was
already "somebody the Admin chose to hand a password to at this console",
which is a person who could equally have been handed the console.

## Why ADR-0006 was right and is superseded anyway

ADR-0006's argument is intact on its own terms. Its *When to revisit* section
names this exact case first:

> If a capability ever needs to be exercised from anywhere but this console.
> Then it stops being a console credential and the whole argument above has to
> be made again against the network, with a real identity behind it.

This is that argument being made. Two things it said, which were consequences
of the console assumption rather than of the credential, do not survive it:

- **"A capability password reaches no endpoint at all."** It is about to reach
  three. What replaces the guarantee is scope: an endpoint accepts exactly the
  capability named on it and never the admin password's own door (rule 7), and
  `tools/server-checks.py` keeps asserting that for every *other* admin
  endpoint rather than dropping the assertion.
- **"Nothing here records who used a capability password, only that the right
  one was given."** On a console that was tolerable, the console being a room
  somebody had to be in. On the network it is not, and the remote channel is
  where that has to be answered.

## What was rejected

**Deleting capability passwords outright.** The console no longer needs them,
so the shortest change is to remove the feature. But the need they were built
for is real and unmet — an Admin away from the machine can do nothing — and
deleting a working credential store to add the same one back six weeks later
throws away `capability_hashes` on every install that had set one.

**Leaving the console gate in place until the remote endpoints land.** That
would keep four windows asking for a password the door had already taken, which
is the defect this removes, and it would leave `_authorise` reading as a console
gate in the one file somebody would look at to find out what a capability
password is.

**A capability password opening the console door.** It would then open
everything behind that door, which is the admin password with an extra step —
the same refusal ADR-0006 made about Change Admin Password, applied one level
up now that the level exists.

## When to revisit

- If a fourth remote capability is wanted. Adding a name to
  `CAPABILITY_REMOTE` is one line and is the whole of the decision, which is
  what makes it worth making on purpose rather than by default - and
  `ssl_cert` is the one that must never be added, for rule 1's reason above.
- If a holder name is ever wanted as proof of who acted rather than as a label
  for what was handed out. It is not one and cannot become one by being typed
  more carefully; what that asks for is an account, which is the line this ADR
  and ADR-0006 both decline to cross.
- If the console ever has more than one operator to tell apart. The door
  records `console.unlocked` and nothing about who opened it, which is exactly
  what ADR-0006 said about capability passwords and is still true one level up.
- If a capability grows past a named subset of actions into something an
  account would describe better. Four labels in a dialog is legible; a
  directory wearing a disguise is not.
