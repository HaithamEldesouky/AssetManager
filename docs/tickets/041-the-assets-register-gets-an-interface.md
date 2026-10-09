# 041 - The Assets register gets an interface

**Type:** refactor · **Depends on:** 036, 038 · **Found by:** architecture review, Sep 2026 · **Issue:** [#215](https://github.com/HaithamEldesouky/AssetManager/issues/215)

## Finding

039 (#210) named one Register for Assets, Transactions and Engineers and put it last in
the chain because it is the largest single piece. It is also three concerns wearing one
name: an Asset row, a Transaction row and an Engineer row are different tables with
different callers, and folding all three into one module the same size as 039 described
would just move the drift 039 is standing against into a bigger file instead of removing
it. Filing one ticket per table gives each a real seam - a route adapter and a console
adapter apiece - instead of a single module three times the size of 038's or 036's.

This ticket is the Assets third: the four functions that read and write the `assets`
table.

- `_load_assets()` - `server.py:4512`
- `_save_asset(asset_number, serial_number, asset_type, asset_model="", ...)` -
  `server.py:4539`
- `_delete_asset(asset_id, actor="Admin (Server GUI)")` - `server.py:4615`
- `_asset_key_sql(number="asset_number", serial="serial_number")` - `server.py:5530`

Both adapters call them today, not one. `_load_assets`, `_save_asset` and `_delete_asset`
are reached from `server.py`'s own routes and from `server_gui.py`'s console windows
(`manage_assets`, `asset_proposals`, `asset_sync`) as `S._load_assets`,
`S._save_asset`, `S._delete_asset` - the `bind()` pattern 035 and 036 set, `server_gui.py`
holding the module object `S` and reaching back into whatever stayed in `server.py`. A
count against the current tree: `_load_assets(`/`_save_asset(`/`_delete_asset(`/
`_asset_key_sql(` appear 19 times in `server.py`, 4 times in `server_gui.py`
(`S.<name>`), and `tools/server-checks.py` calls them directly 54 times - "the register
directly for what is not HTTP", the shape 039 §3 asks for, already true of this cluster
before the module exists to name it.

`_asset_key_sql` is not a query function, it is the identity rule the other two tables
lean on: `_modify_transaction` builds a WHERE clause against it at `server.py:6726`
(`_asset_key_sql()` and `_asset_key_sql("?", "?")` in the same call), and
`_create_transaction` resolves an asset's canonical number, serial and type through
`_load_lookup_table()` before ever touching the `transactions` table. Neither Transactions
ticket (042) nor Engineers ticket (043) can be scoped without Assets moving first, which
is why both depend on this one and not the other way round.

## Scope

One new module, `register_assets.py`, beside `server.py`.

1. **Move the four functions verbatim.** No behaviour change, no signature change, no
   renaming - the same discipline 035 and 036 used.
2. **`server.py` imports them back**, `from register_assets import (_load_assets,
   _save_asset, _delete_asset, _asset_key_sql)`, at module level. The module reads and
   writes SQLite only; nothing in it draws, so it needs no deferred-import treatment.
3. **The connection.** `_load_assets`, `_save_asset` and `_delete_asset` call `get_db()`
   today; `get_db` stays in `server.py` for this ticket (039's finding named it as part of
   the same problem, but moving the connection itself is not required to give Assets a
   seam) - import it back the same way the four functions come in, `from server import
   get_db` would be the second-server trap `server_cert.py`'s docstring already explains,
   so it is handed in through a small `bind()` the way `server_cert.py` takes its paths:
   `register_assets.bind(get_db=...)`, called once from `server.py` at import.
4. **`server_gui.py` keeps reaching the four functions as `S.<name>`.** Because `server.py`
   re-imports them into its own namespace, `S._load_assets` etc. still resolve - no change
   to `server_gui.py` is needed for this ticket, verify by grep rather than assuming it.
5. **`tools/server-checks.py`'s staging tuple** (`tools/server-checks.py:141`, currently
   `("server.py", "server_gui.py", "server_cert.py", "ui_kit.py")`) gains
   `"register_assets.py"`, or the helpers that call `_load_assets`/`_save_asset`/
   `_delete_asset`/`_asset_key_sql` directly against `M.<name>` stop resolving against the
   staged copy.

## Not in this ticket

- Transactions or Engineers. Those are 042 and 043, both behind this one.
- `_create_transaction`'s reliance on `_load_lookup_table()`. That function is the xlsx
  lookup sheet reader, not an Assets-table function, and stays where it is; 039's finding
  and rule 11 both treat the sheet as a separate concern from the `assets` table since 024.
- The schema, and `_import_records_xlsx`'s direct insert into `transactions` - both
  explicitly out of scope in 039 and unchanged by splitting it.
- Deleting anything. The four functions move; whether `register_assets.py` grows further
  internals is a later ticket's choice, not this one's.

## Cascade

- `CLAUDE.md` - "The files" table gains a `register_assets.py` row.
- `docs/reference/architecture.md` - the same row, in full.
- `docs/CODING_STANDARDS.md` "Where code goes" - gains the module.
- `tools/package.ps1:148` `$SourceFiles` - gains `register_assets.py`, or the release ships
  a server that cannot start. This is the line 035 and 036 already shared and were
  sequenced over; 041, 042 and 043 all touch it too, which is why they are sequenced
  against each other rather than started together.
- `tools/server-checks.py:141` staging tuple, per Scope §5.
- `tools/dev-run.ps1:283` `$ClientShared` is unaffected - this is server-side, not a
  client module - but check before assuming; `dev-run.ps1` may stage server sources by
  name elsewhere and needs the same grep 042 and 043 owe their own cascades.
- `tools/gate.py` `MAP` (`tools/gate.py:78`) - add a row for `register_assets.py` mapped
  to `("server",)`, the same tag `server_gui.py` carries, or a change to the new file runs
  no gate at all.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- Hit every route that reads or writes an asset (`GET /assets`, the asset side of
  `POST /transactions`, the lookup-import endpoints) against a running server, before and
  after, and diff the responses.
- Open Manage Assets, Asset Proposals and Asset Sync in the Server GUI with the listener
  stopped, and confirm they still read - the guarantee `server.py:6027` (now moved)
  records, unchanged by this ticket.
- `py -3.12 tools\server-checks.py` green.
