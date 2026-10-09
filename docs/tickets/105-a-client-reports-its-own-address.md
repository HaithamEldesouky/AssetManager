# 105 - A Client reports its own address

**Type:** feature · **Depends on:** none · **Issue:** [#281](https://github.com/HaithamEldesouky/AssetManager/issues/281)

## Finding

Connected Clients shows one Source Address for every Client on the 2.9.1 IIS
install: `198.51.100.29` for both `client-lt-11220` and `store-11-9365`. That
value is correct for what it claims to be. `_client_addr` in `server.py` reads
the `X-Forwarded-For` that IIS fills from `REMOTE_ADDR`, which is the TCP peer
IIS saw, and between the client subnet and `192.0.2.0` there is a NAT / VPN
gateway. `client-lt-11220`'s own address is `198.51.100.11`, and its default
route goes through the VPN tunnel (gateway `198.51.100.12`).

The `clients` table says the address is "what the Admin needs when they have
to go and find the machine" (`docs/reference/database.md`). Behind NAT it no
longer tells anyone that. Nothing is broken and nothing should change about
`address`: it is the one fact here the server actually observed, and the
System Log keeps it for that reason (`CONTEXT.md`, System Log). What is missing
is the Client's own side.

## Design

A new check-in field, `reported_address`, sits beside `address` and never
replaces it. It is a **claim by the Client**, like `hostname` and
`cert_fingerprint`, so both are shown and neither overwrites the other.

- **How the Client finds it.** A UDP socket `connect()`ed to the server's host
  and port, then `getsockname()[0]`. That returns the address of the interface
  the OS would route to the server through, which is the one that matters on a
  multi-homed laptop: VPN, Wi-Fi and Ethernet all at once. It sends no packet.
  Any failure answers `""`. The server URL is resolved from the URL `checkin`
  already holds; nothing is hardcoded.
- **Sent on every check-in**, for `cert_fingerprint`'s reason (see `checkin`'s
  docstring in `common.py`): every field is overwritten, and a DHCP lease or a
  VPN reconnect moves this.
- **Additive on the wire.** An older Client sends nothing and its row reads
  `""`, shown as `—`. An older server ignores the key, since `_record_checkin`
  reads only `_CHECKIN_FIELDS`. Neither side needs the other upgraded first.

## Scope

1. `common.py`: a small helper next to `own_cert_fingerprint` that returns the
   address, and one more key in the `checkin` JSON, capped at `CHECKIN_MAX`
   like the rest.
2. `server_clients.py`: add `reported_address` to `_CHECKIN_FIELDS`, and add
   the column to the `INSERT OR REPLACE INTO clients` column list in
   `_record_checkin`. Check `_CHECKIN_MEMBER_AT` still indexes `member`. The
   registry readers use `SELECT *`, so `GET /clients` carries it without a
   change there.
3. `server.py` `init_db()`: the column in `CREATE TABLE IF NOT EXISTS clients`,
   and the idempotent `ALTER TABLE clients ADD COLUMN reported_address TEXT
   DEFAULT ''` next to `cert_fingerprint`'s.
4. Migration `016_client_reported_address.py` under `migrations/`, shaped like
   `013_client_cert.py`: `_existing`, `up`, `down`, and a docstring that says
   it is a claim.
5. `gui_clients.py` (the console's Connected Clients): a "Reported Address"
   column directly after Source Address, painted `—` when empty. The loopback
   test that reads `address` stays on `address`.
6. `notifier_remote.py` (the Remote Admin Connected Clients panel): the same
   column in the same place.

## Not in this ticket

- Replacing, merging or preferring either address over the other. `address`
  keeps its meaning everywhere it is read, including every System Log entry.
- Trusting the claim for anything. It is displayed, never used to authorise,
  route or key anything.
- An `APP_VERSION` bump. **Deliberate, at the owner's direction:** the change
  is additive both ways, and it ships with the next bump rather than causing
  one. `package.ps1`'s four-source agreement is untouched because none of the
  four moves.

## Coverage

- `tools/server_checks/clients.py`: a check-in that carries `reported_address` stores it and
  `GET /clients` returns it, with `address` still the peer. A check-in without
  it stores `""`. An over-long value is capped.
- `tools/server_checks/archive.py`, where the suite already drives the
  migrations: 016 `up`, `down`, `up` on a copy of a pre-016 database.
- `tools/client_checks/wire.py`: the helper returns a dotted IPv4 string against a
  loopback server, `""` when the host does not resolve, and `checkin` sends the
  key. `tools/client_checks/remote_admin.py`: the panel paints the column.
- `tools/server_checks/windows.py`, which measures Connected Clients (#019/#020): re-run it,
  and re-derive any recorded minimum the new column moves. Do not copy an old
  number forward.

## Cascade

- **A DB column** (CLAUDE.md row): migration 016, `init_db()`'s `ALTER TABLE`,
  and the `clients` schema block in `docs/reference/database.md`, plus a
  sentence next to its "the address is what the Admin needs" saying what the
  reported address adds behind NAT.
- **An endpoint's shape**: the `POST /clients/checkin` body in
  `docs/reference/api.md` gains `reported_address?`. The `GET /clients` row, if
  it lists fields. Every client that calls it goes through `common.checkin`.
- **A new domain term**: "Reported Address" in `CONTEXT.md`, in the Check-in
  entry's list of what a Client says about itself, next to the source address
  the System Log entry already names.
- `docs/reference/apps.md`: the Connected Clients bullet (console and Remote
  Admin) if it lists the columns.
- **A shipped payload**: `common.py` and `notifier_remote.py` are client
  modules, so rebuild the client packages at release. No new module, so the
  staging and `$Payload` rows do not move.

## Verification

- `ast.parse()` every edited Python file.
- Against a running server: `POST /clients/checkin` with and without
  `reported_address`, then `GET /clients` (admin password), and read both
  addresses back.
- Run a Notifier from source against it and confirm the console's Connected
  Clients shows the laptop's own address beside the source address.
- `py -3.12 tools/gate.py` passes.

## Done when

Every check-in from a current Client records the address the Client says it
has, both Connected Clients views show it next to Source Address, older Clients
and older servers behave exactly as before, and `APP_VERSION` is unchanged.
