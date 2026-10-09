# 019 - A window resizable on both axes is judged at its own minimum, not just reported

**Type:** test coverage · **Depends on:** 018 (done) · **Found by:** the 017-018 gate run (CHECK 7)

## Finding

018 made the window-size group say something about a window resizable on both axes
instead of printing nothing, because a window that produces no line at all is
indistinguishable from one the openers forgot - which is exactly how the System Log
went unmeasured. That was the right fix for the silence, and it named its own cost:
**four windows are now reported rather than judged.** They print their size and their
children's beside it, and nothing asserts anything about the pair.

The four are the ones that make no `resizable` call at all, so Tk's default leaves
both axes draggable:

| window | `Toplevel` | `minsize` |
|---|---|---|
| Lookup Sheet (`manage_assets`) | `server.py:4863` | `frow.min_width() + 36, 420` |
| Connected Clients (`client_list`) | `server.py:6036` | `crow.min_width() + 28, 480` |
| System Log (`system_log`) | `server.py:6274` | `lrow.min_width() + 28, 420` |
| Manage / Delete Records (`manage_records`) | `server.py:6407` | `frow.min_width() + 28, 420` |

There is no `resizable(True, True)` anywhere in `server.py`; every call is
`(False, False)` or `(True, False)`. So these four are draggable by default rather
than by decision.

## Why the current rule stops short

"An axis is judged only where that axis is fixed" is right about the direction it was
looking. A resizable axis **can be dragged open**, so the opening size is not a verdict:
a shortfall there costs a drag, not a control.

But a resizable axis can also be dragged **shut**, and that is bounded by a number the
window itself wrote down. All four set a `minsize`. That floor is the smallest a user
can make the window, so it is the state to judge:

- if the bottom control survives at the minimum, the window can **never** be dragged
  into losing it - a pass the gate can actually assert;
- if it does not, the window can be dragged into exactly the state this group exists to
  catch, with the control packed last squeezed out.

## Scope

`tools/server-checks.py` only. No change to `server.py` is expected - all four already
set a `minsize`, and the question is whether it holds their children, not whether it
exists.

Reuse the shape already in this file rather than adding a new one: the Add Transaction
group's `usable(where)` imposes a height the harness cannot otherwise reach and reads
the button back - mapped, at least 20px tall, and not ending below the bottom edge.
`client-checks.py`'s `survives_a_short_screen` is the same idiom for the clients.

Keep 018's reporting line. It is what makes a missing opener visible, and that is a
different question from whether the floor holds.

A window resizable on both axes that sets **no** minimum has no floor to judge and can
be dragged to nothing - that is a finding, naming `minsize` as the remedy, for the
reason 018 gives about silence.

## Verification

Needs a display, so it does not run in the cloud container. On the Windows machine:

    py -3.12 tools\server-checks.py

Expect the four windows above to move off the "so neither is judged" line and onto a
line that says their floor holds their children. A fifth line appearing there later is
a new window nobody judged.

## Not in this ticket

Those four windows state no resize policy at all. Making the default explicit is a
change to `server.py` and a separate argument - this ticket judges them whatever they
state.
