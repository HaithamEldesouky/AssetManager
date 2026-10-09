# 017 - Bug: Manage Users asks for 1423px of height and loses its bottom control

**Type:** bug · **Depends on:** nothing · **Found by:** the 009-015 gate run (CHECK 6)

## What the gate said

    [FAIL] Manage Users is 423px shorter than its children ask for
           (573x1000 of 573x1423) - whatever is packed last is being squeezed

Height, on an axis `fit` leaves fixed. `1000` is `ui_kit.fit`'s own clamp on a 1080p
screen (`min(reqheight, screenheight - 80)`, `ui_kit.py:507`), so the form is asking for
**343px more than a 1080p monitor physically has**. `pack` then gives the shortfall to
whichever child was packed last. Every neighbour in that group passed.

This is the fifth time this gate has caught this defect class, and the first time the cause
is the form being genuinely taller than a screen rather than a stale written-down number.

## Why it happens

Manage Users (009, extended by 010) draws **one card per Engineer**, each carrying a name,
the Own Password state, an Auto-Approve tick, Remove, and - since 010 - Access Profile
radios plus a checkbox per permission. Four engineers already exceed the screen. The
window is honest about what it contains; there is simply more of it than fits, and it grows
with the team.

## Scope

- Give the window a **scrolling body**, the way `installer.py` already does (the gate
  measures that one as "its scrolling body gives 543px to a form asking 403px", so the
  pattern and the assertion for it both exist here already).
- The footer must stay outside the scroll region and packed `side="bottom"` **before** the
  form, so the control that closes the window is never what scrolls away - that is the
  whole rule this window broke.
- `fit` is still called, and still re-called when a row is added or removed (009 added that
  deliberately: a size taken once is a row short the moment an Engineer is added). What
  changes is that the height it asks for is now bounded by the scroll viewport rather than
  by the number of Engineers.
- Do not shrink the cards to fit. A form that is legible for four Engineers and illegible
  for eight is the same bug deferred.

## Verification

`tools/server-checks.py`'s "no dialog is smaller than its own form" group is the check -
it already opens this window and it is what failed. It cannot run in the cloud container
(no flask, no tkinter), so this needs a run on a machine with a display before it is
believed.
