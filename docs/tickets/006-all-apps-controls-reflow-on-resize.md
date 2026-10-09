# 006 - All apps: controls reflow when the window is resized

**Type:** enhancement · **Depends on:** 002, 003, 004, 005

## What is asked

Controls in any app should adjust to the window size when the window is resized.

## Where it stands today

`ui_kit.fit(win, width)` sizes 19 windows **at open** - the height from what the children
ask for, the width from whichever of the argument and the request is larger - and
`ui_kit.row_of` already lays a toolbar or footer out against the width it has, dropping to
short labels and then wrapping. What does not follow a drag: fixed `w=` / `width=` widgets
and `pack`-anchored forms inside the windows that are draggable -
`storekeeper_app.py:582` (`resizable(True, True)`) and the eleven `resizable(True, False)`
windows across the three clients and the Server GUI.

## Scope

- Make the forms in the resizable windows use the width they are given (`fill`/`expand` and
  weighted grid columns rather than fixed widths), so a drag re-lays the row instead of
  leaving a gap or clipping.
- `row_of`'s existing tier behaviour is the model; reach for it rather than writing a second
  layout rule per app.
- Windows fixed on an axis stay fixed: this ticket does not make dialogs resizable that are
  not, and does not touch `fit`'s open-time sizing.

## Why it is last

Every one of 002, 003, 004 and 005 adds or moves a widget inside a window this ticket
re-lays out, and `ui_kit.py` is shared by all four GUIs. Run it only once those four are
merged.

## Cascade

- `CLAUDE.md` -> the `ui_kit.py` row of the architecture table, if the kit itself grows a
  behaviour.
- Run `python tools/client-checks.py` and `python tools/server-checks.py` - both measure
  every window in the file and judge each axis only where that axis is fixed.
