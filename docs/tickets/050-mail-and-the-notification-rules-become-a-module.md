# 050 - Mail and the notification rules become a module

**Type:** refactor · **Depends on:** 043 · **Found by:** 046 (#220), re-derived Sep 2026 · **Issue:** [#224](https://github.com/HaithamEldesouky/AssetManager/issues/224)

## Finding

`server.py` is **9,826 lines** with 043 landed. 046 (#220) named six clusters left in it
and filed no code, on the stated grounds that its own table - measured against a
10,545-line tree - would be wrong by the time it mattered. It is: every span it gives is
out by roughly 700 lines. Everything below is re-derived by grep against the tree 043
left, which is what 046's Verification section asks of this ticket rather than of itself.

This is the first of the six. It is contiguous, and it is two banners:

- `# ─── Mail ───` - `server.py:7680`.
- `# ─── Which events are mailed, and to whom ───` - `server.py:7974`.
- The block ends at `8145`, immediately before `# ─── The external asset system ───`
  at `8146`.

8145 - 7680 + 1 = **466 lines**. 046's table said `8459-8954`, 496 lines.

Inside it: `_smtp_cfg` (`7709`), `_secret_set` (`7727`), `_secret_get` (`7766`),
`_smtp_secret_set` / `_smtp_secret_get` / `_smtp_secret_stored` (`7791` / `7797` /
`7802`), `_save_mail_settings` (`7807`), `_send_test_mail` (`7847`), `_smtp_send_now`
(`7872`), `_send_mail_worker` (`7934`), `_send_mail` (`7947`), `_notify_rules` (`8000`),
`_save_notify_rules` (`8028`), `_notify_gate` (`8076`), `_notify_of` (`8099`).

**Two names in the span are not mail's.** `_secret_set` (`7727`) and `_secret_get`
(`7766`) are the generic stored-secret pair. `_smtp_secret_set` calls the first at
`server.py:7793`; `_sync_secret_set` calls the same one at `server.py:8207`, from the
cluster 051 moves. They sit under the Mail banner because mail needed them first, not
because they belong to mail. Moving them would leave the sync module importing the mail
module for a helper neither owns.

**`_notify_of` is called from inside the System Log cluster.** `server.py:7349`, inside
`_log_event`, is `_notify_of(row[2], row[3], row[1], row[4], row[5], row[0])`. That call
is the seam between this ticket and 053; whichever lands first, the other reaches across
`bind()` rather than by import.

## Scope

One new module, `server_mail.py`, beside `server.py`.

1. **Move `server.py:7680-8145` verbatim**, less `_secret_set` and `_secret_get`
   (`7727-7790`), which stay where they are.
2. **It reaches back through `bind()`, and never imports `server`.** `applaunch.py` runs
`server.py` as `__main__` through `runpy.run_path`, so `import server` from inside the
new module executes the whole server a second time rather than reaching the one running -
the reason `server_cert.py` set this pattern and `register_assets`,
`register_transactions`, `register_engineers` and `server_gui` all repeat it. Build the
handed-over name list with a `symtable` sweep over the moved block rather than by hand:
036's "How it landed" note found fourteen names 035's hand-written plan had missed, and
045 built its list that way for that reason.
3. **`server.py` imports it at module level and binds it** in the block that already does
   this (`server.py:7357-7430`), then imports the moved names straight back into its own
   namespace - which is what leaves `server_gui.py`'s `S._save_mail_settings` and the
   routes at `9286-9441` resolving unchanged, and what made 043 a move with no call site
   edited.

## Not in this ticket

- `_secret_set` and `_secret_get`. They are shared with 051 and stay in `server.py` until
  a ticket exists for the pair itself.
- Any change to what is mailed, to the rules table, or to SMTP behaviour. A move, not a
  redesign.
- The System Log (053) or the external asset system (051).
- The `/admin/mail`, `/admin/mail/test` and `/admin/notify_rules` routes
  (`server.py:9286-9441`). They stay in `server.py`, the way 041-043 left theirs.

## Sequencing

046's six all rewrite `tools/package.ps1:149`, one line, so they are a chain rather than
six independent tickets: 050, 051, 052, 053, 054, 055, merged in that order, one at a
time. The code in most of them is independent; the line is not. This is the same reason
035 and 036 were sequenced, and the reason 041 had to land before 042 and 043.

## Cascade

The set 043 paid for `register_engineers.py`, re-found against this tree rather than
copied from 046:

- `CLAUDE.md`'s files table - a row for the new module.
- `docs/reference/architecture.md`'s table - the same row, at the length that table's
  rows run to.
- `docs/CODING_STANDARDS.md` "Where code goes" (`docs/CODING_STANDARDS.md:12`, the module
  list at `:41`) and the sentence at `:91` naming the modules `server.py` imports.
- **`tools/package.ps1:149` `$SourceFiles`** - one line, and **all six of 046's tickets
  rewrite it**. This is the trap `docs/agents/ticket-workflow.md` "Two tickets that
  cascade to the same line" describes, and the reason 035 and 036 were sequenced over the
  same line. The six are a chain, merged one at a time, never two in parallel.
- `tools/server-checks.py:141-143`, the staging tuple, which carries seven names today; a
  `*_SRC` read beside `ENG_SRC` (`tools/server-checks.py:242`) if any group asserts
  against the module's own source; and the reload block at
  `tools/server-checks.py:9701-9745`, which pops and restores `register_engineers` by
  name and needs the same for this module if a group re-imports `server.py`.
- `tools/gate.py`'s `MAP` (`tools/gate.py:85-90`) - a row tagged `("server",)`, or an edit
  to the new file runs no gate at all, the failure `gate.py`'s own docstring names.
- `tools/cascade-audit.py` - `SHIPS` (`:1448`), `BESIDE_MODULES` (`:1563`), `_FIT_APPS`
  (`:1657`) and `_EVENT_SOURCES` (`:1877`). Check each against this module rather than
  copying four bullets forward: `SHIPS` yes, the file rides in the server payload;
  `_EVENT_SOURCES` only where the moved block calls `_log_event`, which is a grep and not
  an assumption; `_FIT_APPS` counts windows and a server module draws none.
- **Not** `installer.py`'s `SOURCE_FILES`, and **not** `tools/bundle-client.ps1`. Both are
  the client payloads; a server module ships in neither, which is what makes this cascade
  shorter than 044's and 045's.

Specific to this ticket: `_EVENT_SOURCES` **does** need the new module -
`_save_mail_settings` and `_save_notify_rules` each call `_log_event`, and
`docs/system-log-events.md` holds their rows.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- **Import `server.py` headless and confirm it still imports.** The `bind()` pattern's one
  real failure mode is a name handed over after something has already read it.
- `py -3.12 tools\server-checks.py` green, and the same "N check group(s), M
  assertion(s)" line as a run on `main` before the branch - a move changes no assertion.
- Send a test mail from the Server GUI's Mail Settings window, and confirm
  a notification rule still gates an event it gated before.
