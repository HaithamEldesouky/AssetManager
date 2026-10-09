"""
Asset Manager - the window kit the four apps share: two palettes, a live
retint, a button row that re-lays itself as its window changes width, and
`fit`, which sizes a window to the form inside it rather than to a number
somebody typed.

Three things were true of every window in this product and are not any more.

**The palette was a compile-time constant.** `server.py`, `storekeeper_app.py`
and `notifier_app.py` each held a byte-identical copy of thirteen colour names
at module level, every widget took its colour as a construction argument, and
there was no light palette anywhere. The names stay where they are - the three
apps name them several hundred times between them and re-pointing every one of
those would bury the change - but they are seeded from the table here and
rebound when the theme changes.

**A button row was the width it was born at.** `Pill` took a `w=` and drew its
rounded body once, so a row of them could neither shorten nor wrap; the Server
GUI's action row was measured at 978px of the 982px its window makes available,
four pixels from clipping. `Row` below lays a row out against the width it
actually has, at whichever tier of labels fits.

**A window was as big as somebody typed.** Fourteen of them were smaller than
the form they contain, and `pack` gives a shortfall to whichever child was
packed last - the button, every time. `fit` below takes the size from the
children instead; its docstring carries what each of the fourteen lost.

And one thing was tried and taken out again. **A window was drawn on a
render.** The depth layer (157) put every window on a lit gradient with
frosted panels cut out of it, in a module of its own from #222. It is gone
(074): a widget standing on a gradient cannot be transparent, so it took one
sampled colour painted flat across the whole of itself, and two labels side
by side sampled at different x and stepped. Text tuned against a flat CARD
was drawn on a sampled slab of that ground, which is how `FAINT` reached
2.3:1 in the light palette - a ratio no palette retune could reach, because
on a render the colour under a word depends on where the word is. Every
window here is drawn on flat colour, and ADR-0022 carries the argument.

The prototypes that settled the first two are on the `prototype/redesign-ui`
branch, under `prototypes/`; `responsive_buttons.py` is the layout comparison
and `elastic_kit.py` is the throwaway ancestor of this file. The render's are
on `prototype/modern-3d-ui` and in `prototypes/NOTES-3.md`, which is the pass
that measured the two defects above. Neither branch is imported by anything.

**No module-level tkinter.** `server.py` must stay importable headless - under
IIS and under the Windows Service, where there is no window station - and it
imports tkinter inside each GUI function for that reason. This module is
imported at the top of all four apps for its palette tables, so it has to hold
the same line: every tkinter import here is inside a function or a method.

**pillow is optional and stays optional.** `app_icon` below is the one reader
of it left in this build, and it answers `None` where it is not installed, the
way every optional dependency here degrades: the caller shows no icon rather
than not starting. Nothing draws a window out of it any more.

And one shape was added rather than taken away. **A window was a table, or a
form, and nothing in between.** 076 puts the list-and-detail shape here -
`SectionBar`, `ListPane`, `DetailPane` - because four of the Server console's
fourteen windows, the Storekeeper's history and the Notifier's whole reason for
having a popup are the same thing: a list of movements, and what one of them
needs a decision about. Each was its own Toplevel with its own tree, its own
toolbar and its own close behaviour. The three classes are the pieces; which
list is in the pane is the section bar's answer, and every window built after
this one is made of them.
"""


import base64
import io
import sys

try:
    from PIL import Image
    from PIL import ImageChops
    from PIL import ImageDraw
    from PIL import ImageFilter
    HAS_PIL = True
except ImportError:
    # The same guard the tray makes, and the same answer: an app with no
    # pillow shows no icon and still starts. See "Optional dependencies" in
    # docs/CODING_STANDARDS.md.
    HAS_PIL = False

try:
    import pystray
    # pillow is what a tray icon actually needs an image from, so the one
    # guard above is the one this checks too - a `pystray` with no `pillow`
    # beside it still can't draw the icon `run_tray_icon` hands it.
    HAS_TRAY = HAS_PIL
except ImportError:
    HAS_TRAY = False

# ---------------------------------------------------------------- the palettes

#: The colour names the apps use, in the order the reverse map prefers them.
#: An alias (two names, one value) resolves to whichever comes first here, so
#: the order is part of the contract rather than incidental - see `reverse`.
TOKENS = ("BG", "CARD", "CARD2", "LINE", "ACCENT", "ACCENT2", "TEXT",
          "SUBTEXT", "SUCCESS", "WARNING", "DANGER", "INPUT_BG", "MONO",
          "FAINT")

#: The names all three apps shipped before this file existed, and since the
#: E retune not the values: a steel shell of one hue family, and **colour
#: reserved for what a Transaction is doing**. SUCCESS, WARNING and DANGER are
#: the only saturated entries in the table, so amber on this window means a
#: movement waiting and green means one settled, and nothing else competes
#: with them for the eye. ACCENT is therefore a neutral steel rather than a
#: brand hue - it still has to carry white text at 6.2:1, since it is what
#: every primary pill in these four apps is drawn in, so it is a control
#: colour and not a decoration.
DARK = {
    "BG":       "#1e2427",
    "CARD":     "#262e32",
    "CARD2":    "#3a4348",
    "LINE":     "#39434a",
    "ACCENT":   "#55636b",
    "ACCENT2":  "#6c7c85",
    "TEXT":     "#e8ecec",
    "SUBTEXT":  "#9aa5aa",
    "SUCCESS":  "#58a87c",
    "WARNING":  "#d08e33",
    "DANGER":   "#d08079",
    "INPUT_BG": "#171c1f",   # a recess, darker than CARD - no longer an alias of CARD2
    "MONO":     "#c3ced1",
    "FAINT":    "#8d979c",
}

#: `TEXT`, `SUBTEXT`, `FAINT` and the three direction colours below are pass
#: 3's measured values (`prototypes/pass3_ui.py`, `prototypes/NOTES-3.md`),
#: not derived from the dark table the way an earlier retune's used to be:
#: each one clears 4.5:1 against every one of CARD, BG and INPUT_BG on its
#: own measure, and `tools/palette-contrast.py` holds that floor rather than
#: a docstring repeating a handful of the ratios by hand.
LIGHT = {
    "BG":       "#e8ebeb",
    "CARD":     "#ffffff",
    "CARD2":    "#dfe4e3",
    "LINE":     "#ccd3d3",
    "ACCENT":   "#3f4d55",
    "ACCENT2":  "#55636b",
    "TEXT":     "#141a1d",
    "SUBTEXT":  "#4d575c",
    "SUCCESS":  "#2c6b48",
    "WARNING":  "#8a5405",
    "DANGER":   "#a2453c",
    "INPUT_BG": "#f2f5f5",   # a recess, darker than CARD - no longer an alias of CARD2
    "MONO":     "#2a5f72",
    "FAINT":    "#5d686d",
}

PALETTES = {"dark": DARK, "light": LIGHT}
MODES = ("system", "dark", "light")
MODE_LABELS = {"system": "Follow Windows", "dark": "Dark", "light": "Light"}


def reverse(pal):
    """hex -> token, which is how a widget already on screen is retinted.

    The alternative was registering every widget against the token it was
    painted with, which means editing all ~800 places the apps name a colour.
    Reading the colour back off the widget and looking it up needs none of
    them, and it is exact: the palette is a closed set of literals.
    """
    rev = {}
    for name in TOKENS:
        rev.setdefault(pal[name].lower(), name)
    # An app's own extras come after the shared names, so a colour that is both
    # (the Storekeeper's DANGER_HOT is nothing else's) can never shadow one of
    # the eighteen every window is built out of.
    for name in sorted(k for k in pal if k not in TOKENS):
        rev.setdefault(str(pal[name]).lower(), name)
    return rev


def aliases(pal):
    """Which names share a colour, as a comparable shape."""
    seen = {}
    for name in sorted(pal):
        seen.setdefault(str(pal[name]).lower(), []).append(name)
    return tuple(sorted(tuple(v) for v in seen.values()))


def palettes(extra_dark=None, extra_light=None):
    """The shared tables plus one app's own colours, checked as a pair.

    Each app has a handful of literals of its own - a pressed-state red, a
    hover green - that were inline hex strings before this file existed. They
    belong to the app rather than to the kit, so they are merged in here rather
    than added to `DARK`/`LIGHT`, and the same alias check runs over the result.
    """
    dark = dict(DARK, **(extra_dark or {}))
    light = dict(LIGHT, **(extra_light or {}))
    missing = set(dark) ^ set(light)
    if missing:
        raise ValueError("extras differ between the palettes: %s"
                         % ", ".join(sorted(missing)))
    if aliases(dark) != aliases(light):
        raise ValueError("extras break the alias shape, so a retint would not "
                         "be reversible: %s vs %s"
                         % (aliases(dark), aliases(light)))
    return dark, light


def _check():
    """Both palettes must alias the same way, or a retint is not reversible.

    Two names sharing one colour in one palette and not the other is a silent
    one-way trip: a widget painted through the alias reads back the same hex
    in both palettes, or a retheme moves it and nothing painted through the
    other name follows. Checked at import so the failure is a startup error
    naming the pair, not a window nobody can restore.
    """
    for name, pal in (("DARK", DARK), ("LIGHT", LIGHT)):
        missing = [t for t in TOKENS if t not in pal]
        if missing:
            raise ValueError("%s palette is missing %s"
                             % (name, ", ".join(missing)))
    if aliases(DARK) != aliases(LIGHT):
        raise ValueError(
            "DARK and LIGHT do not alias identically, so a retint is not "
            "reversible: %s vs %s" % (aliases(DARK), aliases(LIGHT)))


_check()


# ------------------------------------------------------------------- the faces

#: The typefaces, written down once for the same reason the colours above are.
#: A face was stated at 580 construction sites across the four apps - 298 in
#: `server.py`, 141 in `notifier_app.py`, 106 in `storekeeper_app.py`, 32 here
#: and 3 in this file - with no name anywhere saying what the text *was*, so
#: changing the product's typeface meant editing 580 call sites and being right
#: 580 times. That is the argument `TOKENS` already makes, so this is the same
#: mechanism rather than a second one: a table here, bound into each app's
#: globals by `Theme`, and `cascade-audit.py` failing an app that restates a
#: family.
#:
#: **The mono face is the one that carries meaning rather than taste.** Every
#: machine identifier is drawn in it and nothing else is: a serial number is
#: read a character at a time, off a label, by somebody comparing it against a
#: screen, and a proportional face is what makes `0`/`O` and `1`/`l` the same
#: shape at 9px. That treatment already existed - the Notifier's popup and the
#: Storekeeper's bulk field were drawing identifiers in Consolas before this
#: table did - at eight sizes with nothing saying which of them meant *this is
#: an identifier* and which meant *this is a path*. What the roles below add
#: is the name, so the two can stop being the same decision.
#: **Variant E draws no word of this product in Segoe UI**, and that is the
#: half of it the four layout tickets could not carry. `#179` to `#182` moved
#: each window's hierarchy and the palette above was retuned to E's own
#: slate, but a face is stated in one table rather than per window, so none
#: of those four could reach it - and a face is the first thing read off a
#: window. The prototype names the face it is replacing rather than leaving
#: it to be inferred: "Deliberately not Segoe UI, which is the one face this
#: product currently uses for every word in it."
#:
#: **Condensed rather than Bahnschrift plain**, which is the variant's own
#: choice and not a preference: every window here is a column of identifiers
#: with labels beside them, so what a narrower prose face buys is width for
#: the identifiers rather than for the words about them. Nothing measures
#: wider than it did, which is what makes this safe to apply under a product
#: whose every window is sized by `fit` and whose pills carry written-down
#: widths: each is met with a shorter string than the one it was measured
#: against.
#:
#: **`figure` is E's fourth face** and the one the three-entry table had
#: nowhere to put. The variant draws a *number* the way it draws an
#: identifier - in the code face - because a count of what is out of the
#: store is read rather than skimmed, and because that is what stops the
#: numerals being the largest prose on the window. `ident` already said
#: this about identifiers; the figures beside them were still being drawn
#: in the prose face at display sizes.
FAMILIES = {
    "prose": "Bahnschrift",
    "emph":  "Bahnschrift SemiBold Condensed",
    "code":  "Consolas",
}

