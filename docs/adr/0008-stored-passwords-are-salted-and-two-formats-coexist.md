---
status: accepted
---

# Stored passwords are salted, and two formats coexist on purpose

Every password this server stores is hashed with PBKDF2-HMAC-SHA256 — a random
16-byte salt per password and 200,000 iterations — and the stored value says so:

```
pbkdf2_sha256$200000$<salt hex>$<digest hex>
```

That covers all three of them: the admin password in `admin_config.json`, each
capability password in that file's `capability_hashes` map, and each Engineer's
Own Password in `team_members.password_hash`. Two functions do all of it —
`hash_password` makes a stored value, `password_matches` checks a candidate
against one — and every comparison site in `server.py` goes through them.

**A bare 64-character hex digest is still accepted, and is upgraded the first
time the password it stands for is used.** That is the second format, and the
rest of this document is mostly about why it is there.

## Why salt them at all

They were bare unsalted SHA-256. Three things follow from that, and only the
third is about this system in particular:

- No salt means one rainbow table answers for every machine this app has ever
  been installed on. The admin password's hash on one server is the admin
  password's hash on every server that chose the same password.
- No work factor means recovery is a seconds-to-minutes offline job against
  passwords a human chose. SHA-256 is built to be fast; that is the wrong
  property here.
- An Own Password is about to stop being an admin convenience and become
  something the Engineer sets at first login and changes themselves. A password
  a person chose, probably reused from somewhere else, and stored recoverable is
  a different exposure from an admin-set one, and it is not only this system's
  to lose.

None of this was ever a replay risk over the wire: no hash has ever been on the
wire, in either direction, and every comparison is made against the plaintext
the caller sent. Offline recovery from a file or the database is the exposure
being closed, not impersonation. That is also why nothing about the wire
changes here — `/auth/verify`, `/admin/verify` and `/admin/change_password` keep
their exact request and response shapes, no JSON key is renamed, no DB column is
renamed, and `GET /members` still publishes `has_password` and no hash. A client
built before this cannot tell the difference, which is what lets the server go
first in a rollout.

## Why the stored value is self-describing

The alternative was a second column, or a second JSON key, saying which format
the value beside it is in — and then a migration to fill it, and then another
one the next time the format changes. A value that names its own algorithm,
iteration count and salt needs none of that: the verifier reads the value and
knows what to do with it, the iteration count can be raised without invalidating
what is already stored, and the next format after this one costs a prefix rather
than a schema change.

It also means the *iteration count in the stored value* is what a hash is
checked at, not the constant in this build. Raising `PBKDF2_ITERATIONS` later
does not lock anybody out; each password moves up on its next use, the same
mechanism the legacy format uses.

## Why two formats coexist

Because there is no other way to do this without asking an admin to reset the
admin password to take an update, and because the server never holds more than
one password at a time.

A hash cannot be converted. The only moment the server knows the plaintext
behind a stored hash is the moment somebody types it, so a migration — the
`migrations/NNN_*.py` kind, or a manual step in a runbook — has nothing to work
with. It could only clear the hashes, which means resetting the admin password
and every Own Password on the install, coordinated with the people who hold
them. For an internal tool with one server and five people that is a worse
outcome than a verifier with two branches.

So `password_matches` reads both, and each caller rewrites a legacy value on the
verification that proved it: `_admin_password_ok` for the admin password,
`_authorise` for a capability password, `/auth/verify` for an Own Password.
Nobody is asked to do anything, there is no step to skip, and an install drains
itself of legacy hashes as the passwords in it get used. A password nobody ever
uses keeps its legacy hash — which is exactly the password whose exposure
matters least, and it will be upgraded the day it matters at all.

The legacy branch is recognised by shape: 64 characters, all hex. Nothing this
build writes looks like that, and a value in neither format matches nothing at
all rather than being guessed at.

## Why the upgrade must not be able to refuse a correct password

The rewrite happens on a *verify* path, so a verify now performs a write — a
config file, or one `UPDATE` on `team_members`. If that write fails, the
password was still correct. `_upgrade_stored_hash` swallows the failure and
leaves the legacy hash in place to be upgraded on the next use.

