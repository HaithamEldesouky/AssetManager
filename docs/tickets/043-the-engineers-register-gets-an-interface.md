# 043 - The Engineers register gets an interface

**Type:** refactor · **Depends on:** 041 · **Found by:** architecture review, Sep 2026 · **Issue:** [#217](https://github.com/HaithamEldesouky/AssetManager/issues/217)

## Finding

The last third of 039 (#210): the six functions that read and write the `members` table -
the ones 039's own finding named first (`_member_rows` 6021, `_member_row` 5998,
`_member_row_by_id` 6005 in that description; the current tree has moved since, see below)
as the clearest case of the console and the routes reading the same table through
different code.

- `_member_row(name)` - `server.py:5914`
- `_member_row_by_id(member_id)` - `server.py:5921`
- `_member_rows()` - `server.py:5937`
- `_save_member(name, admin_password, auto_approve, ...)` - `server.py:6054`
- `_delete_member(name, admin_password, authorised_as=None)` - `server.py:6232`
- `_rename_member(member_id, new_name, admin_password, authorised_as=None)` -
  `server.py:6327`

Both adapters call them today. The six appear 19 times in `server.py`'s own routes
(`GET /members`, `POST /members`, the rename and delete routes), 11 times in
`server_gui.py` as `S.<name>` (Manage Users' add/rename/delete/auto-approve controls), and
`tools/server-checks.py` calls them directly 10 times.

**Independent of 042.** Nothing in this cluster calls `_asset_key_sql` or any Assets
function - an engineer's name, password hash and auto-approve flag carry no asset
identity - so this ticket depends on 041 for the same reason every module in the chain
depends on something (`tools/package.ps1:148` is one line, see Cascade) but not because
Engineers needs Assets' data the way Transactions does. 042 and 043 may be worked in
either order once 041 lands; do not start them together, for the line they share.

## Scope

One new module, `register_engineers.py`, beside `server.py`.

1. **Move the six functions verbatim.**
2. **`server.py` imports them back** at module level, same flat-import shape as 041 and
   042, so `server_gui.py`'s `S.<name>` calls keep resolving unchanged.
3. **The connection.** Same `bind(get_db=...)` shape as 041 and 042.
4. **The password check.** `_save_member`, `_delete_member` and `_rename_member` each take
   an admin password or an `authorised_as` argument and check it inline. 038 (#209) is
   filed and open, not yet the one enforcement point rule 7 and this cluster both lean on;
   this ticket does not wait for 038 to land (it depends on 041 only) but must not move the
   password check anywhere 038 would then have to find twice - keep it exactly where it is
   inside each function, a straight move, nothing folded in.
5. **`tools/server-checks.py`'s staging tuple** (`tools/server-checks.py:141`) gains
   `"register_engineers.py"`.

## Not in this ticket

- Assets or Transactions - 041 and 042.
- Any change to the password check itself. That is 038, independent of this chain.
- The engineer list seed. `TEAM_MEMBERS` in `common.py` and `server.py`'s own seed list
  (CLAUDE.md's cascade table) are untouched - this ticket moves the functions that read
  and write the `members` table, not the fallback list clients show when the server is
  unreachable.

## Cascade

- `CLAUDE.md` - "The files" table gains `register_engineers.py`.
- `docs/reference/architecture.md` - the same row, in full.
- `docs/CODING_STANDARDS.md` "Where code goes" - gains the module.
- `tools/package.ps1:148` `$SourceFiles` - gains `register_engineers.py`. **Same line 041
  and 042 touch** - sequence against whichever of them is still in flight.
- `tools/server-checks.py:141` staging tuple, per Scope §5.
- `tools/gate.py` `MAP` - a row for `register_engineers.py`, tagged `("server",)`.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- Hit `GET /members`, `POST /members`, rename and delete against a running server, before
  and after, responses diffed.
- Open Manage Users in the Server GUI with the listener stopped and confirm add, rename,
  delete and auto-approve all still work.
- `py -3.12 tools\server-checks.py` green.
