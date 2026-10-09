# 042 - The Transactions register gets an interface

**Type:** refactor · **Depends on:** 041 · **Found by:** architecture review, Sep 2026 · **Issue:** [#216](https://github.com/HaithamEldesouky/AssetManager/issues/216)

## Finding

The second third of 039 (#210), split out for the reason 041 gives: one Register the size
039 described is three tables under one name, and Transactions is its own seam.

- `_create_transaction(data, timestamp=None, actor=None)` - `server.py:5575`
- `_cancel_transaction(tid, reason, cancelled_by="", password=None, ...)` -
  `server.py:6609`
- `_modify_transaction(tid, fields, actor="Admin (Server GUI)", ...)` - `server.py:6910`
- `_pending_rows(member)` - `server.py:5737`

Both adapters call them today. `_create_transaction`, `_cancel_transaction`,
`_modify_transaction` and `_pending_rows` appear 11 times in `server.py`'s own routes,
3 times in `server_gui.py` as `S.<name>` (Manage Records' cancel and modify controls,
and the Add Transaction dialog reached from `manage_records`), and `tools/server-checks.py`
calls them directly 40 times - already the register-not-HTTP shape 039 §3 asks for.

**The identity check runs through Assets, not through this table.** `_modify_transaction`
builds its WHERE clause with `_asset_key_sql()` at `server.py:6726` - moved to
`register_assets.py` by 041 - and `_create_transaction` resolves the canonical asset
number, serial and type through `_load_lookup_table()` before it ever writes a row. A
Transactions module that does not import `register_assets` cannot enforce rule 6, which is
the concrete reason this ticket is sequenced behind 041 rather than filed independently of
it - not a preference, a dependency 041's own finding names and this one confirms from the
other side.

## Scope

One new module, `register_transactions.py`, beside `server.py`.

1. **Move the four functions verbatim.** Same discipline as 041: a move plus the imports
   it needs, not a redesign.
2. **`server.py` imports them back** at module level, the same flat-import shape 041 uses,
   so `server_gui.py`'s `S.<name>` calls keep resolving with no change on that side.
3. **`register_transactions.py` imports `register_assets`** for `_asset_key_sql`, and calls
   back into it rather than re-deriving the WHERE clause - the whole point of 041 landing
   first.
4. **The connection.** Same `bind(get_db=...)` shape 041 gives `register_assets.py`; do not
   invent a second pattern for the same problem.
5. **`tools/server-checks.py`'s staging tuple** (`tools/server-checks.py:141`) gains
   `"register_transactions.py"` alongside `"register_assets.py"`.

## Not in this ticket

- Assets or Engineers. 041 is behind this one; 043 is independent of it (both depend on
  041, neither on the other) and files separately.
- `_create_transaction`'s second writer, `_import_records_xlsx` inserting into
  `transactions` directly at `server.py:4313` - 039 named this out of scope and it stays
  out here; a refactor and a rule-6 fix in one ticket is two tickets.
- The schema and the migration.

## Cascade

- `CLAUDE.md` - "The files" table gains `register_transactions.py`.
- `docs/reference/architecture.md` - the same row, in full.
- `docs/CODING_STANDARDS.md` "Where code goes" - gains the module.
- `tools/package.ps1:148` `$SourceFiles` - gains `register_transactions.py`. **Same line
  041 and 043 also touch** - sequenced, not parallel, the same trap 035/036 hit over
  `tools/package.ps1:147` before the certificate module existed.
- `tools/server-checks.py:141` staging tuple, per Scope §5.
- `tools/gate.py` `MAP` - a row for `register_transactions.py`, tagged `("server",)`.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- Hit `POST /transactions`, the cancel and modify routes, and the pending-queue read
  against a running server, before and after, responses diffed.
- Open Manage Records in the Server GUI with the listener stopped and confirm cancel and
  modify still work, and that an asset absent from the lookup sheet is still refused with
  `code: "not_in_lookup"` - rule 6, unmoved by this ticket but reachable only through
  041's module now, which is the fact this verification exists to confirm.
- `py -3.12 tools\server-checks.py` green.
