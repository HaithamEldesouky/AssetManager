r"""Contrast floor for ui_kit.py's flat material (073).

Every text-on-surface pair the four apps draw through `ui_kit.DARK` and
`ui_kit.LIGHT`, held to the floor pass 3 settled (`prototypes/pass3_ui.py`'s
`--check`, `prototypes/NOTES-3.md`): 4.5:1, the WCAG floor for body text.
`ui_kit._check()` holds distances between tokens - how far CARD sits from
GROUND2, how close a hue drifts - and none of them is a contrast ratio, which
is why `FAINT #8b959a` on `GROUND #cfd6d5` shipped at 2.3:1 and nothing here
caught it.

    py -3.12 tools\palette-contrast.py
    py -3.12 tools\palette-contrast.py -v     every pair, not just a failure

Plain Python, standard library only, same as the other three gates - and it
does no more than import two dicts and do arithmetic, so it takes no shard
and builds no window. `ratio()` is its own copy of `pass3_ui.py`'s, not an
import of it: that file is a throwaway prototype (`prototypes/` is unmapped
in `tools/gate.py`'s MAP on purpose) and this script has to run after it is
gone.
"""
import os
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)
import ui_kit  # noqa: E402 - after sys.path is set, on purpose (see above)

VERBOSE = "-v" in sys.argv[1:] or "--verbose" in sys.argv[1:]

FLOOR = 4.5

# The text hierarchy and the direction colours, against the three flat levels
# `ui_kit._check()` does not measure a contrast ratio between. Not `CARD2`,
# `ACCENT`, `MONO`, `GROUND`, `GROUND2`, `GLASS` or `EDGE` - 073 does not
# touch those, and pass 3's own table (`prototypes/NOTES-3.md`) does not name
# them either.
FOREGROUNDS = ("TEXT", "SUBTEXT", "FAINT", "WARNING", "SUCCESS", "DANGER")
BACKGROUNDS = ("CARD", "BG", "INPUT_BG")

fails = []
worst = [None]                    # (ratio, palette, fg, bg), the lowest seen


def _unit(colour):
    h = colour.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def _lum(colour):
    out = []
    for c in _unit(colour):
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def ratio(fg, bg):
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def check(name, pal):
    print("\n=== %s ===" % name)
    for fg in FOREGROUNDS:
        for bg in BACKGROUNDS:
            r = ratio(pal[fg], pal[bg])
            if worst[0] is None or r < worst[0][0]:
                worst[0] = (r, name, fg, bg)
            if r < FLOOR:
                print("  [FAIL] %s on %s: %.2f, floor is %.1f" % (fg, bg, r, FLOOR))
                fails.append("%s: %s on %s is %.2f" % (name, fg, bg, r))
            elif VERBOSE:
                print("  [OK]   %s on %s: %.2f" % (fg, bg, r))


check("dark", ui_kit.DARK)
check("light", ui_kit.LIGHT)

print("\n" + "=" * 66)
_r, _name, _fg, _bg = worst[0]
print("worst pair: %s on %s in %s, %.2f (floor %.1f)" % (_fg, _bg, _name, _r, FLOOR))
if fails:
    print("%d FAIL(S)" % len(fails))
    for f in fails:
        print("  FAIL: %s" % f)
else:
    print("no drift (%d pair(s) checked)"
          % (len(FOREGROUNDS) * len(BACKGROUNDS) * 2))
sys.exit(1 if fails else 0)
