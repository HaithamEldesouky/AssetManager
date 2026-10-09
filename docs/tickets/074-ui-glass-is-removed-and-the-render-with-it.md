# 074 - `ui_glass.py` is removed, and the render with it

**Type:** refactor · **Depends on:** 073 · **Found by:** Pass 3 review (`prototypes/NOTES-3.md`), Sep 2026 · **Issue:** [#249](https://github.com/HaithamEldesouky/AssetManager/issues/249)

## Finding

The two defects pass 3 raised against the shipped windows are one defect, and it is
the render.

`ui_glass.Surface.tint` hands a widget standing on the render "the colour of the point
it stands at" - one pixel sampled from under the middle of the widget, painted flat
across the whole of it. Two labels side by side sample the gradient at different x and
get a hard step between them: the Notifier's count strip, the Storekeeper's
`Submit / History / Tools` row and its `resolved` caption.

The second defect is the same mechanism. Text tuned against a flat `CARD` is drawn on a
*sampled slab* of the ground, which puts `FAINT` at 2.3:1 in the light palette.
Retuning the palette (073) does not reach it, because on a render the background under
a word depends on where the word is.

## Scope

1. Delete `ui_glass.py` and `ui_kit.py`'s re-export of it. The app icon half -
   `app_icon`, `write_ico`, `set_window_icon`, `ICO_SIZES`, `ICON_*` - moves back into
   `ui_kit.py` with the pillow guard; it is not a background and is unchanged.
2. Every `.ground()` becomes a `tk.Frame` in the parent's own colour. Every `.panel()`
   becomes a `tk.Frame` in the face it named, with a 1px `LINE` edge where the panel
   had one. Every `.tint()`, `.follow()`, `.reface()` and `.refresh()` becomes nothing
   at all - the widget is constructed in the colour it should be, which is what those
   calls existed to work around. Call sites: `server_gui.py` 15, `notifier_app.py` 30,
   `storekeeper_app.py` 21, `notifier_remote.py` 3, `installer.py` 10.
3. `GROUND`, `GROUND2`, `GLASS` and `EDGE` go from both palettes with the module that
   read them, and `ui_kit._check`'s ground-to-card distance assertions go with them -
   `PANEL_GROUND_MIN_L`, `GROUND_HUE_MAX`, `_unit`, `_lightness`, `_hue`. The two
   `highlightcolor=EDGE` focus rings in `storekeeper_app.py` become `ACCENT`, which is
   what the other two Entries in that file already use.
4. `Theme.unwatch` goes: a `Surface` was its only caller. `Theme.watch` stays -
   `notifier_remote.py` and `storekeeper_export.py` register their palette seeding
   there.
5. `installer.py`'s selected component card is a face written onto the frame **and onto
   each of its two children**, which is what it was before #161 made it an alpha.
   `CARD_SELECTED_ALPHA` goes.

## Not in this ticket

- Any palette value. 073 set those and `tools/palette-contrast.py` holds them.
- Any window's layout, size or the controls on it. This ticket moves no control and
  changes no geometry call: a canvas and a frame are both geometry masters, so every
  measurement the two window suites make is of the same children in the same places.
- Type, and the left rail `NOTES-3.md` describes.

## Cascade

- `CLAUDE.md` - the `ui_glass.py` row of the file table goes, the `ui_kit.py` row
  beside it gains the icon, and the ADR count moves to twenty-two.
- `docs/CODING_STANDARDS.md` - the `ui_glass.py` bullet under "Where code goes" and
  its name in the headless-safety list.
- `docs/agents/ticket-workflow.md` - it cites this module's architecture row as a
  worked example of a cascade collision. Replaced by the one this ticket is, and every
  number in that sentence re-derived on this branch.
- `docs/reference/architecture.md` - the `ui_glass.py` row goes; the `ui_kit.py` row
  loses its depth-layer paragraph and gains the icon.
- `docs/reference/tooling.md` - the payload lists, the `MAP` sentence, the dev-run
  closure note, and the check groups this ticket rewrote.
- `docs/adr/0022-a-window-is-drawn-on-flat-colour.md`, new. It supersedes nothing: the
  depth layer was chosen in a prototype and built over four tickets, and no ADR was
  ever written for it.
- The staging and payload lists that name the module: `MAP` in `tools/gate.py`,
  `tools/server_checks/stage.py`, `tools/client-checks.py`'s staging block,
  `SOURCE_FILES` in `installer.py`, `$Payload` in `tools/bundle-client.ps1`,
  `$SourceFiles` in `tools/package.ps1`, and `dev-run.ps1`'s two staged lists.
- `tools/cascade-audit.py` - three comments used this module as the worked example of
  a transitive-only import. The machinery is right and stays; the example is reworded,
  since the module it named is the one being deleted.

**Left alone deliberately.** The ticket files under `docs/tickets/` that name
`ui_glass.py` - 048, 049, 056 to 061 and 073 - are the record of work already done and
are true about the moment they describe. `prototypes/` likewise. A historical record
left alone is correct; a live instruction left alone fails the gate.

## Coverage

The five check groups that measured the render go with it:
`check_the_{storekeeper,notifier,installer}_stands_on_the_depth_layer`,
`check_the_depth_layer_draws_both_ways` and `check_the_ground_ramps_without_banding` in
`tools/client-checks.py`, and `check_the_server_window_stands_on_the_depth_layer` in
`tools/server_checks/console.py`.

What replaces them is the positive form of this ticket, one group per window:
**no backdrop canvas is placed under the window**, and **a band and every label on it
read back as one colour**, compared with each other rather than each against the token
it was assigned - which is the step this ticket is named for and fails on it whatever
produced it. The installer's group keeps the assertion `CODING_STANDARDS.md` cites: the
three component cards are asserted to be three colours, read off the widgets.

## Done when

`py -3.12 tools/gate.py --all` passes, and all four apps open in both themes with no
widget carrying a sampled colour.

`git grep -l ui_glass` finds no import, no staging list and no path - the module is
named only where a reader needs to know it existed and where it went: `CLAUDE.md`,
`docs/CODING_STANDARDS.md`, `docs/reference/architecture.md` and ADR-0022, whose whole
subject is the deletion. Those are the historical record this ticket leaves alone by the
rule two sections up; a bare grep for the name cannot tell them from a live instruction,
so it is not the test.
