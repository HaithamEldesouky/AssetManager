---
status: accepted
---

# The SMTP password is the one secret that is not a hash

Every password this system has stored until now is a one-way salted hash
(ADR-0008). The admin password, the four capability passwords, each Engineer's
Own Password: all of them are values the server can only ever *compare*
something against. Nothing on this machine can recover one, which is the whole
reason a stolen `admin_config.json` is not a stolen password, and it is why
that file can sit in an install directory that gets zipped into rollback copies
and carried around in backups without that being a second incident.

An SMTP password is not that shape. It has to be **replayed** at every send, so
whatever holds it has to be able to read it back. It is the first secret of that
kind this system holds, and ADR-0008 says nothing about it because ADR-0008 is
about the other kind.

## The decision

The SMTP password is encrypted with **Windows DPAPI at machine scope**
(`win32crypt.CryptProtectData` with `CRYPTPROTECT_LOCAL_MACHINE`) and written to
**`smtp_secret.dat`** beside the server. Where DPAPI is not available the
password is **refused**, with a message naming why. There is no plaintext
fallback and there is no key file.

## Why DPAPI rather than a key of our own

Encrypting it ourselves moves the problem rather than solving it: the key has to
live somewhere, and somewhere is the same directory, in the same backups, read
by the same process. A key file beside the ciphertext is obfuscation written out
in two files instead of one, and the honest version of that is storing the
password in plaintext and saying so.

DPAPI is the operating system holding the key instead. There is nothing to
manage, nothing to rotate, nothing to leak, and the ciphertext is useless off
this machine. It is `pywin32`, which is already a dependency here and already
guarded for being absent (`HAS_WIN32SVC`), so this costs no new dependency.

## Why machine scope rather than user scope

User scope is the stronger of the two and it is the wrong one here, for a reason
that is about this deployment rather than about cryptography: **one install is
opened by three different accounts.** The interactive Admin sets this at the
Server GUI; under the Windows Service the sends happen as LocalSystem; under IIS
(ADR-0001, the supported host) they happen as the app pool identity. A secret
written under user scope by the Admin at the console cannot be read by either of
the other two, so mail would work while somebody was logged in and silently stop
when they were not - which is the failure mode nobody would diagnose, because the
GUI's own test mail would pass.

What machine scope costs is that any account on that machine can decrypt it. That
is the `asset-server` server, where anybody with an account already has the
database, the lookup sheet and `admin_config.json` on the same disk. The
threat it defends against is a copy of the install directory leaving the machine -
in a backup, in a `rollback/` folder, in a package - and machine scope answers
that one completely.

## Why a file of its own rather than `server_config.json`

`server_config.json` has **three writers outside the server** - `install-iis.ps1`
records the port it bound the IIS site to, `bind-port.ps1` records the port it
moved the binding to (ADR-0021), `installer.py` read-modify-writes the port on a
reinstall - and `dev-run.ps1` stages a copy of it for a local run. Each of those read-modify-writes precisely so it does not destroy keys it
does not know about, but a ciphertext is not a setting, and a value that
PowerShell and Python writers might rewrite, re-encode or drop a BOM into is not
a value to store as bytes. `smtp_secret.dat` is written and read by three
helpers in `server.py` and by nothing else, and no script here touches it.

It also keeps the property that file already has and that the ticket for this
work leaned on: **there is no password of any kind in `server_config.json`**, and
that sentence stays true.

## Why a refusal rather than a fallback

A source install without `pywin32` cannot do this, and the obvious kindness is to
write the password in plaintext and warn. That is refused. The password is for
*somebody else's* mail server, the file would sit in the install directory, and
the install directory is what gets zipped into `rollback/<version>/` by
`update.ps1` and carried around by whoever is doing the deployment. A warning at
the moment of setting it is read once; the file is there for years.

The refusal is also cheap to work around in the deployment this system actually
has: an internal relay that accepts unauthenticated mail from the server's own
address needs no password at all, which is the better arrangement anyway. So the
refusal names DPAPI, names `pywin32`, and says that a relay asking for no
password works there as it does anywhere else.

### Which installs those actually were (#188)

