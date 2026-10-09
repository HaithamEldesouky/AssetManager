---
status: accepted
---

# An Own Password has a lifecycle, and an Admin-set one is temporary

An **Own Password** used to be an admin convenience: the only place it could be
set was the Storekeeper's Add Engineer dialog, an Admin was the only person who
could ever change it, and nothing recorded that a particular one had been
handed over rather than chosen. It now has three states and a life of its own.

An Admin sets the first one, from the Server GUI's Manage Users window, on
the Engineer's own card. (The Storekeeper's Add Engineer dialog was the other
door when this was written; ticket 013 removed it, so no password of any kind
is set from a client any more. The window named here was Engineer Passwords,
one of its own beside Capability Passwords, until ticket A5 moved its one job
onto the card in Manage Users that was already showing the state - shown on one
card and changed on another was two windows wording the same sentence. Nothing
below depends on which console set it - the endpoint arms the mark whoever
wrote it.) That password is a **Temporary Own Password**: the
first time the Engineer authenticates with it they are made to replace it
before anything else proceeds. Once they have chosen one, the mark comes down.
An Engineer changes their own password after that whenever the server is
reachable, proving their current one — or the admin password, which is what
makes a forgotten password recoverable. An Engineer with **no** Own Password is
untouched by any of it.

`team_members.must_change_password` is the mark, one stored column, added by
migration `006_own_password_lifecycle` and by `init_db()` alike.

## Why a password an Admin set is temporary by default

Because until the Engineer has typed one, the password is not theirs.

Everything an Own Password unlocks is scoped to one Engineer: their own
Notifier Settings, and — with `view_all_history` — what their Dashboard shows.
So the person who knows an Engineer's Own Password can act as that Engineer at
that Engineer's client. While an Admin has set it and the Engineer has not
replaced it, at least two people know it, and one of them wrote it down
somewhere to tell the other. That is a normal thing to have to do once; it is
not a normal thing to leave in place.

Temporary **by default** rather than by a checkbox, for the reason `profile` is
stored beside `permissions` rather than inferred: the safe state has to be the
one nobody has to remember to pick. A "make this temporary" tick would be
unticked by whoever was in a hurry, which is exactly the Admin setting a
password over the phone.

It is also what makes the reset path honest. An Engineer rings up having
forgotten their password; the Admin sets another one and the Engineer is asked
to replace it again. There is no separate reset mechanism to build, no
one-time token to expire, and no state where a password an Admin knows has
become permanent because nobody followed up.

## Why the mark is stored and not derived

An empty `password_hash` and a hash awaiting replacement are different states,
and a hash cannot tell you who chose the password behind it. Deriving the mark
would mean deriving it from something — a timestamp, a naming convention, a
second table — and every one of those is a worse copy of one integer.

Existing rows read 0. An install upgrading to this has Own Passwords an Admin
set, but nobody was ever told they were temporary, and arming the flag on all
of them would make every Engineer with a password replace it because of a
release. The state is honest about what it knows: from here on, an Admin-set
password is marked; the ones already out there are not.

## Why setting one is not delegable

A **Capability Password** opens one Server GUI action, at one console, and
reaches no endpoint at all (ADR-0006). Setting an Engineer's Own Password does
not fit that shape. Whoever can set it can then authenticate as that Engineer
at that Engineer's client — open their Settings, point their Notifier at
another server, see their history if their profile allows. That is not one
delegated action; it is a second Admin, arriving through a door labelled as
something smaller.

So setting one took the **admin password** and only that, checked directly
rather than through `_authorise`, exactly as Change Admin Password is (rule 7)
- which is the password Manage Users asks for at the top regardless.

**#171 delegates it, and to exactly one capability.** What changed is not the
argument above but what it is an argument against: a *narrow* capability named
for one action, which is what ADR-0006 was about. **Server Settings** is not
that - it is the whole of administering this server from somewhere else
(ADR-0015), and its holder can already add and delete Engineers, so a rule
leaving the Own Password behind would leave a delegate who can remove an
Engineer outright and cannot reset a forgotten password, which is the shape
that makes somebody reach for the bigger action. The second-Admin cost is
therefore accepted rather than argued away, and is paid for in visibility:
`CAPABILITY_REACH` states it on the Capability Passwords row, the panel says so
on its face, and every act is one `remote.action` at `warn` plus a
`member.password_set` attributed to the delegate rather than to the Admin. The
admin password's own door is still closed to it (rule 7), and the capability
set stays at five.

## Why the Engineer's own change is an endpoint and the Admin's is not

The Engineer is at a laptop somewhere on the network, so their change has to be
a request: `POST /auth/change_password`, the Engineer's pair to `/auth/verify`
the way `/admin/change_password` is the Admin's pair to `/admin/verify`. The
Admin is at the console, so their setting of one is a call into
`_set_member_password` — the same helper `POST /members` goes through, which is
what stops the arming rule holding at the endpoint and quietly not in the
window an Admin uses. It is the shape Add Transaction, Modify and Cancel
already have.

The change endpoint **changes** an Own Password and never creates one. An
Engineer with none is refused with `no_password`, naming the Server GUI's
Manage Users window as where a first one is set. Without that refusal, an
Admin standing at a Notifier could type the admin password and stand up a first
Own Password that was *not* temporary, which is the one thing this document
rests on.

That refusal is reached **before** either password is examined, so the admin
password does not open it either, and the Notifier shows the server's words
verbatim. The message therefore has to say that the password typed was not the
problem — an Admin who read only that there was nothing to change retyped the
admin password, which had never failed. It names Manage Users rather than
`POST /members` for the same reason: whoever is reading it is standing at a
Notifier and cannot call an endpoint.

