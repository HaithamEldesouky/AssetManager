# 071 - A System Log entry carries structured data, and its sentence reads it

**Type:** feature · **Depends on:** nothing · **Found by:** System Log review, Sep 2026 · **Issue:** [#246](https://github.com/HaithamEldesouky/AssetManager/issues/246)

## Finding

A System Log row is nine columns (`server.py:3878-3889`; `database.md:419`): `ts`,
`component`, `event`, `level`, `actor`, `detail`, `client_id`, `address`, `client_ts`.
`detail` is one free line, 400 characters, in whatever shape each call site chose -
`"was %s  ->  now %s"` for `cert.installed` (`server_gui.py:6006`), a field diff
`_log_diff` (`server_log.py:537`) has to parse back out of `transaction.modified`, a
bare fingerprint for `cert.removed`. There are around a hundred writers.

The reading side is already good and is what to build on: `EVENT_SENTENCES`
(`server_log.py:191-339`) gives every event a verb phrase, `event_sentence(event,
actor, detail)` (`:345`) renders `actor + phrase + " - " + detail`, the window shows it
as the **meaning** column (`server_gui.py:3589`) and the export writes the same columns
(`server_archive.py:680`). What cannot be done is to read a fact back out of a row -
which asset, which client, which port - without parsing prose, and a phrase cannot
name a value it was never handed. That is the "future proof" gap: every new question
asked of the log is a new regex over `detail`.

## Scope

1. **`system_log.data`** TEXT, nullable, a JSON object or NULL. Migration
   `015_system_log_data.py` in the shape `014` set; `init_db()`'s idempotent `ALTER
   TABLE` beside `:3858`; `down()` keeps the column (`database.md:480`'s rule).
2. **`_log_event(..., data=None)`** (`server_log.py:368`): a dict, serialised with
   `sort_keys`, capped at `LOG_DETAIL_MAX` bytes and dropped to NULL with the event
   still written where it exceeds - never a refused entry.
3. **`EVENT_SENTENCES` values may be templates.** `event_phrase(event, data=None)`
   formats the phrase with `data` where it has `{keys}`, and falls back to the bare
   phrase where `data` is None or a key is missing - a row written before this ticket
   reads exactly as it does today. `event_sentence` takes `data` and passes it through.
   `_log_rows` and `_log_entry` return the column; the window's meaning column and the
   export call the same function they call now.
4. **The mail hook** (`server_mail.py`) does not call `event_sentence` today (zero
   matches); it renders through it after this - one renderer, three readers.
5. **Convert the call sites this ticket names and no others**: `cert.installed`,
   `cert.removed`, `cert.cutover`, `server.config_changed`, `transaction.modified`
   (so `_log_diff` reads `data` first and parses `detail` only for old rows). `detail`
   keeps being written beside `data` at each of them, so an old build's export still
   has its line. The rest of the hundred convert as they are touched.

## Not in this ticket

- Rewriting every `_log_event` call. The templates fall back, so nothing forces it.
- A new export format. `.xlsx` with the meaning column is the human-readable one and
  exists (`server_gui.py:3814`).
- Clients shipping `data` - 072.

## Cascade

- The "a DB column" row: migration, `init_db()`, `database.md:419` schema block.
- The "a `_log_event` call" row: no new event names; the five converted rows in
  `docs/system-log-events.md` say what `data` carries.
- `docs/reference/api.md` - none: no route returns the log (`system_log`'s docstring).
- `tools/cascade-audit.py` holds `EVENT_SENTENCES` equal to `system-log-events.md`;
  a template's `{key}` must not break that comparison - run it before assuming.
- `docs/reference/files-on-disk.md` - none.

## Verification

- `py -3.12 tools/migrate.ps1`-driven up and down on a copy of a real `assets.db`; old
  rows render unchanged in the window and the export.
- A converted event shows its values in the meaning column; a row with `data` NULL
  shows the bare phrase.
- `py -3.12 tools/gate.py` on the diff; `ast.parse()` on every file touched.