#: What each face falls back to where the machine does not carry it, best
#: first. Bahnschrift ships with Windows 10 1709 and later, so a Server 2016
#: host - which is a machine this Server GUI really runs on - has none of
#: it, and **Tk answers a missing family by silently substituting** whatever
#: it likes rather than by raising: the window opens drawn in something
#: nobody chose, with nothing anywhere saying so. The last entry of each is
#: the face it replaced, which is a face every machine here already had.
FACE_FALLBACKS = {
    "prose": ("Bahnschrift", "Segoe UI"),
    "emph":  ("Bahnschrift SemiBold Condensed", "Bahnschrift SemiBold",
              "Segoe UI Semibold"),
    "code":  ("Consolas", "Courier New"),
}

#: Answered once by `_resolved_faces` and then kept.
_FACES = None


def _resolved_faces():
    """`FAMILIES`, with any face this machine does not carry swapped for one
    it does.

    **Lazily rather than at import**, unlike `_check_faces` below: asking Tk
    which families exist needs an interpreter, and this module is imported
    long before any app builds a root - `installer.py` imports it to read the
    palette on a machine that may have no window at all. So where there is
    nothing to ask, the table is used exactly as written and the answer is
    **not** kept, so the next call asks again once a root exists. What that
    costs on such a machine is the behaviour every release before this had,
    which is Tk substituting on its own.
    """
    global _FACES
    if _FACES is not None:
        return _FACES
    try:
        import tkinter.font as tkfont
        have = set(tkfont.families())
    except Exception:
        return FAMILIES
    out = {}
    for key, written in FAMILIES.items():
        out[key] = written
        for name in FACE_FALLBACKS.get(key, (written,)):
            if name in have:
                out[key] = name
                break
    _FACES = out
    return out

#: What the text *is*, to how it is drawn: `(family key, size, weight)`.
#:
#: The names are the hierarchy these apps already had - the eleven distinct
#: specs behind those 580 sites were a size scale used consistently enough to
#: be named honestly. So the values here are exactly what each level measured
#: before this table existed, and introducing it moved no pixel in any window;
#: what it buys is that the *next* change is one line rather than 580.
ROLES = {
    "micro":   ("prose", 9,  ""),        # the line under a field
    "caption": ("prose", 9,  "bold"),
    "body":    ("prose", 9,  ""),        # most of the product
    "strong":  ("prose", 9,  "bold"),
    "value":   ("prose", 10, ""),
    "heading": ("prose", 10, "bold"),
    "label":   ("prose", 11, ""),
    "title":   ("prose", 11, "bold"),
    "section": ("prose", 12, "bold"),
    "display": ("prose", 13, "bold"),
    "hero":    ("prose", 15, "bold"),
    # The identifiers. Sized apart from the prose scale on purpose: what makes
    # an Asset Number legible is not what makes a sentence legible.
    # The mono scale, sized from what it is actually used for rather than
    # alongside the prose one: these two answer different questions and a
    # shared scale would imply they move together.
    "mono":    ("code",  8,  ""),        # a fingerprint, a path, fine print
    "code":    ("code",  9,  ""),
    "code_lg": ("code",  10, ""),
    "ident":   ("code",  10, "bold"),    # the thing somebody is holding
    # A count, drawn the way an identifier is. Variant E's own `disp`, and
    # at its own size: 17 rather than the 22 the prose face was using, a
    # condensed sans and a monospace not measuring the same at one size,
    # and this row having to fit four cells at the 940px minimum.
    "figure":  ("code",  17, "bold"),
    # `Segoe UI Semibold` is a family rather than a weight - 600 where Tk's
    # own bold is 700 - so it is its own entry and never what `strong` and
    # the rest resolve to. One role rather than the eleven sizes it is used
    # at: 8 is what twenty of the forty sites ask for and the others are
    # one-off display sizes, which go through `size=` so the face still
    # comes from here and the size reads as the exception it is.
    "emph":    ("emph",  8,  ""),
}


def font(role, size=None, weight=None):
    """The tuple Tk wants, for a named role.

    `size` and `weight` are for the call site that genuinely needs a one-off -
    a heading that has to fit a narrow chip, say. They go *through* the table
    rather than around it, so the family still comes from one place and the
    override is visible as an override.

    Bold is Tk's own `"bold"` on the prose family and never the separate
    `Segoe UI Semibold` face: the two are 700 and 600, so swapping one for the
    other would change how a hundred existing labels are drawn. Semibold is
    reached only where it already was, through `Font` below.
    """
    try:
        fam, sz, wt = ROLES[role]
    except KeyError:
        raise KeyError("no such font role: %r - one of %s"
                       % (role, ", ".join(sorted(ROLES))))
    wt = wt if weight is None else weight
    spec = (_resolved_faces()[fam], sz if size is None else size)
    return spec + ((wt,) if wt else ())


def _check_faces():
    """Every role resolves, and names a family this table holds.

    At import for `_check`'s reason: a font table is a table of literals
    nothing reads back, and a role that resolves to nothing is a `TclError`
    from inside a widget construction somewhere, at whatever moment that window
    first opens - which for most of these is a dialog nobody opens on a good
    day.
    """
    for role in ROLES:
        fam = ROLES[role][0]
        if fam not in FAMILIES:
            raise ValueError("font role %r names family %r, which is not in "
                             "FAMILIES" % (role, fam))
        spec = font(role)
        if not isinstance(spec[1], int) or spec[1] <= 0:
            raise ValueError("font role %r has no usable size: %r"
                             % (role, spec))


_check_faces()


# ----------------------------------------------------------------- which theme

def system_mode():
    """What Windows says the apps should be, and why.

    `AppsUseLightTheme` is 1 for light and 0 for dark. A missing key is a build
    of Windows without the setting, which is not the same fact as dark, so it
    is reported as unknown and the caller keeps its own default. Windows raises
    no event when this changes, so whoever wants to follow it has to poll -
    every app here already has a tick that can carry the read.
    """
    if not sys.platform.startswith("win"):
        return None, "not Windows"
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes"
                r"\Personalize") as k:
            v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        return ("light" if int(v) else "dark",
                "AppsUseLightTheme=%d" % int(v))
    except OSError as ex:
        return None, "AppsUseLightTheme unreadable (%s)" % ex.__class__.__name__


def resolve(mode, fallback="dark"):
    """(mode, why) for a saved setting of 'system', 'dark' or 'light'."""
    if mode == "system":
        got, why = system_mode()
        if got:
            return got, "follows Windows  ·  %s" % why
        return fallback, "follows Windows  ·  %s, using %s" % (why, fallback)
    if mode in PALETTES:
        return mode, "set to %s" % mode
    return fallback, "unknown theme %r, using %s" % (mode, fallback)


def read_mode(cfg, key="theme", default="system"):
    """The saved setting out of a config dict, never raising on a bad value.

    Unlike the admin password's file, a theme nobody can read is not worth
    refusing to start over: the worst a wrong value can do is paint the window
    the wrong colour, and `resolve` says so in the line it returns.
    """
    v = str((cfg or {}).get(key, default) or default).strip().lower()
    return v if v in MODES else default


# --------------------------------------------------------------- the live swap

#: Every widget option that can hold one of our colours. Read back and remapped
#: one widget at a time; anything holding a colour that is not in the palette
#: (a Windows system colour, a one-off literal) is left exactly as it is.
COLOUR_OPTIONS = (
    "background", "bg", "foreground", "fg", "activebackground",
    "activeforeground", "disabledforeground", "highlightbackground",
    "highlightcolor", "insertbackground", "selectbackground",
    "selectforeground", "troughcolor", "readonlybackground",
    "selectcolor", "buttonbackground",
)


def retint(widget, old, new):
    """Repaint a whole widget tree from one palette into another, in place.

    A rebuild would be simpler and is what a theme switch usually is. It is
    also wrong here: it would take the Storekeeper's filters, its search text
    and its table selection with it, and on the Notifier it could pull a popup
    out from under an engineer who was halfway through answering it. So nothing
    is destroyed - every widget is read, mapped and re-configured.

    A widget carrying a `_retint_hook` callable is handed `(rev, new)` and is
    responsible for itself. That is how anything drawn on a canvas is reached:
    canvas *items* are not widgets and this walk cannot see them.

    Returns how many widgets were touched, which is what a check asserts on.
    """
    import tkinter as tk
    rev = reverse(old)
    seen = 0
    stack = [widget]
    while stack:
        w = stack.pop()
        try:
            stack.extend(w.winfo_children())
        except tk.TclError:            # destroyed mid-walk
            continue
        changed = False
        for opt in COLOUR_OPTIONS:
            try:
                cur = str(w.cget(opt)).lower()
            except (tk.TclError, TypeError):
                continue
            token = rev.get(cur)
            if token is None:
                continue
            try:
                w.configure(**{opt: new[token]})
                changed = True
            except tk.TclError:
                pass
        # After the options, not instead of them: a hook exists for the state
        # this walk cannot see - a canvas's items, a Treeview's tag colours -
        # and the widget's own options are still ordinary options.
        hook = getattr(w, "_retint_hook", None)
        if hook is not None:
            try:
                hook(rev, new)
                changed = True
            except tk.TclError:
                pass
        seen += 1 if changed else 0
    return seen


def combo_popdown(root, pal):
    """Colour the dropdown list of every ttk Combobox, born and unborn.

    The list a combobox drops down is not part of the combobox: it is a plain
    Tk listbox inside a Toplevel that ttk builds lazily, the first time the
    arrow is clicked, and it takes nothing from the ttk style. It is not a
    child of the combobox in the tree `retint` walks either, so both of the
    mechanisms this file has for repainting a window miss it entirely.

    `option_add` writes the option *database*, which is read when a widget is
    created - so on its own it reaches only the popdowns that do not exist yet,
    and a combobox that has been dropped down once keeps its old colours for
    the rest of the session. Hence both halves: the database for the unborn,
    and a direct configure for the ones already built, which also catches the
    one being looked at as the theme changes.

    Returns how many existing popdowns were repainted.
    """
    import tkinter as tk
    opts = (("background", pal["INPUT_BG"]), ("foreground", pal["TEXT"]),
            ("selectBackground", pal["ACCENT"]), ("selectForeground", "white"))
    for name, value in opts:
        root.option_add("*TCombobox*Listbox." + name, value)
    # Tk's own font spelling rather than a tuple, this being an option
    # string; the family still comes from `FAMILIES` so a dropdown list and
    # the entry above it cannot end up on two different faces.
    root.option_add("*TCombobox*Listbox.font",
                    "{%s} %d" % (FAMILIES["prose"], ROLES["body"][1]))

    painted = 0
    stack = [root]
    while stack:
        w = stack.pop()
        try:
            stack.extend(w.winfo_children())
        except tk.TclError:            # destroyed mid-walk
            continue
        try:
            if w.winfo_class() != "TCombobox":
                continue
            # ttk names it <combobox>.popdown, with the listbox at .f.l. Asking
            # whether it exists rather than calling ttk::combobox::PopdownWindow,
            # which would build one for every combobox in the window.
            lb = str(w) + ".popdown.f.l"
            if not w.tk.call("winfo", "exists", lb):
                continue
            w.tk.call(lb, "configure",
                      "-background", pal["INPUT_BG"],
                      "-foreground", pal["TEXT"],
                      "-selectbackground", pal["ACCENT"],
                      "-selectforeground", "white")
            painted += 1
        except tk.TclError:
            continue
    return painted