The same argument reaches the Engineer who *has* one, so **the mark follows
which password was proved, not who sent the request**. The Engineer's own
password clears it: they proved the password they already had, so the new one
is theirs. The admin password arms it, because this endpoint is on the network
and the admin password proves an Admin and nothing about whose fingers typed
the new password — after such a call the new password may be known only to
the Admin, which is precisely the state this document exists to mark. What it
leaves behind is therefore a Temporary Own Password, exactly like one set at
the console, and the reset path reads the same from either end: an Admin sets
another one, the Engineer replaces it.

It costs the Admin who is standing at the Engineer's desk one further
replacement, and that is the right trade. The server cannot tell that Admin
from one on the far side of the network, and the whole reason the mark is
temporary by default is that the safe state must not be the one somebody has
to remember to pick.

`name` in the body is not proof of anything and is not meant to be. What stops
an Engineer changing somebody else's is that the current password is checked
against *that* Engineer's row: one Engineer's password is simply the wrong
password there, and only the admin password opens every row, as it always has.

## Why a server nobody can reach must not lock an Engineer out

The Notifier exists so an Engineer is asked to confirm the movements recorded
against them. A replacement demand that could block that would be worse than
the exposure it closes: the store carries on recording Transactions either way,
and an Engineer who cannot answer them is the failure this app was built to
prevent.

So the replacement form is a Toplevel the Engineer can close, it takes no grab,
the poll loop and the popup queue never consult it, and a server that cannot be
reached ends as a line on that window. `/confirm`, `/reject`, `/transactions`
and `/clients/checkin` stay unauthenticated (ADR-0002, ADR-0005) and nothing
here touches them.

The forcing point is where the password is actually used: the dialog that
authenticates an Engineer into Settings. A Temporary Own Password that is never
used opens nothing, so there is nothing to force at any other moment — and the
tray's Change My Password is there for the Engineer who wants to deal with it
without opening Settings at all.

It is asked **before** the profile is consulted, not inside it. An Engineer on
the default profile is refused Settings, but their Own Password is not inert:
it stands up a Notifier configured as them (ADR-0007). Telling them their
profile cannot change settings and nothing else would leave a password two
people know in place for ever, on the one Engineer nobody had configured.
Replacing it does not grant what the profile withholds — Settings still opens
only where it would have opened anyway.

The installer is the one place that authenticates an Own Password and does
**not** force a replacement, deliberately: there is no Notifier running yet to
force anything, and refusing the install would refuse the Engineer the one
thing they were handed the password for. The demand arrives on that machine the
first time they open Settings on it.

## What was rejected

**A `password_set_at` timestamp, with an expiry.** It answers a question nobody
asked — how old is this password — and not the one that matters, which is
whether the person holding it chose it. It would also need a policy for how
long temporary is, and a background job to act on it, for a department of five
people.

**A one-time token instead of a temporary password.** A second credential
format, a second store, an expiry, and a delivery channel this system does not
have: there is no email here, so the token would be read out over the phone,
which is what the temporary password already is. The temporary password reuses
`password_matches` and the column that exists.

**Making it a fifth Capability.** Covered above: it would look like a
delegation of one console action and hand over an Engineer's identity.

**Forcing the replacement at the Notifier's startup or on the poll tick.**
Discoverable, and the wrong trade. A window raised on a timer over whatever the
Engineer is doing, on the app whose whole job is a popup they must answer, is
how a replacement demand becomes the reason a Transaction went unconfirmed.
The authentication path is where the password is used, so it is where the
demand belongs.

**Reporting the mark on `/auth/verify` only, or on `GET /members` only.** Both
are needed and both are additive. `/auth/verify` answers it on the round-trip
that proved the password, which is what lets the client decide without asking a
second question; `GET /members` is where a client reads what it may show before
anyone has logged in, and the state is three-valued there rather than two.
Neither renames or drops a field, so a client built before this behaves exactly
as it did.

**Letting the Engineer clear their own password.** Then an Engineer could
remove the only thing that distinguishes their Settings from anybody else's,
and an Admin who had given them one would have no way to know. Clearing is an
Admin's decision, from the Engineer's card in Manage Users.

## Consequences

- Two verifications are paid on `POST /members` when a `member_password` is
  sent, because the helper checks the admin password again. A tenth of a second
  each (ADR-0008), on an admin endpoint used a few times a month, bought
  against one place that answers what may set an Engineer's Own Password.
- `PASSWORD_MIN` is now one constant for the admin password, an Own Password an
  Admin sets, and one an Engineer chooses. It used to be the literal 4 in two
  endpoints. `CAPABILITY_MIN` stays its own number: a delegation bound is a
  different rule and ADR-0006 argues it separately.
- `/auth/change_password` replaces the stored hash outright, so it does not
  bother upgrading a legacy one on the way past. `/auth/verify` remains the
  place an Own Password is verified and kept, and therefore the only place that
  upgrade is worth making.
- An Admin who clears an Engineer's Own Password takes nothing else away. The
  admin password still opens that Engineer's Settings, and their Transactions
  are unaffected — a passwordless Engineer is a normal Engineer.

## When to revisit

- If an Engineer ever needs an Own Password for something that is not scoped to
  them. The argument for "not delegable" is that the password grants their
  identity and nothing wider; a permission that reached further would need this
  read again.
- If the department grows past the point where an Admin can set a password by
  speaking to the person. Then a delivery channel is the missing piece, and a
  one-time token stops being a second copy of the temporary password.
