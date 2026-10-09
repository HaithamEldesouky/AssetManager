# 047 - tools/server-checks.py splits by check group

**Type:** refactor · **Depends on:** 043 · **Found by:** architecture review, Sep 2026 · **Issue:** [#221](https://github.com/HaithamEldesouky/AssetManager/issues/221)

## Finding

`tools/server-checks.py` is 18,758 lines - larger than `server.py` was before 035 and 036
took 8,208 lines out of it, and 036's own ticket named it out of scope: "Splitting
`tools/server-checks.py`... File it separately if wanted; it ships in no package and hurts
less." This is that ticket.

**How it runs today**, read from the file itself:

- `main()` (`tools/server-checks.py:18728`) collects every module-level name starting
  `check_` into a list, sorted by source line (`__code__.co_firstlineno`) rather than by
  name - the order groups were written in, preserved regardless of how they are split
  later.
- `--shard i/n` (`tools/server-checks.py:66-95`) slices that list **by position**,
  `checks[i - 1::n]` (`18735`), not by name or file - the comment at `70-73` states this on
  purpose: "so that adding a group needs no list kept anywhere... any slice of them is a
  valid run."
- `tools/gate.py` (`run_gate`, `tools/gate.py:164-176`) is what actually shards: it reads
  `SHARDABLE`/`SHARD_CAP`, and for `server-checks.py` builds `n` subprocess commands each
  passed `--shard i/n`, then aggregates their exit codes and printed lines.
- One staging tree, `STAGE` (`tools/server-checks.py:140`), is built once at import time
  and every group reads from it. `tools/server-checks.py:141` copies `server.py`,
  `server_gui.py`, `server_cert.py`, `ui_kit.py` into it - 041, 042 and 043 each add a
  `register_*.py` to this line, so by the time this ticket starts the tuple carries seven
  names, not four.

The file is not organised by concern the way `server.py` was - it is one flat sequence of
`check_*` functions, each self-contained (`"Groups do not hand each other state - each
builds the database it needs and tears it down"`, `tools/server-checks.py:70`), which is
what makes a mechanical split possible without touching what any single check asserts.

## Scope

A `tools/server_checks/` package, or several files - whichever keeps `main()`'s
position-sorted, sharded collection working, since that is the property `--shard` depends
on and `gate.py` calls unconditionally.

1. **Group the `check_*` functions by what they check** (the natural clusters: register/
   register_assets, register_transactions, register_engineers, server_gui, server_cert,
   mail/sync/clients per 046's split once those clusters have their own modules, and
   whatever is left over) into separate files under `tools/server_checks/`, each importing
   the shared staging setup (`STAGE`, `M`, `C`, `GUI_SRC`, etc., `tools/server-checks.py:
   140-274`) from one place rather than each file re-staging its own tree - a second
   staging tree per file multiplies the setup cost `tools/gate.py`'s own comment already
   measures (`5m47s` serial).
2. **`main()` moves to a thin `tools/server-checks.py`** (kept as the entry point `gate.py`
   already names) that imports every group module, collects their `check_*` functions the
   same position-sorted way, and runs `--shard i/n` exactly as today - the shard slice must
   still be stable across a run with no shard flag and a sharded run, which position-sort
   across all group modules (imported in a fixed order) preserves and name-sort would not.
3. **`tools/gate.py`'s `GATES`/`SHARDABLE`/`SHARD_CAP`** (`tools/gate.py:51` and
   neighbouring tables) keep pointing at `tools/server-checks.py` as the one command to
   run - `gate.py` does not need to know the package exists underneath it, only that the
   entry point still accepts `--shard i/n` and still exits nonzero on failure.
4. **`tools/gate.py` `MAP`** (`tools/gate.py:78`) gains a row for
   `r"^tools/server_checks/"` alongside the existing `r"^tools/server-checks\.py$"` row, or
   an edit inside the new package runs no gate at all - the exact failure `gate.py`'s own
   docstring names for an unrecognised path.

## Not in this ticket

- Any change to what a check asserts, or to the staging tree's contents. A structural
  split, not a rewrite of coverage.
- `tools/client-checks.py`, which is 8,782 lines and has not grown the way
  `server-checks.py` has - out of scope unless a later measurement says otherwise.
- The groups 046 plans (sync, mail, clients, system log, lookup/proposals, backup/restore)
  existing as modules yet. This ticket organises the *checks* by group; 046's clusters are
  the *server-side* code the checks exercise, and may land in either order relative to this
  one - re-check once both have a real shape, since a check group's natural split should
  follow the module it tests once that module exists.

## Cascade

- `tools/gate.py` `MAP` (`tools/gate.py:78`) - the new row, per Scope §4.
- `docs/reference/tooling.md` - `tools/server-checks.py`'s section describes a single file
  today; update it to describe the package and where a new check group goes.
- `docs/agents/ticket-workflow.md` "Finished" - names `tools/server-checks.py` as one of
  two places a check belongs; unaffected by name, but confirm the sentence still reads
  correctly once the entry point is a package's front door rather than the whole thing.
- Nothing in `CLAUDE.md`'s cascade table changes - `tools/server-checks.py` is not one of
  the shipped payloads (`package.ps1`/`installer.py` do not stage it), so
  `SOURCE_FILES`/`$SourceFiles`/`$Payload` are untouched.

## Verification

- `ast.parse()` every file in the new package.
- `py -3.12 tools\server-checks.py` (no shard) green, same pass/fail count as before the
  split - diff the "N check group(s), M assertion(s)" line against a run on `main` before
  this ticket's branch.
- `py -3.12 tools\server-checks.py --shard 1/8` through `--shard 8/8`, unioned, cover every
  group exactly once - the same guarantee the unsplit file gives today, now depending on
  import order across files rather than function order in one file, so confirm that order
  is fixed (module import order in the entry point, not filesystem or alphabetical).
- `py -3.12 tools/gate.py` and `py -3.12 tools/gate.py --all` both green, and the
  `server-checks` line still reports shard timing the way `docs/reference/tooling.md`'s
  measured numbers describe.
