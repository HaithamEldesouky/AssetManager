r"""Open the gates' Tk windows where they cannot take the screen or the keyboard.

    set AM_GATE_OFFSCREEN=1        tools\gate.py sets it; a direct run does not

server-checks.py and client-checks.py measure real mapped windows. A withdrawn
Tk window reports 1x1 at its parent's last position, which is why the client
suite calls `deiconify` in four places on purpose - so hiding the windows is not
on the table, and for the nine minutes a full serial run takes they were the
developer's screen: forty-one roots flashing up, and `focus_force` at four sites
plus every `ui_kit.raise_open` taking the keyboard out of whatever else was
being typed.

Both patches go on `tkinter` itself rather than on the 41 `tk.Tk()` sites,
because the windows that matter are opened by the apps under test and not by
the suites at all:

  * **Translated.** Every window is placed OFFSET px to the right of the
    desktop, and `wm_geometry` rewrites the position half of whatever an app
    asks for afterwards. The size half is passed through untouched, and the size
    half is what every assertion in both suites reads. No check reads an
    absolute position: the nineteen `winfo_rootx`/`winfo_rooty` uses are all
    differences between a child and its own window, and a translation cancels in
    a difference. Neither suite captures screen pixels, so a window nothing
    composites costs nothing here - `grep -n 'ImageGrab\|BitBlt\|PrintWindow'`
    over both files comes back empty, and that is the thing to re-run before
    assuming it still holds.
  * **Disabled.** `-disabled` is WS_DISABLED: the window cannot be activated, so
    it cannot take focus from whatever the developer is typing into. Moving a
    window offscreen does not do this on its own - an invisible window that
    holds the keyboard is the worse half of the problem, not the smaller one.
    Tk's `event_generate` puts events straight into Tk's own queue rather than
    through Windows, so the synthetic clicks and keystrokes both suites drive
    still land.

Measured rather than argued, because the second one is the one that could have
eaten a whole suite silently. Both suites come back the same either side of this
module, and the counts rather than the colour are the check - a synthetic event
that stopped being delivered would take its assertions with it and still print
green. Re-measured 2026-09-22: client-checks.py is 928 assertions in 69 groups
serial with it off and the same 928 in 69 summed over four shards with it on;
server-checks.py is 2626 in 236 serial with it off and 2626 in 236 serial with
it on. (The earlier measurement was 872 in 68 and 2615 in 234; both
suites have grown since.)
The server side is serial both ways here rather than sharded, because eight
shards of it came back red twice the same afternoon on load - see gate.py's
SHARD_CAP. Re-measure the same way if either patch is touched.

Off by default, and env-gated rather than always-on, because a run of one suite
by hand while iterating on it is a run where watching the window is the point.
"""
import os
import re
import tkinter

# Far enough right of any real desktop that no second monitor reaches it, and
# well inside the 16-bit range some window-message coordinates are still packed
# into. Position only - nothing here changes how big a window is.
OFFSET = 20000

# The trailing `+x+y` of a geometry spec. `wm geometry` also takes `WxH` alone,
# and that form is left exactly as it is: a window that asks only for a size
# keeps the offscreen position it was given when it was created.
_POS = re.compile(r"([+-]\d+)([+-]\d+)$")

_ORIG_TK_INIT = tkinter.Tk.__init__
_ORIG_TOPLEVEL_INIT = tkinter.Toplevel.__init__
_ORIG_WM_GEOMETRY = tkinter.Wm.wm_geometry


def translate(spec):
    """Move the position half of a geometry spec offscreen, size half intact."""
    m = _POS.search(spec)
    if not m:
        return spec
    x = int(m.group(1))
    y = int(m.group(2))
    if x >= OFFSET:
        # Already ours. An app that reads its own geometry back and writes it
        # again would otherwise walk the window right by OFFSET per round trip.
        return spec
    return spec[:m.start()] + "+%d%+d" % (x + OFFSET, y)


def _hide(win):
    """Place one new window offscreen and take its ability to steal focus.

    A TclError here is a window that was destroyed between construction and
    this call, which a check that opens and closes windows in a loop does reach.
    Swallowing it is right: this function is a courtesy to the developer, and a
    gate that fails because the courtesy failed would be a gate reporting on
    itself.
    """
    try:
        _ORIG_WM_GEOMETRY(win, "+%d+%d" % (OFFSET, 0))
        win.wm_attributes("-disabled", True)
    except tkinter.TclError:
        pass


def enable():
    """Patch tkinter in this process. Idempotent."""
    if getattr(tkinter, "_am_offscreen", False):
        return

    def tk_init(self, *args, **kwargs):
        _ORIG_TK_INIT(self, *args, **kwargs)
        _hide(self)

    def toplevel_init(self, *args, **kwargs):
        _ORIG_TOPLEVEL_INIT(self, *args, **kwargs)
        _hide(self)

    def wm_geometry(self, newGeometry=None):
        if newGeometry:
            newGeometry = translate(newGeometry)
        return _ORIG_WM_GEOMETRY(self, newGeometry)

    tkinter.Tk.__init__ = tk_init
    tkinter.Toplevel.__init__ = toplevel_init
    # `geometry` is an alias assigned in Wm's class body, so it is a second
    # name for the unpatched function until it is rebound too.
    tkinter.Wm.wm_geometry = wm_geometry
    tkinter.Wm.geometry = wm_geometry
    tkinter._am_offscreen = True


def enable_if_asked():
    """Called first thing by both suites' main(). True if the patch went on."""
    if os.environ.get("AM_GATE_OFFSCREEN") == "1":
        enable()
        return True
    return False
