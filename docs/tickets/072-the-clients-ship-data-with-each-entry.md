# 072 - The clients ship structured data with each entry

**Type:** feature · **Depends on:** 071 (the column and the parameter it writes into) · **Found by:** System Log review, Sep 2026 · **Issue:** [#247](https://github.com/HaithamEldesouky/AssetManager/issues/247)

## Finding

A client entry is `{ts, event, detail, level, actor}` (`common.py:1033` `log_event`,
`:1089` `ship_log`, batch of `LOG_BATCH` 50 to `POST /clients/log`), and the server's
`_record_log` (`server_log.py:593-629`) copies those five into `_log_event`. After 071
the server can hold `data` and the clients cannot send it, so every Storekeeper and
Notifier event stays prose-only.

## Scope

1. `common.log_event(..., data=None)`: same dict, same serialisation and cap as the
   server's; written into the local `client.log` line as a trailing JSON field so the
   file stays one line per entry; queued and shipped as a sixth key `data`.
2. `_record_log` reads `data` where present and passes it on. **Additive both ways**:
   an old server ignores a key it does not read (`_record_log` picks named keys), an
   old client sends none and the column is NULL - the mid-rollout rule of `CLAUDE.md`'s
   cascade section, held without a flag.
3. Convert the client call sites 071's list has server-side twins for, and no others.

## Not in this ticket

- New client events. None.
- Any change to the batch size, queue or rotation.

## Cascade

- `docs/reference/api.md` `POST /clients/log` row - the entry shape gains `data`.
- `docs/reference/files-on-disk.md` - `client.log` line format.
- `tools/client-checks.py` - the check that reads a `client.log` line, if one asserts
  its shape; grep before assuming none.
- `docs/system-log-events.md` - the converted client rows say what `data` carries.

## Verification

- An old server (pre-071 build) accepts a batch carrying `data` and writes the row.
- A new server writes `data` from a new client and NULL from an old one.
- `py -3.12 tools/gate.py` on the diff; `ast.parse()` on `common.py`, `server_log.py`.