class Theme(object):
    """One app's live theme: the setting, what it resolved to, and the swap.

    The apps keep their colours as module-level names (`BG`, `CARD`, ...) that
    several hundred widget constructions already read, and this rebinds those
    names rather than replacing them - so code written before a theme existed
    goes on working, and a widget built after a switch is born the right
    colour. `retint` deals with the widgets built before it.

    `restyle(root)` is the app's own ttk block: ttk widgets take their colours
    from a style rather than from construction arguments, so they are outside
    the walk and the app re-runs its own block instead.
    """

    def __init__(self, module_globals, extra_dark=None, extra_light=None,
                 restyle=None):
        self.g = module_globals
        self.dark, self.light = palettes(extra_dark, extra_light)
        self.pals = {"dark": self.dark, "light": self.light}
        self.mode = "dark"                 # the setting: system / dark / light
        self.active = "dark"               # what it resolved to
        self.why = "set to dark"
        self.restyle = restyle
        self.roots = []
        # What has to be *rebound* rather than recoloured after a swap: a
        # module that seeded its own globals off the palette holds the values
        # it was seeded with, and `retint` walks widgets rather than globals.
        # Registered rather than reached for, because this file must not know
        # what the modules beside the apps are.
        self.watchers = []
        # Seeded here, so the table above is the only place these eighteen
        # names are written down. Each app used to restate them as literals
        # under this call - agreeing with this table by hand, and with its
        # own extras a second time. What a drift there costs is invisible:
        # retint maps a widget by reading its colour back and looking it up
        # in reverse(old), where old is this table, so a widget painted from
        # a drifted literal has no entry, is skipped, and stays dark inside
        # a light window.
        self._bind(self.dark)
        # And the faces beside the colours, for the same reason and by the
        # same mechanism: one name rather than fourteen, since a role is
        # resolved by `font` at the call site rather than bound as a tuple.
        # A theme switch never moves it - a face is not a palette - so it is
        # seeded once here and never rebound.
        self.g["font"] = font

    def register(self, root):
        """A window to repaint on a switch. One `Tk` is enough for a whole app:
        its `Toplevel`s are its children and the walk reaches them."""
        if root not in self.roots:
            self.roots.append(root)
        # Before the app builds anything, so the first popdown of the session is
        # born in the palette that is live rather than in Tk's white default.
        combo_popdown(root, self.palette())

    def palette(self):
        return self.pals[self.active]

    def watch(self, fn):
        """Run `fn` after every swap, once the widgets have been recoloured.

        `notifier_remote.py` and `storekeeper_export.py` register their palette
        seeding here: a module beside an app is handed the colours it draws
        with rather than importing them, so a switch has to hand it the new
        ones. There is no `unwatch` beside this, and there was one until 074:
        a `Surface` was the only caller, registering one window's render and
        dropping it when that window went.
        """
        if fn not in self.watchers:
            self.watchers.append(fn)

    def _bind(self, pal):
        global _LIVE
        # What `reveal` below draws in. Every other colour in this file is
        # either handed in by the call site or read back off a widget, and a
        # free function that takes neither has no other way to be in the
        # palette that is live - a literal there is exactly the widget the
        # retint walk cannot recognise and leaves dark inside a light window.
        # Written here rather than in `_swap` because a switch is not the only
        # time it moves: this is also the seeding, and an app is bound before
        # it builds anything.
        _LIVE = pal
        for k, v in pal.items():
            self.g[k] = v

    def _swap(self, want):
        if want == self.active:
            return False
        import tkinter as tk
        old, new = self.pals[self.active], self.pals[want]
        self.active = want
        self._bind(new)
        for r in list(self.roots):
            try:
                retint(r, old, new)
                if self.restyle:
                    self.restyle(r)
                # After the restyle: an app's ttk block may re-run its own
                # option_add, and this is the copy that also repaints the
                # popdowns already built.
                combo_popdown(r, new)
            except tk.TclError:            # the window has gone
                self.roots.remove(r)
        # After the walk and the restyle, so a watcher reads a window that is
        # already in the new palette.
        for fn in list(self.watchers):
            try:
                fn()
            except tk.TclError:
                self.watchers.remove(fn)
        return True

    def set(self, mode):
        """Apply a setting. Returns whether the window actually changed."""
        self.mode = mode if mode in MODES else "system"
        want, self.why = resolve(self.mode, fallback=self.active)
        return self._swap(want)

    def follow(self):
        """Re-read Windows if the setting is 'system'. Windows raises no event
        for a theme change, so this belongs on a tick the app already runs."""
        if self.mode != "system":
            return False
        return self.set("system")


def remap(value, rev, new, default=None):
    """One colour string through the reverse map. Anything unrecognised comes
    back unchanged, so a literal a caller chose on purpose survives a switch."""
    token = rev.get(str(value).lower())
    return new[token] if token else (value if default is None else default)


# ------------------------------------------------------------------ the sizing

def fit(win, width):
    """Size a window to what its children actually ask for.

    A written size is a second copy of something the children already know, and
    it is the copy that goes stale the next time a field is added. What makes it
    a defect rather than a cosmetic one is where `pack` puts the shortfall: on
    whichever child was packed last, which in every window this was measured on
    was the button at the bottom. So each caller also packs its buttons into a
    frame at `side="bottom"` before packing the form, and the button is then the
    first child served rather than the last.

    Every window that carried its size in a geometry string and was smaller
    than the form it contains is below, measured before this existed. Six in
    the Server GUI:

        Capability Passwords   116px short   Close, 1px, never mapped
        Cancel Transaction      54px short   its button, 1px, never mapped
          (its Pending branch)  33px short   the same button, 13px of 46
        Add Transaction         49px short   submit, 1px, never mapped
        Modify Transaction      49px short   Save Correction, 1px, unmapped
        Change Admin Password   14px short   the delegation button, 19px of 33
                                62px narrow  and its caption clipped
        Delete Records           9px short   the Delete button, 37px of 46

    Four of those had no usable button at all: Capability Passwords could not be
    closed, Modify Transaction could not be saved, Add Transaction could not be
    submitted - closing the one way a backdated Transaction reaches the history -
    and a Confirmed Transaction could not be cancelled, which is the case only an
    admin password opens.

    And five in the client apps, whose height is fixed by `resizable(True,
    False)` so there is no drag to recover with either:

        Notifier    Admin Login        50px short   Login, 1px of 46, unmapped
        Storekeeper Admin Login        47px short   Login, 1px of 46, unmapped
        Storekeeper Server Settings    35px short   Save, 11px of 46
        Notifier    First Time Setup   26px short   Complete Setup, 27px of 53
        Notifier    Rejection Reason    2px short   the bottom 2px of both
                                                    footer pills, clipped

    Three more are short on an axis that can be dragged - four shortfalls
    between them - all in the Storekeeper and all of them windows with no
    `resizable` call at all, so both axes give: Add Engineer by 37px of width,
    Delete Engineer by 47px of height, and Cancel Transaction by 21px in its
    Pending branch and 27px in its Confirmed one. There a shortfall costs a
    drag rather than a control - except that Delete Engineer's button was not
    mapped at its own written 370x300 either, 1px of the 46 it asks for, which
    is a control nobody would think to drag for; and forced onto a 150px-tall
    screen all three lose the button completely. They call this as well.

    The bulk-scan window is 129px short on the same terms and deliberately does
    not. Both its axes drag, so the shortfall costs a drag; and what it lands
    on is the expanding Treeview that space is there for, rather than a
    control. That it also computes its position is not the reason - the
    position half is out of scope here, which is a thing nobody changed rather
    than a reason to keep a written size.

    Cancel Transaction shows why a computed size is worse than a typed one, not
    better: its height was `370 if needs_pw else 300` in the Server GUI and
    `350 if confirmed else 290` in the Storekeeper, so it was wrong by a
    different amount in each branch and no sweep for geometry literals saw it at
    all. Asking the children removes the `if`.

    Width is max(), not the request: most callers are written wider than their
    children need and should stay that way, while Change Admin Password and Add
    Engineer are written narrower and would clip a label. Height is clamped to
    the screen, since a fixed height leaves no way to shrink a window taller
    than the display and a title bar above the top edge cannot be dragged
    either. Where that clamp does bite, the footer packed first is what keeps
    the button on the screen.

    Fourteen windows, then, and the count is by window: Cancel Transaction has
    two branches in each app and is one window in both tables, which is what
    makes the two comparable. The bulk-scan window above is a fifteenth window
    short of its form and is not one of the fourteen, because it is the one
    that deliberately does not call this.

    Call it once, after every child is packed. A window whose contents are
    settled may keep a written size instead - a table that is meant to be
    dragged, or a form nothing is added to - but then it is the writer's job to
    keep it larger than its form, and `tools/server-checks.py` and
    `tools/client-checks.py` hold both kinds to the same rule.
    """
    win.update_idletasks()
    need_w = win.winfo_reqwidth()
    w = max(width, need_w)
    h = min(win.winfo_reqheight(), win.winfo_screenheight() - 80)
    win.geometry("%dx%d" % (w, h))
    # A minsize taller than the form is the same written number one level down,
    # and it is the copy that wins: wm honours a minimum even on an axis it
    # will not let anybody drag, so `minsize(360, 420)` beside a 368px form
    # quietly puts the 52px back.
    #
    # An **absent** one is the other half of that and is what #192 is about: a
    # window that states no floor at all can be dragged below its form on
    # whichever axis it lets go, and `pack` answers by squeezing whichever
    # child went in last - which is the button, on every window measured
    # above. So the floor is derived here rather than written at each call
    # site, for the reason the size itself is: a number typed beside a form is
    # the copy that goes stale the next time a field is added, and six of
    # these windows had none at all.
    #
    # The height floor is the fitted height, the axis a footer is squeezed on.
    # The width floor is what the children actually ask for and never the
    # `width` argument, which is an opening width most callers write wider
    # than their form on purpose: pinning the floor to it would stop a window
    # being narrowed at all, where what is really being protected is the point
    # at which labels start to clip. An explicit floor already wider than that
    # is a real decision and is left alone.
    floor_w, floor_h = win.minsize()
    win.minsize(max(floor_w, need_w), min(floor_h, h) if floor_h > 1 else h)


