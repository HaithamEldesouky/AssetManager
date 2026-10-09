---
status: superseded
superseded-by: 0015
---

# Capability passwords are a console credential, never an endpoint one

**Superseded by [ADR-0015](0015-a-capability-password-is-a-remote-credential.md).**
The *When to revisit* section at the foot of this file names the case that
superseded it, first on its own list: a capability is now exercised from
somewhere other than this console, so it is not a console credential and the
argument below has been made again against the network. The console has one
door instead, with the admin password on it. What follows is kept as written,
because it is the record of why the credential exists at all and every part of
the store it describes is still in `server.py` unchanged.

Four actions in the Server GUI can be given a password of their own: Change
Host / Port, SSL Certificate, Manage / Delete Records, and Import Archive. A
capability password opens exactly one of them and nothing else. The admin
password keeps opening all four, and is what is required to set or clear any of
them.

Nothing else changes. `admin_config.json` gains one key, `capability_hashes`, a
map of capability name to a stored password hash — bare SHA-256 when this was
written, salted PBKDF2 since ADR-0008, which also says why a value in the old
format still verifies; a file written before this existed has no
key and merges over the default of `{}`, so an older install needs no
migration. No endpoint accepts a capability password. No endpoint publishes
whether one is set.

The reason the feature exists is that four of the six actions on that row are
things the Admin does not want to do personally and does not want to hand the
admin password over for either: a colleague who has to install a renewed
certificate, or clear a fortnight of test rows, or move the port after a
firewall change. Before this the only way to let somebody do one of those was
to tell them the password that also lets them do all six, change the admin
password itself, and reach every admin endpoint on the network.

## Why not permissions

The obvious place to put this was `PERMISSIONS` — the list already exists, it
is already per-name, and the Storekeeper already draws checkboxes from it
(rule 8). It would have been less code. It is the wrong mechanism, for two
reasons.

`PERMISSIONS` names things an **Engineer** may do in **their own client**. A
permission is looked up by engineer name, captioned in `server.py`'s own
`PERMISSION_LABELS`, and enforced at endpoints that already know who is
calling. These four actions have no engineer, no client and no endpoint — they
are buttons on one window, on one machine, in the server room. Putting them in
the same list would mean the Engineer profile form grew four checkboxes that
gate nothing an engineer can reach, which is exactly the failure rule 8 already
forbids: a permission that gates no real behaviour, ticked by an admin who
believes something changed. (That form was the Storekeeper's Add Engineer
dialog when this was written; ticket 013 moved it to the Server GUI's Manage
Users window, which changes nothing here — the two lists stay apart wherever
the ticks are drawn.)

The second reason is that a permission is granted to a *person* the server
knows about, and these are granted to *whoever is standing at the console*.
There is no identity here to attach a grant to, and inventing one — a second
user table for the server room — is a much larger thing than the problem asked
for.

## Why the admin password always works

A delegation that could take the delegated action away from the Admin would be
a way to lock the Admin out of their own server using a feature meant to be
convenient. So `_authorise(capability, password)` accepts the admin password
for every capability, and the capability's own password only for that one
capability. It also means the failure mode of forgetting which password was set
for what is harmless: the admin password is always the answer.

Two consequences follow, and both are enforced rather than documented:

- **A capability password cannot grant or revoke itself.** Setting or clearing
  any of them takes the admin password, checked by hand against
  `ADMIN_CFG['password_hash']` rather than through `_authorise` — going through
  `_authorise` would have let the SSL delegate set the SSL password, which is
  self-renewal, and let them clear the others.
- **Changing the admin password is not one of the four and is not delegable.**
  It is the credential every capability password is measured against, so
  delegating it would be delegating everything with an extra step. The dialog
  that changes it is also where the delegation dialog is reached from, which is
  the right adjacency: it is the window an admin opens to think about who holds
  which password.

The admin password is also refused as a capability password (`same_as_admin`).
Accepting it would produce something that looked like a delegation while
handing over everything, and clearing it later would take nothing away.

## What the System Log records

`_authorise` is the only thing that knows which of the two passwords was
typed, so it answers with the credential — `"capability"`, `"admin"` or `""`
— rather than with a bool, and `_console_actor` turns that into the `actor`
column: `Delegate: <label> (Server GUI)` or `Admin (Server GUI)`. Worded in
one place for the reason `_pw_caption` is, five actions being five chances to
write a different sentence about a column that is filtered on.

It returned a bool until #74, which threw that away: every delegated action
wrote the entry the Admin would have got. That is this decision's own point
lost at the one place it survives the act — a capability password is **not**
the admin password, and the log was saying it was. Sharpest on **Manage /
Delete Records**: a deletion's rows are gone, so the entry is the entire
record that it happened, and it named the wrong person.

The `(Server GUI)` suffix stays on both. A capability password reaches no
endpoint, so a delegate is always at this console and the suffix reads as
redundant — but the Admin's own rows carry it, and a filter over it must not
stop matching this console's entries partway down the table.

## Why no endpoint accepts one

Every endpoint that takes the admin password is reachable from anywhere on the
internal network. The four capabilities are not: they are reachable only by
somebody with physical access to `asset-server`'s console, which is the
implicit second factor that makes a four-character minimum defensible at all.

(That sentence is the superseded half: ADR-0015 put the credential on the
wire, and #209 made *which* routes it opens a `door(...)` declaration at each
route rather than a fact spread over the bodies. Only a capability in
`CAPABILITY_REMOTE` may be declared, so the one thing this section was right
about and ADR-0015 kept — that `ssl_cert` reaches no endpoint — is now held by
the declaration itself.)

So a capability password is checked in exactly one place — the GUI callbacks —
and `POST /transactions/delete`, `POST /members`, `POST /members/delete`,
`POST /lookup/upload`, `POST /admin/verify`, `POST /admin/change_password`,
`POST /admin/server_config`, `POST /auth/verify` and `_queue_command` all
continue to compare against the admin hash alone. `tools/server-checks.py`
asserts that for each of them: the check is that a capability password is
refused *and* that the admin password still works, so the assertion cannot pass
by the endpoint having become broken.

Nothing about capabilities appears on `GET /health` either. The Cancel switch
is published there because a Client changes its own behaviour from it
(ADR-0003); no Client has any use for knowing that the certificate button has
its own password, and publishing it would tell an unauthenticated caller which
console actions have been delegated.

## Why the state is derived, and why a bad map raises

Whether a capability has its own password is read from the map every time it is
needed (`_capability_state`), never stored as a flag beside it. A flag would be
a second copy of what the map already says, and it is the copy that goes stale
— the same reasoning `client_commands` uses for not storing a status.

A `capability_hashes` value that is not an object raises at load, the same way
the rest of a malformed `admin_config.json` does. The alternative — falling
back to `{}` — would silently drop every delegation the Admin had made, on a
server that then started and looked healthy, and the Admin would find out when
a colleague's password stopped working for reasons nobody could reconstruct. A
*missing* key is not malformed and does not raise: that is just an older file.

## When to revisit

- If a capability ever needs to be exercised from anywhere but this console.
  Then it stops being a console credential and the whole argument above has to
  be made again against the network, with a real identity behind it.
- If the four grow to a number where remembering which password opens what
  becomes the problem the feature was supposed to solve. A list of four labels
  in one dialog is legible; twelve is a user directory wearing a disguise.
- If the console ever gets more than one operator who needs to be told apart in
  an audit trail. Nothing here records *who* used a capability password, only
  that the right one was given — which is the same thing the admin password
  offers today, and is the reason this is not a substitute for accounts.
