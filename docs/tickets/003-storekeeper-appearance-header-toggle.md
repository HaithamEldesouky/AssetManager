# 003 - Storekeeper: Appearance moves to the header as a sun/moon button

**Type:** enhancement · **Depends on:** nothing

## What is asked

Move the Appearance control out of the Tools tab and onto the app header, as a sun/moon
button.

## Where it stands today

`storekeeper_app.py` ~line 1060 builds an **Appearance** card in the Tools tab whose body
is `_theme_row` (~1077): three pills - Dark, Light, Follow Windows - the current one lit,
with `_paint_theme_row` repainting them and `_set_theme` writing `theme` into
`config.json`. "Follow Windows" is polled on the 15s background tick (~1650).

## Scope

- One button in the window header, showing the sun or the moon for the theme in force, and
  cycling on click.
- **Keep all three modes.** `theme: system` is a real value in `config.json`, the 15s tick
  polls Windows for it, and the Notifier and the Server GUI both offer it - dropping it
  here alone would make one app's `config.json` disagree with the other two. A three-state
  cycle (dark -> light -> follow) with the button's tooltip/caption naming the current mode
  is the smallest thing that keeps it.
- Remove the Appearance card from the Tools tab; `_theme_row` and `_paint_theme_row` either
  go or shrink to the header button's painter.
- Asks for no password, as today.

## Cascade

- `CLAUDE.md` -> Storekeeper App -> the **Appearance** bullet: it describes a card in the
  Tools tab.
- Run `python tools/client-checks.py`, which measures this window.
