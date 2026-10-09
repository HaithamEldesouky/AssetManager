# 020 - Bug: Connected Clients loses its whole footer at its own minimum

**Type:** bug fix · **Depends on:** 019 · **Found by:** the 019 gate run (CHECK 9)

## Finding

    [FAIL] Connected Clients at its own 420x480 minimum: the bottom control is not mapped
    [FAIL] status chip 2 (Connected Clients) at its own 420x480 minimum: the bottom control is not mapped

Two lines, one window - it is opened directly and through its status chip. 019's new
assertion is the first thing that ever measured this window at the size it is allowed to
be dragged to, and it found the footer gone.

The window opens at a written `900x640` and writes down a floor of `crow.min_width() + 28,
480`. The gate's own measurement of the form is `907x564`: the children ask for 564px of
height against a 480px floor, so at the minimum the cavity is 84px short. `pack` allocates
in packing order and gives the shortfall to whichever child was served last, and the footer
was packed last, after the `expand=True` treeview. So at the minimum the footer gets no
height at all - not clipped, unmapped.

What is lost with it is **⏻ Log Off Selected** and **↺ Reset Identity**, which `CLAUDE.md`
says "live here and nowhere else" because the list is built from check-ins and a Client
that has never checked in has no row to select - plus ↻ Refresh and Close.

**Why the eight `fit` dialogs do not have this and this window does.** They pack their
footer at `side="bottom"` **before** the body, which makes the button the first child
`pack` serves rather than the last, and they then call `ui_kit.fit`, which lowers a written
`minsize` height to match what the form actually asks for. This window does neither: no
`ui_kit.fit` call appears anywhere in it, so the 480 it wrote down was never reconciled
against the 564 the form needs. System Log, four lines away in the same file, writes a
floor and then calls `ui_kit.fit(win, 1120)` - and passes.

## Scope

`server.py` only, in `client_list`. Move the two lines that create and pack `btnf` from
below the form up to immediately after `win.transient(root)`, and pack them
`side="bottom"`. The `ui_kit.row_of` call, `cbox.pack` and the `minsize` stay where they
are: the button callbacks close over `queue`, `load_rows` and `load_commands`, which are
defined later in the function and resolve at click time.

**Not `ui_kit.fit`**, which would also be a fix: it would reconcile the 480 against the
form, but it takes the opening size from the children as well, and this window keeps a
written `900x640` on purpose - a wide table wants a width no form measurement would give
it. The `side="bottom"` footer fixes the floor and leaves the opening size alone.

No gate changes. 019 is what catches this, and it is already in place.

## Verification

`tools/server-checks.py`, which needs a display. The two FAIL lines become

    [OK] Connected Clients: its 420x480 minimum holds its bottom control, so no drag can
         squeeze it out

and the same for the status chip, joining the lines Manage Records and System Log already
print. The opening-size line is unchanged - both axes are still resizable, so it is still
reported as a drag rather than judged.

## Not in this ticket

The Lookup Sheet (`manage_assets`) is named in `CLAUDE.md` as one of the twelve dialogs
that call `ui_kit.fit`, and the same sentence says `tools/server-checks.py` "opens every
window in the file" - but it appears nowhere in that gate and produced no measurement line
in this run. That is an 018-style unmeasured window and gets its own ticket.