class ScrollRegion(object):
    """A window body that scrolls, with everything pinned left outside it.

    Three windows here grew a form with no bound at all - a card per Engineer,
    a card per capability password, a card per notification rule - and a form
    with no bound meets `fit`'s clamp: the height is taken from what the
    children ask for and then clamped to the screen, and `pack` gives the
    shortfall to whatever it served last. Manage Users asked for 1423px of
    height at four Engineers, and the Server GUI's Notification Rules asked for
    1794px at 24 rules against a screen with 1080, both of them on a window
    fixed on both axes so nothing could be dragged open to reach the rest.
    Five more are bounded forms that are simply taller than a 768px screen
    leaves once `fit` has clamped them - Asset Sync, Server Settings, Mail
    Settings, Add Transaction and the opened Remote Admin console (095) -
    and both check suites now fail any window over that line that does not
    scroll the way this does.

    What it is, and each part of it is load-bearing:

    * the body is a `tk.Frame` windowed into a `tk.Canvas`, which is the one
      shape `measure_scrolled_body` in `tools/client-checks.py` measures - a
      region built some other way is not a check that fails, it is a check that
      silently stops measuring;
    * the scrollbar is **ttk**, like every other scrollbar in these files, so
      it takes the palette through the `Vertical.TScrollbar` style rather than
      sitting in a dark window wearing the system grey;
    * the wheel is bound **on the window**, never with `bind_all`: Tk delivers
      a key or a wheel event to the widget, then its class, then the
      toplevel's, so binding the toplevel catches the wheel anywhere inside it
      and nothing in a sibling window - where a global binding in an app that
      stacks five dialogs off one console would scroll whichever of them was
      bound last. `installer.py` is the exception that documents this, being
      one window in a process of its own;
    * `size` is what keeps `fit` honest, and is asked **beside** it on the same
      repaint: laid flat, the window reports what everything *but* the region
      needs, and what is left of the screen is what the region may have. So a
      form that fits opens exactly as tall as itself with nothing to scroll,
      and one more card lengthens the scroll rather than the window.

    What it deliberately does not do is shrink a card to make room. A form
    legible for four rows and illegible for eight is the same bug deferred.

    It is here rather than copied into each window for rule 10's reason - this
    is one behaviour in two apps - and the call sites that predate it are left
    alone: each is inlined into a window's own layout and converting them is a
    refactor of working code rather than part of the bug this answers.
    """

    def __init__(self, win, bg):
        import tkinter as tk
        from tkinter import ttk
        self.win = win
        self.canvas = tk.Canvas(win, bg=bg, highlightthickness=0)
        self.bar = ttk.Scrollbar(win, orient="vertical",
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._item = self.canvas.create_window((0, 0), window=self.body,
                                               anchor="nw")
        self.body.bind("<Configure>", self._body_resized)
        self.canvas.bind("<Configure>", self._canvas_resized)
        win.bind("<MouseWheel>", self._wheel)

    def _body_resized(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _canvas_resized(self, e):
        self.canvas.itemconfig(self._item, width=e.width)

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def pack(self, padx=18, pady=(8, 0)):
        """Put the region in, which every pinned child must already have done.

        `pack` serves a cavity in the order it was filled, so a canvas taking
        the room before a footer or a caption went in is that footer getting
        whatever is left, which is nothing. The scrollbar goes in before the
        canvas for the same reason one level down.
        """
        self.bar.pack(side="right", fill="y", padx=(0, 6), pady=pady)
        self.canvas.pack(side="left", fill="both", expand=True,
                         padx=(padx, 0), pady=pady)

    def size(self, floor=160, margin=80):
        """How much height the region gets: the form's, or what the screen has.

        Asked beside `fit` on the same repaint, and again whenever the form
        gains or loses a card, so what `fit` is told about is the height of the
        scrolling body rather than the number of rows in it.
        """
        self.canvas.configure(height=1)
        self.win.update_idletasks()
        chrome = self.win.winfo_reqheight() - 1
        room = self.win.winfo_screenheight() - margin - chrome
        self.canvas.configure(
            height=max(floor, min(self.body.winfo_reqheight(), room)))

    def width(self, floor):
        """The width to hand `fit`, which cannot measure this for itself.

        A frame windowed into a canvas does not pass its request up, so the
        window's own `reqwidth` is the canvas's configured width whatever is
        inside it. The floor stays whatever the call site always opened at.
        """
        return max(floor, self.body.winfo_reqwidth() + 24
                   + self.bar.winfo_reqwidth())


def rewrap(label, inset=0):
    """Keep a paragraph wrapped to the width its box actually has.

    `wraplength` is a written-down width, and in a window whose width can be
    dragged it goes stale the same way a written-down window size does: the
    number was the answer once, and the moment somebody widens the window what
    is left is a paragraph wrapped at 820px inside a 1268px card, with 448px
    of empty card to the right of it. So the number is read as a
    floor rather than as the answer - the narrowest this text may be drawn,
    which is a real decision and is left alone for the reason `fit` leaves a
    `minsize` width alone - and anything wider than that is taken from the box
    the label sits in.

    `inset` is the horizontal padding between the label and that box's edges,
    which the caller has already written into its own `pack`; it is the
    padding rather than the width, and the box is what is asked for the width.
    Only when it changed, for the reason `Row.relay_at` gives: setting
    `wraplength` changes the height the label asks for, which fires
    `<Configure>` again, and inside a nested `update_idletasks` that queue
    never drains.

    Returns the label, so it can be wrapped around one that is constructed and
    packed in the same expression.
    """
    floor = label.winfo_pixels(label.cget("wraplength")) or 1
    box = label.master

    def relay(_e=None):
        want = max(floor, box.winfo_width() - inset)
        if label.winfo_pixels(label.cget("wraplength")) != want:
            label.config(wraplength=want)

    box.bind("<Configure>", relay, add="+")
    return label


# ------------------------------------------------------------- closing a window

#: The palette that is live, for the one drawing function here that is handed
#: no colour and has no widget to read one back off (`reveal`). Seeded with
#: `DARK` so it is never undefined - `Theme._bind` overwrites it before an app
#: builds anything, and the seed is what answers a module imported without one.
_LIVE = DARK

#: What a password field masks with where nothing says otherwise. The four
#: apps state their own at each construction and `reveal` reads that back, so
#: this is the fallback for a field that masks with nothing recognisable
#: rather than a value anything is held to.
MASK = "●"


def escape_closes(win, command=None):
    """Esc closes this sub-window, by the same route its X does (G4).

    There was no Escape binding anywhere in this product, across the
    forty-five sub-windows that take one now, so every dialog had to be
    closed by finding its Close button or its title bar.

    **It is the same close, not a second one.** `command` is whatever that
    window registered on `WM_DELETE_WINDOW`, and where it registered nothing
    it is `win.destroy` - which is exactly what the window manager does with
    an X on a window carrying no protocol handler. That is the whole of the
    design, and it is what makes this safe to put on windows nobody re-read
    for it: a window that asks before discarding a typed change (A2) goes on
    asking, a confirmation that reads its answer after `wait_window` reads
    the same cancel it reads from the X, and a grab is released by the
    destroy that ends the window rather than by a second rule here. A copy of
    any of those three decisions in this function would be the one free to
    drift from the window it is about.

    **Bound on the window and never with `bind_all`.** Tk delivers a key to
    the widget's own tag, then its class, then the **toplevel's**, then
    `all` - so binding the toplevel catches Esc typed into any field inside
    it and catches nothing typed into a sibling window. `bind_all` would put
    every open window's Esc on every other one, which in an app that opens
    five dialogs off one console is a keypress closing whichever of them the
    binding happened to be added by last.

    **What must not call this**: a main window (the Server GUI's root, the
    Storekeeper's, the installer's - Esc is a dismissal and those are not
    dismissable), the Notifier's confirm/reject popup (it has no close button
    on purpose and stays up until the engineer answers - a popup dismissed by
    a stray keypress is an engineer who was never asked and a Transaction
    auto-accepted a day later with nobody having looked), and any window that
    refuses its own X while a worker is running - the two forced-update
    windows and the installer's progress window, each of which already
    answers `WM_DELETE_WINDOW` with a no-op. **Those three are the whole of
    the mid-operation case**: every other long job in these apps runs on the
    Tk thread, where no keypress is delivered at all until it finishes, so
    there is no window to ignore an Esc on and nothing for a busy flag to
    guard.
    """
    def on_escape(event=None):
        (command or win.destroy)()

    win.bind("<Escape>", on_escape, add="+")
    return on_escape


def reveal(entry):
    """Let whoever is typing see what they typed, in one masked field (#202).

    Every password field in these four apps is `show`-masked, so the only way
    to find out that a character went astray is to be refused - and the
    refusal cannot say which character, because the server compares a hash. A
    password already in a field on a screen somebody is standing at is not a
    secret being disclosed to anybody new; it is the value they typed a moment
    ago. What it defends against is a shoulder, which is why it is **off by
    default, per field, and never remembered**: there is no setting, nothing
    is written anywhere, and the next window opens masked like the last one.

    **It reveals what was typed into this field and nothing else, ever.** Two
    of these fields stand in front of a *stored* secret - Mail Settings' SMTP
    password and Asset Sync's credential, the two replayable ones this product
    holds (ADR-0013, ADR-0014) - and those windows are deliberately never told
    what is stored: they open **empty**, `GET /admin/mail` answers whether a
    password is stored and never what it is, and the Notifier's Remote Admin
    Mail panel is the same over the network. This toggle shows the contents of
    an entry widget, so on an empty field it shows nothing until somebody
    types, and there is no path from here to a file, an endpoint or a
    clipboard. It must never grow one: "show the password" is the first place
    somebody would later reach for a convenience that breaks that property.

    Nothing about a password reaching the System Log changes either - what is
    revealed is a widget's own contents and `_log_event` is not handed one
    (`tools/server-checks.py` asserts that as a source check).

    **The mask is the entry's own**, read back rather than assumed: this file
    does not get to decide what a field masks with, and the four apps do not
    agree - `●` at twenty-seven sites and `•` at one. Re-masking
    with a constant would silently restyle one field the first time it was
    revealed and hidden again.

    **The control is placed inside the entry** rather than packed beside it,
    which is the whole reason this is one function and not an edit to
    twenty-eight forms: these fields are packed, gridded and placed, some
    inside a helper that returns the widget and some built before their row
    exists, and a sibling widget would have to be added by whichever geometry
    manager that call site happens to use. A `tk.Entry` is a geometry master
    like any other widget, so `place` on it needs to know nothing about the
    form around it.

    It is a **word and not a glyph**, in the caption face and `SUBTEXT`, for
    the reason #179 to #182 took the glyphs off the pills: direction is the
    only colour in this product and a control that says what it does needs no
    icon to be guessed at. It is drawn in the palette that is live so the
    retint walk recognises it on a theme switch, and on the entry's own
    background so it reads as part of the field.

    Re-masks on the entry's own `<Destroy>`, which is belt and braces rather
    than a mechanism: the widget is going, so nothing could see it either way.
    What it states is the rule - a revealed field never outlives the window it
    was revealed in - in the one place somebody would later be tempted to
    carry the state somewhere that does.
    """
    import tkinter as tk
    mask = str(entry.cget("show")) or MASK
    lab = tk.Label(entry, text="show", bg=entry.cget("bg"),
                   fg=_LIVE["SUBTEXT"], font=font("caption"), cursor="hand2")
    lab.place(relx=1.0, rely=0.5, anchor="e", x=-4)

    def remask(_event=None):
        try:
            entry.configure(show=mask)
            lab.configure(text="show")
        except tk.TclError:                # the field has gone
            pass

    def toggle(_event=None):
        if entry.cget("show"):
            entry.configure(show="")
            lab.configure(text="hide")
        else:
            remask()

    lab.bind("<Button-1>", toggle)
    entry.bind("<Destroy>", remask, add="+")
    return lab


#: The windows that are open right now, keyed by what each one is *about*.
#: Module level because these apps are one process each and a window is one
#: per process; `single` is the only writer and every entry leaves on its own
#: window's <Destroy>.
# What `flash` below asks Windows for: the taskbar button, and until the
# window is brought to the foreground rather than for a fixed count. The
# second is what makes it a signal instead of a blink somebody was looking
# away for.
FLASH_TRAY = 0x00000002
FLASH_UNTIL_FOREGROUND = 0x0000000C

_OPEN_WINDOWS = {}


def raise_open(key):
    """Is a window already open under `key`? Then raise it and hand it back (#191).

    The first half of the single-instance guard, and it is a pair rather than
    one call because the decision has to be made **before** the window is
    built: an opener asks this and returns, or builds and registers with
    `single` below. A guard that could only run after `tk.Toplevel` had
    already been constructed would be a second window destroyed a moment
    after it appeared, which is a flicker rather than a fix.

    What a second copy costs is not cosmetic. Two Manage Users windows over
    one Engineer: the second was built from the row as it was before the
    first saved, and its own Set writes that stale form back - the one-writer
    helpers keep the *rules* and say nothing about the ordering. Two
    Notification Rules windows: that is the one window here with a real edit
    buffer, so the second holds the list from before the first saved and its
    Save replaces the whole list with it. And the console's unsaved-changes
    count (#119) walks its tracked windows, so two copies of one window are
    two entries naming the same thing.

    **Raised rather than refused in silence**: the person clicked the menu
    because they want that window, and the honest answer is the one that is
    already there. `deiconify` first, since a minimised window lifts to
    nothing.

    It answers the **window** rather than a bool, which every ordinary
    caller reads as one (`if raise_open(key): return`); what the extra costs
    nothing and buys is the one window opened *about* something - the feed
    row that opens Manage Transaction History on a Transaction has to be able
    to re-select on a window that is already up, or clicking a second row
    would raise the first row's selection and look like nothing happened.

    A key naming a window that has since gone - destroyed without its
    `<Destroy>` reaching us, which is what an interpreter torn down under a
    dying window does - is dropped and answered None, because a registry
    that cannot forget is a window that opens once per process.
    """
    import tkinter as tk
    win = _OPEN_WINDOWS.get(key)
    if win is None:
        return None
    try:
        if not win.winfo_exists():
            raise tk.TclError("gone")
        win.deiconify()
        win.lift()
        win.focus_force()
    except tk.TclError:
        if _OPEN_WINDOWS.get(key) is win:
            del _OPEN_WINDOWS[key]
        return None
    return win


def single(win, key):
    """Register `win` as the one window under `key` (#191).

    The other half of `raise_open` above, called once the window exists. The
    key is what the window is **about** rather than who opened it: most of
    these are one per app and are keyed by their own name, while a window
    opened about a selected row is keyed by the row as well - Transaction
    Detail is `"transaction_detail:<id>"`, so two different Transactions open
    two windows and one Transaction opens one.

    **The cleanup is on this window's own `<Destroy>` and never a child's.**
    Tk delivers that event for every widget in the tree, so an unguarded
    handler drops the registration the moment the first label inside the
    window goes - which is a window still on screen that can be opened a
    second time, exactly what this exists to stop. The same trap
    `set_window_icon` below documents, and the same answer:
    compare `event.widget` against the window itself.

    **What must not call this**: the Notifier's confirm/reject popup, where
    one at a time is already the queue's job and a refused second popup would
    silently drop the Transaction behind it - an engineer who stops being
    asked to confirm anything is the one failure that app exists to prevent;
    and the two forced-update windows and the installer's progress window,
    the three that already refuse their own X, a guard adding nothing to a
    window that cannot be left in the first place.
    """
    _OPEN_WINDOWS[key] = win

    def gone(event=None):
        if event is not None and event.widget is not win:
            return
        if _OPEN_WINDOWS.get(key) is win:
            del _OPEN_WINDOWS[key]

    win.bind("<Destroy>", gone, add="+")
    return gone


def flash(win):
    """Ask for attention without taking it (#193).

    The answer to a window that has something to say while somebody is
    working in another app. Every other spelling of that in this product was
    `lift()` plus `-topmost`, which does not ask - it takes the screen off
    whatever was in front of it, and on a Storekeeper machine that is
    somebody mid-scan or mid-sentence in another window. The taskbar button
    is where Windows already says *this app wants you*, so that is what is
    used: `FLASHW_TRAY | FLASHW_TIMERNOFG` flashes the button and then leaves
    it highlighted until the window is brought to the foreground, which is
    the one signal here that survives being ignored for ten minutes.

    **It never raises, never focuses and never returns an error.** The two
    callers are a notification the app decided to show, and a notification
    that could not be flashed is still a notification on the window - so this
    answers True or False and the caller is free not to look. `ctypes` and
    `user32` are guarded the way `pillow` is throughout this file: on
    anything that is not Windows there is no taskbar button to flash, and the
    window it was called about is already showing what it had to say.

    `GetAncestor(hwnd, GA_ROOT)` rather than `winfo_id()` alone, because Tk
    on Windows hands out the HWND of its own inner window and the button on
    the taskbar belongs to the frame above it - flashing the inner one is a
    call that succeeds and does nothing visible, which is the worst answer
    available.
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False
    try:
        user32 = ctypes.windll.user32
    except Exception:
        return False

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT),
                    ("hwnd", wintypes.HWND),
                    ("dwFlags", wintypes.DWORD),
                    ("uCount", wintypes.UINT),
                    ("dwTimeout", wintypes.DWORD)]

    try:
        hwnd = user32.GetAncestor(wintypes.HWND(int(win.winfo_id())), 2)
        if not hwnd:
            hwnd = wintypes.HWND(int(win.winfo_id()))
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd,
                          FLASH_TRAY | FLASH_UNTIL_FOREGROUND, 0, 0)
        return bool(user32.FlashWindowEx(ctypes.byref(info)))
    except Exception:
        return False



# ------------------------------------------------------------------- the pills

#: Two sets of metrics because the apps have two kinds of row, and both were
#: measured off the shipped windows rather than picked. A Server toolbar label
#: is Segoe UI 9 with padx=11 and a 4px gap; a client footer pill is Segoe UI
#: Semibold 10 with a 13px inset and an 8px gap.
TOOLBAR = {"size": 9, "pad": 11, "gap": 4, "bold": False, "h": 32}
FOOTER = {"size": 10, "pad": 13, "gap": 8, "bold": True, "h": 38}

FLOOR = 46        # narrowest a pill is ever drawn, whatever the label says
CAP = 210         # widest a footer cell is stretched to


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    """Tkinter has no rounded widget and a flat tk.Button cannot round its
    corners, so every button in this product is a polygon on a canvas."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class Pill(object):
    """Rounded, hover-lit button that redraws at whatever width and palette it
    is given.

    The signature is the one the three apps' own `Pill` classes had, so the
    twenty-odd existing calls read the same; `short` and `size`/`pad` are the
    new part, and only the rows a `Row` manages need them. `w` is still the
    width a pill asks for when it is simply packed - a `Row` overrides it.

    Not a `tk.Canvas` subclass, unlike the copies this replaces in the two
    clients: a class body naming `tk.Canvas` needs tkinter imported when the
    module is, and `server.py` must stay importable headless. Call `.pack()`
    and friends on the pill; they forward to `.cv`.
    """

    def __init__(self, parent, text, bg, fill, hot, fg="white", w=150, h=40,
                 radius=10, bold=True, command=None, short=None, size=10,
                 pad=None, gated=False):
        import tkinter as tk
        from tkinter import font as tkfont
        self.cv = tk.Canvas(parent, width=w, height=h, bg=bg,
                            highlightthickness=0, cursor="hand2")
        self.cv._retint_hook = self._retint
        # A way back from the widget to the pill. The retint walk sees widgets,
        # and so does anything checking this window from outside it.
        self.cv._pill = self
        self.full = text
        self.short = short or text
        self.gated = gated
        self.bg, self.fill, self.hot, self.fg = bg, fill, hot, fg
        self._w, self._h, self._r = w, h, radius
        self._pad = pad if pad is not None else (13 if bold else 11)
        self._tier = "full"
        self._on = False
        self.truncated = False
        self.command = command
        self._font = tkfont.Font(
            family=FAMILIES["emph" if bold else "prose"], size=size)
        self.cv.bind("<Configure>", lambda _e: self.redraw(), add="+")
        self.cv.bind("<Enter>", lambda _e: self._light(True), add="+")
        self.cv.bind("<Leave>", lambda _e: self._light(False), add="+")
        self.cv.bind("<Button-1>", lambda _e: self._fire(), add="+")
        self.redraw()

    # -- what a layout asks it ------------------------------------------------

    def words(self, tier=None):
        text = self.full if (tier or self._tier) == "full" else self.short
        return (text + "  \U0001f512") if self.gated else text

    def intrinsic(self, tier=None):
        """The width this pill wants at a tier - never below FLOOR, so a row of
        one-word buttons does not collapse into a row of squares."""
        return max(FLOOR, self._font.measure(self.words(tier)) + 2 * self._pad)

    def set_tier(self, tier):
        if tier != self._tier:
            self._tier = tier
            self.redraw()

    def set_text(self, text, short=None):
        self.full = text
        self.short = short or text
        self.redraw()

    def fit_text(self):
        """Widen this pill to the label it is actually carrying (165).

        `w` is the width a pill asks for when it is simply packed, and every
        one of those numbers was written at the display scaling it was measured
        on - while a label's width is `_font.measure`, which is not. At any
        other scaling the two part company and `_fit` above answers the way it
        has to, by eliding: the Storekeeper's theme button is `w=158` and its
        caption is drawn at 175px on a 175% display, so the control that says
        which of Dark, Light and Follow Windows is in force reads `Follow Wi...`
        and the mode behind the icon - the whole reason that caption is there -
        is the half that goes.

        A `Row` never calls this: a row's whole job is deciding the width, and
        a pill that widened itself inside one would be arguing with it. This is
        for the packed pill, which has nothing to decide it.
        """
        want = self.intrinsic()
        if int(self.cv.cget("width")) != int(want):
            self.cv.configure(width=int(want))
        return want

    # -- drawing --------------------------------------------------------------

    def _fit(self, w):
        s = self.words()
        room = w - 2 * self._pad
        if self._font.measure(s) <= room:
            return s, False
        while s and self._font.measure(s + "…") > room:
            s = s[:-1]
        return (s + "…") if s else "…", True

    def redraw(self):
        import tkinter as tk
        w = self.cv.winfo_width()
        if w <= 1:
            w = self._w
        h = self.cv.winfo_height()
        if h <= 1:
            h = self._h
        try:
            self.cv.delete("all")
            self._body = round_rect(self.cv, 1, 1, w - 1, h - 1, self._r,
                                    fill=(self.hot if self._on else self.fill),
                                    outline="")
            text, self.truncated = self._fit(w)
            self._label = self.cv.create_text(w / 2.0, h / 2.0 + 1, text=text,
                                              fill=self.fg, font=self._font)
        except tk.TclError:            # destroyed between the bind and here
            pass

    def _light(self, on):
        self._on = on
        self.redraw()

    def _fire(self):
        if self.command:
            self.command()

    def _retint(self, rev, new):
        self.bg = remap(self.bg, rev, new)
        self.fill = remap(self.fill, rev, new)
        self.hot = remap(self.hot, rev, new)
        self.fg = remap(self.fg, rev, new)
        self.cv.configure(bg=self.bg)
        self.redraw()

    # -- geometry, forwarded --------------------------------------------------

    def pack(self, **kw):
        self.cv.pack(**kw)
        return self

    def grid(self, **kw):
        self.cv.grid(**kw)
        return self

    def place(self, **kw):
        self.cv.place(**kw)
        return self

    def pack_forget(self):
        self.cv.pack_forget()

    def grid_forget(self):
        self.cv.grid_forget()

    def place_forget(self):
        self.cv.place_forget()

    def destroy(self):
        self.cv.destroy()

    def winfo_ismapped(self):
        return self.cv.winfo_ismapped()


# ------------------------------------------------------------------- the rows

class Row(object):
    """One button row that re-lays itself as its box changes width.

    Two layouts, one per kind of row, and which one a row gets is a property of
    the row and not of the window it is in:

    **toolbar** - full labels on one line if they fit, short labels on one line
    if those fit, and only then wrap into more lines, still at short labels.
    Nothing is ever truncated, hidden behind a More menu, or reduced to a bare
    icon: this row is the only place several of these actions exist, so an
    action the window decided not to show is an action nobody can reach.

    **footer** - every button gets an equal column and fills it, capped at
    `CAP` so a maximised window does not draw a 600px Close button; a capped
    row sits right, where a footer's buttons already were. It takes the short
    tier before it truncates anything, which is the one thing added rather than
    taken from the prototype: a footer that has "Delete" available and draws
    "Delete Selec..." instead is strictly worse, and Delete is the button here
    where a half-read label costs the most.

    `place` rather than `pack`, because the arithmetic is the point. The box is
    told its own height by whatever the layout returns, which is how a wrapped
    toolbar pushes the window taller instead of drawing over its neighbour.
    """

    def __init__(self, box, pills, kind="toolbar", h=None, gap=None,
                 report=None):
        m = TOOLBAR if kind == "toolbar" else FOOTER
        self.box, self.pills, self.kind = box, pills, kind
        self.gap = m["gap"] if gap is None else gap
        self.h = h or m["h"]
        self.rows = 1
        self.report = report
        self.last = ""
        box._ui_row = self          # findable by walking the widget tree
        box.pack_propagate(False)
        box.configure(height=self.h)
        box.bind("<Configure>", lambda _e: self.relay(), add="+")

    def min_width(self):
        """The narrowest this row can be drawn without lying - the number a
        dialog should set `minsize` from.

        A toolbar can always wrap, so it is the widest single short label. A
        footer never wraps and its columns are equal, so it is that same widest
        short label *times the number of buttons* - the prototype used the pill
        floor here and the number it produced was one that still truncated
        `Cancel`, which is a minsize that lies in exactly the way
        `resizable(False, False)` does.
        """
        if not self.pills:
            return FLOOR
        widest = max(p.intrinsic("short") for p in self.pills)
        if self.kind == "toolbar":
            return widest
        n = len(self.pills)
        return n * widest + self.gap * (n - 1)

    def relay(self):
        self.relay_at(self.box.winfo_width())

    def relay_at(self, avail):
        """Lay out against a width given rather than measured: `winfo_width`
        still reports the old one until Tk gets an idle turn, so a caller that
        has just set the width has to say what it set."""
        if avail <= 1 or not self.pills:
            return
        h = (self._toolbar if self.kind == "toolbar" else self._footer)(avail)
        # Only when it changed. Setting the height fires <Configure> again, and
        # inside a nested update_idletasks that queue never drains - which is
        # what wedged the prototype at 700px into a window that painted black.
        if int(self.box.cget("height")) != int(h):
            self.box.configure(height=int(h))

    def _say(self, text):
        self.last = text
        if self.report is not None:
            self.report(text)

    def _toolbar(self, avail):
        n = len(self.pills)
        for tier in ("full", "short"):
            need = (sum(p.intrinsic(tier) for p in self.pills)
                    + self.gap * (n - 1))
            if need <= avail:
                x = 0
                for p in self.pills:
                    p.set_tier(tier)
                    w = p.intrinsic()
                    p.place(x=int(x), y=0, width=int(w), height=self.h)
                    x += w + self.gap
                self.rows = 1
                self._say("%s labels, 1 row, %dpx of %dpx"
                          % (tier, need, avail))
                return self.h
        x, y, rows = 0, 0, 1
        for p in self.pills:
            p.set_tier("short")
            w = p.intrinsic()
            if x and x + w > avail:
                x, y, rows = 0, y + self.h + self.gap, rows + 1
            p.place(x=int(x), y=int(y), width=int(min(w, avail)),
                    height=self.h)
            x += w + self.gap
        self.rows = rows
        total = rows * self.h + (rows - 1) * self.gap
        self._say("short labels, %d rows, %dpx of height" % (rows, total))
        return total

    def _footer(self, avail):
        n = len(self.pills)
        cell = (avail - self.gap * (n - 1)) / float(n)
        capped = cell > CAP
        if capped:
            cell = CAP
        tier = "full"
        if max(p.intrinsic("full") for p in self.pills) > cell:
            tier = "short"
        for p in self.pills:
            p.set_tier(tier)
        used = cell * n + self.gap * (n - 1)
        x = avail - used if capped else 0    # a capped row sits right
        for p in self.pills:
            p.place(x=int(x), y=0, width=int(cell), height=self.h)
            x += cell + self.gap
        cut = sum(1 for p in self.pills if p.intrinsic() > cell)
        self.rows = 1
        self._say("%d column%s of %dpx%s, %s labels, %s, min %dpx"
                  % (n, "" if n == 1 else "s", int(cell),
                     " capped right" if capped else "", tier,
                     ("%d truncated" % cut) if cut else "all fit",
                     self.min_width()))
        return self.h


def row_of(parent, specs, kind="toolbar", h=None, gap=None, report=None,
           **pill_kw):
    """A box, its pills and the `Row` that lays them out, in one call.

    `specs` is a list of `(full, short, colours, command)` - or of
    `(full, short, colours, command, extra)`, where `extra` is a dict of further
    `Pill` arguments for that one button, which is how the Server GUI marks the
    four actions that ask for a password. `colours` is `(bg, fill, hot, fg)` and
    `short` may be None for a label that does not shorten. Returns
    `(box, row)` - pack the box, and the row follows it.
    """
    import tkinter as tk
    m = TOOLBAR if kind == "toolbar" else FOOTER
    box = tk.Frame(parent, bg=specs[0][2][0] if specs else None)
    pills = []
    for spec in specs:
        full, short, colours, command = spec[:4]
        extra = dict(pill_kw, **(spec[4] if len(spec) > 4 else {}))
        bg, fill, hot, fg = colours
        pills.append(Pill(box, full, bg, fill, hot, fg=fg, h=h or m["h"],
                          bold=m["bold"], size=m["size"], pad=m["pad"],
                          command=command, short=short, **extra))
    return box, Row(box, pills, kind=kind, h=h, gap=gap, report=report)


# --------------------------------------------------- the list-and-detail shape

#: The list pane's width. Fixed rather than a share of the window: the pane
#: carries an Asset Number over a Serial Number in a monospace face, so what it
#: needs is a property of the identifiers rather than of how wide somebody has
#: dragged the window - the detail beside it is the half that wants the room.
#: The figure is `Split.LIST_W` in `prototypes/pass3_ui.py`, which is where the
#: proportion of this shape was settled.
LIST_W = 420

#: The row, the section cell, the direction gutter and the selection mark. They
#: are here rather than inside the three classes because they have to agree
#: with each other: the mark and the gutter are two marks on one leading edge,
#: and a 3px mark beside a 3px gutter is a row with two gutters on it.
ROW_H = 54
SECTION_H = 38
GUTTER_W = 3
MARK_W = 2


class SectionBar(object):
    """The app's whole navigation: one horizontal strip, one selected section.

    The selected section is `PANEL` against the `SHELL` the strip stands on,
    with a 2px `TEXT` bar along its edge; every other section is the shell
    colour with its label in `MUTE`. There is no second selection device in
    this material - the list row below is this one rotated, and the
    Storekeeper's and the Notifier's existing tabs are this widget with fewer
    entries rather than a second thing that looks like it. Converting those two
    is their own ticket; this one only adds the widget.

    **The bar is on the bottom edge and not the leading one.** That is what
    `prototypes/pass3_ui.py`'s `Flat._tabs` draws, and the reason is that a
    horizontal strip of abutting cells has no visible leading edge: a 2px mark
    down the left of one cell is a 2px mark down the right of its neighbour,
    and which of the two it belongs to is a guess. The list row keeps its mark
    on the leading edge, where the rows are stacked and that edge is a column
    of its own.

    Not a `tk.Frame` subclass, for `Pill`'s reason: a class body naming
    `tk.Frame` needs tkinter imported when this module is, and this module is
    imported headless. Call `.pack()` and friends on the bar.
    """

    def __init__(self, parent, names, shell, panel, text, mute, line,
                 command=None, current=None, size=11, pad=17):
        import tkinter as tk
        self.shell, self.panel = shell, panel
        self.text, self.mute = text, mute
        self.command = command
        self.names = tuple(names)
        self.current = None
        self.cells = {}
        self.box = tk.Frame(parent, bg=shell)
        strip = tk.Frame(self.box, bg=shell, height=SECTION_H)
        strip.pack(fill="x")
        strip.pack_propagate(False)
        # The hairline is part of the widget rather than something each window
        # remembers to draw under it: the strip is SHELL and the pane below it
        # is PANEL, so without the rule the selected cell is the only thing
        # saying where one ends and the other starts.
        tk.Frame(self.box, bg=line, height=1).pack(fill="x")
        for name in self.names:
            cell = tk.Frame(strip, bg=shell, cursor="hand2")
            # Which section this cell picks, read from outside the window.
            # `ListPane.add`'s `_ui_list_row` idiom and its reason, one shape
            # along: a bound frame is a status chip unless it says otherwise,
            # and `tools/server-checks.py` opens every bound frame it can
            # find to prove that a chip nobody remembered still opens its
            # dialog. A cell opens nothing; it swaps the stage.
            cell._ui_section_cell = name
            cell.pack(side="left", fill="y")
            # `side="bottom"` first, and the label after it: `pack` gives a
            # shortfall to whichever child it served last, and the 2px mark is
            # the one thing on this cell that cannot be allowed to vanish.
            mark = tk.Frame(cell, bg=shell, height=MARK_W)
            mark.pack(side="bottom", fill="x")
            lbl = tk.Label(cell, text=name, bg=shell, fg=mute, padx=pad,
                           cursor="hand2", font=font("label", size=size))
            lbl.pack(fill="both", expand=True)
            self.cells[name] = (cell, lbl, mark)
            for w in (cell, lbl):
                w.bind("<Button-1>", lambda _e, n=name: self._click(n))
        self.select(current or (self.names[0] if self.names else None))

    def _click(self, name):
        self.select(name)
        if self.command:
            self.command(name)

    def select(self, name):
        """Paint `name` as the selected section, and nothing else.

        Deliberately does **not** call `command`: a window restoring the
        section it was left on would otherwise fire the callback that rebuilds
        what it is restoring, which is the one path where the two differ.
        """
        self.current = name
        for key, (cell, lbl, mark) in self.cells.items():
            on = key == name
            fill = self.panel if on else self.shell
            cell.configure(bg=fill)
            lbl.configure(bg=fill, fg=self.text if on else self.mute)
            mark.configure(bg=self.text if on else fill)

    def pack(self, **kw):
        self.box.pack(**kw)
        return self

    def grid(self, **kw):
        self.box.grid(**kw)
        return self


class ListPane(object):
    """A fixed-width column of rows, and which one of them is selected.

    Each row is the Asset Number over the Serial Number - rules 3 and 4, those
    two identifiers, in that order, first - with the direction word and the
    state right-aligned against them, a 3px direction gutter on the leading
    edge, and a 2px `TEXT` mark on that same edge when the row is selected. The
    selected row's fill is `WELL`, the recess, so the mark and the fill say one
    thing between them rather than two.

    **Real widgets rather than a `ttk.Treeview`**, which is the decision 076
    was asked to make for everything built after it; it is written down in
    `docs/CODING_STANDARDS.md` rather than only here, because the tickets that
    read it are building other lists and will not be reading this file. The
    short of it is that a Treeview row is one font, one foreground and one
    height, and this row is two lines in two faces with a third colour beside
    them.

    The wheel is bound on the **canvas and its body** rather than on the
    window. That is the `_ScrollArea` shape rather than `ScrollRegion`'s, and
    it is deliberate: `ScrollRegion` is a window's whole body, so the toplevel
    binding it uses is unambiguous, while a pane has siblings - a detail beside
    it, a form under it - and a window-level binding would scroll this pane
    wherever the pointer happened to be.
    """

    def __init__(self, parent, panel, well, text, mute, line,
                 width=LIST_W, command=None):
        import tkinter as tk
        from tkinter import ttk
        self.panel, self.well, self.text = panel, well, text
        self.mute, self.line = mute, line
        self.command = command
        self.width = width
        self.selected = None
        self._rows = []
        self.frame = tk.Frame(parent, bg=panel, width=width)
        self.frame.pack_propagate(False)
        # width/height small on purpose, `_ScrollArea`'s reason: a bare canvas
        # asks for ~378px and defeats `pack(expand=True)` in a short column.
        self.cv = tk.Canvas(self.frame, bg=panel, highlightthickness=0, bd=0,
                            width=10, height=10)
        self.sb = ttk.Scrollbar(self.frame, orient="vertical",
                                command=self.cv.yview)
        self.cv.configure(yscrollcommand=self.sb.set)
        # The scrollbar before the canvas, `ScrollRegion.pack`'s reason: `pack`
        # serves a cavity in the order it was filled, and a canvas that took
        # the room first leaves the bar whatever is left, which is nothing.
        self.sb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.cv, bg=panel)
        self._win = self.cv.create_window((0, 0), window=self.body,
                                          anchor="nw")
        self.body.bind("<Configure>", lambda _e: self.cv.configure(
            scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>",
                     lambda e: self.cv.itemconfig(self._win, width=e.width))
        for w in (self.cv, self.body):
            w.bind("<MouseWheel>", lambda e: self.cv.yview_scroll(
                int(-e.delta / 120), "units"), add="+")

    def clear(self):
        for child in self.body.winfo_children():
            child.destroy()
        self._rows = []
        self.selected = None

    def add(self, ident, sub="", word="", word_fg=None, state="",
            state_fg=None, gutter=None, key=None):
        """One row. `key` is what `command` is handed and what `select` takes.

        The caller says what to draw rather than handing over a record: this
        module is shared by four apps and imported by the installer on a
        machine with no database anywhere near it, so a Transaction never
        crosses this line.
        """
        import tkinter as tk
        if key is None:
            key = len(self._rows)
        wrap = tk.Frame(self.body, bg=self.panel)
        # A way back from the widget to the pane, `Pill.cv._pill`'s idiom and
        # its reason: the retint walk sees widgets and so does anything reading
        # this window from outside it. Here it also tells a row apart from a
        # status chip - both are frames with a `<Button-1>` on them, and
        # `tools/server-checks.py` opens every bound frame it can find to prove
        # that a chip nobody remembered still opens its dialog. A row opens
        # nothing; it selects.
        wrap._ui_list_row = self
        wrap.pack(fill="x")
        mark = tk.Frame(wrap, bg=self.panel, width=MARK_W)
        mark.pack(side="left", fill="y")
        # The gutter carries the **direction**, which is the one thing on this
        # row that must not be misread: an asset going out becomes an
        # engineer's responsibility and one coming back stops being it, where
        # the state is a word two labels along and is read as a word.
        tk.Frame(wrap, bg=gutter or self.mute,
                 width=GUTTER_W).pack(side="left", fill="y", padx=(11, 0))
        pad = tk.Frame(wrap, bg=self.panel, padx=11, pady=8)
        pad.pack(side="left", fill="both", expand=True)
        top = tk.Frame(pad, bg=self.panel)
        top.pack(fill="x")
        low = tk.Frame(pad, bg=self.panel)
        low.pack(fill="x", pady=(2, 0))
        # The identifier is the hero of the row, sized up **through** the mono
        # role rather than beside it so the face still comes from one place.
        ident_lbl = tk.Label(top, text=ident, bg=self.panel, fg=self.text,
                             font=font("code", size=13))
        ident_lbl.pack(side="left")
        word_lbl = tk.Label(top, text=word, bg=self.panel,
                            fg=word_fg or self.mute, font=font("value"))
        word_lbl.pack(side="right")
        sub_lbl = tk.Label(low, text=sub, bg=self.panel, fg=self.mute,
                           font=font("code_lg"))
        sub_lbl.pack(side="left")
        state_lbl = tk.Label(low, text=state, bg=self.panel,
                             fg=state_fg or self.mute, font=font("value"))
        state_lbl.pack(side="right")
        tk.Frame(self.body, bg=self.line, height=1).pack(fill="x")

        def _pick(_e=None, k=key):
            self.select(k)
            if self.command:
                self.command(k)

        # Bound on every child rather than on the frame alone: the labels sit
        # on top of it, so a click on the asset number would otherwise land on
        # a widget with no binding - which is the row a person actually aims
        # at. The cursor goes on with it, for the same reason.
        def _clickable(w):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", _pick)
            for ch in w.winfo_children():
                _clickable(ch)
        _clickable(wrap)

        self._rows.append({
            "key": key, "mark": mark,
            "tint": (wrap, pad, top, low, ident_lbl, word_lbl, sub_lbl,
                     state_lbl)})
        return key

    def select(self, key):
        """Paint one row as selected. Does not call `command`, `SectionBar`'s
        reason: a pane restoring its own selection would fire the callback that
        repaints what it is restoring."""
        self.selected = key
        for row in self._rows:
            on = row["key"] == key
            fill = self.well if on else self.panel
            for w in row["tint"]:
                w.configure(bg=fill)
            row["mark"].configure(bg=self.text if on else fill)

    def keys(self):
        return [row["key"] for row in self._rows]

    def pack(self, **kw):
        self.frame.pack(**kw)
        return self

    def grid(self, **kw):
        self.frame.grid(**kw)
        return self


class DetailPane(object):
    """The selected item, at the size a decision about it needs.

    The identifier is the hero at 26 - it is what somebody is holding a machine
    up against - with the Serial Number beside it, the direction and state
    under it behind the same 3px gutter the list row uses, then a label/value
    field list, what this same asset did before now, and the actions for this
    one item.

    This is the pane the Notifier gains most from and the argument for the
    whole shape: confirming a movement is a decision, and the decision wants
    the model, the engineer, what that asset did last and the deadline - which
    does not fit on a row, and is why that app has a popup at all.

    Handed what to draw rather than a record, `ListPane.add`'s reason.
    """

    def __init__(self, parent, panel, well, text, mute, faint, line,
                 hot=None, ink=None):
        import tkinter as tk
        self.panel, self.well, self.text = panel, well, text
        self.mute, self.faint, self.line = mute, faint, line
        self.hot = hot or well
        # What a primary action's label is drawn in. It sits on `TEXT`, so it
        # is the shell colour and never `TEXT` itself - a default of `panel`
        # rather than white, which is a colour neither palette holds.
        self.ink = ink or panel
        self.frame = tk.Frame(parent, bg=panel)
        self.body = tk.Frame(self.frame, bg=panel)
        self.body.pack(fill="both", expand=True, padx=(24, 12), pady=(4, 0))

    def clear(self, message=None):
        import tkinter as tk
        for child in self.body.winfo_children():
            child.destroy()
        if message:
            tk.Label(self.body, text=message, bg=self.panel, fg=self.mute,
                     font=font("value")).pack(anchor="w", pady=(18, 0))

    def show(self, ident, sub="", word="", word_fg=None, state="",
             state_fg=None, gutter=None, caption="movement", fields=(),
             history=(), history_title="This asset, before now",
             history_empty="nothing before this", actions=()):
        """Repaint the pane for one item.

        `fields` is `(label, value)` pairs, `history` is already-worded lines,
        and `actions` is `(label, primary, command)` - at most one of them
        primary, since two primaries is no primary.
        """
        import tkinter as tk
        self.clear()
        tk.Label(self.body, text=caption, bg=self.panel, fg=self.faint,
                 font=font("micro")).pack(anchor="w")
        head = tk.Frame(self.body, bg=self.panel)
        head.pack(fill="x", pady=(2, 0))
        tk.Label(head, text=ident, bg=self.panel, fg=self.text,
                 font=font("ident", size=26)).pack(side="left")
        if sub:
            tk.Label(head, text=sub, bg=self.panel, fg=self.mute,
                     font=font("code", size=14)).pack(side="left",
                                                      padx=(16, 0),
                                                      pady=(14, 0))
        band = tk.Frame(self.body, bg=self.panel)
        band.pack(fill="x", pady=(8, 0))
        tk.Frame(band, bg=gutter or self.mute, width=GUTTER_W,
                 height=18).pack(side="left")
        tk.Label(band, text=word, bg=self.panel, fg=word_fg or self.text,
                 font=font("label")).pack(side="left", padx=(10, 0))
        if state:
            tk.Label(band, text=state, bg=self.panel, fg=state_fg or self.mute,
                     font=font("label")).pack(side="left", padx=(16, 0))
        tk.Frame(self.body, bg=self.line,
                 height=1).pack(fill="x", pady=(14, 0))
        grid = tk.Frame(self.body, bg=self.panel)
        grid.pack(fill="x", pady=(10, 0))
        for r, (label, value) in enumerate(fields):
            tk.Label(grid, text=label, bg=self.panel, fg=self.mute,
                     font=font("micro")).grid(row=r, column=0, sticky="w",
                                              pady=3)
            tk.Label(grid, text=str(value), bg=self.panel, fg=self.text,
                     font=font("label")).grid(row=r, column=1, sticky="w",
                                              padx=(18, 0), pady=3)
        tk.Frame(self.body, bg=self.line,
                 height=1).pack(fill="x", pady=(12, 0))
        tk.Label(self.body, text=history_title, bg=self.panel, fg=self.mute,
                 font=font("micro")).pack(anchor="w", pady=(10, 2))
        for entry in (tuple(history) or (history_empty,)):
            tk.Label(self.body, text=entry, bg=self.panel, fg=self.mute,
                     font=font("value")).pack(anchor="w", pady=1)
        if actions:
            box = tk.Frame(self.body, bg=self.panel)
            box.pack(anchor="w", pady=(16, 10))
            for label, primary, command in actions:
                pill = Pill(box, label, self.panel,
                            self.text if primary else self.well, self.hot,
                            fg=self.ink if primary else self.text,
                            h=34, radius=0, bold=False, size=10,
                            command=command)
                # The width comes from the label the pill is actually carrying
                # rather than from a number written here, `Pill.fit_text`'s
                # argument: these labels are sentences and a written width is
                # measured at whatever display scaling somebody had.
                pill.cv.configure(width=pill.intrinsic())
                pill.redraw()
                pill.pack(side="left", padx=(0, 10))

    def pack(self, **kw):
        self.frame.pack(**kw)
        return self

    def grid(self, **kw):
        self.frame.grid(**kw)
        return self


# ---------------------------------------------------------------- the app icon

#: The icon is drawn in a 1024-unit square and scaled to whatever size is asked
#: for, so there is one set of coordinates rather than one artwork per size.
#: Supersampled and resampled down because `ImageDraw` has no antialiasing of
#: its own: every edge here is a polygon, an ellipse or a pieslice, and drawn
#: straight at 32px they all come back stepped.
ICON_UNITS = 1024
ICON_SS = 4

#: How far the letter stands off the tile, in those same units. It is a design
#: distance rather than a pixel one for the reason above: 46 units is a bevel
#: at 256px and under three pixels at 16px, where it is the only thing left
#: saying the mark has a thickness.
ICON_DEPTH = 46

#: The icon's own colours, named apart from the palettes above on purpose. A
#: palette is the theme in force and swaps under the user's feet; these do not,
#: because the icon is drawn on a Windows taskbar, a Windows tray and an
#: Explorer listing rather than inside one of our windows. The values are the
#: dark palette's ACCENT2, SUCCESS, WARNING and DANGER, so the icon and the app
#: behind it read as the same product.
ICON_SKY = (129, 140, 248)
ICON_DEEP = (55, 48, 163)
ICON_RED = (239, 68, 68)
ICON_GREEN = (34, 197, 94)
ICON_WHITE = (255, 255, 255)

#: The letter's own three: the lit and unlit ends of the extruded side wall,
#: and the foot of the ramp across its face. They are not palette colours and
#: never were - they are where the light falls on one shape, so they are darker
#: and lighter siblings of ICON_DEEP rather than anything an app draws with.
ICON_EDGE = (98, 86, 202)
ICON_EDGE_DEEP = (40, 34, 132)
ICON_FACE = (222, 227, 255)

#: One PNG per size actually asked for. Drawing is cheap but not free, and
#: `set_window_icon` is called once per window.
_ICON_PNG = {}


def _icon_gradient(px, top, bottom):
    """A vertical ramp, drawn one pixel wide and stretched.

    `ImageDraw` has no gradient, and a per-pixel loop over the whole square is
    the same ramp computed `px` times over.
    """
    strip = Image.new("RGB", (1, px))
    d = ImageDraw.Draw(strip)
    for y in range(px):
        t = y / float(max(1, px - 1))
        d.point((0, y), fill=tuple(int(top[i] + (bottom[i] - top[i]) * t)
                                   for i in range(3)))
    return strip.resize((px, px), Image.BICUBIC)


def _icon_paint(img, mask, source):
    """Composite a flat colour or an image through `mask`."""
    if not isinstance(source, Image.Image):
        source = Image.new("RGB", img.size, source)
    layer = source.convert("RGBA")
    layer.putalpha(mask)
    img.alpha_composite(layer)


def _icon_diagonal(px, near, far):
    """A ramp running down-and-right, to shade the extruded wall with.

    The light comes from the upper left, so the wall's brightness is a function
    of x+y rather than of y alone: a vertical ramp on a shape extruded
    diagonally leaves the top of the far side lit like the top of the near one.
    Computed at 160px and stretched, for the reason `_icon_gradient` gives.
    """
    n = 160
    g = Image.new("RGB", (n, n))
    p = g.load()
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2.0 * (n - 1))
            p[x, y] = tuple(int(near[i] + (far[i] - near[i]) * t)
                            for i in range(3))
    return g.resize((px, px), Image.BICUBIC)


def _icon_letter(w, u):
    """The monogram as a mask: outer triangle, counter, notch.

    A mask rather than three fills, because the counter and the notch are holes
    in one shape: filling them with the background's colour works over a flat
    fill and leaves a seam down a gradient.
    """
    m = Image.new("L", (w, w), 0)
    d = ImageDraw.Draw(m)
    d.polygon([(u(512), u(132)), (u(908), u(898)), (u(116), u(898))], fill=255)
    d.polygon([(u(512), u(376)), (u(648), u(626)), (u(376), u(626))], fill=0)
    d.polygon([(u(400), u(714)), (u(624), u(714)),
               (u(688), u(898)), (u(336), u(898))], fill=0)
    return m


def app_icon(size=256, badge=False, status=None):
    """The product's icon: the monogram A, extruded, on the indigo tile.

    The same mark `storekeeper_app.py` already draws beside the app name, at
    icon size - so this is not a new mark, it is the one the product has. What
    it buys over the storefront-on-a-monitor that was here before is that it
    has nothing to lose: the A is 792 of the 1024 units wide, where the shop
    front was 424, and there is no part of it small enough to become noise at
    16px. That is why this one needs no reduced small-size artwork, and the
    `fine` threshold survives only for the glyph inside the badge.

    Drawn rather than shipped as a file. A `.png` beside the apps would have to
    be staged by `package.ps1` into the exes, by `package.ps1 -Source` and by
    `bundle-client.ps1` into the source bundles, resolved next to the exe in one
    mode and next to the source in the other, and degraded from where it was
    missing - four packaging decisions for an artwork that never changes at
    runtime. Drawing it costs none of them, and `pillow` is pinned in both
    `requirements-*.txt` already, for the tray.

    `badge` is the Notifier's pending marker. It is drawn here rather than in
    that app because it sits on top of this artwork and has to move with it.

    `status` is the Server tray's light - `"online"` or `"offline"`, or `None`
    for the CHECKING moment before anything has been asked, which draws no dot
    at all. It is a plain disc at the opposite corner from the badge, with no
    glyph inside it: the badge means transactions are waiting on an engineer,
    this means something else entirely, and the two must never be read as the
    same mark on the one icon that could in principle carry both.

    Returns None where `pillow` is not installed, the way every optional
    dependency here degrades: the caller shows no icon rather than not starting.
    """
    if not HAS_PIL:
        return None

    w = size * ICON_SS
    k = w / float(ICON_UNITS)

    def u(v):
        """A design-space coordinate, in canvas pixels."""
        return v * k

    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))

    # Background: an indigo ramp clipped to a rounded square.
    bg = _icon_gradient(w, ICON_SKY, ICON_DEEP).convert("RGBA")
    mask = Image.new("L", (w, w), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, w - 1],
                                           radius=int(u(228)), fill=255)
    bg.putalpha(mask)
    img.alpha_composite(bg)

    letter = _icon_letter(w, u)
    depth = u(ICON_DEPTH)

    # The shadow the letter casts on the tile, cast by the *far* copy: the
    # extrusion is what stands off the background, so a shadow under the face
    # would be a shadow under the wrong shape.
    far = Image.new("L", (w, w), 0)
    far.paste(letter, (int(depth), int(depth)))
    shadow = far.filter(ImageFilter.GaussianBlur(depth * 0.55))
    lifted = Image.new("L", (w, w), 0)
    lifted.paste(shadow.point(lambda v: v // 2), (0, int(depth * 0.65)))
    _icon_paint(img, lifted, (8, 10, 40))

    # The side wall, as the union of the offset copies rather than as a stack
    # of them: stacked fills each carry their own hard edge, and a fraction of
    # a pixel of overhang is swept into a ridge running the length of every
    # stroke. The union leaves one edge however many copies went into it, and
    # the depth becomes a gradient across that single shape. One step per pixel
    # of depth is what makes consecutive copies overlap at every size - at 16px
    # the whole extrusion is under three pixels and eight steps is plenty.
    steps = max(8, int(depth))
    union = Image.new("L", (w, w), 0)
    for i in range(steps, 0, -1):
        off = Image.new("L", (w, w), 0)
        off.paste(letter, (int(round(depth * i / steps)),
                           int(round(depth * i / steps))))
        union = ImageChops.lighter(union, off)
    _icon_paint(img, union, _icon_diagonal(w, ICON_EDGE, ICON_EDGE_DEEP))

    # The face, lit from the top like everything else on the tile.
    _icon_paint(img, letter, _icon_gradient(w, ICON_WHITE, ICON_FACE))

    if badge:
        d = ImageDraw.Draw(img)
        bx, by, br = u(852), u(172), u(150)
        d.ellipse([bx - br - u(22), by - br - u(22),
                   bx + br + u(22), by + br + u(22)], fill=ICON_WHITE)
        d.ellipse([bx - br, by - br, bx + br, by + br], fill=ICON_RED)
        # The stroke of the "!" is 48 units - three quarters of a pixel at
        # 16px, where it only greys the disc. The disc is what carries the
        # meaning at that size, and it survives on its own.
        if size > 32:
            d.rounded_rectangle([bx - u(24), by - u(84), bx + u(24), by + u(22)],
                                radius=int(u(24)), fill=ICON_WHITE)
            d.ellipse([bx - u(28), by + u(44), bx + u(28), by + u(100)],
                      fill=ICON_WHITE)

    if status:
        # The mirror corner from the badge, on purpose - the two are drawn
        # from the same grid and must still read as different marks at a
        # glance, badge included, on the one icon that could carry both.
        d = ImageDraw.Draw(img)
        sx, sy, sr = u(852), u(852), u(150)
        d.ellipse([sx - sr - u(22), sy - sr - u(22),
                   sx + sr + u(22), sy + sr + u(22)], fill=ICON_WHITE)
        d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr],
                  fill=ICON_GREEN if status == "online" else ICON_RED)

    return img.resize((size, size), Image.LANCZOS)


