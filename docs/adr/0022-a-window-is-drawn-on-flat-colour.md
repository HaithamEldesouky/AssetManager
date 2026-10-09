---
status: accepted
---

# A window is drawn on flat colour

157 chose Glass over a neumorphic light product and a flat extrusion, and 158
to 161 drew all four windows out of it: a lit gradient behind each one, panels
frosted out of that gradient, and a bloom under whichever control the window
exists for. #222 lifted the whole of it into `ui_glass.py`, 1,229 lines of
pillow renders placed on canvases, because Tkinter has no blur, no shadow and
no alpha compositing.

**A Tkinter widget is opaque, and that was never worked around - it was worked
with.** A `tk.Entry` cannot be transparent, so a widget standing on the render
could not show what was behind it; what it got instead was `Surface.tint`,
which handed it "the colour of the point it stands at" - one pixel sampled
from under the middle of the widget, then painted flat across the whole of it.

Pass 3 (`prototypes/NOTES-3.md`) raised two defects against the shipped
windows, and they are one defect:

- **The step.** Two widgets side by side sample the gradient at different x
  and are painted two different flat colours, so the band they sit on has a
  hard edge down the middle of it. Reported against the Notifier's count
  strip, the Storekeeper's `Submit / History / Tools` row and its `resolved`
  caption.
- **The contrast.** Text tuned against a flat `CARD` is drawn on a *sampled
  slab* of the ground instead, which put `FAINT` at 2.3:1 in the light
  palette. 073 retuned the palette to a 4.5:1 floor and `tools/palette-
  contrast.py` holds it there - and neither reaches this, because the
  background under a word on a render is a function of where the word is.

A sampled colour is a measurement of one point presented as the colour of a
rectangle. Every defect above is that sentence.

## Decision

**Every window in this product is drawn on flat palette colours, and no
widget takes a colour sampled from anything.**

- `ui_glass.py` is deleted, and with it `Surface`, `ground`, `panel`, `frost`,
  `gradient`, `glow`, `sample` and `ImageBank`.
- A container that stood on the ground is a `tk.Frame` in `BG`. A frosted
  panel is a `tk.Frame` in `CARD` (or the face it named), with a 1px `LINE`
  edge where it had one.
- `GROUND`, `GROUND2`, `GLASS` and `EDGE` leave both palettes with the module
  that read them, and `ui_kit._check`'s ground-to-card distance assertions go
  with them. What holds the palette now is `tools/palette-contrast.py` (073),
  which measures a contrast ratio rather than a distance between two tokens.
- `app_icon` and its kin come back into `ui_kit.py`. It is pillow's one reader
  left here and it still answers `None` without it, which is unchanged: an
  icon can be absent and a background cannot.

## What follows

- **pillow stops being load-bearing.** `prototypes/NOTES.md` recorded that
  choosing Glass committed this product to two drawings of every window - the
  render, and a `HAS_PIL` fallback it called "not acceptable yet". There is
  one drawing now, and it is the one every machine gets.
- **The gates measure the positive form of this.** Three groups assert that no
  backdrop canvas is placed under a window and that a band and every label on
  it read back as **one colour**, compared with each other rather than each
  against the token it was assigned - so a window that steps fails whatever
  produced the step. The five groups that measured the render itself are gone
  with it.
- **`Theme.watch` stays and `Theme.unwatch` goes.** A `Surface` was the only
  caller of the second; the first is how `notifier_remote.py` and
  `storekeeper_export.py` are handed the palette after a switch.

## What was rejected

**Retuning the palette again.** 073 had just done it, to a measured 4.5:1
floor, and the light palette still read at 2.3:1 where a word sat on the
ground. A floor held against `CARD`, `BG` and `INPUT_BG` says nothing about a
colour that is none of them and is different at every x.

**Sampling per widget rather than per widget-centre.** A gradient under a
label could be sampled at each end and the label drawn in the mean, which
narrows the step without closing it - and leaves the contrast defect exactly
where it was, since the mean is still not a palette colour anything was tuned
against.

**Keeping the render behind a setting.** Two drawings of every window is what
`NOTES.md` already refused, and a setting makes it two drawings that must both
be measured for ever. The four windows here are a form, a queue, a console and
an installer; none of them is improved by a gradient enough to pay for that.

**Keeping `GROUND` and its three in the palettes, unread.** That is the state
166 found them in - written down, read by nothing, `frost` taking a literal
`#ffffff` instead - where retuning either moved no pixel and the comment above
them saying the renders read them was simply untrue. A token nothing reads is
a token that will be wrong the next time somebody trusts it.