The alternative is an admin who typed their password correctly being told it is
wrong because `admin_config.json` is read-only, on the console they went to in
order to fix something else. There is no version of that which is better than
carrying an old hash for one more login.

## What was rejected

**Salting only the new Own Password path.** The cheapest option, and it leaves
two philosophies in one codebase: a reviewer reading the admin password's
comparison would have to know which of two rules applied to it, and the next
person to add a stored credential would copy whichever one they happened to see
first. The admin password is also the credential every capability password is
measured against (ADR-0006), so leaving it unsalted would mean the weakest hash
in the file is the one that opens everything.

**A dedicated hashing library — `bcrypt`, `argon2-cffi`, `passlib`.** Better
algorithms, and one of them would have supplied the format string for free.
Refused on rule 13: `requirements-server.txt` feeds a vendored `lib\` pinned to
one Python minor version, and every one of those carries compiled extensions, so
adding one narrows the set of machines the source-mode payload runs on for a
benefit PBKDF2 already delivers. `hashlib.pbkdf2_hmac` is standard library and
OpenSSL-backed.

**Putting the pair in `common.py`.** Rule 10 says shared client code lives
there, and `installer.py` also writes a hash — the admin password, during a
server install. But the server deliberately does not import `common.py`, so the
pair would have to be copied into `server.py`, and a copied security primitive
is precisely what rule 10 exists to prevent. A fifth shared module for it would
have to be staged by `package.ps1 -Source` and by `bundle-client.ps1`, and named
in the architecture table and the source-mode runbook — a large blast radius for
a window that closes at the admin's first login.

**So two writers of the legacy format are left, both deliberately:**
`installer.py` during a server install, and `tools/dev-run.ps1`, which seeds
`admin_config.json` for a local run and computes the digest in PowerShell.
Neither can reach `hash_password`. The server upgrades what they wrote the first
time the password is used, which is the same mechanism every existing install
gets. It leaves a real, if narrow, window on a fresh install: an unsalted hash
of a brand-new password, on the server machine, in the file that install just
wrote and that already had to be trusted a minute earlier. `dev-run.ps1` seeds
a throwaway tree and does not have even that.

**A per-install pepper in `server_config.json`.** It would defeat a rainbow
table without a per-password salt, and it puts the secret next to the hash it
protects, in a file that is not treated as a secret and is read at import. A
salt in the stored value costs nothing and does not pretend to be a secret.

## Consequences

- A verification costs a tenth of a second of CPU at 200,000 iterations,
  deliberately. Measured on the dev machine over 20 runs: minimum 82.6ms,
  median 106.5ms, maximum 207.3ms — a spread that wide is what a busy desktop
  does to a CPU-bound loop, so the median is the number to quote and the
  maximum is what a user could actually wait. Every path that pays it is an
  admin dialog or an admin endpoint used a few times a month, plus
  `/auth/verify` at a client's Settings; nothing on the Storekeeper's 15s tick
  or the Notifier's poll checks a password. `tools/server-checks.py` roughly
  doubles in wall clock, because it verifies passwords in a loop where a real
  install verifies one at a time — that is the price of checking this at all,
  and it is paid by a gate script rather than by anybody waiting.
- `tools/server-checks.py` no longer builds stored values with a hash helper of
  the server's — it memoises `hash_password` per password for setup, and builds
  the legacy form itself, because the point of the legacy branch is to read a
  value this build would never write.
- `admin_config.json` still raises on a malformed file and on a
  `capability_hashes` that is not an object. Nothing here relaxes that: a bad
  read that fell back to the defaults would reset the admin password to its
  install-time value, and reading `{}` out of a corrupt map would drop every
  delegation (ADR-0006).

## When to revisit

- If `PBKDF2_ITERATIONS` starts to be felt at a dialog. Raise it or lower it;
  stored values carry their own count and nothing breaks either way.
- If the vendored `lib\` ever stops being pinned to one Python minor version.
  Then `argon2` is on the table and this format string is the migration path
  that makes it a one-line change.
- If an install is ever known to hold no legacy hashes — every password used at
  least once since this landed — the legacy branch can go. It cannot be dropped
  on a schedule, only on that evidence, and the evidence is in the files.
