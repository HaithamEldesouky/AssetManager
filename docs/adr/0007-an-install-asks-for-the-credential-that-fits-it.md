---
status: accepted
---

# An install asks for the credential that fits it

Installing a **Notifier** now takes the **Engineer's Own Password** or the admin
password. Installing a **Storekeeper** now takes the **admin password**, which it
did not take before. Installing a **Server** is unchanged: it sets the first
admin password at the console, and there is nothing to check it against yet.

## What was there before

The Notifier install demanded the admin password and verified it live against
the server. That check was added to replace a Setup PIN, and the admin password
was the only credential that existed at the time.

It is the wrong credential to ask an Engineer for. The Notifier goes on that
Engineer's own laptop, they are the only person who will ever use it, and the
only way they could install or reinstall it was for somebody to read them the
password that also opens Clear All Records, Manage / Delete Records and the
admin password's own dialog. So either an Admin walks to every laptop, or the
admin password is spoken aloud to four Engineers — and the second is what
actually happens.

The Storekeeper install asked for a Server URL and nothing else. Anybody holding
the package could stand one up and point it at the store's server.

## The decision

**An Engineer proves their own identity to install their own client.** The
Engineer's Own Password already exists, `/auth/verify` already accepts it
alongside the admin password, and the Notifier's Settings dialog already takes
it. The install is the last place that demanded more.

The admin password keeps working, for the Engineer who has no Own Password and
for the Admin installing on their behalf. Nothing here can lock an Admin out.

**The Own Password is checked against the Engineer the install is being
configured as**, not against whoever is typing. Accepting any Engineer's Own
Password for any name would let one Engineer install a Notifier configured as
another, and then confirm or reject that person's Transactions — which is worse
than the admin-password prompt it replaces, not better.

**A Storekeeper install takes the admin password.** This one deserves stating
plainly, because it looks like more security than it is: `POST /transactions` is
deliberately unauthenticated (ADR-0002), so requiring a password to *install* a
Storekeeper does not stop anyone on the network from doing what a Storekeeper
does. It is a control over who sets one up and points it at the store's server,
and nothing more. A reader who finds ADR-0002 first should not conclude that one
of the two is confused.

**The check stays live in both cases.** A server that cannot be reached means
the install does not proceed. There is no offline path and no local credential
to fall back on. The Engineer dropdown's fallback to the baked-in list is a
convenience for choosing a name, not a licence to skip the check — and the
failure says the check could not be made, rather than implying the password was
wrong.

## What was rejected

**A built-in `storeadmin` password, set by `package.ps1`.** Considered and
dropped for three reasons. ADR-0002 leaves `POST /transactions`
unauthenticated on purpose, so gating who may *install* a Storekeeper stops
nobody from doing what a Storekeeper does — the gate would buy nothing it
appears to buy. It collides with rule 7, which says the admin password is the
only credential of its kind and is never delegable, and with ADR-0006, which
says a Capability Password opens one console action and reaches no endpoint;
`CONTEXT.md` lists "second admin password" on Capability Password's avoid list
for the same reason. And no credential may be baked into a package by a build
script: a package travels to laptops, and a password shipped inside one cannot
be revoked without a new release. (The hashes here were unsalted SHA-256 when
this was written, which made that worse still; ADR-0008 salted them, and the
argument stands without it.)

**A prompt worded from `has_password`.** The installer could read `GET /members`,
see whether the selected Engineer has an Own Password, and word the prompt
differently in each case. It buys only the caption: `/auth/verify` already
accepts either password and already refuses an Own Password that was never set.
One caption naming both covers everybody, including the Engineer who has none,
and the installer needs no second opinion to word a label.

**Setting an Engineer's Own Password as a fifth Capability.** Whoever can set an
Engineer's password holds that Engineer's identity, which is not what a
Capability is for (ADR-0006). Setting one stays on the admin password.

## Consequences

An Engineer can install their own Notifier without ever being told the admin
password. The admin password stops being the thing four people know.

A Storekeeper install now fails without the admin password, so an admin has to
be present for it. That is the intent, and it is a change in behaviour for
anyone who has been installing one from a Server URL alone.

The fallback for a server that predates `/auth/verify` lives in `common.py` and
is called from both the Notifier and the installer, rather than being copied into
each — rule 10. `tools/cascade-audit.py` fails the build if a second client
module grows its own `/auth/verify` call.

Three callers want the admin password specifically and nothing else: this
Storekeeper install, the Notifier's setup wizard, and the Storekeeper's Server
Settings dialog. Routing them through `verify_password` would quietly let an
Engineer's Own Password open them, so they are deliberately **not** routed
through it.

They are not three hand-rolled copies of `/admin/verify` either, which is what
they were when this ADR was first written: `common.py` carries a second door,
`verify_admin_password`, and all three go through that. Two doors rather than one
function with a flag, because a flag would put "may an Own Password open this?"
at every call site, and that is the one decision here that must not be gettable
wrong. What actually refuses an Own Password is `/admin/verify` itself, checked
against the admin hash and nothing else; the client's whole contribution is to
knock on that door and not the other one. `tools/cascade-audit.py` refuses any
client module that asks either endpoint itself.
