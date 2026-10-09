# 066 - Connected Clients on the action row; Database Location behind the console door

**Type:** feature · **Depends on:** 065 (both rewrite `ACTIONS` and `server_administration`, the same lines) · **Found by:** console review, Sep 2026 · **Issue:** [#241](https://github.com/HaithamEldesouky/AssetManager/issues/241)

## Finding

**Connected Clients** has one door and it is inside a menu: the fourth entry of
`server_administration` (`server_gui.py:6357-6358`) opens `client_list` (`:2930`).
#205 took the side column and its CLIENTS box away (`:7474-7493`, `:7539`, `:7593`), so
the window that says which installations exist, which certificate each holds and where a
command is sent is a menu away from the console it belongs on.

**Database Location** is the opposite: on the action row (`ACTIONS`, `:7198-7200`),
**ungated** (`False` in its tuple), and it is the dialog that edits `db_path` - the
setting ADR-0004 says is moved only deliberately, and the one a wrong value in stops the
server starting. `docs/reference/apps.md:87` records it on the row.

The side column is not coming back: #205 removed it deliberately and
`tools/server_checks/console.py:27-77` measures a rail of pills, not a panel. One pill
does what the box did.

## Scope

1. `ACTIONS` gains **Connected Clients**, gated, its caption carrying the count of
   installations heard from (`_client_rows` already answers it), the same way 065's hub
   carries the pending proposals. Opens `client_list(root)`.
2. `ACTIONS` loses **Database Location**; `server_administration` gains it as an entry
   opening `change_db_location()` unchanged. Behind the door, so `_console_unlock` has
   already been passed when it opens.
3. `server_administration` loses **Connected Clients**.

Rail after this: Server Administration, Lookup Sheet (065), Connected Clients, Manage
Transaction History, Import Transaction Archive, Server Settings, Display Settings -
seven. The measurement, not this ticket, says whether that fits; if it does not, Import
Transaction Archive moves into Server Administration beside Backup / Restore, and this
ticket says so in its commit.

## Not in this ticket

- Any change inside `client_list` or `change_db_location`.
- The Lookup Sheet hub - 065.

## Cascade

- `tools/server_checks/console.py:2763-2780` asserts a status chip opens Database
  Location and fails with "Database Location is reachable no other way". That sentence
  is already stale (the row, not a chip, opens it today). Open it from the Server
  Administration walk; keep the chip loop only for whatever chips remain and reword the
  failure. `tools/server_checks/db_path.py:312` keeps asserting `change_db_location`
  exists - unchanged.
- `tools/server_checks/console.py:62-77` reads the action count out of `ACTIONS`;
  confirm nothing else states six.
- `docs/reference/apps.md:87` (Database Location "opens from the action row") and `:92`
  ("Connected clients is an entry on the action row" - false against `:6357` today; the
  doc is ahead of the tree) - both rewritten to what lands.
- `console.py:134-138` requires a document to state the action row's measurement: the
  paragraph in `apps.md` is re-derived from the run, never edited by hand.
- `docs/adr/0004` gains one sentence: Database Location is behind the admin door. The
  decision is unchanged.

## Verification

- `ast.parse()` on `server_gui.py`; `py -3.12 tools/gate.py` on the diff.
- By hand: seven pills, no label truncated at the console's minimum width; Connected
  Clients opens from the rail after the door; Database Location opens from Server
  Administration and nowhere else; the count on the pill matches the window's row count.
