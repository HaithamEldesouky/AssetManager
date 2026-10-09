# 032 - An external asset system syncs into the register

**Type:** feature · **Depends on:** 024, 025, 027, 031 · **Needs an ADR**

## What changes

A configurable outbound connection to another asset system, pulling its asset list and
reconciling it into this one's register.

**Configuration** (Server GUI, admin password): base URL, the path that lists assets, an
auth mode (none, bearer token, basic), the credential, a field mapping, and how often to
run. The credential is stored the way 030's SMTP password is - DPAPI at machine scope, in
its own file, refused rather than stored in plaintext where DPAPI is unavailable. The
mapping is **027's mapper over JSON keys instead of spreadsheet headers**: same helper, same
guess, same manual override, so the two importers cannot disagree about what an Asset Number
is called.

**Transport is `urllib.request`, not `requests`.** `server.py` imports no HTTP client today
and `requests` is not in `requirements-server.txt`; adding it means re-vendoring `lib\`,
which is pinned to one Python minor version (rule 13). The stdlib does what this needs.
TLS verification is **never** relaxed - rule 1 is about the clients but the reason is the
same, and a sync that shipped `verify=False` would be the first place in this repo that did.

**Reconciliation is explicit and conservative**, decided once and written down here rather
than per run:

- an asset the external system has and the register does not is **added**;
- an asset both have, differing in type or model, is **updated from the external system**
  only where the register's value is empty, and otherwise **reported as a conflict** and
  left alone. This system's register is what rule 6 refuses Transactions against; a remote
  system overwriting it silently is how an asset that has been transacted for a year
  becomes a different asset overnight;
- an asset the register has and the external system does not is **never deleted**. It is
  reported. Deleting one would take the Transactions' only description of the thing they
  moved.

**Identity is the identifiers**, matched case-insensitively through 025's helper, never a
remote id - there is no column for one and adding one would be a second identity for a
thing rule 3 says has two.

Every run writes System Log entries - `sync.started`, `sync.added`, `sync.conflict`,
`sync.failed` - which is how a run reaches a mailbox: **through 031's rules**, not through
mail code in here. That is the dependency on 031 and the whole of it.

A run is also startable by hand from the console, and the last run's result is shown there:
a scheduled job whose outcome is only in a log is a job nobody knows has been failing.

## The ADR

Why the register is authoritative over the external system for a field it already holds,
why nothing is ever deleted by a sync, and why identity is the identifiers.

## Verification

`tools/server-checks.py` against a stubbed transport: added / updated / conflict / absent
each behaving as above, a malformed payload refused whole rather than half-applied, a
credential never reaching a log entry or the config file, and a sync failure leaving the
register exactly as it was.

## Not in this ticket

Pushing anything outward. This reads. A write-back is a different ticket and a different
argument about which system is authoritative.

## As built

- **The premise about `requests` was half wrong and the conclusion stands.**
  `run_gui`'s stats probe already imports `requests` lazily behind a
  `try/except`, pinning this server's own certificate over loopback. What is
  true is the part the argument rests on: `requests` is not in
  `requirements-server.txt`, so making it a hard dependency means re-vendoring
  `lib\` (rule 13). `_sync_fetch` is `urllib.request` and
  `ssl.create_default_context()`, and the gate scopes its "no `requests`, no
  relaxed TLS" assertion to that one function rather than to the file, which is
  what stops it failing on a probe written years earlier for another reason.

- **The credential is the second replayable secret, and it did not become a
  store.** ADR-0013 said the moment a second one appeared was the moment to
  decide; ADR-0014 decides. 030's three helpers became a path-taking pair,
  `_secret_set` / `_secret_get`, with `_smtp_secret_*` as wrappers over
  `SMTP_SECRET_PATH` and `_sync_secret_*` over `SYNC_SECRET_PATH` - a file per
  secret, so clearing one cannot take the other and the gate's "three helpers
  name `smtp_secret.dat` and nothing else" assertion survives untouched. One
  rule is added rather than copied: a credential is **never sent over a plain
  `http://` base URL**, refused by name instead of warned about.

- **A fifth event name, `sync.finished`.** The ticket names four. A successful
  run that changed nothing would then write `sync.started` and nothing else,
  which is indistinguishable from a run that never came back - which is exactly
  the "a job nobody knows has been failing" this ticket exists to prevent. It
  is also what the console's last-run line is derived from, alongside
  `sync.failed`, so there is no `last_sync` key and no second copy of what the
  log already says (`client_commands`' own argument).

- **A payload that collides with itself refuses both records.** The identifiers
  are pre-counted across the whole answer before anything is written, so a list
  carrying one Asset Number twice, describing two assets, takes neither and
  says so. Taking the first would be this code deciding which of two
  descriptions is real, which is the answer 027 already refuses to give a
  spreadsheet in the same shape.

- **The window hangs off the Lookup Sheet's footer**, beside Import Assets and
  Asset Proposals: all three write the register through `_save_asset`, and that
  is the window an Admin opens to ask what this server holds. A full-width
  secondary button rather than an eighth pill, so the measured footer row is
  not widened - the same shape Mail Settings uses to reach Notification Rules.

- **The form is a two-column grid**, which no other dialog here is. Eleven
  fields in this file's stacked idiom measured 596x1231, 151px taller than a
  1080p screen, and `ui_kit.fit`'s clamp gives the shortfall to whatever was
  packed last (017). Manage Users' scrolling body is the other answer and is
  for a form with no bound at all; this one has eleven fields and will have
  eleven tomorrow. Measured **596x959**.

## Verified

- `tools/server-checks.py` (135 groups), `tools/cascade-audit.py` (no drift)
  and `tools/client-checks.py` (12 groups) all exit 0. `ast.parse` over every
  `.py` in the repo.
- Five new gate groups against a stubbed opener: a run that **adds** what the
  register lacks, **corrects** only an empty field, **reports** a disagreement
  and leaves the stored value exactly as it was, and leaves an asset the
  payload never mentioned alone; a payload that cannot be read, is not JSON, is
  not a list, or whose keys map to nothing, each refused **whole** with the
  register unchanged and `sync.failed` written; the credential absent from
  `server_config.json`, from every System Log row, from the window that sets
  it, and refused outright over `http://`; every write going through
  `_save_asset` with no `DELETE FROM assets` or `_delete_asset` anywhere in the
  feature, asserted as source since an absence is what is being claimed; and
  the last-run line derived from `sync.finished` / `sync.failed` rows rather
  than from a stored key.
- Smoke run outside the gate: the mapping guessed over JSON keys the way 027
  guesses over headers, Bearer and Basic headers formed correctly, and the
  window opened, saved through `_save_server_cfg` and showed the last-run line
  back.

## Not done here

- **Write-back.** Out of scope by name, and ADR-0014 says why it is a different
  argument rather than a bigger version of this one.
- **Mailing a run.** `sync.*` are ordinary System Log events, so a rule (031)
  points them at a mailbox with no mail code in the sync - which is what the
  dependency on 031 was for.
- **A remote id column.** ADR-0014, "Identity is the identifiers".
