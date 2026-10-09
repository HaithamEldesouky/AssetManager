# 073 - The flat palette, and the contrast gate that holds it

**Type:** feature · **Depends on:** nothing · **Found by:** Pass 3 review (`prototypes/NOTES-3.md`), Sep 2026 · **Issue:** [#248](https://github.com/HaithamEldesouky/AssetManager/issues/248)

## Finding

Pass 3 chose **I Split** on a flat material (`prototypes/pass3_ui.py`,
`prototypes/NOTES-3.md`'s "The material, shared by all three" table). `ui_kit.py`'s
`DARK` and `LIGHT` tables still hold the retune two passes back argued for, not the
material pass 3 measured: `FAINT #8b959a` on `GROUND #cfd6d5` is 2.3:1, because
`_check()` holds distances between tokens and none of them is a contrast ratio.
`INPUT_BG` is also still an alias of `CARD2`, one step *lighter* than `CARD` - a field
somebody types into is a hole, not a tile.

## Scope

1. `ui_kit.py`'s `DARK` and `LIGHT` tables take the pass 3 values for the ten tokens
   the material's three flat levels and direction colours name: `BG`\<-SHELL,
   `CARD`\<-PANEL, `INPUT_BG`\<-WELL, `LINE`\<-LINE, `TEXT`\<-TEXT, `SUBTEXT`\<-MUTE,
   `FAINT`\<-FAINT, `WARNING`\<-OUT, `SUCCESS`\<-IN, `DANGER`\<-BAD
   (`prototypes/pass3_ui.py`'s `DARK`/`LIGHT` dicts). Token names stay - several
   hundred call sites name them and re-pointing every one would bury the change.
2. `INPUT_BG` gets its own value in both tables rather than reusing `CARD2`'s.
   `CARD2`, `ACCENT`, `ACCENT2`, `MONO`, `GROUND`, `GROUND2`, `GLASS` and `EDGE` are
   not in pass 3's table and are untouched by this ticket - `GROUND`, `GROUND2`,
   `GLASS` and `EDGE` go with 065, the module that reads them.
3. `_check()`'s docstring and the inline comments on `INPUT_BG` in both tables
   describe `INPUT_BG`/`CARD2` as one colour on purpose; that stops being true and
   the words need to say so. The check `_check()` runs - `aliases(DARK) ==
   aliases(LIGHT)` - needs no code change: dropping the same alias from both tables
   keeps the two shapes equal.
4. A new script under `tools/`, the contrast gate, modelled on
   `prototypes/pass3_ui.py`'s `--check`: the same `ratio()` (relative luminance,
   WCAG formula), walking every `{TEXT, SUBTEXT, FAINT, WARNING, SUCCESS, DANGER} x
   {CARD, BG, INPUT_BG}` pair both of `ui_kit.DARK` and `ui_kit.LIGHT` draw,
   asserting 4.5:1, naming every failing pair, and exiting non-zero on a failure.
5. Wire the new script into `tools/gate.py`: a new gate name, its `GATES` entry, its
   slot in `main()`'s `order` tuple, and the `ui_kit.py` row of `MAP` gets it added
   alongside `server`/`client` - a change to `ui_kit.py`'s palette is exactly what
   this gate exists to catch, so it runs whenever that row already would. Not
   sharded: it imports two dicts and does arithmetic, there is no window to build.

## Not in this ticket

- Any window, layout, or the left rail NOTES-3.md's "G - Panel" section describes.
  This ticket moves no window.
- `GROUND`, `GROUND2`, `GLASS`, `EDGE` or `ui_glass.py`.
- `CARD2`'s own value.
- Type (Bahnschrift Condensed, the 8px-9px label floor) - a separate concern from
  the material's colour, not asked for here.

## Cascade

- `ui_kit.py`'s module docstring and the palette comment paragraphs above `DARK`
  and `LIGHT` that argue for the values this ticket replaces.
- `docs/reference/architecture.md` - the `ui_kit.py` row, if it states the palette
  values or the `INPUT_BG`/`CARD2` alias as fact.
- `docs/reference/tooling.md` - the new script gets its own section, the same as
  every other `tools/*.py`.

## Verification

- `py -3.12 tools/gate.py --all` passes, the new gate runs in it (named in the gate
  list it prints), and both palettes clear 4.5:1 with the worst pair named in its
  output.
- `ast.parse()` on every file touched.
- `py -3.12 tools/gate.py` on the diff, not just `--all` - the `ui_kit.py` row of
  `MAP` is what proves the new gate is reachable from an ordinary change and not
  only from a release run.