#: Every size Windows actually asks an .ico for: 16 and 32 in the taskbar and
#: Explorer's list views, 48 in its icon view, 256 for the extra-large one and
#: for a shortcut. 24, 64 and 128 are the scaling steps in between.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def write_ico(path, sizes=ICO_SIZES):
    """Write the icon as a multi-size `.ico`.

    Two callers, for the two places Windows wants a file rather than an image:
    `tools/_devtools.py icon`, which PyInstaller stamps the exes from, and the
    installer, which points a source-mode Desktop shortcut at one. One writer
    rather than two, because the sizes are the decision - a `.ico` missing the
    16px entry is a taskbar that resamples the 256px one badly.

    Each size is drawn at its own size rather than downsampled from the largest:
    the coordinates are in a 1024-unit space, so a 16px entry supersamples from
    64px instead of being a shrunk 256px one, which is the difference between a
    taskbar icon that reads and one that does not.

    Returns False where there is no `pillow`, so the installer can carry on
    without an icon and the build can refuse - the two answers that differ.
    """
    if not HAS_PIL:
        return False
    images = [app_icon(s) for s in sizes]
    images[-1].save(path, format="ICO", sizes=[(s, s) for s in sizes],
                    append_images=images[:-1])
    return True


def _icon_png(size, badge):
    """The icon as PNG bytes, drawn once per size actually asked for."""
    if not HAS_PIL:
        return None
    key = (size, badge)
    if key not in _ICON_PNG:
        buf = io.BytesIO()
        app_icon(size, badge).save(buf, format="PNG")
        _ICON_PNG[key] = buf.getvalue()
    return _ICON_PNG[key]