"A source install without `pywin32`" was every source install until
#188, and not because the dependency was missing:
`requirements-server.txt` pins it and `vendor.ps1` vendors it. What was
missing is the path to it - `pip install --target` lays its extension
modules out in `lib\win32` and `lib\win32\lib` rather than at the root
of `lib\`, and the `pywin32.pth` naming those directories is read by
nothing, a `.pth` being processed by `site` for a *site* directory while
`lib\` is one entry on `sys.path`. So `HAS_DPAPI` was false on machines
that have DPAPI, and the refusal above - which is this decision's answer
for a machine that genuinely cannot encrypt anything - was what every
server got, every time, with the reason named being a reason that did not
hold.

Nothing about the refusal changes. `applaunch.py` puts those two
directories on `sys.path` and `lib\pywin32_system32` on the DLL search
path before any app is started, so the refusal now fires on the machines
it was written for rather than on all of them.

## What was rejected

- **Plaintext with a warning.** Above. The warning is read once and the file
  outlives it.
- **A key file beside the ciphertext.** Obfuscation with extra steps: both halves
  travel together in every copy that matters.
- **A passphrase the Admin types at every start.** The server runs headless as a
  service and under IIS; there is nobody at the console to type it, and a server
  that cannot restart unattended is a worse failure than no mail.
- **Deriving the key from the admin password.** It would tie mail to a password
  that is changed for unrelated reasons, and changing the admin password would
  silently break sending with nothing saying so until a notification did not
  arrive.
- **Not storing it at all - OAuth, or an app password held elsewhere.** Neither is
  a thing this department's mail server offers, and inventing a credential store
  for one password is the abstraction this repo's working style refuses.

## Consequences

- `smtp_secret.dat` is a per-machine file. A restore of this install onto a
  different machine leaves a file that cannot be decrypted; `_smtp_secret_get`
  answers `""` for it rather than raising, and the Admin sets the password again.
  That is the correct behaviour for a secret that was scoped to a machine.
- The password is read at the moment it is replayed rather than held in a module
  variable, so it is in memory for the length of one send rather than for the
  life of the process.
- It never reaches the System Log: `_log_event` is never handed it, and the two
  entries mail writes carry the recipient, the subject and the mail server's own
  error text. `tools/server-checks.py` asserts all three of those absences.
- Nothing else in this system changes. ADR-0008 still describes every *other*
  stored password, and this ADR is the exception rather than a revision of it.

## It may be set from off this machine, and read from nowhere (#172)

Mail Settings reached the network with the rest of **Server Settings**: `GET`
and `POST /admin/mail` behind the admin password or that capability password,
over HTTPS (ADR-0015). So the SMTP password can now be **set** by somebody who
is not standing at this console, which is a widening of who may write it and
deliberately not of who may read it.

Nothing about this ADR changes, because the property it is about is the one
half that was left alone. `smtp_secret.dat` is still written and read by the
same three helpers and by nothing else; the endpoint calls
`_save_mail_settings`, the one writer the console's own window calls, so the
DPAPI refusal sits in the same place on both paths and a machine that cannot
encrypt refuses a remote caller exactly as it refuses the Admin at the console -
`no_secret_store`, naming the reason, and still no plaintext fallback.

**`GET /admin/mail` answers whether a password is stored and never what it
is.** That is the sentence worth writing down, because it is what makes the
write side safe to delegate: a route that answered with the secret would be a
way to read back off the network the one value on this machine that can be read
back at all, which is precisely what machine-scope DPAPI and the refusal above
exist to prevent. The answer carries `password_stored` and `can_store` - the
second so a form that is not at this console can say *why* the field is refused,
a machine with no DPAPI being a different situation from a relay that asks for
no password. `tools/server-checks.py` asserts the absence at all four places the
secret could leak to: that answer, `server_config.json`, a System Log row and
the test mail.

What follows from a form that is never shown the value is the wire convention:
an **absent** `smtp_password` keeps what is stored while `""` clears it, which
is `_save_member`'s `_KEEP` shape and the only one a caller that cannot read the
field can use to change the host beside it. The key is `smtp_password` rather
than `password`, which at every door in this system means the caller's own
credential; one name for two secrets in one body is the kind of thing that gets
logged by the wrong half.

## When to revisit

If a second replayable secret ever appears, this stops being one file and one
pair of helpers and becomes a store - and that is the point to decide what a
store looks like, not now, with one password in it.

**It appeared, and the answer was no.** 032's external asset system needs a
bearer token or a basic-auth password replayed on every run. ADR-0014 records
what was decided at that point: the DPAPI calls, the machine-scope flag and the
refusal move into one pair of path-taking helpers so they are written down once,
and each secret keeps a **file of its own** - `sync_secret.dat` beside
`smtp_secret.dat` - rather than becoming a map in one blob. Everything this ADR
says about the SMTP password is unchanged by that; `_smtp_secret_set`,
`_smtp_secret_get` and `_smtp_secret_stored` are still the only three functions
that name this file. The store question is a third secret's.
