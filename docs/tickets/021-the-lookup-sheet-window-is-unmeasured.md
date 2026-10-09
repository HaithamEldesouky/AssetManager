# 021 - The Lookup Sheet window is unmeasured, and 019 never noticed

**Type:** test coverage · **Depends on:** 019 · **Found by:** verifying 020 (CHECK 9)

## Finding

`tools/server-checks.py` never opens the Lookup Sheet. The string `manage_assets` appears
in it **zero times**, and the window-size group's run prints no line for it - not a
measurement, not a drag, not a floor.

Two windows are missing, not one:

| window | opened at | sizes itself with | axes |
|---|---|---|---|
| Lookup Sheet (`manage_assets`) | `server.py:4863` | `minsize(frow.min_width() + 36, 420)` then `ui_kit.fit(win, 720)` | **no `resizable` call at all** - draggable on both |
| its asset form (`form`, inside it) | `server.py:5002` | `resizable(False, False)` then `ui_kit.fit(dlg, 440)` | fixed on both |

**This is 018's lesson recurring, and 019 walked past it.** 019's own ticket names Lookup
Sheet as one of the four both-axes windows, lists it at `server.py:4863` with the floor
`frow.min_width() + 36, 420`, and its Verification says to "expect the four windows above
to move off the 'so neither is judged' line and onto a" floor line. **Three did.** Manage
Records, System Log and Connected Clients each print a floor line; the fourth prints
nothing, and the run still reported 106 groups and exited 0. That is exactly the failure
018 wrote down - "a window that silently produces no line is indistinguishable from one
the harness forgot" - and this time it hid a window from the very assertion that had just
been written for it. 020's defect was in that category. Nobody knows whether this one is,
because nobody has measured it.

## Why the openers miss it

The group reaches windows three ways: the action row's pills, a handful of named openers,
and the status chips. Lookup Sheet is on none of them. It is reached from a `tk.Button`
**inside** the Database Location dialog (`server.py:7725`), which the gate opens as
`status chip 1`, measures, and closes without pressing anything in it - unlike Manage
Records and Connected Clients, whose inner controls it does press.

**The existing `press` helper cannot reach it as it stands.** `press` looks through
`pills_of`, which collects `ui_kit.Row` pills off widgets carrying `_ui_row`
(`tools/server-checks.py:1603`), and this control is a plain `tk.Button`. A
`press(chip1, "Lookup Sheet")` would report "no control matching" rather than opening
anything - so the fix is a way to reach a `tk.Button` by its text, not a new entry in a
list.

The asset form has a second wrinkle: `add_asset` and `edit_asset` both call `unlocked()`
first, so the form only opens once the admin password in that window's own field has been
accepted. The harness already stages its own `admin_config.json`, so it knows a password
that works; it has to type it into `admin_e` before pressing Add.

## Scope

`tools/server-checks.py` only. No change to `server.py` is expected - both windows already
size themselves the way the rule asks, and whether they hold is the question this ticket
exists to answer rather than to assume.

Do **not** answer it by adding Lookup Sheet to an ignore list, and do not call it measured
because it calls `ui_kit.fit`: `fit` is what Connected Clients did not have, and Manage
Users called `fit` and still lost its bottom control (017).

## Verification

Needs a display. Both windows should produce lines in the window-size group:

- Lookup Sheet, draggable on both axes, reported rather than judged on its opening size,
  **and** judged at its own `420`-high floor the way 019 holds the other three.
- its asset form, fixed on both axes, judged against what its children ask for.

The group count rises. Whether either line is an `[OK]` is not decided in advance.

## Not in this ticket

`CLAUDE.md` says of the same group that `tools/server-checks.py` "opens every window in
the file". That sentence was false for the System Log until 018 and is false for these two
now. Whether it should be narrowed to what the gate actually enumerates, or kept as the
standard the gate is held to, is a question about the sentence rather than about this
window - and the answer is worth nothing until the gate has been made to measure them.
