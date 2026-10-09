# 040 - The last duplicated client helpers move into common.py

**Type:** refactor · **Depends on:** nothing · **Found by:** architecture review, Sep 2026 · **Issue:** [#211](https://github.com/HaithamEldesouky/AssetManager/issues/211)

## Finding

Rule 10 says shared client code lives in `common.py`. Four helpers are instead copied into
both clients, two of them under different names:

| helper | Notifier | Storekeeper | lines | state |
|---|---|---|---|---|
| `_has_client_package` | 275-313 | 37-85 | 88 | identical |
| `_mark` | 395-424 | 184-209 | 55 | identical |
| `load_config` / `load_cfg` | 208-214 | 97-117 | 28 | identical, renamed |
| `save_config` / `save_cfg` | 215-219 | 118-130 | 18 | identical, renamed |

About 190 lines. A fix to any of them has to be made twice, and the two names for one act
are how the second copy gets missed.

`common.py` itself is in good shape - 1,382 lines, 46 functions, zero tkinter imports, one
deliberate bridge to the Tk thread (`confirm_on_tk_thread`, 241-271). It is the only module
in this repo whose interface is narrower than its implementation. This ticket just finishes
the job.

## Scope

1. **Move the four across, under one name each.** `load_config` and `save_config`, since
   the Notifier's names are the ones `common.py`'s existing naming fits.
2. **Record why each moved** in the module docstring, as `CODING_STANDARDS.md:24` requires.

**`_tag_status` stays where it is.** Notifier 341-372 and Storekeeper 152-183 look like a
fifth pair, but they have genuinely diverged - the Notifier filters by client at line 372.
`CODING_STANDARDS.md:24` says what a command *does* stays in the app.

## Not in this ticket

- Anything in `ui_kit.py`. `_mark` renders an icon and arguably belongs there rather than
  in `common.py`; that argument is worth having separately and is not worth blocking 190
  lines of duplication on.
- Deepening `common.py`. It does not need it.

## Cascade

- `CLAUDE.md` - rule 10's wording only if it gains an exception. It should not.
- `docs/reference/architecture.md` - the `common.py` row. **~1,931 characters on one
  line**, so sequence against anything else touching it.
- `tools/bundle-client.ps1` `$Payload` and `installer.py:49` `SOURCE_FILES` - unchanged
  here, since no new file appears. Confirm rather than assume.

## Verification

- `ast.parse()` every file touched.
- `py -3.12 tools/gate.py --all`.
- Start both clients offline and confirm each reads and writes its config, and that the
  update check still finds a staged package.
