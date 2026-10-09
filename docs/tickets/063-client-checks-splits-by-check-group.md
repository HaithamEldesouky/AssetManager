# 063 - tools/client-checks.py splits by check group

**Type:** refactor · **Depends on:** nothing (sequence after the 2.6.0 release) · **Found by:** modularisation review, Sep 2026 · **Issue:** [#238](https://github.com/HaithamEldesouky/AssetManager/issues/238)

## Finding

`tools/client-checks.py` is 9,050 lines, 69 top-level `check_*` functions
(`grep -cE '^def check_' tools/client-checks.py`). `#221`'s own ticket named it out of
scope at the time ("8,782 lines and has not grown the way `server-checks.py` has - out of
scope unless a later measurement says otherwise"); it has grown since, past
`server.py`'s pre-035 size, and this is that later measurement.

`tools/server_checks/` (`#221`, landed) is the model: a package with one `stage.py`
holding the shared staging tree and the `ok`/`bad`/`skip`/`head`/`eq` reporting helpers
plus the counters, one file per group of `check_*` functions, and a thin entry point
(`tools/server-checks.py`, 18,758 lines before the split, now the front door) that imports
every group module, collects their `check_*` functions position-sorted by
`__code__.co_firstlineno`, and runs the `--shard i/n` slice `tools/gate.py` asks for
(`ls tools/server_checks` lists 27 files: `stage.py`, `__init__.py` and 25 group modules).
`tools/client-checks.py`'s own `main()` (`:9020-9046`) already does the position-sort and
`--shard` slice the same way, over one flat file - the mechanical part of the split is
already proven to work, since it is the same collection logic minus the package boundary.

**`--group NAME`, which `server-checks.py` gained in the split, is absent from
`client-checks.py` today** (`grep -n "\-\-group" tools/client-checks.py` finds nothing) -
`docs/CODING_STANDARDS.md:512-522` says so explicitly: "`client-checks.py` has no such
flag - it is one module, so running one check there is loading it by path, calling the
`check_*` function by name and printing `fails`." That sentence describes today's
one-file shape and is wrong the moment this ticket lands.

**The two popup groups.** `#194`/`#201` drive four `check_*` functions against real `after`
timers turned down to the smallest interval a wall clock can show:
`check_the_popup_hides_itself_and_comes_back` (`:5293`),
`check_dismiss_defers_the_popup_and_never_answers_it` (`:5447`),
`check_what_the_popup_timers_may_be_set_to` (`:5640`), and
`check_only_the_notifier_popup_is_topmost` (`:5695`). None shares module-level state with
any other - each builds and tears down its own `tk.Tk()` root, the same "groups hand each
other no state" property `tools/server_checks/stage.py` states for its own package, and no
monkeypatched `time.time`/`time.sleep` exists anywhere in the file
(`grep -n "time\.time\s*=\|time\.sleep\s*=" tools/client-checks.py` is empty) that would
need them in one process together. **What actually ties them together is not shared state
but shared margin**: `tools/gate.py:56-65`'s own comment says running more than four
shards concurrently steals enough wall-clock slack from these four groups' real timers
that both fail - measured, not guessed, four shards green twice at 872 assertions
matching a serial run, eight shards failed both times - which is why
`tools/gate.py:73` caps `SHARD_CAP = {"client": 4}`. The constraint this split has to
preserve is the **cap on concurrent shards**, not co-locating the four groups in one file
or one shard slot; splitting them into separate group modules changes nothing about it,
since `--shard` slices by position across whichever modules the entry point imports in a
fixed order, the same guarantee `#221`'s ticket held for `server-checks.py`.

## Scope

A `tools/client_checks/` package, modelled on `tools/server_checks/` exactly:

1. **A `stage.py` inside the new `tools/client_checks/` package** - the shared staging tree (`STAGE`, `APPS`,
   `SRC_FILES`/`SRC`, the `config.json` fixture, `sys.path` insertion) and the reporting
   helpers (`ok`, `bad`, `skip`, `head`, `eq`) plus their counters, moved out of
   `tools/client-checks.py`'s current top section, the same split `stage.py`'s own
   docstring describes for the server side.
2. **Group the 69 `check_*` functions by what they check** into files under
   `tools/client_checks/` - the natural clusters visible in the current file's own
   headings and the Cascade table below: window-size groups per app (`storekeeper`,
   `notifier`, `installer`), the masked-field group, the two source-only groups (no
   `geometry()` branching, one `_fit`), the offline/`ReadTimeout`/`ConnectTimeout` group,
   the two `applaunch.py` groups, and the popup-timer group holding the four `#194`/`#201`
   checks named in Finding together (not because they must run in the same process, but
   because they are one concern and grouping them the way `server_checks/console.py` groups
   the console's checks keeps a reader from having to know the cap's reasoning to find
   them).
3. **`tools/client-checks.py` becomes the thin entry point**, kept as the command
   `tools/gate.py` already names: imports every group module, collects `check_*` the same
   position-sorted way `server-checks.py`'s does, and runs `--shard i/n` exactly as today.
4. **Add `--group NAME`** (and `--list-groups`), the flag `#221` gave the server side and
   this file has never had - `docs/CODING_STANDARDS.md:512-522`'s "no such flag" sentence
   is what makes this an addition rather than a preserved behaviour.
5. **`tools/gate.py`'s `GATES`/`SHARDABLE`/`SHARD_CAP`** (`:51-73`) keep pointing at
   `tools/client-checks.py` as the one command to run, and **`SHARD_CAP["client"] = 4`
   stays exactly 4** - nothing in this split changes the timer-margin measurement that cap
   is against, so it is not re-derived, only carried over untouched.
6. **`tools/gate.py`'s `MAP`** (`:111`, the existing `(r"^tools/client-checks\.py$",
   ("client",))` row) gains a second row, `(r"^tools/client_checks/", ("client",))`,
   matching `:110`'s row for `tools/server_checks/`.

## Not in this ticket

- Any change to what a check asserts, the staging tree's contents, or the fixtures it
  builds. A structural split, not a rewrite of coverage.
- `tools/server_checks/`, already split by `#221`.
- Deciding the exact group boundaries beyond what Finding and Scope §2 name - the precise
  file-per-cluster mapping is this ticket's implementation, not a decision to make in
  advance of grepping the current file's own section banners.

## Cascade

- `tools/gate.py:111` `MAP` - the new row, per Scope §6.
- `docs/CODING_STANDARDS.md:512-522` - the "`client-checks.py` has no such flag" sentence
  is corrected to describe `--group`/`--list-groups` the way the surrounding paragraph
  already describes `server-checks.py`'s; the by-hand one-check invocation two paragraphs
  down (`py -3.12 -c "import sys; sys.path.insert(0, 'tools'); from server_checks import
  console, stage; ..."`) gains the equivalent client-side line once `tools/client_checks/`
  exists, on the same page rather than assuming a reader infers it.
- `docs/CODING_STANDARDS.md:420-424` (the "Tests" bullet: "`tools/client-checks.py` - the
  same idiom for the three client apps' windows... Its own file rather than more groups in
  `server-checks.py`") - the sentence is about why it is not folded into the server suite,
  which stays true; it does not need to say "package" to remain accurate, but confirm
  against the finished prose rather than assuming.
- `docs/reference/tooling.md:1359-1420`+ (the `### tools/client-checks.py` section) -
  describes a single file today the way `tools/server-checks.py`'s section described one
  before `#221`; rewrite it the same way that section was rewritten, including the
  `--group`/`--list-groups` addition and the package layout.
- `docs/reference/tooling.md:1649` (`client-checks.py`'s two popup groups (#194, #201)
  drive real `after` timers...") and `tools/gate.py:56-65`'s comment - both describe the
  shard-count cap; confirm both still read correctly once the four checks live in a named
  group file rather than loose in one flat file, and correct "68 groups" at
  `docs/reference/tooling.md:1725` if the count printed by a real run differs from 69 -
  re-derive it rather than copying either number forward.
- Nothing in `CLAUDE.md`'s cascade table changes - `tools/client-checks.py` is not one of
  the shipped payloads (`package.ps1`/`installer.py`/`bundle-client.ps1` do not stage it),
  so `SOURCE_FILES`/`$SourceFiles`/`$Payload` are untouched, the same conclusion `#221`'s
  ticket drew for the server side.

## Verification

- `ast.parse()` every file in the new package.
- `py -3.12 tools\client-checks.py` (no shard) green, same "N check group(s), M
  assertion(s)" count as a run on `main` before this ticket's branch - diff the two lines.
- `py -3.12 tools\client-checks.py --shard 1/4` through `--shard 4/4`, unioned, cover every
  group exactly once, matching `SHARD_CAP["client"] = 4`'s existing cap - do not test a
  higher shard count, since `tools/gate.py`'s own measurement already found 8 unreliable
  and this ticket does not reopen that question.
- `py -3.12 tools\client-checks.py --group <name>` for at least the popup-timer group and
  one window-size group, confirming `--list-groups` prints the finished file list.
- `py -3.12 tools/gate.py` and `py -3.12 tools/gate.py --all` both green.