#: The sizes a window's icon is handed over at. Windows asks a window for two
#: icons - a small one for the title bar and Alt-Tab, a large one for the
#: taskbar - and takes the nearest of what it was given, so what a list buys
#: is that it never has to scale one itself: 16 and 24 answer the small slot
#: at 100% and 150% display scaling, 32 and 48 the large one. Handed one image
#: it scales with no filtering at all, and a 64px icon crushed into a 16px
#: title bar is the hazy, pixelated thing that was there before.
ICON_WINDOW_SIZES = (16, 24, 32, 48)


def set_window_icon(win, badge=False, sizes=ICON_WINDOW_SIZES):
    """Give a window, and every Toplevel opened after it, the app icon.

    A PNG through `tk.PhotoImage(data=...)` rather than `iconbitmap`: Tk 8.6
    reads PNG itself, so this needs neither `PIL.ImageTk` nor an `.ico` on
    disk, and one call covers the title bar and the taskbar both.

    Every size goes over, because Tk passes the whole list to Windows and
    Windows picks per slot - and each is drawn at its own size rather than
    resampled from one large image, which is the difference between a title
    bar that shows the icon and one that shows a smear of it.

    Returns the images, or None where there is no `pillow` and where Tk
    refused them - a window with the default icon is still a window, and this
    must never be what stops one opening.
    """
    import tkinter as tk

    pngs = [_icon_png(s, badge) for s in sizes]
    if any(png is None for png in pngs):
        return None
    try:
        photos = [tk.PhotoImage(master=win, data=base64.b64encode(png))
                  for png in pngs]
        win.iconphoto(True, *photos)
    except tk.TclError:
        return None
    # Tk does not own the images. A PhotoImage nothing else references is
    # collected and the title bar goes blank some seconds after it was set,
    # which reads as an icon that never worked - so the window holds them.
    win._app_icon = photos

    def _release(event):
        """Let the image go with the window that was holding it.

        Held past `destroy()` it outlives the Tcl interpreter, and the delete
        in `tkinter.Image.__del__` then runs during interpreter shutdown,
        where `TclError` has already been torn down to None and the `except`
        clause itself raises - "Exception ignored ... catching classes that do
        not inherit from BaseException", printed after the last line of
        whatever was running. Dropping it here deletes the image while Tcl is
        still whole.

        A child's `<Destroy>` reaches this binding too, through the toplevel's
        bindtag, so the window's own is what it acts on.
        """
        if event.widget is win:
            win._app_icon = None

    win.bind("<Destroy>", _release, add="+")
    return photos


def run_tray_icon(root, name, tooltip, image, items, on_ready=None):
    """Build a tray icon from `items` and run it - blocks until told to stop.

    `items` is a list of `(label, callback)` pairs read top to bottom: `None`
    in place of a pair draws a separator, and a pair whose callback is `None`
    draws a disabled item - a caption, or (`label` itself a callable) one that
    reads live state such as who is logged on. A callback runs on pystray's
    own thread, so it is wrapped to land back on `root`'s through
    `root.after(0, ...)` before it touches any widget.

    `on_ready`, given, is called with the `pystray.Icon` before `run()` blocks
    - the caller's one chance to keep the reference `icon.icon`/`icon.title`
    are then updated through and `icon.stop()` is later called on.

    A no-op, returning `None` without calling `on_ready`, where `HAS_TRAY` is
    false: the caller is meant to run this on a thread of its own and never
    call it at all otherwise.
    """
    if not HAS_TRAY:
        return None

    def _entry(label, callback):
        if callback is None:
            return pystray.MenuItem(label, None, enabled=False)

        # Two parameters exactly: pystray counts them to decide how to call
        # an action and refuses a third, a defaulted one included (#272).
        def _on_tk_thread(icon, item):
            root.after(0, callback)

        return pystray.MenuItem(label, _on_tk_thread)

    menu = pystray.Menu(*(pystray.Menu.SEPARATOR if item is None
                          else _entry(*item) for item in items))
    icon = pystray.Icon(name, image, tooltip, menu)
    if on_ready is not None:
        on_ready(icon)
    icon.run()
    return icon


__all__ = ["TOKENS", "DARK", "LIGHT", "PALETTES", "MODES", "MODE_LABELS",
           "aliases", "palettes", "Theme",
           "system_mode", "resolve", "read_mode", "reverse", "retint",
           "remap", "rewrap", "round_rect", "Pill", "Row", "row_of", "TOOLBAR",
           "FOOTER", "FLOOR", "CAP", "HAS_PIL", "HAS_TRAY", "ICO_SIZES",
           "ICON_WINDOW_SIZES", "app_icon", "set_window_icon", "write_ico",
           "run_tray_icon"]
