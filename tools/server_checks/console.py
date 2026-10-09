r"""The Server GUI: the toolbar, the depth layer, the tray, every form.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast
import io
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta

from server_checks.stage import (GM, M, R, SRC_ALL, _add_client, _admin,
                                 _blank_lookup, _call_name, _code,
                                 _resolves_to, add_txn, bad, eq, fails,
                                 fresh_db, gui_root, head, log_rows, ok,
                                 read_server_cfg, skip, stored_form,
                                 tk_or_skip, widgets, write_admin_cfg,
                                 write_server_cfg)



def section_names():
    """The sections the console's bar carries, read out of `SECTIONS`.

    Read rather than restated for `check_the_section_bar_fits`'s reason: a
    seventh section would otherwise be added to that window without being
    added to anything that walks it.
    """
    node = next((n for n in ast.walk(ast.parse(SRC_ALL))
                 if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "SECTIONS"
                         for t in n.targets)), None)
    return [] if node is None else [e.elts[0].value for e in node.value.elts]


def show_section(tk, root, name):
    """Put one section on the stage, the way a person does - by clicking its
    cell on the bar.

    `SectionBar` is not a widget and keeps no back-pointer, so the label a
    person aims at is what a check has in common with them. Every section but
    the one on the stage is `pack_forget`-ten, and a click on an unmapped
    widget does nothing at all - which is why a walk that opens the console's
    doors has to come through here first rather than clicking whatever bound
    frame it can find.
    """
    for w in widgets(root):
        if w.winfo_class() != "Label":
            continue
        try:
            text = str(w.cget("text"))
        except tk.TclError:
            continue
        if text == name and "<Button-1>" in w.bind():
            w.event_generate("<Button-1>")
            root.update_idletasks()
            root.update()
            return True
    return False


def section_entries(tk, root, name):
    """The entry rows of one section, with that section on the stage.

    A row is told apart by the `_ui_section_row` the console stamps on it,
    `ui_kit.ListPane`'s `_ui_list_row` idiom and its reason: on this window a
    bound frame is a status chip unless it says otherwise.
    """
    if not show_section(tk, root, name):
        return []
    out = []
    for w in widgets(root):
        if getattr(w, "_ui_section_row", None) != name:
            continue
        label = next((c for c in widgets(w)
                      if c.winfo_class() == "Label"), None)
        try:
            out.append((str(label.cget("text")) if label else "", w))
        except tk.TclError:
            continue
    return out


def open_section_entry(tk, root, section, label):
    """Click one named entry of one section. Returns whether it was found."""
    for text, row in section_entries(tk, root, section):
        if label in text:
            row.event_generate("<Button-1>", x=3, y=3)
            root.update_idletasks()
            root.update()
            return True
    return False


def check_the_section_bar_fits():
    """Six sections, at every width this console is dragged to.

    The successor to `check_toolbar_fits`, and it is a smaller claim because
    the widget is. The action row was six labels laid out against the width
    it had, so it shortened them at 940px and would have wrapped at a
    seventh; `ui_kit.SectionBar` is six cells of a label and 17px either
    side, which is a width the *names* decide and the window does not. What
    is left to keep true is that the names are the whole navigation - so all
    six are drawn, none is squeezed, and what the strip spends is a figure
    the documents are held to rather than one copied forward.

    Read out of `SECTIONS` rather than restated here, `check_toolbar_fits`'s
    reason: a seventh section would otherwise be added to this window without
    being added to the thing that measures it.

    Skipped rather than failed when Tk cannot open a display, so the rest of
    this file stays runnable where there is no desktop.
    """
    head("the Server GUI section bar fits")
    tk = tk_or_skip()
    if tk is None:
        return

    db = fresh_db()
    add_txn(db)

    sections = next((n for n in ast.walk(ast.parse(SRC_ALL))
                     if isinstance(n, ast.Assign)
                     and any(getattr(t, "id", "") == "SECTIONS"
                             for t in n.targets)), None)
    if sections is None:
        bad("SECTIONS is gone from run_gui - nothing to measure")
        return
    names = [e.elts[0].value for e in sections.value.elts]
    wanted = len(names)

    root = gui_root(tk)
    # A section cell is the frame behind a label carrying that section's name
    # and a click of its own. Found that way rather than by walking down from
    # the bar, because `SectionBar` is not a widget and has no back-pointer:
    # the label a person aims at is what this has in common with them.
    cells = {}
    for w in widgets(root):
        if w.winfo_class() != "Label":
            continue
        try:
            text = str(w.cget("text"))
        except tk.TclError:
            continue
        if text in names and "<Button-1>" in w.bind():
            cells[text] = w.master
    missing = [n for n in names if n not in cells]
    if missing:
        bad("no section cell for %s - the bar is gone, or is no longer the "
            "whole navigation" % ", ".join(missing))
        root.destroy()
        return
    ok("all %d sections are on the bar" % wanted)

    # 940px is this window's own minsize and 1700px a maximised 1080p screen:
    # the two ends a real console is dragged between.
    measured = set()
    for width in (940, 1000, 1180, 1360, 1700):
        root.geometry("%dx760" % width)
        # Settled rather than flushed, #204's reason: `wm geometry` is a
        # request the window manager grants when it gets round to it, so a
        # read taken off `update()` alone can have the old width against the
        # new content. Ends when the reading repeats, not on a clock.
        last = None
        for _ in range(20):
            root.update_idletasks()
            root.update()
            root.after(60, root.quit)
            root.mainloop()
            now = [(cells[n].winfo_width(), cells[n].winfo_reqwidth())
                   for n in names]
            if root.winfo_width() == width and now == last:
                break
            last = now
        squeezed = [n for n in names
                    if cells[n].winfo_width() < cells[n].winfo_reqwidth()]
        gone = [n for n in names if not cells[n].winfo_ismapped()]
        spend = sum(cells[n].winfo_reqwidth() for n in names)
        have = cells[names[0]].master.winfo_width()
        if squeezed:
            bad("squeezed at %dpx: %s" % (width, ", ".join(squeezed)))
        elif gone:
            bad("hidden at %dpx: %s" % (width, ", ".join(gone)))
        else:
            ok("%dpx: the bar spends %dpx of %dpx" % (width, spend, have))
            measured.add((spend, have))
    try:
        root.destroy()
    except Exception:
        pass

    # The other direction, and the one that matters: the documents are where
    # this measurement is written down, so they are held to what the bar just
    # did rather than to themselves. `server.py` restated the action row's
    # figure six times and three of those were from before an action moved -
    # a number nothing re-derived, which is exactly what the cascade rule
    # says a documented measurement must never be.
    DOCS = ["CLAUDE.md", os.path.join("docs", "reference", "apps.md")]
    paras = []
    for name in DOCS:
        text = io.open(os.path.join(R, name), encoding="utf-8").read()
        paras.extend((name, line) for line in text.split(chr(10)))
    owner, sentence, home = -1, "", DOCS[-1]
    for i, (name, para) in enumerate(paras):
        if "section bar's measurement is stated here" in para:
            owner, sentence, home = i, para, name
            break
    if not sentence:
        bad("no document states the section bar's measurement - it is the "
            "one place it is written down, so nothing re-derives it now")
        return
    pairs = [(int(a), int(b)) for a, b in
             re.findall(r"(\d+)px of (?:the )?(\d+)px", sentence)]
    if not pairs:
        bad("%s's own sentence about the bar states no measurement" % home)
    for used, avail in pairs:
        if (used, avail) in measured:
            ok("%s's %dpx of %dpx is what the bar measures" %
               (home, used, avail))
        else:
            bad("%s says %dpx of %dpx and the bar measures %s - a width "
                "copied forward rather than re-derived"
                % (home, used, avail, sorted(measured)))

    # And that it is the only paragraph in either file carrying that number.
    spent = sorted(set(u for u, _a in measured))
    stray = []
    for width in spent:
        for i, (name, para) in enumerate(paras):
            if i != owner and ("%dpx" % width) in para:
                stray.append("%dpx in %s: %r"
                             % (width, name, " ".join(para.split())[:70]))
    if stray:
        bad("the width this bar spends is written down outside the one "
            "paragraph that owns it: " + "; ".join(stray))
    else:
        ok("and it is written down in the one paragraph that says it is")
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
             7: "seven", 8: "eight"}
    if ("%s sections" % words.get(wanted, wanted)) in sentence:
        ok("and it says %s sections, which is what SECTIONS holds" %
           words.get(wanted, wanted))
    else:
        bad("%s does not say %s sections, which is what SECTIONS holds: %r"
            % (home, words.get(wanted, wanted), sentence[:160]))


def check_the_action_rows_width_is_not_restated_in_the_code():
    """A width is a measurement, so it is measured rather than written down.

    Six comments and docstrings in server.py restated what the action row
    spends, and three of them were the figure from before Copy Server URL
    moved to the health banner: 978px of 982px with seven actions, against a
    row that has six and spends 846px of 964px. Two of the three sat five
    lines apart in one function, on two Pills in the same feed header, one
    saying seven-at-978 and the other saying six full labels - so whoever
    asked whether a new control fits that row got a budget wrong by 132px or
    a seventh action that does not exist, depending which comment they read
    first.

    The cascade rule's own answer is that a documented measurement is
    re-derived from the source and never copied forward from an earlier
    draft, and CLAUDE.md already states the design: the measurement is a fact
    about the row rather than a reason for anything, so it lives there and
    the code cites the row without restating a width. The group below is what
    re-derives it, off the real window; this one is what stops a second copy
    coming back.

    Widened by #92 to the two rows the first pass deliberately left: the chip
    row carried `811px of 956px` and the side panel `204px of free height`, one
    apiece here and two and three copies in CLAUDE.md. Both were still true
    when that ticket was written, which is how every stale copy starts - the
    978px was true once too - and neither is re-derivable off this machine at
    all, the chips carrying this server's own hostname, address and URL and the
    panel spending what its content asks for. So a width for any of the three
    may not sit in this file, and the group below lays the other two out.

    ui_kit.py's own 978px of 982px is deliberately left alone and is not
    scanned here: it is past tense, it is the measurement that made `Row`
    exist, and that docstring keeps what each too-small window had lost for
    the same reason.
    """
    head("a measured row's width is not restated in the code")

    # The clause holding the number, not the paragraph around it: three rows on
    # that screen are measured, and the chip row and the side panel each sit in
    # a sentence that says "not on the action row" first, so a scan over the
    # paragraph answers for whichever row the sentence opened with. Clauses
    # break on ; : ( and a full stop, which is where every one of the copies
    # attached its number.
    ROWS = (("section bar", ("section bar", "the bar", "this bar")),
            ("chip row", ("chip row", "chips", "status card")),
            ("side panel", ("side panel", "this panel", "side column")))
    claims = []
    for m in re.finditer(r"(\d+)px(?: of (?:the )?(\d+)px| of free height)",
                         SRC_ALL):
        around = SRC_ALL[max(0, m.start() - 600):m.end() + 300]
        clause = next((c for c in re.split(r"[;:(.]", around)
                       if m.group(0) in c), "")
        low = clause.lower()
        for row, words in ROWS:
            if any(w in low for w in words):
                line = SRC_ALL[:m.start()].count(chr(10)) + 1
                claims.append("line %d: %s (%s)" % (line, m.group(0), row))
                break
    if claims:
        bad("server.py states a measured row's width itself, which is the copy "
            "that goes stale: " + "; ".join(claims))
    else:
        ok("no comment in server.py carries a width for any of the three rows")

    # And the positive half, so this cannot pass by finding nothing: the six
    # sites still say why the control is not on that row. Each of them is a
    # reason rather than a number, and a reason that disappeared would leave
    # the next person with neither.
    for row, words in ROWS:
        said = sum(SRC_ALL.lower().count(w) for w in words)
        if said >= 2:
            ok("and %d places still say what the %s is full of" % (said, row))
        else:
            bad("only %d mention(s) of the %s left - the width went and the "
                "reason went with it" % (said, row))


def check_the_server_window_is_drawn_on_flat_colour():
    """Nothing on this window carries a colour sampled off a render (074).

    What replaced the render is the rule it existed to work around: a widget
    that cannot be transparent is **constructed in the colour of the thing it
    stands on**. So that is what is asserted, rather than the render's absence
    alone - absence is the half that passes by finding nothing, and a window
    with nothing on it has no sampled colour either.

    The load-bearing assertion is the one about the colour a label on the
    header band takes. Tkinter widgets are opaque, so a label drawn in CARD on
    top of a gradient was a rectangle of a colour the band around it was not,
    and two labels side by side sampled that gradient at different x and
    stepped. Here the band and every label on it are read back off the widgets
    and **compared with each other**, which fails on a step whatever produced
    it.

    And the theme switch, which is what `retint` is for: a colour is mapped by
    reading it back and looking it up in the table it was drawn in, so what is
    asserted is that band and label moved together and that they moved at all.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("the Server GUI is drawn on flat colour")
    tk = tk_or_skip()
    if tk is None:
        return

    def labelled(root, text):
        for w in widgets(root):
            try:
                if w.winfo_class() == "Label" and w.cget("text") == text:
                    return w
            except Exception:
                pass
        return None

    fresh_db()
    root = gui_root(tk)
    root.update_idletasks()
    root.update()

    placed = [w for w in root.winfo_children()
              if w.winfo_class() == "Canvas" and w.winfo_manager() == "place"]
    eq("no backdrop canvas is placed under the window", placed, [])

    # Anchored on a count caption and on the app bar's own name, the band
    # this used to walk up from having become two things (077): the app bar
    # carries whether the server is answering, for every section, and the
    # Overview section carries the identifier and the counts.
    cap = labelled(root, "recorded")
    name = labelled(root, "Asset Manager")
    if cap is None or name is None:
        bad("the window has no app bar and Overview counts - this group has "
            "stopped measuring what it names")
        root.destroy()
        return
    binner = cap.master.master   # caption -> cell -> count row
    banner = binner.master       # -> Overview's head
    top = name.master.master     # the app bar itself
    eq("the app bar is a plain frame", top.winfo_class(), "Frame")
    eq("  and the section under it is one", banner.winfo_class(), "Frame")

    pal = M.THEME.palette()
    eq("the app bar's own ground is BG", str(top.cget("bg")), pal["BG"])
    eq("  and the section on the stage is CARD",
       str(banner.cget("bg")), pal["CARD"])

    # Labels, not every widget on the band: a 1px groove is LINE on purpose
    # and always was. The defect this measures is text - two words side by
    # side on one band, each painted the colour the ground happened to be
    # under it.
    faces = sorted(set(str(w.cget("bg")) for w in widgets(banner)
                       if w.winfo_class() == "Label"))
    eq("everything on the band is the colour the band is (%s)" % (tuple(faces),),
       faces, [str(banner.cget("bg"))])

    was = str(cap.cget("bg"))
    M.THEME.set("light")
    root.update_idletasks()
    root.update()
    light = M.THEME.palette()
    eq("a theme switch moves the band and its label together",
       (str(banner.cget("bg")), str(cap.cget("bg"))),
       (light["CARD"], light["CARD"]))
    eq("  which is a colour it was not", str(cap.cget("bg")) != was, True)
    M.THEME.set("dark")
    root.destroy()


def check_the_header_band_fits():
    """The one measured row left on this screen, and the successor to
    the two #92 added.

    #205 rebuilt this window to Variant E - a header band, one table and
    a rail - so the chip row and the side panel this group used to lay
    out do not exist. What replaced them is one band carrying the Server
    URL on the left and the four counts on the right, and it inherits the
    property that made those two worth measuring: **what it spends is a
    fact about the machine it runs on rather than a number this repo
    decides.** The URL is `http://<hostname>:<port>` and a hostname is
    whatever the machine is called; the line under it carries this
    server's own address and which of the two protocols is serving. So no
    figure is asserted, here or in CLAUDE.md - the claim is that the band
    holds its content at the width the window can be dragged to, which is
    the claim the chip row made.

    It drove **both** database states until #204, the moved one being the
    wide case, and that leg went with the segment it was about. The
    database is off this band now: a moved one reads as a folder name
    somebody else chose, and a band of a fixed width cannot promise to
    hold a string nobody here bounds - which is what it stopped holding,
    Copy URL being the child `pack` took the shortfall out of. What is
    left on that line is an address and one of two phrases, both bounded,
    so there is one state to drive. DB_DEFAULT_PATH is still moved onto
    the scratch database rather than the other way round, so the window
    has rows to draw and the line reads as an install's does.

    Skipped rather than failed where Tk has no display, like every
    group here that opens a window.
    """
    head("the header band fits")
    tk = tk_or_skip()
    if tk is None:
        return

    def labelled(root, text):
        for w in widgets(root):
            try:
                if w.winfo_class() == "Label" and w.cget("text") == text:
                    return w
            except Exception:
                pass
        return None

    keep_default = M.DB_DEFAULT_PATH
    try:
        db = fresh_db()
        stamped = datetime.now().isoformat()
        for i, who in enumerate(("Alice Carter", "Brian Dawson",
                                 "Carol Evans",
                                 "David Foster")):
            add_txn(db, team_member=who,
                    asset_number="AM-%d" % (i + 1),
                    confirmed=1, confirmed_at=stamped)
        add_txn(db, asset_number="2009")
        M.DB_DEFAULT_PATH = M.DB_PATH
        root = gui_root(tk)
        # Anchored on a count caption rather than on the band's own
        # label: the caption that named this band is on the app bar now,
        # where whether the server is answering is said once for every
        # section, and Overview carries the identifier and the counts.
        cap = labelled(root, "recorded")
        if cap is None:
            bad("Overview has no counts - this group has "
                "stopped measuring what it names")
            root.destroy()
            return
        figs = cap.master.master
        binner = figs.master
        # The positive halves, so no leg can pass by finding
        # nothing: the URL block and the four count cells are the
        # children of the band that are frames with something in
        # them, the rules between the counts being empty and the
        # Copy URL pill being a canvas.
        blocks = [c for c in binner.winfo_children()
                  if c.winfo_class() == "Frame"
                  and c.winfo_children()]
        eq("the URL row and the count row on Overview", len(blocks), 2)
        eq("  and four counts in the second of them",
           len([c for c in figs.winfo_children() if c.winfo_children()]), 4)
        for key in ("recorded", "waiting", "cleared",
                    "out of store"):
            if labelled(root, key) is None:
                bad("  the band has no %r count" % key)
        # The negative half the removed database leg used to carry:
        # this line has to still be saying something, or the group
        # measures a band that lost its widest content and calls the
        # loss a fit.
        sline = [w for w in widgets(root)
                 if w.winfo_class() == "Label"
                 and " \u00b7 " in str(w.cget("text"))]
        if not sline:
            bad("the band's status line carries neither an address "
                "nor a protocol - the line this group measures is "
                "gone, and an empty one always fits")

        # 940x600 is this window's own minsize and 1000x680 what it
        # opens at: the two ends an operator actually meets.
        for width, height in ((940, 600), (1000, 680)):
            # Settled rather than flushed, for #204's reason: `wm
            # geometry` is a request the window manager grants when it
            # gets round to it, so a read taken off `update()` alone
            # can have the old width against the new content. Ends
            # when the reading repeats, not on a clock.
            root.geometry("%dx%d" % (width, height))
            _last = None
            for _ in range(20):
                root.update_idletasks()
                root.update()
                root.after(60, root.quit)
                root.mainloop()
                _now = [(c.winfo_ismapped(), c.winfo_reqwidth(),
                         c.winfo_width())
                        for c in binner.winfo_children()]
                if root.winfo_width() == width and _now == _last:
                    break
                _last = _now
            cells = [c for c in binner.winfo_children()
                     if c.winfo_ismapped()]
            tight = [c.winfo_reqwidth() - c.winfo_width()
                     for c in cells
                     if c.winfo_width() < c.winfo_reqwidth()]
            if tight:
                bad("  %dpx: %d block(s) on the band were given "
                    "less than they asked for, the worst by %dpx "
                    "- the counts and the Server URL cannot both "
                    "be drawn" % (width, len(tight), max(tight)))
            else:
                ok("  %dpx: the band holds its content, %dpx asked "
                   "of %dpx"
                   % (width,
                      sum(c.winfo_reqwidth() for c in cells),
                      binner.winfo_width()))
        root.destroy()
    finally:
        M.DB_DEFAULT_PATH = keep_default

    # And that no figure for this band came back into CLAUDE.md, which
    # is where the action row's one copy lives and where the two rows
    # this group replaces had two and three between them.
    doc = io.open(os.path.join(R, "CLAUDE.md"), encoding="utf-8").read()
    stale = [n for n in ("811px", "956px of", "204px", "284px",
                         "351px") if n in doc]
    if stale:
        bad("CLAUDE.md states a figure for the header band again (%s) "
            "- it cannot be re-derived, so it is not written down"
            % ", ".join(stale))
    else:
        ok("and CLAUDE.md states a figure for it nowhere")

def _scaling(value=None):
    """Read the display's `tk scaling`, or set it, through a throwaway root.

    It is display state rather than interpreter state, so this is how a group
    that raises it puts it back: there is no Tk to ask without a root, and the
    root that raised it has already been destroyed by then.
    """
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    try:
        if value is None:
            return root.tk.call("tk", "scaling")
        root.tk.call("tk", "scaling", value)
    finally:
        root.destroy()


def check_nothing_on_this_window_is_cut_off_at_a_narrow_size():
    """The three controls on this window that ran past the box they had (165).

    The group above measures this window against the machine the gate happens
    to run on, and that is what let these through: it asserts that the last
    chip is placed inside the row, and `pack` answers a row that will not fit
    by **shrinking** a child rather than by refusing it - so a chip cut off at
    its right-hand edge and a chip that fits are the same measurement from
    outside. What is asserted here instead is that every child is given **no
    less than the width it asked for**, which is the property that was false.

    Driven at two display scalings and at the longest hostname Windows will
    hand the window, because the family is a written-down pixel width meeting
    font-measured content: the Server URL chip reads `http://<hostname>:<port>`
    and a hostname is whatever the machine is called, while every `w=` in
    these files was written at the scaling it was measured on and a label's
    width is `font.measure`d at whatever this machine is set to. A gate run at
    100% against a machine called `srv1` measures neither half.

    The two sites, the third being in `tools/client-checks.py`:

    - the header band, which #205 put the Server URL and the four
      counts on: the port is the half of that URL somebody reads it
      for, so a band that shrinks a block is a band that drops it;
    - the line a section entry talks through, packed against the
      bottom edge before the stage: 077 left it the only child on
      that edge, the toolbar it used to sit under having gone with
      the action row. Packed after the stage instead, a section with
      more entries than fit pushes it off the window - which is the
      same fault the old ordering had, where the caption was drawn
      **above** the row it belongs to and read as a label for
      whatever happened to be under it.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("nothing on this window is cut off at a narrow size")
    tk = tk_or_skip()
    if tk is None:
        return

    class LongHost(object):
        """`socket` answering the longest hostname a deployed machine has.

        A shim rather than a name written into the server, since what that row
        spends is a fact about the machine and the whole point is that this
        repo does not decide it. The address is answered too: `gethostbyname`
        of a name that is not this machine would fail into the 127.0.0.1
        fallback and measure a narrower chip than a real deployment has.

        **Fifteen characters, because that is the ceiling** (#257). The band
        builds its URL from `socket.gethostname()`, and on a domain-joined
        Windows machine that is the short computer name, not the FQDN: this
        gate machine answers `client-lt-11220` to `gethostname()` and
        `client-lt-11220.example.com` to `getfqdn()`, and the band never calls
        the second. The short name is the NetBIOS computer name, which Windows
        caps at fifteen characters and refuses to rename past. So a longer name
        is not a worst case this repo can be shipped against - it is a machine
        that cannot exist - and the name below is fifteen rather than longer
        for that reason and not because fifteen happens to fit.

        The name is **not** this machine's. The old one read as correct
        because it was: the shim was patched onto the wrong module (below) and
        the band measured the gate machine, which is called the same fifteen
        characters this hands out, so the leg was green whatever the shim said.
        A name of the same length that no machine here is called is what makes
        the shim visible in the reading. The width is the same either way: the
        Server URL is drawn in the code face, so every fifteen-character name
        measures to the pixel and only the **length** moves this band. Drive it
        at twenty and the 1.75x/940px leg goes red by 14px, which is the proof
        that the shim now reaches the window at all.
        """

        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def gethostname(self):
            return "asset-server-01"

        def gethostbyname(self, _host):
            return "192.0.2.100"

        def getfqdn(self, *_a):
            return "asset-server-01.example.com"

    def resize(root, width, height, read):
        """Ask for a size and wait until the window has actually taken it.

        `wm geometry` is a *request*: the window manager grants it when it
        gets round to it, and `update_idletasks()` plus `update()` return
        before that - they flush what Tk has queued, not what the WM has yet
        to do. So a read below could take `winfo_width()` off the old
        geometry while `winfo_reqwidth()` already answered for the new
        content, and report a shortfall that was a race rather than a layout.
        That is what #204 measured: three runs of this group alone in one
        process came back green, red, green, and across full runs the same
        1000px leg reported 67, 64, 60, 58 and 56px while the 940px leg came
        and went. A number that moves by 60px between runs of unchanged code
        is not measuring the band.

        The settle itself is `docs/CODING_STANDARDS.md`'s, the same one
        `client-checks.py` uses: run the loop long enough for the <Configure>
        the resize sends to arrive and be laid out. **Two conditions on it,
        and the second is what the first was not enough for.** Waiting on the
        root reporting the width asked for still left one run in nine saying
        the band was 3px short at 940px: the root takes the grant before its
        children have re-laid out underneath it, and a band a few pixels short
        is exactly what a half-settled layout looks like. So the reading is
        taken through `read` each pass and the loop ends when it comes back
        the same **three times** running - a measurement that has stopped
        moving, rather than a clock somebody guessed.

        Three rather than two because two was still a knife edge (#239): the
        1.75x/940px leg came and went between runs of unchanged code, and
        under a two-read settle two runs of the same hand-driven case
        disagreed with each other. Every settled read of that leg is
        bit-identical once the third pass has to agree as well, and the leg
        costs one more 60ms pass to get it.

        Bounded rather than endless, and it returns whatever it last read: a
        window manager that will not grant the size is something to measure
        and report on, not to hang on.
        """
        root.geometry("%dx%d" % (width, height))
        last, same = None, 0
        for _ in range(20):
            root.update_idletasks()
            root.update()
            root.after(60, root.quit)
            root.mainloop()
            now = read()
            same = same + 1 if now == last else 0
            if root.winfo_width() == width and same >= 2:
                break
            last = now

    def labelled(root, text):
        for w in widgets(root):
            try:
                if w.winfo_class() == "Label" and w.cget("text") == text:
                    return w
            except Exception:
                pass
        return None

    def freeze_ticks(root):
        """Cancel every timer the window armed, so a reading stays read.

        `refresh_stats` is a five-second timer that rewrites all four count
        cells, and the settle below runs the **real** mainloop in 60ms
        bursts, up to twenty of them - so a leg long enough to cross one
        tick has the counts put back to whatever the probe last said,
        whatever `set_counts` wrote. It reschedules itself at the end of
        each run, so cancelling the one that is pending before it fires is
        the whole of it; the feed's tick goes the same way, this group
        measuring geometry rather than what the feed is holding.

        Timers this group arms itself are created and consumed inside
        `resize`, so there is nothing of its own to cancel here.
        """
        for tid in root.tk.splitlist(root.tk.call("after", "info")):
            try:
                root.after_cancel(tid)
            except Exception:
                pass

    def set_counts(root, digits):
        """Put a real number in each of the band's four count cells (#258).

        `refresh_stats` probes `127.0.0.1:PORT/stats` and nothing answers
        in here, so every cell holds the offline em-dash - one narrow
        glyph where a running server has four numbers that grow with the
        deployment. This group is named for a written-down width meeting
        font-measured content, and an em-dash is neither: the band was
        measured in a state no server is ever in, and passed.

        Written straight onto the labels rather than by answering the
        probe, which is the cheaper of the two doors the ticket left open:
        a listener on that port would be a Flask app and a thread, to
        measure a font with.

        The caption is how a cell is found, here and in `_COUNT_KEEP` -
        the value label beside it is the cell's other child.
        """
        for cap in GM._COUNT_KEEP:
            lbl = labelled(root, cap)
            if lbl is None:
                bad("the band has no %r count - this group has stopped "
                    "measuring what it names" % cap)
                continue
            for sib in lbl.master.winfo_children():
                if sib is not lbl:
                    sib.config(text="9" * digits)

    # Both modules, because the band reads `server_gui`'s own import (#257).
    # `server_gui.py` has `import socket` at its head and builds the Server URL
    # from `socket.gethostname()` there, so patching only the staged
    # `server.py`'s `socket` left the shim measuring nothing and the band
    # measuring whatever the gate machine is called.
    real_socket = M.socket
    real_gui_socket = GM.socket
    real_init = tk.Tk.__init__
    # `tk scaling` is a property of the **display** rather than of the
    # interpreter that set it: a fresh `tk.Tk()` in this same process reads
    # back whatever the last one wrote, so a raised scaling left behind here
    # is every window opened by every group after this one being measured at
    # a size none of them was written for. Read before the first leg and put
    # back after the last, through a root of this group's own, there being no
    # other way to talk to Tk.
    base = _scaling()
    try:
        for scale in (1.0, 1.75):
            # Set on the interpreter as it is created rather than afterwards:
            # `run_gui` builds every named font a line later, and a scaling
            # applied to a window whose fonts already exist moves nothing.
            def init(self, *a, **k):
                real_init(self, *a, **k)
                self.tk.call("tk", "scaling", scale)

            shim = LongHost(real_socket)
            M.socket = shim
            GM.socket = shim
            tk.Tk.__init__ = init
            fresh_db()
            try:
                root = gui_root(tk)
            finally:
                tk.Tk.__init__ = real_init
                M.socket = real_socket
                GM.socket = real_gui_socket
            freeze_ticks(root)

            # The header band rather than the chip row and the side
            # panel (#205): both are gone with that ticket, and the
            # band is what a long hostname overflows now - it carries
            # the Server URL on the left and the four counts on the
            # right, which is the same written-down width meeting
            # font-measured content this group is named for.
            cap = labelled(root, "recorded")
            if cap is None:
                bad("Overview has no counts - this group has "
                    "stopped measuring what it names")
                root.destroy()
                return
            figs = cap.master.master
            binner = figs.master
            blocks = [c for c in binner.winfo_children()
                      if c.winfo_class() == "Frame"
                      and c.winfo_children()]
            eq("%.2fx: the URL row and the count row on Overview"
               % scale, len(blocks), 2)
            eq("  and four counts in the second of them",
               len([c for c in figs.winfo_children()
                    if c.winfo_children()]), 4)

            def packed(child):
                """Whether `pack` is what put this child where it is.

                A widget the geometry manager never saw raises rather than
                answering, and is not something to measure a given width
                against.
                """
                try:
                    child.pack_info()
                except Exception:
                    return False
                return True

            def on_band():
                """Everything pack laid out under the band, block or not.

                Not just the band's own children. 077 stacked it - the URL
                row above the counts, nothing packed against either end - so
                the written-down width meeting font-measured content this
                group is named for is now **inside** a block: the Server URL
                is a font-measured label and the Copy URL pill beside it is
                a hardcoded `w=92`. A sweep that stopped at the blocks would
                call a window with the port cut off green, because the row
                holding it is `fill="x"` and always has the width it asked
                for.
                """
                return [c for c in widgets(binner)[1:] if packed(c)]

            def band():
                """What the assertions below read, as one comparable value.

                Everything on the band, mapped or not, with the width it was
                given against the width it asked for - which is the whole of
                what is judged here, so a run of this that repeats is a band
                that has stopped moving.
                """
                return [(c.winfo_ismapped(), c.winfo_reqwidth(),
                         c.winfo_width()) for c in on_band()]

            # Which cell each caption belongs to, and the one canvas on the
            # band, which is the Copy URL pill. Read once per scaling: the
            # band re-packs both across the legs below and rebuilds
            # neither.
            cells = {}
            for _cap in GM._COUNT_KEEP:
                _lbl = labelled(root, _cap)
                cells[_cap] = None if _lbl is None else _lbl.master
            # Among the band's descendants rather than its own children:
            # 077 stacked the band, so Copy URL sits inside the URL row
            # beside the identifier it copies rather than on one row with
            # the counts.
            pills = [c for c in widgets(binner)[1:]
                     if c.winfo_class() == "Canvas"]
            eq("%.2fx: one Copy URL pill on the band" % scale,
               len(pills), 1)

            for width, height in ((940, 600), (1000, 680)):
                # One, three and six digits: the narrowest real count, a
                # store with 100 assets in it, and the widest the ticket
                # measured. The band held four em-dashes with 28px to
                # spare and went over at three digits, so a leg driven at
                # the placeholder alone is the leg that passed for two
                # releases.
                # The gap between the band's two ends went with 077. It
                # measured the space left between the left-packed blocks and
                # the right-packed ones, and this band has neither end: the
                # URL row and the counts are stacked, each `fill="x"` across
                # the whole width. What is reported instead is how many of
                # the four counts survived each leg, which is the number
                # #258's own report was standing in for - how close the band
                # came to having to give something up.
                #
                # #257 is what makes the shortfall sweep worth running
                # rather than a formality: the long-hostname shim reaches
                # the window now, so the Server URL really is font-measured
                # against the Copy URL pill's written-down `w=92`.
                before = len(fails)
                legs = []
                for digits in (1, 3, 6):
                    set_counts(root, digits)
                    resize(root, width, height, band)
                    where = ("  %.2fx at %dpx on %d-digit counts"
                             % (scale, width, digits))

                    kids = [c for c in on_band() if c.winfo_ismapped()]
                    short = [c.winfo_reqwidth() - c.winfo_width()
                             for c in kids
                             if c.winfo_width() < c.winfo_reqwidth()]
                    if short:
                        bad("%s: %d thing(s) on the band were given less "
                            "than they asked for, the worst by %dpx - a "
                            "label `pack` shrank is a Server URL with its "
                            "port cut off, and measures from outside "
                            "exactly like one that fit"
                            % (where, len(short), max(short)))
                    # A count the band **chose** to give up is not drawn
                    # either, so the two are told apart by name rather than
                    # by counting: anything unmapped that is not one of the
                    # four cells is something that went missing.
                    chosen = set()
                    for _cap, _cell in cells.items():
                        if _cell is not None:
                            chosen.update(widgets(_cell))
                    gone = [c for c in on_band()
                            if not c.winfo_ismapped() and c not in chosen]
                    if gone:
                        bad("%s: %d thing(s) on the band are not drawn at "
                            "all, and none of them is a count the band "
                            "chose to give up" % (where, len(gone)))
                    if pills and not pills[0].winfo_ismapped():
                        bad("%s: Copy URL is not drawn. That is the "
                            "control #205 fixed and #258 found fixed for "
                            "the placeholder state only: what gives when "
                            "the band is full is a decision this window "
                            "makes, not whatever `pack` happened to pack "
                            "last" % where)
                    # And what is left must be the **front** of
                    # `_COUNT_KEEP`. That is the half no shortfall can be
                    # read off: a band that gave up `waiting` and a band
                    # that gave up `out of store` both measure as blocks
                    # that fit.
                    kept = [c for c in GM._COUNT_KEEP
                            if cells[c] is not None
                            and cells[c].winfo_ismapped()]
                    if not kept:
                        bad("%s: the band holds no count at all" % where)
                    elif kept != list(GM._COUNT_KEEP)[:len(kept)]:
                        bad("%s: the counts left on the band are %s, "
                            "which is not the front of _COUNT_KEEP (%s) - "
                            "what the band gives up is an order it states, "
                            "not the one `pack` ran out of room in"
                            % (where, ", ".join(kept),
                               ", ".join(GM._COUNT_KEEP)))
                    legs.append((digits, len(kept)))

                # One line per width rather than per leg: three settles of
                # the same band over three widths of the same content are
                # one measurement with three readings, and what is worth
                # printing is how far it got before it had to give
                # something up.
                if len(fails) == before:
                    ok("  %.2fx at %dpx: every thing on the band has the "
                       "width it asked for, holding %s of four counts at "
                       "%s digits"
                       % (scale, width,
                          "/".join(str(n) for _d, n in legs),
                          "/".join(str(d) for d, _n in legs)))

            # The status line, once per scaling: where it sits is not a
            # function of the width.
            resize(root, 1000, 680,
                   lambda: [(c.winfo_y(), c.winfo_height())
                            for c in root.winfo_children()])

            def packed_side(child):
                """Which edge this child was packed against, or "".

                A child of this root that `pack` never saw - the ground
                canvases the depth layer `place`s behind everything -
                raises rather than answering, and is not a candidate.
                """
                try:
                    return str(child.pack_info().get("side"))
                except Exception:
                    return ""

            bottom = [c for c in root.winfo_children()
                      if packed_side(c) == "bottom"]
            if len(bottom) != 1:
                bad("the window no longer packs exactly one thing against "
                    "its bottom edge - this leg has stopped measuring what "
                    "it names")
            else:
                # Two properties, and the pack order is what buys both: the
                # line is the lowest thing on the window, and it is wholly
                # inside it. A stage packed first would take the height it
                # asks for and leave this off the bottom of a narrow window,
                # which is the shape of the fault the toolbar ordering had.
                line = bottom[0]
                others = [c for c in root.winfo_children()
                          if c is not line and c.winfo_ismapped()
                          and packed_side(c)]
                foot = line.winfo_y() + line.winfo_height()
                over = [c for c in others if c.winfo_y() >= line.winfo_y()]
                if not line.winfo_ismapped():
                    bad("  %.2fx: the line a section entry talks through is "
                        "not drawn at all" % scale)
                elif over:
                    bad("  %.2fx: %d thing(s) on this window are drawn at or "
                        "below the line a section entry talks through - a "
                        "caption reads as a label for whatever is under it"
                        % (scale, len(over)))
                elif foot > root.winfo_height():
                    bad("  %.2fx: the line a section entry talks through "
                        "runs %dpx past the bottom of the window"
                        % (scale, foot - root.winfo_height()))
                else:
                    ok("  %.2fx: the line a section entry talks through is "
                       "the lowest thing on the window, %dpx clear of its "
                       "bottom edge, with %d packed thing(s) above it"
                       % (scale, root.winfo_height() - foot, len(others)))
            root.destroy()
    finally:
        M.socket = real_socket
        tk.Tk.__init__ = real_init
        _scaling(base)


def check_the_tray_says_what_the_banner_says():
    """The tray tooltip must not answer a question the window has contradicted.

    set_health's own docstring says the banner was rebuilt because the old
    window drew a hardcoded green RUNNING and live counts whatever the port was
    doing. The tooltip went on doing exactly that: a literal RUNNING, rewritten
    every ten seconds by a loop that never asked whether anything had answered.
    It is the surface that is actually up - the window hides to the tray on
    close - so it is the one that must not hold a stale answer.

    Driven offline, which is the direction that was wrong and the only one a
    harness can produce honestly: nothing is listening on the port this points
    at, so the probe inside refresh_stats fails the way it does against a
    wedged server, and the banner and the tooltip have to agree about it.
    """
    head("the tray tooltip says what the banner says")
    tk = tk_or_skip()
    if tk is None:
        return
    import ui_kit
    if not ui_kit.HAS_PIL:
        skip("pillow is not installed - there is no tray icon to title")
        return

    made = []

    class _Icon(object):
        def __init__(self, name, image, title, menu=None):
            self.title = title
            made.append(self)

        def run(self):
            # The real one blocks its thread, and run_gui starts it daemonised
            # and never joins it.
            time.sleep(2)

        def stop(self):
            pass

    class _Menu(list):
        SEPARATOR = object()

        def __init__(self, *items):
            list.__init__(self, items)

    class _Stub(object):
        Icon = _Icon
        Menu = _Menu

        @staticmethod
        def MenuItem(*a, **kw):
            return (a, kw)

    was = (M.PORT, M.HAS_TRAY, getattr(M, "pystray", None))
    M.pystray = _Stub
    # A port nothing serves, chosen rather than assumed: this gate runs on
    # machines where the real Asset Server is up on the configured one, and a
    # group about the not-responding branch must not depend on which.
    M.PORT = 59999
    fresh_db()
    root = None
    try:
        root = gui_root(tk, tray=True)

        def word():
            for w in widgets(root):
                if w.winfo_class() == "Label":
                    t = str(w.cget("text"))
                    if t in ("CHECKING", "RUNNING", "NOT RESPONDING"):
                        return t
            return None

        # refresh_stats is scheduled 1.5s out and is what calls set_health.
        # Pumped rather than slept through, since the probe it makes runs on
        # this same thread.
        deadline = time.time() + 15
        while time.time() < deadline and (word() == "CHECKING" or not made):
            root.update_idletasks()
            root.update()
            time.sleep(0.05)

        if not made:
            bad("no tray icon was built - the tooltip cannot be read, and "
                "this group would otherwise pass by finding nothing")
            return
        ok("the tray icon is built and carries a title")

        banner = word()
        eq("the banner says nothing answered", banner, "NOT RESPONDING")
        title = made[0].title or ""
        if "NOT RESPONDING" not in title:
            bad("the tray says %r while the banner says %r" % (title, banner))
        else:
            ok("and so does the tray: %r" % title)
        # The one that shipped: a literal RUNNING, on a window that is
        # reporting nothing answered.
        if "RUNNING" in title.replace("NOT RESPONDING", ""):
            bad("the tray title carries RUNNING on the offline branch: %r"
                % title)
        else:
            ok("and carries no RUNNING of its own")
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        M.PORT, M.HAS_TRAY, M.pystray = was


def check_the_tray_light_follows_the_banner():
    """The tray's status dot must be the same read as the title, not a
    second probe of its own.

    A12: the light is the fact an operator reads without restoring the
    window, so it has to agree with the banner by construction rather than
    by coincidence - both have to come off the one `online` set_health was
    handed, not off two separate calls that could answer differently.
    Asserted by spying on `_make_server_tray_icon` rather than by comparing
    pixels: what matters is which state was asked for, and a pixel compare
    would only prove two drawings differ, not that they were driven off one
    read.

    Driven offline, the one direction a harness can produce honestly and
    also the one the light exists to answer for: nothing is listening on the
    port this points at, so the icon has to leave CHECKING behind and say so.
    """
    head("the tray's status dot follows the banner, not a probe of its own")
    tk = tk_or_skip()
    if tk is None:
        return
    import ui_kit
    if not ui_kit.HAS_PIL:
        skip("pillow is not installed - there is no tray icon to light")
        return

    made = []

    class _Icon(object):
        def __init__(self, name, image, title, menu=None):
            self.icon = image
            self.title = title
            made.append(self)

        def run(self):
            time.sleep(2)

        def stop(self):
            pass

    class _Menu(list):
        SEPARATOR = object()

        def __init__(self, *items):
            list.__init__(self, items)

    class _Stub(object):
        Icon = _Icon
        Menu = _Menu

        @staticmethod
        def MenuItem(*a, **kw):
            return (a, kw)

    calls = []
    real_tray_icon = M._make_server_tray_icon

    def _spy(online=None):
        calls.append(online)
        return real_tray_icon(online)

    M._make_server_tray_icon = _spy

    was = (M.PORT, M.HAS_TRAY, getattr(M, "pystray", None))
    M.pystray = _Stub
    # A port nothing serves, for the reason check_the_tray_says_what_the_
    # banner_says gives: this gate runs on machines where the real Asset
    # Server is up on the configured one.
    M.PORT = 59999
    fresh_db()
    root = None
    try:
        root = gui_root(tk, tray=True)

        def word():
            for w in widgets(root):
                if w.winfo_class() == "Label":
                    t = str(w.cget("text"))
                    if t in ("CHECKING", "RUNNING", "NOT RESPONDING"):
                        return t
            return None

        # refresh_stats is scheduled 1.5s out and is what calls set_health.
        deadline = time.time() + 15
        while time.time() < deadline and (word() == "CHECKING" or not made):
            root.update_idletasks()
            root.update()
            time.sleep(0.05)

        if not made:
            bad("no tray icon was built - the light cannot be read, and "
                "this group would otherwise pass by finding nothing")
            return

        if len(calls) < 1:
            bad("_make_server_tray_icon was never called to build the tray "
                "icon at all")
            return
        eq("the icon opens with no state asked for - CHECKING, nothing has "
           "answered yet", calls[0], None)

        if len(calls) < 2:
            bad("set_health never rebuilt the tray icon - the light is "
                "stuck at CHECKING while the banner moved on")
            return
        eq("and set_health rebuilds it once the probe answers",
           calls[1], False)
        eq("banner", word(), "NOT RESPONDING")
        eq("off exactly the one call the title was written from, not a "
           "second probe of its own", len(calls), 2)
    finally:
        M._make_server_tray_icon = real_tray_icon
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        M.PORT, M.HAS_TRAY, M.pystray = was


def check_the_tray_title_is_written_in_one_place():
    """One writer, and it is the one that knows the answer.

    A source check because the online branch needs a listener this file
    deliberately does not start, and because what is claimed is an absence: no
    second site deriving health or TLS for itself. The two copies were wrong in
    opposite directions - the tooltip was stale about health and premature
    about TLS, calling itself HTTPS the moment a certificate was uploaded, a
    restart before the listener was.
    """
    head("the tray title is written in one place")
    tree = ast.parse(SRC_ALL)

    writes = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            for t in node.targets:
                if (isinstance(t, ast.Attribute) and t.attr == "title"
                        and isinstance(t.value, ast.Subscript)
                        and _resolves_to(t.value.value, "_tray_icon")):
                    writes.append((fn, node))
    # Innermost wins: set_health sits inside run_gui, so an enclosing-function
    # walk answers twice for the one statement - the same rule the Add
    # Transaction actor check and #90 both needed.
    inner = {}
    for fn, node in writes:
        key = (node.lineno, node.col_offset)
        prev = inner.get(key)
        if prev is None or fn.lineno > prev.lineno:
            inner[key] = fn
    eq("exactly one site writes the tray title", len(inner), 1)
    if len(inner) != 1:
        return
    owner = list(inner.values())[0]
    eq("and it is set_health, which is what knows whether anything answered",
       owner.name, "set_health")

    # Worded off whichever function turned out to own the write, not off the
    # one that should: against the build this replaced the owner is
    # _update_tray_title, and a message naming set_health there would be
    # telling the reader about a function the failure is not in.
    body = _code(owner)
    if "_ssl_active" not in body:
        bad("%s does not take the protocol from _ssl_active, which is the "
            "value describing the listener that is running" % owner.name)
    else:
        ok("the protocol comes from _ssl_active, not from the files on disk")
    if "ssl_enabled" in body:
        bad("%s reads ssl_enabled off the config - that is the read the tray "
            "did, and it is premature by one restart" % owner.name)
    else:
        ok("and nothing there re-reads ssl_enabled")

    # The title the icon is constructed with is the other copy, and it claimed
    # RUNNING before anything had been asked.
    built = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "Icon"
             and _resolves_to(n.func.value, "pystray")]
    eq("the tray icon is still built", len(built), 1)
    for n in built:
        lit = [a.value for a in n.args
               if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if any("RUNNING" in s for s in lit):
            bad("the icon is built claiming RUNNING before anything has been "
                "asked: %r" % lit)
        else:
            ok("and is built saying %r" % (lit,))

    # So this cannot pass by finding no tray at all.
    if "_tray_icon" not in SRC_ALL or "HAS_TRAY" not in SRC_ALL:
        bad("the tray is gone from server.py - nothing above is a check")
    else:
        ok("and the tray is still there to be titled")


def check_the_tray_icon_is_written_beside_the_title():
    """The status dot must be written from the same place the title is.

    A source check, for the reason check_the_tray_title_is_written_in_one_
    place is one: what is claimed is an absence - no second site deciding
    the icon for itself, off a probe of its own, which is exactly how the
    title and the tooltip once came to disagree.
    """
    head("the tray icon is written beside the title, in the same function")
    tree = ast.parse(SRC_ALL)

    writes = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            for t in node.targets:
                if (isinstance(t, ast.Attribute) and t.attr == "icon"
                        and isinstance(t.value, ast.Subscript)
                        and _resolves_to(t.value.value, "_tray_icon")):
                    writes.append((fn, node))
    # Innermost wins, the same rule the title's own version of this check
    # needs: set_health sits inside run_gui, so an enclosing-function walk
    # answers twice for the one statement.
    inner = {}
    for fn, node in writes:
        key = (node.lineno, node.col_offset)
        prev = inner.get(key)
        if prev is None or fn.lineno > prev.lineno:
            inner[key] = fn
    eq("exactly one site writes the tray icon", len(inner), 1)
    if len(inner) != 1:
        return
    owner = list(inner.values())[0]
    eq("and it is set_health, the same function that writes the title",
       owner.name, "set_health")

    calls = [n for n in ast.walk(owner) if isinstance(n, ast.Call)
             and _call_name(n.func) == "_make_server_tray_icon"]
    eq("built by calling _make_server_tray_icon", len(calls), 1)
    if not calls:
        return
    args = calls[0].args
    if not args or getattr(args[0], "id", None) != "online":
        bad("_make_server_tray_icon is not passed set_health's own `online` "
            "- the icon could then answer a question of its own")
    else:
        ok("passed the same `online` set_health itself was handed")


def check_add_transaction_can_be_submitted():
    """Its submit button must be on the screen, at every height.

    It was not. The dialog was written at a fixed 580x700 while its children
    asked for 749, and the button - packed last, so last in the queue for the
    space - was given h=1 and never mapped. With resizable(False, False) there
    was no way for the admin to reveal it, so the one path a backdated
    Transaction has into the history was closed, silently, by a number in a
    geometry string.

    Nothing static catches that: the button was in the source, in the right
    place, with the right command. Only Tk knows the height and the form
    disagree. So the dialog is opened from the real window and the button is
    read back off the screen - and then the window is forced far shorter than
    any screen, because the fix has two halves and the second one only shows
    there: the footer is packed before the form, so the button is the first
    child served rather than the last.

    Skipped rather than failed when Tk cannot open a display.
    """
    head("Add Transaction can be submitted")
    tk = tk_or_skip()
    if tk is None:
        return

    db = fresh_db()
    add_txn(db)
    root = gui_root(tk)

    def pill(w, want):
        # The feed header's pill is a ui_kit canvas, so the label is a canvas
        # item rather than a widget's text - found the way a click finds it.
        if isinstance(w, tk.Canvas):
            for i in w.find_all():
                if w.type(i) == "text" and want in w.itemcget(i, "text"):
                    return w
        for c in w.winfo_children():
            r = pill(c, want)
            if r is not None:
                return r
        return None

    # Off the Activity header and onto the Transactions section (077), which
    # is where the bar names it. Opened the way a person opens it rather than
    # by calling the function, because what this group is about is that the
    # door exists: the only way a backdated Transaction reaches the history is
    # through it.
    if not open_section_entry(tk, root, "Transactions", "Add Transaction"):
        bad("no Add Transaction entry on the Transactions section - the only "
            "way a backdated Transaction gets in is gone")
        root.destroy()
        return

    dlgs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
    if not dlgs:
        bad("clicking it opened no dialog")
        root.destroy()
        return
    dlg = dlgs[-1]
    dlg.update_idletasks()

    btns = [w for w in widgets(dlg)
            if w.winfo_class() == "Button"
            and "Add Transaction" in str(w.cget("text"))]
    if len(btns) != 1:
        bad("%d submit buttons in the dialog, expected 1" % len(btns))
        root.destroy()
        return
    btn = btns[0]

    # The height is not written down any more, so this is the assertion that
    # the window is as tall as the form asked for. A hard-coded height that
    # falls behind the form again fails here first.
    eq("the dialog is as tall as its own children ask for",
       dlg.winfo_height(), dlg.winfo_reqheight())

    def usable(where):
        dlg.update_idletasks()
        dlg.update()
        top = btn.winfo_rooty() - dlg.winfo_rooty()
        if not btn.winfo_ismapped():
            bad("%s: the submit button is not mapped - there is no way to add "
                "a Transaction" % where)
        elif btn.winfo_height() < 20:
            bad("%s: the submit button is %dpx tall, which is not a button"
                % (where, btn.winfo_height()))
        elif top + btn.winfo_height() > dlg.winfo_height():
            bad("%s: the submit button ends %dpx below the bottom of the "
                "dialog" % (where, top + btn.winfo_height()
                            - dlg.winfo_height()))
        else:
            ok("%s: the submit button is on the screen (y=%d h=%d of %dpx)"
               % (where, top, btn.winfo_height(), dlg.winfo_height()))

    usable("as the dialog opens")

    # Far shorter than any screen this runs on. The clamp cannot be reached
    # from here, so it is imposed: this is what a 768px laptop does to a 749px
    # dialog, only more so, and the button must still be the child that keeps
    # its space.
    for h in (600, 500, 400):
        dlg.geometry("580x%d" % h)
        usable("forced to %dpx" % h)

    try:
        root.destroy()
    except Exception:
        pass


def check_add_transaction_offers_a_type_it_cannot_change():
    """Asset Type is read, and the time is picked (#197).

    Both halves are about what the window *offers*, which is the one thing no
    endpoint answers for and no source read can measure: the type was an
    editable picker whose value `_create_transaction` overwrites from the sheet
    on every write (rule 6), and the time was a text field holding a format to
    get right at the moment the admin is already reconstructing a movement from
    memory.

    Driven on the real window, reached the way an admin reaches it - a real
    click on the feed header's pill - because which widget a form is made of
    and what it will let somebody type into it are things only Tk can answer.

    What is asserted: the type is not editable and tracks the sheet as an
    identifier resolves; a month is offered only the days it has, so a date
    that does not exist is not offered rather than refused afterwards; a future
    time is still refused with nothing written; and a backdated one lands
    carrying the timestamp that was picked.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("Add Transaction offers a type it cannot change (#197)")
    tk = tk_or_skip()
    if tk is None:
        return
    from tkinter import ttk
    import tkinter.messagebox as mb

    db = fresh_db()
    _blank_lookup()
    _admin()
    M._save_asset("3197", "ST-197", "Screen", "U2419H")
    add_txn(db, asset_number="FEED-1")

    root = gui_root(tk)
    said = []
    real_info = mb.showinfo
    mb.showinfo = lambda *a, **k: said.append(a)
    try:
        def pill(w, want):
            if isinstance(w, tk.Canvas):
                for i in w.find_all():
                    if w.type(i) == "text" and want in w.itemcget(i, "text"):
                        return w
            for c in w.winfo_children():
                r = pill(c, want)
                if r is not None:
                    return r
            return None

        if not open_section_entry(tk, root, "Transactions",
                                  "Add Transaction"):
            bad("no Add Transaction entry on the Transactions section")
            return
        dlgs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        if not dlgs:
            bad("clicking it opened no dialog")
            return
        dlg = dlgs[-1]
        kids = widgets(dlg)

        def pump_until(ready, bound=60.0):
            """Turn the event loop until `ready()` answers true, bounded.

            This waited on a clock until #259: two seconds of `update()` for a
            400ms debounce, five times the margin it needed and still one red
            in twelve runs of this group. The three assertions that failed
            together were the type display, the sibling identifier and the
            backdated write, which is not three measurements taken early but
            one resolve that had not happened - `do_resolve` is synchronous
            once the timer fires and `_load_lookup_table` caches nothing, so
            a red here can only mean the timer had not fired yet.

            `tools/client-checks.py` learned this at #205 and carries the
            measured version of it: `update()` does not dispatch the queue
            anything like as often when the process is one of a dozen
            competing for the cores, so the `<KeyRelease>` that arms the timer
            is itself late and a fixed margin is a margin a busy machine eats.
            So wait on the **event** rather than on the clock, and bound it at
            a minute - long enough that no load reaches it, short enough that
            a debounce which never fires is reported rather than hung on.

            Tighter than the old wait as well as safer: the caller stops the
            moment the state arrives instead of always spending two seconds.
            """
            end = time.time() + bound
            while True:
                root.update_idletasks()
                root.update()
                if ready():
                    return True
                if time.time() >= end:
                    return False
                time.sleep(0.02)

        combos = [w for w in kids if isinstance(w, ttk.Combobox)]
        spins = [w for w in kids if isinstance(w, ttk.Spinbox)]
        entries = [w for w in kids if w.winfo_class() == "Entry"]
        plain = [e for e in entries if not str(e.cget("show"))]
        labels = [w for w in kids if isinstance(w, tk.Label)]

        def values(w):
            return [str(v) for v in w.cget("values")]

        # -- the type is not a field ---------------------------------------
        eq("no control on the form offers the Asset Type as a choice",
           [c for c in combos if "Screen" in values(c)], [])
        eq("  and it is not typeable either",
           any("Screen" in str(e.get()) for e in plain), False)
        eq("the form says it takes the type from the lookup sheet",
           any("Asset Type" in str(l["text"]) and "lookup sheet" in
               str(l["text"]) for l in labels), True)
        eq("  and shows an em dash until an identifier resolves",
           any(str(l["text"]) == "\u2014" for l in labels), True)

        # -- and it tracks the sheet ---------------------------------------
        if not plain:
            bad("no identifier field on the form")
            return
        asset_e = plain[0]
        asset_e.focus_force()
        asset_e.insert(0, "3197")
        asset_e.event_generate("<KeyRelease>", when="tail")
        landed = pump_until(
            lambda: "Screen" in [str(l["text"]) for l in labels])
        shown = [str(l["text"]) for l in labels]
        eq("the type is filled from the sheet as the identifier resolves",
           "Screen" in shown, True)
        if not landed:
            # Everything below waits on this one resolve - the sibling, and
            # the backdated write at the foot of the group - so three reds
            # here are one cause reported three times. Say what the resolve
            # line held instead, which is the state the run #259 came from
            # did not keep, and stop.
            said_it = [t for t in shown if t[:1] in ("\u2713", "!")]
            bad("  and what the resolve line held when the bound expired: %s"
                % (said_it[0] if said_it else "nothing at all"))
            return
        eq("  and the sibling identifier with it",
           plain[1].get().strip(), "ST-197")

        # -- a month is offered only the days it has ------------------------
        def when_combo(kind):
            for c in combos:
                vals = values(c)
                if kind == "year" and vals and len(vals[0]) == 4:
                    return c
                if kind == "month" and vals == ["%02d" % m
                                                for m in range(1, 13)]:
                    return c
                if kind == "day" and vals and vals[0] == "01" and len(vals) > 13:
                    return c
            return None

        year_cb, month_cb, day_cb = (when_combo("year"), when_combo("month"),
                                     when_combo("day"))
        if not (year_cb and month_cb and day_cb and len(spins) >= 2):
            bad("the date-time picker is not three comboboxes and two "
                "spinboxes - %d combobox(es), %d spinbox(es) found"
                % (len(combos), len(spins)))
            return
        eq("the picker offers no year a Transaction could not be dated in",
           max(values(year_cb)), "%04d" % datetime.now().year)
        year_cb.set("2026")
        month_cb.set("02")
        root.update()
        eq("February is offered twenty-eight days rather than thirty-one",
           values(day_cb)[-1], "28")
        day_cb.set("28")
        month_cb.set("11")
        root.update()
        eq("  and a day past the end of a newly picked month moves back",
           values(day_cb)[-1], "30")

        # -- a future time is refused --------------------------------------
        # No password field since 096: the entry asked at the door.
        eq("the form carries no password field of its own",
           [e for e in entries if str(e.cget("show"))], [])
        later = datetime.now() + timedelta(days=1)
        year_cb.set("%04d" % later.year)
        month_cb.set("%02d" % later.month)
        root.update()
        day_cb.set("%02d" % later.day)
        spins[0].set("%02d" % later.hour)
        spins[1].set("%02d" % later.minute)
        root.update()
        btns = [w for w in kids if w.winfo_class() == "Button"
                and "Add Transaction" in str(w.cget("text"))]
        if len(btns) != 1:
            bad("%d submit buttons on the form, expected 1" % len(btns))
            return
        btns[0].invoke()
        root.update()
        errs = [str(l["text"]) for l in labels if "future" in str(l["text"])
                and str(l["text"]).startswith("\u2717")]
        eq("a time in the future is still refused", bool(errs), True)
        conn = sqlite3.connect(db)
        n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        conn.close()
        eq("  and nothing was written", n, 1)

        # -- and a backdated one lands carrying what was picked -------------
        back = datetime.now() - timedelta(days=3)
        year_cb.set("%04d" % back.year)
        month_cb.set("%02d" % back.month)
        root.update()
        day_cb.set("%02d" % back.day)
        spins[0].set("07")
        spins[1].set("45")
        root.update()
        btns[0].invoke()
        root.update()
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM transactions WHERE asset_number=? "
                           "ORDER BY id DESC", ("3197",)).fetchone()
        conn.close()
        if row is None:
            bad("the backdated Transaction was not recorded")
            return
        eq("a backdated Transaction lands with the timestamp that was picked",
           row["timestamp"][:16],
           back.strftime("%Y-%m-%d") + "T07:45")
        eq("  and the type the sheet gave rather than one somebody picked",
           row["asset_type"], "Screen")
        eq("  recorded against the Admin at this console",
           row["storekeeper"], "Admin (Server GUI)")
    finally:
        mb.showinfo = real_info
        try:
            root.destroy()
        except Exception:
            pass


def check_a_feed_row_opens_that_record():
    """The activity feed is a door into Manage Transaction History (A11).

    The feed shows six facts about a movement and every remaining question -
    cancel it, correct it, read who confirmed it and from which machine - is
    in that other window, reached until now by reading an id off this screen
    and sorting or scrolling for it.

    Since 076 the door is one control over: the row **selects**, painting
    itself into the detail pane beside the list, and that pane's Open in
    history is what opens the window. Both halves are driven here, because a
    click that never reaches the label and a pane that does not follow the
    selection are two different failures and the second is the silent one - a
    pane that never repaints still names *a* movement.

    Driven as a **real click on a real label**, for the reason the select
    column's group gives about real coordinates: the row is a frame with four
    labels packed on top of it, so a binding on the frame alone leaves a click
    on the asset number landing on a widget that has none - which is the whole
    of what can go wrong here and the one thing only Tk can answer. The
    fallback halves are asserted beside it: an id the table no longer holds
    opens the window with nothing selected rather than raising, since the feed
    is a snapshot of a table that goes on moving.

    Skipped rather than failed where Tk has no display, like every group that
    opens a window.
    """
    head("a feed row opens that record (A11)")
    tk = tk_or_skip()
    if tk is None:
        return
    from tkinter import ttk

    db = fresh_db()
    _blank_lookup()
    older = add_txn(db, asset_number="FEED-OLD")
    wanted = add_txn(db, asset_number="FEED-CLICK")
    root = gui_root(tk)

    # The history table is the Transactions section's pane since 088, so
    # "opened" is "on the stage": mapped, and told apart from the console's
    # other Treeviews by the column only it carries.
    def history_tree():
        return next((x for x in widgets(root) if isinstance(x, ttk.Treeview)
                     and "member" in (x.cget("columns") or ())), None)

    def history_on_stage():
        tree = history_tree()
        return tree is not None and bool(tree.winfo_ismapped())

    eq("the history table is not on the stage before anything is clicked",
       history_on_stage(), False)

    # The label carrying the identifier, which is the deepest child of the
    # row and the one a person actually aims at. The OLDEST PENDING box in the
    # side panel draws the same identifier in the same font, so the row is
    # picked by what sits beside the label rather than by the text on it: a
    # feed row is the only place an Out/In chip is packed next to one.
    def on_a_feed_row(lbl):
        beside = [w.cget("text") for w in lbl.master.winfo_children()
                  if isinstance(w, tk.Label)]
        return "Out" in beside or "In" in beside

    def row_label(text):
        return [w for w in widgets(root)
                if isinstance(w, tk.Label) and w.cget("text") == text
                and on_a_feed_row(w)]

    def pane_names(text):
        """The identifier as the **detail pane** draws it: the same string, on
        a label that is not on a feed row. Picked by where it is rather than by
        its size, a size being the thing about this pane a type retune is
        expected to move."""
        return [w for w in widgets(root)
                if isinstance(w, tk.Label) and w.cget("text") == text
                and not on_a_feed_row(w)]

    if not row_label("FEED-CLICK") or not row_label("FEED-OLD"):
        bad("the feed drew no row for the transactions - nothing to click")
        root.destroy()
        return

    # Driven off the older row first and the newer one second, because the
    # pane opens on the newest row already: clicking that one first and finding
    # it named would pass against a pane that never repaints at all. The pair
    # is the assertion - what was clicked is on show, and what was on show has
    # gone.
    for want, gone in (("FEED-OLD", "FEED-CLICK"), ("FEED-CLICK", "FEED-OLD")):
        target = row_label(want)[-1]
        eq("the %s row says it is clickable" % want,
           str(target.cget("cursor")), "hand2")
        target.event_generate("<Button-1>", x=2, y=2)
        root.update_idletasks()
        root.update()
        if not pane_names(want):
            bad("clicking the %s row did not repaint the pane beside it - "
                "either the binding does not reach the labels packed on top "
                "of the row, or the pane is not reading the selection" % want)
            root.destroy()
            return
        ok("clicking the %s row paints it into the detail pane" % want)
        eq("  and %s is no longer the movement on show" % gone,
           len(pane_names(gone)), 0)

    def pill(w, want):
        # A ui_kit Pill is a canvas, so its label is a canvas item rather than
        # a widget's text - found the way a click finds it.
        if isinstance(w, tk.Canvas):
            for i in w.find_all():
                if w.type(i) == "text" and want in w.itemcget(i, "text"):
                    return w
        for c in w.winfo_children():
            r = pill(c, want)
            if r is not None:
                return r
        return None

    cv = pill(root, "Open in history")
    if cv is None:
        bad("the detail pane carries no Open in history action - the movement "
            "the feed is showing is unreachable from it")
        root.destroy()
        return
    cv.event_generate("<Button-1>", x=5, y=5)
    root.update_idletasks()
    root.update()

    if not history_on_stage():
        bad("the pane's Open in history did not put the history table on the "
            "stage")
        root.destroy()
        return
    tree = history_tree()

    def selected_ids():
        return [str(tree.set(i, "id")) for i in tree.selection()]

    eq("the clicked record is selected, and only it",
       selected_ids(), [str(wanted)])
    # The box is painted from the selection by <<TreeviewSelect>>, so a row
    # selected this way is ticked by the same path a ctrl-click ticks it -
    # what Delete is holding and what the admin can see cannot disagree.
    ticked = [str(tree.set(i, "id")) for i in tree.get_children("")
              if tree.item(i, "text") == "\u2611"]
    eq("  and its box is ticked with it", ticked, [str(wanted)])

    # An id that has gone between the feed's paint and the click on it, asked
    # of the pane the way `open_in_history` asks it.
    hist = next((w for w in widgets(root)
                 if getattr(w, "_select_transaction", None) is not None), None)
    if hist is None:
        bad("the Transactions pane carries no _select_transaction, so a feed "
            "row has nothing to ask")
        root.destroy()
        return
    hist._select_transaction(999999)
    root.update_idletasks()
    root.update()
    eq("a record that is no longer there leaves the table open with nothing "
       "selected", (history_on_stage(), selected_ids()), (True, []))
    eq("  and the table is still whole",
       sorted(str(tree.set(i, "id")) for i in tree.get_children("")),
       sorted([str(older), str(wanted)]))

    # Put on the stage from the bar, with no record asked for, nothing is
    # selected - which is what the section entry opened before 088.
    tree.selection_set(tree.get_children("")[0])
    show_section(tk, root, "Overview")
    show_section(tk, root, "Transactions")
    eq("put on the stage from the bar it selects nothing",
       selected_ids(), [])

    # **The door did not move** (ADR-0015). With the console locked, the
    # section shows a row where the table is, and a feed row is not a way
    # round it: refused at the prompt, nothing is shown or selected; answered,
    # the table is there and on its record. The prompt is stubbed because a
    # modal with nobody to answer it would hang the gate.
    real_prompt = GM.simple_password_prompt
    answer = [None]
    GM.simple_password_prompt = lambda *a, **k: answer[0]
    GM._CONSOLE_UNLOCKED[0] = False
    try:
        show_section(tk, root, "Overview")
        show_section(tk, root, "Transactions")
        eq("locked, the Transactions section holds no table",
           history_on_stage(), False)
        eq("  and a row naming it stands in for the table",
           [t for t, _r in section_entries(tk, root, "Transactions")
            if "Manage Transaction History" in t] != [], True)
        hist._select_transaction(wanted)
        root.update_idletasks()
        root.update()
        eq("refused at the door, a feed row opens nothing",
           (history_on_stage(), list(tree.selection())), (False, []))
        answer[0] = "admin"
        hist._select_transaction(wanted)
        root.update_idletasks()
        root.update()
        eq("answered, it lands on its own record",
           (history_on_stage(), selected_ids()), (True, [str(wanted)]))
    finally:
        GM.simple_password_prompt = real_prompt
        GM._CONSOLE_UNLOCKED[0] = True
    root.destroy()


def check_the_list_and_detail_shape():
    """The selection has to be **visible**, or the pane beside it is a pane of
    facts about nothing in particular (076).

    This is the one group holding `ui_kit.SectionBar`, `ListPane` and
    `DetailPane`, the shape every window after 076 is built out of. What it
    asserts is what a person could see: the three rows are read off the window
    and compared **with each other**, so a selection painted in the colour it
    was already drawn in fails here rather than passing as the code agreeing
    with itself. The same for the section bar, which has no caller in this
    build yet - the six sections that need it are #252 - and is therefore
    built here against the console's own root, where it gets the fonts and the
    ttk styles the app configures at startup rather than a bare `tk.Tk()`'s.

    Rules 3 and 4 are asserted off the real geometry too: the Asset Number is
    the first thing on the row and the Serial Number is under it, which is the
    one claim about this shape that a layout change can quietly invert.
    """
    head("the list-and-detail shape (076)")
    tk = tk_or_skip()
    if tk is None:
        return

    db = fresh_db()
    _blank_lookup()
    for n in range(3):
        add_txn(db, asset_number="SPLIT-%d" % n)
    root = gui_root(tk)

    def on_a_feed_row(lbl):
        beside = [w.cget("text") for w in lbl.master.winfo_children()
                  if isinstance(w, tk.Label)]
        return "Out" in beside or "In" in beside

    idents = {}
    for w in widgets(root):
        text = str(w.cget("text")) if isinstance(w, tk.Label) else ""
        if text.startswith("SPLIT-") and on_a_feed_row(w):
            idents[text] = w
    eq("the list pane drew a row per transaction", len(idents), 3)
    if len(idents) != 3:
        root.destroy()
        return

    def wrap_of(lbl):
        return lbl.master.master.master          # top -> pad -> wrap

    fills = dict((k, str(wrap_of(v).cget("bg"))) for k, v in idents.items())
    marks = dict((k, str(wrap_of(v).winfo_children()[0].cget("bg")))
                 for k, v in idents.items())
    # SPLIT-2 is the newest, so it is the row the pane opens on. Compared
    # against SPLIT-0 rather than against the token it should have been
    # painted with: what is being asserted is that one row looks different
    # from the others, which is the thing somebody can actually see.
    eq("one row is filled differently from the rest, and it is the newest",
       sorted(k for k in fills if fills[k] != fills["SPLIT-0"]), ["SPLIT-2"])
    eq("  and the 2px mark is lit on that same row alone",
       sorted(k for k in marks if marks[k] != marks["SPLIT-0"]), ["SPLIT-2"])
    if fills["SPLIT-2"] == marks["SPLIT-2"]:
        bad("the selected row's mark is its fill, so there is no mark on it")
    else:
        ok("the fill and the mark are two colours rather than one")

    ident = idents["SPLIT-2"]
    row = wrap_of(ident)
    root.update_idletasks()
    others = [w for w in widgets(row)
              if isinstance(w, tk.Label) and w is not ident]
    eq("nothing on the row sits above the Asset Number (rules 3 and 4)",
       [str(w.cget("text")) for w in others
        if w.winfo_rooty() < ident.winfo_rooty()], [])
    eq("  and the Serial Number is on a second line under it",
       len([w for w in others if w.winfo_rooty() > ident.winfo_rooty()]) > 0,
       True)

    # The section bar. No window carries one yet, so it is built here rather
    # than measured through a caller - in a Toplevel of the console's own root,
    # which is what gets it the fonts and ttk styles the app configures at
    # startup while still leaving it room to be mapped. Packed into the
    # console itself it would be the child `pack` served last, which on a full
    # window is a strip nothing can be clicked on.
    kit = GM.ui_kit
    names = ("Overview", "Assets", "System")
    picked = []
    pal = kit.DARK
    holder = tk.Toplevel(root)
    holder.geometry("520x120")
    bar = kit.SectionBar(holder, names, pal["BG"], pal["CARD"], pal["TEXT"],
                         pal["SUBTEXT"], pal["LINE"], command=picked.append)
    bar.pack(fill="x")
    holder.update_idletasks()
    holder.update()

    def lit():
        faces = dict((n, str(bar.cells[n][0].cget("bg"))) for n in names)
        return sorted(n for n in names if faces[n] != faces["Assets"])

    eq("the section bar opens with one section selected", lit(), ["Overview"])
    bar.cells["System"][1].event_generate("<Button-1>", x=4, y=4)
    holder.update_idletasks()
    holder.update()
    eq("clicking another moves the selection rather than lighting a second",
       lit(), ["System"])
    eq("  and the click reaches the callback", picked, ["System"])
    bar.select("Overview")
    holder.update_idletasks()
    eq("  while restoring a section paints it and says nothing",
       (lit(), picked), (["Overview"], ["System"]))
    holder.destroy()
    root.destroy()


def check_the_history_window_ticks_what_it_will_act_on():
    """The select column is the selection, drawn - not a second one.

    This window has always multi-selected with ctrl-click, which is invisible
    to anybody who has not been told, and what it does with that selection is
    ask for the admin password and an archive and then delete the rows. So the
    box is about making the selection legible **before** that prompt, and the
    one way it can fail at that is by disagreeing with what Delete is actually
    holding - which is why every assertion here reads the box and the
    selection together rather than either alone.

    Driven on the **real window**, with real clicks at the coordinates the
    column reports: which region a click lands in is a thing only Tk knows,
    and a handler called directly would be testing the harness. Skipped rather
    than failed where Tk has no display, like every group that opens a window.
    """
    head("the history window ticks what it will act on")
    tk = tk_or_skip()
    if tk is None:
        return
    from tkinter import ttk

    db = fresh_db()
    _blank_lookup()
    first = add_txn(db, asset_number="SEL-1")
    second = add_txn(db, asset_number="SEL-2")
    third = add_txn(db, asset_number="SEL-3")
    root = gui_root(tk)
    # The Transactions section, put on the stage the way a person puts it
    # there: the history table is that section's pane since 088 and is not
    # opened by call any more. `show_section` is what maps the tree, and an
    # `event_generate` on an unmapped widget is a click Tk delivers nowhere.
    if not show_section(tk, root, "Transactions"):
        bad("the Transactions section is not on the bar, so the history "
            "table cannot be reached")
        root.destroy()
        return
    # Told apart from the console's other Treeviews by the column only it
    # carries.
    tree = next((x for x in widgets(root) if isinstance(x, ttk.Treeview)
                 and "member" in (x.cget("columns") or ())), None)
    if tree is None or not tree.winfo_ismapped():
        bad("no history table on the Transactions section")
        root.destroy()
        return
    rows = tree.get_children("")

    eq("the pane is named for what it manages",
       any(isinstance(w, tk.Label)
           and "Manage Transaction History" in str(w.cget("text"))
           for w in widgets(tree.master)), True)
    eq("the table carries a select column", "tree" in str(tree.cget("show")),
       True)
    eq("  which does not stretch into the data",
       (int(tree.column("#0", "width")), bool(tree.column("#0", "stretch"))),
       (34, False))
    # Rule 4: the box is a control and sits ahead of the data as one, so the
    # identifiers are still the first data columns rather than the third and
    # fourth of something.
    eq("  and is not a data column, so rule 4 is untouched",
       list(tree.cget("columns"))[:3], ["id", "asset_number", "serial_number"])
    eq("every row opens unticked",
       sorted({tree.item(r, "text") for r in rows}), ["\u2610"])

    def click_box(item):
        """A real click in the box of one row."""
        box = tree.bbox(item, "#0")
        if not box:
            bad("row %r has no box to click" % item)
            return
        tree.event_generate("<Button-1>", x=box[0] + box[2] // 2,
                            y=box[1] + box[3] // 2)
        root.update_idletasks()
        root.update()

    def state():
        return ([tree.item(r, "text") for r in rows],
                sorted(tree.selection()), tree.heading("#0")["text"])

    click_box(rows[0])
    ticks, sel, hdr = state()
    eq("clicking a box ticks that row", ticks, ["\u2611", "\u2610", "\u2610"])
    eq("  and selects it, which is what Delete acts on", sel, [rows[0]])

    # The defect a plain click would have: the default binding replaces the
    # selection, so ticking a second box would silently untick the first.
    click_box(rows[1])
    ticks, sel, hdr = state()
    eq("a second box adds rather than replaces", ticks,
       ["\u2611", "\u2611", "\u2610"])
    eq("  so two rows are selected", len(sel), 2)
    eq("  and the header box is not yet ticked", hdr, "\u2610")

    click_box(rows[0])
    ticks, sel, _ = state()
    eq("clicking a ticked box unticks it", ticks,
       ["\u2610", "\u2611", "\u2610"])
    eq("  and deselects that row alone", sel, [rows[1]])

    # A click anywhere else is an ordinary click, which is the behaviour this
    # window already had and is what ctrl-click still goes through.
    cell = tree.bbox(rows[2], "asset_number")
    if cell:
        tree.event_generate("<Button-1>", x=cell[0] + cell[2] // 2,
                            y=cell[1] + cell[3] // 2)
        root.update_idletasks()
        root.update()
        ticks, sel, _ = state()
        eq("a click on the data selects the usual way", sel, [rows[2]])
        eq("  and the boxes follow it rather than being a second selection",
           ticks, ["\u2610", "\u2610", "\u2611"])

    # Select All is the header box, and a box that cannot be unticked is not
    # one - so the same control flips.
    hdr_cmd = str(tree.heading("#0", "command"))
    if not hdr_cmd:
        bad("the header box carries no command, so Select All is not on it")
        root.destroy()
        return
    tree.tk.call(hdr_cmd)
    root.update_idletasks()
    root.update()
    ticks, sel, hdr = state()
    eq("the header box selects every row", len(sel), len(rows))
    eq("  ticking all of them", ticks, ["\u2611"] * 3)
    eq("  and ticking itself", hdr, "\u2611")

    tree.tk.call(hdr_cmd)
    root.update_idletasks()
    root.update()
    ticks, sel, hdr = state()
    eq("clicking it again clears them", (len(sel), hdr), (0, "\u2610"))
    eq("  and unticks every row", ticks, ["\u2610"] * 3)
    eq("the ids behind the boxes are the Transactions themselves",
       sorted(int(tree.item(r, "values")[0]) for r in rows),
       sorted([first, second, third]))

    root.destroy()


def check_transaction_detail_finds_the_right_log_entries():
    """The detail popup's data layer: a bounded "#<id>" match, not a column.

    /confirm and /reject write the id into `detail` as "#<id>" rather than
    into a column of their own, so what stands in for the foreign key this
    table does not have is a token match - and the one way that can go wrong
    is "#4" answering for "#42" as well. Ids are chosen to make exactly that
    collision possible rather than trusting a fresh database to hand out ids
    that happen to trap it.

    Source-level rather than through the window: this is the query the popup
    is built on, and it is what a fuzzy match actually has to get right.
    """
    head("a Transaction's detail reads the right log entries")
    db = fresh_db()
    tid4  = add_txn(db, id=4,  asset_number="TRAP-4")
    tid42 = add_txn(db, id=42, asset_number="TRAP-42")

    # The server's own /confirm write: no client_id, just the address it saw.
    M._log_event("transaction.confirmed", "#%d" % tid4, address="192.0.2.50")
    # The Notifier's own copy of the same act, shipped through
    # POST /clients/log and so carrying the client_id /confirm cannot.
    M._log_event("transaction.confirmed", "#%d" % tid4, actor="Brian Dawson",
                 client_id="notifier-1", address="192.0.2.51",
                 component="Notifier")
    # A trap for the boundary: an entry naming the *other* id, which must
    # never answer for tid4 - "#4" is a substring of "#42".
    M._log_event("transaction.confirmed", "#%d" % tid42, actor="Brian Dawson",
                 client_id="notifier-2", address="192.0.2.52",
                 component="Notifier")
    # Not found this way, on purpose: its ids are a plain comma-separated
    # list with no "#" token at all.
    M._log_event("transaction.deleted", "1 record(s): %d" % tid4,
                 actor="Admin (Server GUI)", level="warn")

    _add_client(db, "notifier-1", "Brian Dawson")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE clients SET hostname=?, os_user=? WHERE client_id=?",
                ("ENG-LAPTOP-3", "bdawson", "notifier-1"))
    conn.commit()
    conn.close()

    rows4 = M._transaction_log_rows(tid4)
    eq("only the entries naming this id are found", len(rows4), 2)
    eq("  #42's entry does not leak in",
       all(r["client_id"] != "notifier-2" for r in rows4), True)
    eq("  and the deleted event, with no # token, is not found",
       all(r["event"] != "transaction.deleted" for r in rows4), True)

    rows42 = M._transaction_log_rows(tid42)
    eq("the other id finds only its own entry", len(rows42), 1)

    client4 = M._transaction_client(rows4)
    eq("the shipped entry's client is found and joined on clients",
       client4, {"hostname": "ENG-LAPTOP-3", "os_user": "bdawson",
                "address": "192.0.2.51"})

    client42 = M._transaction_client(rows42)
    eq("a client_id naming no row in `clients` still answers, just empty",
       client42, {"hostname": "", "os_user": "", "address": "192.0.2.52"})

    eq("no client_id anywhere answers None, not a guess",
       M._transaction_client([r for r in rows4 if not r["client_id"]]), None)


def check_the_history_window_opens_a_transaction_detail():
    """Double-clicking a row opens a read-only Transaction Detail popup.

    Double, not single: a single click on the data area already selects the
    row the usual way (the sibling group above holds that promise), and
    stealing it here would take away the only way to multi-select from the
    data area rather than the box column. Driven with real double-clicks at
    real coordinates, the same idiom that group uses, because which region a
    click lands in is a thing only Tk knows.
    """
    head("the history window opens a Transaction Detail popup")
    tk = tk_or_skip()
    if tk is None:
        return
    from tkinter import ttk

    db = fresh_db()
    _blank_lookup()
    tid = add_txn(db, asset_number="DTL-1", serial_number="SN-1",
                 asset_type="Laptop", asset_model="ThinkPad T14",
                 team_member="Brian Dawson", direction="Out Store",
                 notes="handed over at the desk", confirmed=1,
                 confirmed_at=datetime.now().isoformat())
    M._log_event("transaction.confirmed", "#%d" % tid, address="203.0.113.9")
    M._log_event("transaction.confirmed", "#%d" % tid, actor="Brian Dawson",
                 client_id="notifier-9", address="203.0.113.10",
                 component="Notifier")
    _add_client(db, "notifier-9", "Brian Dawson")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE clients SET hostname=?, os_user=? WHERE client_id=?",
                ("ENG-LAPTOP-9", "bdawson9", "notifier-9"))
    conn.commit()
    conn.close()

    root = gui_root(tk)
    # The Transactions section, put on the stage the way a person puts it
    # there: the history table is that section's pane since 088 and is not
    # opened by call any more. `show_section` is what maps the tree, and an
    # `event_generate` on an unmapped widget is a click Tk delivers nowhere.
    if not show_section(tk, root, "Transactions"):
        bad("the Transactions section is not on the bar, so the history "
            "table cannot be reached")
        root.destroy()
        return
    # Told apart from the console's other Treeviews by the column only it
    # carries.
    tree = next((x for x in widgets(root) if isinstance(x, ttk.Treeview)
                 and "member" in (x.cget("columns") or ())), None)
    if tree is None or not tree.winfo_ismapped():
        bad("no history table on the Transactions section")
        root.destroy()
        return
    rows = tree.get_children("")

    def open_toplevels():
        # A child of the console (dlg = tk.Toplevel(top)) since 088, the
        # window it sat over having become a pane on it - a Toplevel's master
        # is whatever window it names, and winfo_children follows that.
        return [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel) and w.winfo_exists()
               and w.title().startswith("Transaction #")]

    def dbl(item, col):
        """Two real presses at one spot - what a double-click is to Tk.

        event_generate refuses "<Double-1>" outright ("Double, Triple, or
        Quadruple modifier not allowed"): those are detected, not synthesised.
        Two <Button-1> presses close together at the same point are what Tk's
        own detector is watching for, the same way click_box's single press
        above is what fires an ordinary <Button-1> binding.
        """
        box = tree.bbox(item, col)
        if not box:
            bad("no cell to double-click for %r/%r" % (item, col))
            return
        x, y = box[0] + box[2] // 2, box[1] + box[3] // 2
        tree.event_generate("<Button-1>", x=x, y=y)
        root.update_idletasks()
        root.update()
        tree.event_generate("<Button-1>", x=x, y=y)
        root.update_idletasks()
        root.update()

    dbl(rows[0], "#0")
    eq("double-clicking the box column opens nothing", open_toplevels(), [])

    dbl(rows[0], "asset_number")
    detail = open_toplevels()
    if not detail:
        bad("double-clicking a row opened no Transaction Detail popup")
        root.destroy()
        return
    dlg = detail[-1]
    eq("it is titled for the row that was clicked", dlg.title(),
       "Transaction #%d" % tid)

    text = "\n".join(w["text"] for w in widgets(dlg) if isinstance(w, tk.Label))
    for expect in ("DTL-1", "SN-1", "ThinkPad T14", "Brian Dawson",
                  "handed over at the desk", "ENG-LAPTOP-9", "bdawson9",
                  "203.0.113.10"):
        eq("the popup shows %r" % expect, expect in text, True)

    log_trees = [w for w in widgets(dlg) if isinstance(w, ttk.Treeview)]
    eq("its own System Log entries are listed", len(log_trees), 1)
    if log_trees:
        eq("  both the server's write and the shipped one",
           len(log_trees[0].get_children("")), 2)

    dlg.destroy()
    root.destroy()


def check_a_system_log_row_opens_a_detail_popup():
    """Double-clicking a System Log row opens everything it holds (#195).

    This window elides: `Detail` is 270px against a column holding up to
    `_LOG_DETAIL_MAX` characters, the actor is a sentence naming a capability
    and the person it was handed to, and the two clocks and the source address
    are three columns read against each other. So the row somebody
    double-clicks is precisely the row they could not finish reading, which is
    what the popup is for - and it is driven with real double-clicks at real
    coordinates, the Transaction Detail group's idiom, because which row a
    click lands on is a thing only Tk knows.

    Four properties. The diff, which is the half that depends on #200 - a
    correction records what changed, and this is the window it can be read on.
    The plain detail, which is every other event and every correction written
    by a build before that, shown as it is rather than guessed at. The join on
    the entry's own `client_id`, since a shipped entry names an installation
    and not a machine. And a client row that has gone, which opens the entry
    without it rather than raising: an installation is reset or removed long
    after it wrote a line, and an entry that cannot be read because the machine
    behind it has gone is the record failing at the moment it is read.
    """
    head("a System Log row opens a detail popup (#195)")
    tk = tk_or_skip()
    if tk is None:
        return
    from tkinter import ttk

    db = fresh_db()
    _blank_lookup()
    _admin()
    tid = add_txn(db, asset_number="LD-1", serial_number="LS-1",
                  team_member="Brian Dawson", direction="Out Store",
                  notes="first go")
    payload, status = M._modify_transaction(
        tid, {"serial_number": "LS-2", "direction": "In Store"})
    eq("the correction the popup is about was accepted", status, 200)
    M._log_event("transaction.confirmed", "#%d" % tid, actor="Brian Dawson",
                 component="Notifier", client_id="notifier-7",
                 address="203.0.113.7", client_ts="2026-09-01T07:59:00")
    M._log_event("app.started", "a client whose row has since gone",
                 component="Storekeeper", client_id="gone-9",
                 address="203.0.113.9")
    _add_client(db, "notifier-7", "Brian Dawson")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE clients SET hostname=?, os_user=? WHERE client_id=?",
                 ("ENG-LAPTOP-7", "bdawson7", "notifier-7"))
    conn.commit()
    conn.close()

    root = gui_root(tk)
    try:
        # The System Log section, put on the stage the way a person puts it
        # there: the log is a section of its own since 090 (the list under
        # System's rows from 087) and is not opened by call. `show_section`
        # is what makes the tree mapped, and an `event_generate` on an
        # unmapped widget is a click Tk delivers nowhere - which would be
        # this check passing on a popup that never opened.
        if not show_section(tk, root, "System Log"):
            bad("the System Log section is not on the bar, so the System Log "
                "pane cannot be reached")
            return
        # Driven at a real working size rather than at the console's opening
        # one, so every row has a cell to click rather than whichever few the
        # opening size serves - which would make this group pass on whichever
        # row happened to be newest and report nothing about the others. The console is
        # resizable on both axes and this is the size an Admin reading a log
        # has it at; what is being asserted here is that a row opens its
        # entry, not what the window opens at.
        root.geometry("1400x900")
        root.update_idletasks()
        root.update()
        # The table this check is about, told apart from the console's two
        # other Treeviews by the derived column only this one carries.
        trees = [x for x in widgets(root) if isinstance(x, ttk.Treeview)
                 and "meaning" in (x.cget("columns") or ())]
        if not trees:
            bad("no System Log table on the System Log section")
            return
        tree = trees[-1]
        cols = list(tree.cget("columns"))
        rows = tree.get_children("")
        eq("the pane drew the three entries", len(rows) >= 3, True)

        # The popup is still a Toplevel (#195) - it is a detail opened from a
        # row and not a second list - and it is parented on the console now
        # rather than on the window that went, so it is a child of `root`.
        def popups():
            return [w for w in root.winfo_children()
                    if isinstance(w, tk.Toplevel) and w.winfo_exists()
                    and w.title().startswith("System Log Entry")]

        def open_row(event):
            """Double-click the newest row carrying that event, and read it."""
            want = [r for r in tree.get_children("")
                    if tree.item(r)["values"][cols.index("event")] == event]
            if not want:
                bad("no %r row on the window to open" % event)
                return None
            box = tree.bbox(want[0], "event")
            if not box:
                bad("the %r row has no cell to click" % event)
                return None
            x, y = box[0] + box[2] // 2, box[1] + box[3] // 2
            for _ in range(2):
                tree.event_generate("<Button-1>", x=x, y=y)
                root.update_idletasks()
                root.update()
            open_now = popups()
            if not open_now:
                bad("double-clicking the %r row opened nothing" % event)
                return None
            return open_now[-1]

        def text_of(dlg):
            return "\n".join(w["text"] for w in widgets(dlg)
                              if isinstance(w, tk.Label))

        # -- the correction, which is the entry with a diff on it -----------
        dlg = open_row("transaction.modified")
        if dlg is None:
            return
        text = text_of(dlg)
        eq("the popup shows both values of a changed field",
           ('"LS-1"' in text and '"LS-2"' in text), True)
        eq("  and the other changed field beside it",
           ('"Out Store"' in text and '"In Store"' in text), True)
        eq("  naming the field rather than printing the raw line",
           "Serial Number" in text, True)
        eq("  and says in words what the event was (#196)",
           M.EVENT_SENTENCES["transaction.modified"] in text, True)
        eq("  and who asked, exactly as the column holds it",
           "Admin (Server GUI)" in text, True)
        eq("it asks for no password", _entries_on(tk, dlg), [])
        eq("  and closes on Escape like every other sub-window",
           bool(dlg.bind("<Escape>")), True)
        dlg.destroy()
        root.update()

        # -- a shipped entry, joined to the installation that sent it -------
        dlg = open_row("transaction.confirmed")
        if dlg is None:
            return
        text = text_of(dlg)
        eq("a shipped entry names the machine behind the client_id",
           ("ENG-LAPTOP-7" in text and "bdawson7" in text), True)
        eq("  with the address that entry itself carries",
           "203.0.113.7" in text, True)
        eq("  and both clocks, this server's beside the Client's claim",
           ("01/09/2026" in text), True)
        eq("  and its detail as it is, there being no diff on it",
           "#%d" % tid in text, True)
        dlg.destroy()
        root.update()

        # -- and one whose installation is no longer in the registry --------
        dlg = open_row("app.started")
        if dlg is None:
            return
        text = text_of(dlg)
        eq("an entry whose client row has gone still opens",
           "gone-9" in text, True)
        eq("  saying so rather than raising or showing a blank hostname",
           "no longer in the Client registry" in text, True)
        dlg.destroy()
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def check_a_correction_diff_is_read_back_off_the_entry():
    """`_log_diff` reads only what #200 actually wrote, and only there.

    Beside the window group above, because what it answers is where the popup
    may show a diff at all. Three refusals and they are the whole of it: any
    other event, whose `detail` is a line of context and never a diff, so
    guessing at one would put made-up old values in front of somebody
    reconstructing a dispute; a correction written by a build before #200,
    which has no diff to read; and a correction that moved nothing, which says
    so in words rather than carrying an empty one.
    """
    head("a correction's diff is read back off the entry (#195)")
    db = fresh_db()
    _blank_lookup()
    _admin()
    tid = add_txn(db, asset_number="RD-1", team_member="Brian Dawson",
                  direction="Out Store")
    M._modify_transaction(tid, {"direction": "In Store",
                                "team_member": "Carol Evans"})
    rows = {r["event"]: r for r in log_rows(db)}
    diff = M._log_diff(rows["transaction.modified"])
    eq("a correction reads back as its changes", diff is not None, True)
    if diff:
        changes, dropped = diff
        eq("  one per field that moved, in the order the entry names them",
           changes, [("team_member", "Brian Dawson", "Carol Evans"),
                     ("direction", "Out Store", "In Store")])
        eq("  with nothing said to have been dropped", dropped, 0)

    # Every other event's `detail` is a line of context rather than a diff.
    M._log_event("transaction.cancelled", "#%d  a mis-scan" % tid)
    other = [r for r in log_rows(db)
             if r["event"] == "transaction.cancelled"][-1]
    eq("another event is not read as a diff", M._log_diff(other), None)

    # A build before #200 wrote the row as it read afterwards, which is not a
    # diff and must not be shown as one - the window falls back to `detail`.
    # `data` is cleared too (#246/071): the row above was written by this
    # build and so carries a real one, and a build before #200 - before #071
    # too - never wrote that column at all, so simulating its row means
    # simulating the absence of both.
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("UPDATE system_log SET detail=?, data=NULL WHERE event=?",
                 ("#%d  Brian Dawson  Out Store  RD-1" % tid,
                  "transaction.modified"))
    conn.commit()
    old = conn.execute("SELECT * FROM system_log WHERE event=?",
                       ("transaction.modified",)).fetchone()
    conn.close()
    eq("an entry written before the diff existed reads back as none",
       M._log_diff(old), None)

    M._modify_transaction(tid, {"direction": "In Store"})
    latest = [r for r in log_rows(db)
              if r["event"] == "transaction.modified"][-1]
    eq("and a correction that moved nothing carries no diff either",
       M._log_diff(latest), None)


def _ask_recorder(answers):
    """Stand in for the modal, and record what it was asked.

    Every prompt here ends in `askyesnocancel`, so the question is driven by
    replacing that rather than by calling the handlers directly: what is being
    asserted is that it is asked at all, and by which control.
    """
    asked = []

    def ask(title, message, **kw):
        asked.append(message)
        return answers.pop(0) if answers else None

    return asked, ask


def _win_named(root, tk, title):
    """The last open Toplevel with that title, or None."""
    found = [w for w in root.winfo_children()
             if isinstance(w, tk.Toplevel) and w.winfo_exists()
             and w.title() == title]
    return found[-1] if found else None


def _entries_on(tk, win):
    """Every Entry on this window, in the order they were built.

    The **first** is the admin password on every console window: it is asked
    for once at the top, above the form, which is what these windows have in
    common rather than a coincidence of layout.

    ttk's Entry is a subclass of Tk's, and a Combobox is a subclass of that,
    so the two dropdowns on a Notification Rules row answer this question as
    Entries unless they are excluded by hand.
    """
    from tkinter import ttk
    return [w for w in widgets(win)
            if isinstance(w, tk.Entry) and not isinstance(w, ttk.Entry)]


def _entry_holding(tk, win, text):
    """The one Entry on this window already holding that value."""
    hits = [w for w in _entries_on(tk, win) if w.get() == text]
    return hits[0] if len(hits) == 1 else None


def _close_window(root, win):
    """Click this window's X - the control that goes through WM_DELETE_WINDOW.

    The title bar is the window manager's and its message arrives whatever
    grab is held, which is the whole reason the console can be closed over a
    window with something typed into it.
    """
    cmd = str(win.protocol("WM_DELETE_WINDOW"))
    if not cmd:
        bad("%r answers no WM_DELETE_WINDOW, so its X discards silently"
            % win.title())
        return
    win.tk.call(cmd)
    root.update_idletasks()
    root.update()


_MAIL_ON_DISK = {"smtp_host": "mail.example.com", "smtp_port": 25,
                 "smtp_from": "server@example.com", "smtp_username": "",
                 "smtp_starttls": False}


def check_a_window_asks_before_closing_over_something_typed():
    """Unsaved changes are read off the widgets, and answered for on the way out.

    Every writer behind these windows is immediate and goes through one
    enforcement point, so what is unsaved on one of them is text in a field
    that no button has been pressed on yet - which is exactly the state that
    vanished without a word when somebody clicked the X. Mail Settings carries
    most of this because its fields are a straight difference against the
    file, so "unsaved" has a value that can be read back off disk afterwards
    rather than inferred.

    **The window is the whole of it.** There was a console above these until
    077 - `server_administration`, which took a grab on everything it opened,
    so its own X was the one way to close over a half-typed window and it
    answered for that by asking about all of them at once. 089 deleted what
    was left of that after the window went: the console is the main window
    now and its close is a hide to the tray, which leaves every one of these
    open and reachable rather than shutting a door on it. So what is driven
    here is the window's own X, which is where the protection bites.

    Driven on the **real window** and through the real WM_DELETE_WINDOW
    handler, with `askyesnocancel` replaced: which control asks, and what is
    still open afterwards, are things only Tk can answer.
    """
    head("a window asks before closing over something typed")
    tk = tk_or_skip()
    if tk is None:
        return
    import tkinter.messagebox as mb

    # What `_console_unsaved` answered until 089, asked here instead: the
    # table is the state, and a reader of it whose only caller is this check
    # is a function nothing in the application reaches.
    def unsaved():
        return [e for e in M._CONSOLE_UNSAVED if e.dirty()]

    fresh_db()
    _blank_lookup()
    write_server_cfg(dict(_MAIL_ON_DISK))
    root = gui_root(tk)
    real_ask = mb.askyesnocancel
    try:
        # 1. Nothing typed: the X asks nothing and the window goes.
        del M._CONSOLE_UNSAVED[:]
        asked, mb.askyesnocancel = _ask_recorder([])
        M.mail_settings(root)
        root.update_idletasks()
        root.update()
        win = _win_named(root, tk, "Mail Settings")
        if win is None:
            bad("Mail Settings did not open")
            return
        eq("an open console window is tracked", len(M._CONSOLE_UNSAVED), 1)
        eq("  and a form matching the file is not unsaved",
           unsaved(), [])
        _close_window(root, win)
        eq("closing it asks nothing", asked, [])
        eq("  and it is gone", bool(win.winfo_exists()), False)
        eq("  leaving nothing behind to refuse a later close",
           unsaved(), [])

        # 2. A field edited and not saved: the X asks, and Cancel keeps it.
        asked, mb.askyesnocancel = _ask_recorder([None])
        M.mail_settings(root)
        root.update_idletasks()
        root.update()
        win = _win_named(root, tk, "Mail Settings")
        host = _entry_holding(tk, win, _MAIL_ON_DISK["smtp_host"])
        if host is None:
            bad("no single Mail Settings field holds the stored mail server")
            return
        host.delete(0, "end")
        host.insert(0, "relay.example.com")
        eq("an edited field is an unsaved change",
           [e.label for e in unsaved()], ["Mail Settings"])
        _close_window(root, win)
        eq("closing over it asks", len(asked), 1)
        eq("  naming the window", "Mail Settings" in asked[0], True)
        eq("  and Cancel leaves it open", bool(win.winfo_exists()), True)
        eq("  with nothing written", read_server_cfg()["smtp_host"],
           _MAIL_ON_DISK["smtp_host"])

        # 3. Discard closes it and keeps nothing, which is the answer this
        #    window used to take without asking.
        asked, mb.askyesnocancel = _ask_recorder([False])
        _close_window(root, win)
        eq("Discard closes it", bool(win.winfo_exists()), False)
        eq("  and writes nothing", read_server_cfg()["smtp_host"],
           _MAIL_ON_DISK["smtp_host"])
    finally:
        mb.askyesnocancel = real_ask
        del M._CONSOLE_UNSAVED[:]
        try:
            root.destroy()
        except Exception:
            pass


def check_the_assets_pane_states_its_count_where_it_can_be_read():
    """The Asset Proposals count is on the Assets section, and it moves (090).

    Driven on the real console rather than read off the source, because what
    this is about is a number `pack` can take away. 086 made the list a pane
    under the Assets rows and found its count drawn 1px high and never mapped;
    090 made it a row again, with the count as the row's subtitle and the list
    in a pop-up. So there are two counts to hold now, and they are held to
    each other: the row's caption is **mapped**, at a readable height, on the
    Assets section; clicking the row opens the pop-up, whose own line says the
    same number; and answering a proposal moves **both** - the pop-up's
    through the decision path, and the row's the next time Assets is shown,
    which is when `show_section` asks the callable again.

    `_decide_proposal` is called directly - it is the one writer either way,
    and the password in front of it is a Tk field no harness can answer.

    Skipped rather than failed when Tk cannot open a display.
    """
    head("the Asset Proposals count is on the Assets section, and it moves "
         "(090)")
    tk = tk_or_skip()
    if tk is None:
        return
    from tkinter import ttk

    db = fresh_db()
    conn = sqlite3.connect(db)
    for n in (1, 2, 3):
        conn.execute(
            "INSERT INTO asset_proposals(asset_number, serial_number, "
            "asset_type, asset_model, proposed_by, proposed_at, status) "
            "VALUES (?,?,?,?,?,?, 'pending')",
            ("790%d" % n, "SN-90%d" % n, "Laptop", "T14", "Storekeeper User",
             "2026-09-23T09:0%d:00" % n))
    conn.commit()
    conn.close()

    root = gui_root(tk)
    if not show_section(tk, root, "Assets"):
        bad("the Assets section is not on the bar, so its row cannot be "
            "reached and this is measuring nothing")
        return

    def row_caption():
        """The subtitle beside the row's own name, on the same row."""
        name = next((w for w in widgets(root)
                     if w.winfo_class() == "Label"
                     and str(w.cget("text")) == "Asset Proposals"
                     and w.winfo_ismapped()), None)
        if name is None:
            return None
        return next((w for w in name.master.winfo_children()
                     if w.winfo_class() == "Label"
                     and "waiting on an answer" in str(w.cget("text"))), None)

    cap = row_caption()
    if cap is None:
        bad("no Asset Proposals row with a count on the Assets section")
        return
    if cap.winfo_height() < 12:
        bad("the row's count is %dpx high, which is not a line of text"
            % cap.winfo_height())
    else:
        ok("the row's count is mapped at %dpx on the Assets section"
           % cap.winfo_height())
    eq("and it says how many are waiting off the one reader",
       str(cap.cget("text")), "3 waiting on an answer")

    # The row opens the pop-up, the way a person opens it.
    if not show_section(tk, root, "Asset Proposals"):
        bad("the Asset Proposals row takes no click")
        return
    wins = [w for w in root.winfo_children()
            if isinstance(w, tk.Toplevel) and w.winfo_exists()
            and w.title() == "Asset Proposals"]
    if not wins:
        bad("clicking the Asset Proposals row opened no window")
        return
    win = wins[-1]
    pane = next((w for w in widgets(win)
                 if getattr(w, "_ui_reload", None) is not None
                 and any(isinstance(c, ttk.Treeview) for c in widgets(w))),
                None)
    if pane is None:
        bad("the pop-up holds no Asset Proposals list")
        return

    def count_label():
        return next((w for w in widgets(pane)
                     if w.winfo_class() == "Label"
                     and "waiting on an answer" in str(w.cget("text"))), None)

    lbl = count_label()
    if lbl is None or not lbl.winfo_ismapped():
        bad("the pop-up states no count it can be read at")
    else:
        eq("the pop-up's own line says the same number as the row",
           str(lbl.cget("text")).startswith("3 waiting on an answer"), True)

    # The re-read. `_decide_proposal` is the one writer whichever door calls
    # it, and the list is asked the way its decision path asks it.
    M._decide_proposal(1, True)
    pane._ui_reload()
    root.update_idletasks()
    root.update()
    after = str(count_label().cget("text"))
    eq("answering a proposal moves the pop-up's count",
       after.startswith("2 waiting on an answer"), True)
    eq("  and the one answered is counted as decided",
       "1 decided" in after, True)
    win.destroy()
    show_section(tk, root, "Overview")
    show_section(tk, root, "Assets")
    cap = row_caption()
    eq("  and the row's, the next time Assets is shown",
       str(cap.cget("text")) if cap is not None else None,
       "2 waiting on an answer")

    try:
        root.destroy()
    except Exception:
        pass


def check_no_dialog_is_smaller_than_its_own_form():
    """Every window must be at least as big as its own children asked for.

    Six were not, and all six carried their size in a geometry string. pack
    gives the shortfall to whichever child was packed last, which in every one
    of them was the button at the bottom. Measured on the merge-base:

        Capability Passwords           116px short  Close, 1px, never mapped
        Cancel Transaction (Confirmed)  54px short  its button, 1px, unmapped
        Add Transaction                 49px short  submit, 1px, never mapped
        Modify Transaction              49px short  Save Correction, 1px, gone
        Cancel Transaction (Pending)    33px short  the same button, 13px of 46
        Change Admin Password           14px short  delegation button 19px of 33
                                        62px narrow and its caption clipped
        Delete Records                   9px short  the Delete button, 37 of 46

    Those are measured inside the real window rather than a bare root, which is
    the same reason this group opens one: run_gui configures the ttk styles and
    fonts these forms are drawn with, and Modify Transaction asks for 725px
    without them against 749px with.

    Four of them had no usable button at all: Capability Passwords could not
    be closed, Modify Transaction could not be saved, Add Transaction could not
    be submitted, and a Confirmed Transaction could not be cancelled.
    Add Transaction is measured by the group above rather than here - both
    its size and the button itself, since that is the dialog the button
    actually went missing from. Every other window in this file is measured
    here.

    The windows that do not call ui_kit.fit are held to the same rule, since they
    pass by being written larger than their children rather than by asking, and
    that is a thing to keep true rather than to assume. Each axis is judged on
    its own - a height shortfall used to hide a width one - and only where that
    axis is fixed: a resizable window can be dragged open, so a shortfall there
    costs a drag rather than a control, and calling it a pass without saying so
    is how Connected Clients came to be reported as holding a width it does not.

    A window that is resizable on **both** axes is judged on neither, and says
    so in as many words with its size and its children's beside it. The silent
    version of that is the failure mode this group cannot see from the inside:
    a window that prints nothing reads exactly like a window nobody opened, and
    the System Log was both at once - missing from the openers below *and*
    draggable on both axes - so the gate reported a clean run over a window it
    had never looked at.

    The windows are opened the way a user opens them: by their own control
    where there is one, by call where the function is module-level, and by the
    chip binding for the ones a status chip opens. Database Location is not
    one of them since 066 moved it into Server Administration; it is pressed
    open from that console above, the way Change Admin Password beside it is.
    Two are opened by call because their control is a
    Pill packed straight into the activity feed header rather than laid out by
    ui_kit.row_of, so it carries no _ui_row for the pills_of loop to find: the
    System Log here, and Add Transaction in the group above, which reaches it
    by its canvas text because the button itself is what that group is for.
    Import Archive is the one exception, because it opens a native file dialog
    and blocks with nobody there to answer it.

    Skipped rather than failed when Tk cannot open a display.
    """
    head("no dialog is smaller than its own form")
    tk = tk_or_skip()
    if tk is None:
        return
    from tkinter import ttk

    db = fresh_db()
    # A Pending row and a Confirmed one, because Cancel Transaction asks for a
    # password on a Confirmed row and not on a Pending one - two branches, and
    # the height it used to carry was short by a different amount in each.
    add_txn(db, asset_number="IT-0001", serial_number="SN-1")
    add_txn(db, asset_number="IT-0002", serial_number="SN-2", confirmed=1,
            confirmed_at=datetime.now().isoformat())
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO clients (client_id, hostname, os_user, app, "
                 "version, member, address, first_seen, last_seen) "
                 "VALUES (?,?,?,?,?,?,?,?,?)",
                 ("cid-1", "LAP-02", "bdawson", "Notifier", M.APP_VERSION,
                  "Brian Dawson", "192.0.2.5",
                  datetime.now().isoformat(), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    root = gui_root(tk)

    def bottom_control(dlg):
        """The clickable thing nearest the bottom, or None.

        A tk.Button is one; a ui_kit.Pill is a rounded polygon on a canvas, so
        it is the other. The bottom-most is the one pack squeezes, and the one
        a form's Close or Save always is.
        """
        out = []
        for x in widgets(dlg):
            if x.winfo_class() == "Button" or getattr(x, "_ui_row", None):
                out.append(x)
            elif isinstance(x, tk.Canvas) and x.master is not None \
                    and getattr(x.master, "_ui_row", None):
                out.append(x)
        if not out:
            return None
        return sorted(out, key=lambda x: (x.winfo_rooty(), x.winfo_rootx()))[-1]

    def survives_its_own_floor(name, dlg):
        """Hold it at the smallest a user can drag it to and read the control.

        The opening size above is judged only on a fixed axis, because a
        resizable one can be dragged open - and that is half of it: it can be
        dragged **shut** as well, and how far is a number the window itself
        wrote down. A `minsize` is not a detail of a resizable window, it is
        the only floor there is.

        **Both axes**, since #192: the loss is not always vertical. A footer is
        packed along the width, so what a narrow window takes is its right-hand
        end - the Save it was opened to press - while the height is untouched
        and a vertical-only probe reports it as fine. A window that lets go of
        one axis is measured on that one; a window fixed on both has no floor
        to judge and is the opening measurement's.

        `tools/client-checks.py` holds the three client apps to exactly this.
        """
        grow_w, grow_h = dlg.resizable()
        if not grow_w and not grow_h:
            return
        floor_w, floor_h = dlg.minsize()
        for axis, grow, floor in (("width", grow_w, floor_w),
                                  ("height", grow_h, floor_h)):
            if grow and floor <= 1:
                bad("%s can be dragged smaller on its %s and sets no minsize, "
                    "so it can be pulled down to nothing and there is no floor "
                    "to judge - give it one" % (name, axis))
                return
        btn = bottom_control(dlg)
        if btn is None:
            bad("%s has no button at all" % name)
            return
        w = floor_w if grow_w else dlg.winfo_width()
        h = floor_h if grow_h else dlg.winfo_height()
        dlg.geometry("%dx%d" % (w, h))
        dlg.update_idletasks()
        dlg.update()
        top = btn.winfo_rooty() - dlg.winfo_rooty()
        left = btn.winfo_rootx() - dlg.winfo_rootx()
        at = "%s at its own %dx%d minimum" % (name, w, h)
        if not btn.winfo_ismapped():
            bad("%s: the bottom control is not mapped" % at)
        elif btn.winfo_height() < 20:
            bad("%s: the bottom control is %dpx, which is not a button"
                % (at, btn.winfo_height()))
        elif top + btn.winfo_height() > dlg.winfo_height():
            bad("%s: the bottom control ends %dpx below the bottom edge"
                % (at, top + btn.winfo_height() - dlg.winfo_height()))
        elif left + btn.winfo_width() > dlg.winfo_width():
            bad("%s: the bottom control ends %dpx past the right-hand edge"
                % (at, left + btn.winfo_width() - dlg.winfo_width()))
        else:
            ok("%s: its %dx%d minimum holds its bottom control, so no drag can "
               "squeeze it out" % (name, w, h))

    def measure(label, opener):
        """Open it, measure both axes, hand back the windows it opened."""
        before = {str(w) for w in widgets(root) if isinstance(w, tk.Toplevel)}
        try:
            opener()
        except Exception as ex:
            bad("%s raised %s: %s" % (label, type(ex).__name__, ex))
            return []
        root.update_idletasks()
        root.update()
        new = [w for w in widgets(root)
               if isinstance(w, tk.Toplevel) and str(w) not in before]
        if not new:
            bad("%s opened no window" % label)
            return []
        for dlg in new:
            dlg.update_idletasks()
            title = dlg.title()
            name = label if title in label else "%s (%s)" % (label, title)
            grow_w, grow_h = dlg.resizable()
            h, rh = dlg.winfo_height(), dlg.winfo_reqheight()
            w, rw = dlg.winfo_width(), dlg.winfo_reqwidth()
            if grow_w and grow_h:
                # The opening size is not judged: both axes can be dragged, so
                # a shortfall there costs a drag rather than a control. It is
                # said out loud all the same, and with the numbers, because a
                # window that produces no line at all is indistinguishable
                # from one nobody opened - which is exactly how the System Log
                # went unmeasured, and a silent pass is the one kind this
                # group cannot tell from a gap in its own opener list.
                lost = ("  (short by %dx%d, draggable)"
                        % (max(rw - w, 0), max(rh - h, 0))
                        if rw > w or rh > h else "")
                ok("%s: %dx%d against its children's %dx%d - resizable on "
                   "both axes, so the opening size is not judged%s"
                   % (name, w, h, rw, rh, lost))
                # The floor is judged, though, and on whichever axes this
                # window lets go of - which is every window here that lets go
                # of one, not only the two-axis ones this branch is about.
                survives_its_own_floor(name, dlg)
                continue
            for axis, short, grow, cost in (
                    ("shorter", rh - h, grow_h,
                     "whatever is packed last is being squeezed"),
                    ("narrower", rw - w, grow_w,
                     "a label in it is being clipped")):
                if short <= 0:
                    continue
                if grow:
                    ok("%s is %dpx %s than its children ask for, but that axis "
                       "is resizable - a drag, not a lost control"
                       % (name, short, axis))
                else:
                    bad("%s is %dpx %s than its children ask for (%dx%d of "
                        "%dx%d) - %s" % (name, short, axis, w, h, rw, rh, cost))
            if rh <= h and rw <= w:
                ok("%s: %dx%d holds its children's %dx%d"
                   % (name, w, h, rw, rh))
            # A window fixed on one axis and draggable on the other has a
            # floor too, on the axis it lets go of, and had never been held to
            # it: the branch above only ran for windows draggable on both.
            survives_its_own_floor(name, dlg)
        return new

    def close(wins):
        for w in wins:
            try:
                w.destroy()
            except Exception:
                pass
        root.update_idletasks()

    def pills_of(w):
        """Every pill `ui_kit.row_of` laid out anywhere under this window.

        The console's own action row went with 077 and this did not: the row
        is what fourteen **dialogs** foot themselves with, and two of them
        are pressed open from inside below.
        """
        return [p for x in widgets(w)
                for p in (getattr(x, "_ui_row").pills
                          if getattr(x, "_ui_row", None) is not None else [])]

    def press(w, key):
        hits = [p for p in pills_of(w) if key in str(p.full)]
        if not hits:
            bad("no control matching %r in %r"
                % (key, w.winfo_toplevel().title()))
            return lambda: None
        return hits[0].command

    def press_button(w, key):
        """The same, for a window whose controls are plain tk.Buttons.

        Manage Users' Add an Engineer is a full-width button rather than a
        pill on a footer row, so `pills_of` cannot see it.
        """
        hits = [x for x in widgets(w)
                if x.winfo_class() == "Button"
                and key in str(x.cget("text"))]
        if not hits:
            bad("no button matching %r in %r" % (key, w.title()))
            return lambda: None
        return hits[0].cget("command") and hits[0].invoke

    def dbl_first_row(w):
        """Two real presses on this window's first row, as an opener.

        `event_generate` refuses "<Double-1>" outright - those are detected
        rather than synthesised - so two <Button-1> presses close together at
        one point is what Tk's own detector is watching for, the idiom the
        Transaction Detail group already uses.
        """
        def go():
            tvs = [x for x in widgets(w) if isinstance(x, ttk.Treeview)]
            if not tvs or not tvs[-1].get_children():
                bad("no row to open in %r" % w.title())
                return
            tv = tvs[-1]
            box = tv.bbox(tv.get_children()[0], tv.cget("columns")[0])
            if not box:
                bad("the first row of %r has no cell to click" % w.title())
                return
            x, y = box[0] + box[2] // 2, box[1] + box[3] // 2
            for _ in range(2):
                tv.event_generate("<Button-1>", x=x, y=y)
                root.update_idletasks()
                root.update()
        return go

    def select(w, status):
        """Select a row - the first, or the first the status column matches."""
        for tv in [x for x in widgets(w) if isinstance(x, ttk.Treeview)]:
            kids = tv.get_children()
            if not kids:
                continue
            want = [k for k in kids if status == "any"
                    or status in str(tv.item(k)["values"])]
            if not want:
                bad("no %s row to select in %r"
                    % (status, w.winfo_toplevel().title()))
                continue
            tv.selection_set(want[0])
        root.update_idletasks()
        root.update()

    # Every door on the bar, section by section. This was the action row,
    # each dialog by its own pill, and it is the same walk one shape along -
    # except that the row named six of the fourteen windows and the bar names
    # all of them, so the four that were behind a hub are measured here
    # directly rather than through the menu that used to hold them. Change
    # Admin Password and Database Location were each reached by pressing an
    # entry inside Server Administration; there is no Server Administration,
    # and they are entries on People and System.
    #
    # Manage Users is opened below instead of here, so it is opened once
    # rather than twice: it carries a dialog of its own that has to be
    # pressed open while it is still up. Manage Transaction History is not an
    # entry since 088 but the Transactions pane, and the row it shows while
    # the console is locked opens no window - its four dialogs are pressed
    # open through the pane below. Import
    # Transaction Archive is not measured at all, for the reason on the skip.
    walked = 0
    for name in section_names():
        if name == "Overview":
            continue
        for label, row in section_entries(tk, root, name):
            if ("Manage Transaction History" in label
                    or "Manage Users" in label):
                continue
            # Import Transaction Archive opens `askopenfilename` and nothing
            # of ours: a native file dialog is not a form this repo laid out
            # and there is no size of ours to hold it to. Skipped by the
            # action row's walk before this one for the same reason - an
            # entry measured here would report "opened no window" for ever.
            if "Import Transaction Archive" in label:
                continue
            walked += 1
            close(measure(label, (lambda r=row: r.event_generate(
                "<Button-1>", x=3, y=3))))
            # Back to the section, which the dialog that just closed may have
            # left: `measure` destroys what it opened and the stage is
            # whatever was on it, so the next entry is looked up again.
            show_section(tk, root, name)
    if walked:
        ok("%d doors walked off the bar" % walked)
    else:
        bad("no section carries an entry - the bar opens nothing, and this "
            "walk is measuring no dialog at all")
    # Engineer Passwords is not opened here because there is no such window
    # since A5: Set and Clear are on the Engineer's card in Manage Users,
    # which is measured below and whose cards grew a row for them.
    # The second entry in that console. It asks for its size after the Engineer
    # cards are built rather than once, because its children change while it is
    # open, so what is measured here is the size it settles on with the
    # Engineers this database has.
    mu = measure("Manage Users", lambda: M.manage_users(root))
    if mu:
        # Add an Engineer (A4/#121) moved off the bottom of this window and
        # into its own popup - a link at the top, opened the way a user
        # opens it, the same nested-dialog pattern Change Admin Password
        # above is measured with.
        close(measure("Add an Engineer",
                      press_button(mu[-1], "Add an Engineer")))
    close(mu)
    # Mail Settings, Notification Rules, the Lookup Sheet and the two
    # windows behind it were each opened here by name, being module-level
    # where the entry that reached them was not. They are entries on the
    # System and Assets sections now and the walk above opens every one of
    # them, so opening them again here would measure each twice and say so
    # twice.
    #
    # Asset Proposals was one of those entries until 086 and is the Assets
    # section's pane now, so the walk above no longer finds a row for it -
    # and there is nothing here to put in its place. A pane cannot be too
    # small for its own form: it is served whatever the console has and
    # writes no size of its own to be held to. Unlike Connected Clients one
    # ticket back, nothing of ours opens from inside it either - Approve
    # asks with a `messagebox` and Reject with a `simpledialog`, neither of
    # which is a form this repo laid out, which is the same reason Import
    # Transaction Archive is skipped above.

    # Four dialogs live inside Manage Transaction History and each needs a row
    # selected. It is the Transactions section's pane since 088, so it is not
    # measured as a window - a pane is served whatever the console has and
    # writes no size of its own to be held to - but it is still put on the
    # stage once and held there while all four are pressed open through it.
    if not show_section(tk, root, "Transactions"):
        bad("the Transactions section is not on the bar, so the four dialogs "
            "inside Manage Transaction History are measuring nothing")
    else:
        # The pane rather than `root`: `select` selects in every Treeview
        # under what it is handed, and this console carries four.
        mgr = next((w for w in widgets(root)
                    if getattr(w, "_select_transaction", None) is not None),
                   None)
        if mgr is None:
            bad("no history pane on the Transactions section, so its four "
                "dialogs cannot be reached")
        else:
            for label, key, row in (
                    ("Delete Records", "Delete", "any"),
                    ("Modify Transaction", "Modify", "Pending"),
                    ("Cancel Transaction, a Pending row", "Cancel", "Pending"),
                    ("Cancel Transaction, a Confirmed row", "Cancel",
                     "Confirmed")):
                select(mgr, row)
                close(measure(label, press(mgr, key)))

    # The System Log is not a window since 087 and so is not measured as one.
    # It is the System section's pane, and a pane cannot be too small for its
    # own form: it is served whatever the console has and writes no size of
    # its own to be held to. What still has to be reached is the row-detail
    # popup (#195) one level inside it, so the section is put on the stage the
    # way a person puts it there and the popup is pressed open off a row in
    # the pane - the same nested pattern Change Admin Password and Send
    # Command are measured with.
    #
    # One entry first, so there **is** a row to open: this database is fresh,
    # and a System Log with nothing in it would measure the pane and skip the
    # popup in silence. That was the gap this block was written for when the
    # window went unmeasured entirely, and it is the half of it a pane does
    # not remove.
    M._log_event("server.started", "measured by the window gate")
    if not show_section(tk, root, "System Log"):
        bad("the System Log section is not on the bar, so its pane cannot "
            "be reached and this is measuring nothing")
    else:
        # The pane rather than `root`, unlike the Clients block below.
        # `dbl_first_row` takes the **last** Treeview under whatever it is
        # handed, and this console carries several - the history table,
        # this one, and the Clients pane's registry and its command queue,
        # which are built after the section loop. Handed `root`
        # this would double-click an unmapped tree on a section that is not on
        # the stage, where Tk delivers nothing at all and the popup silently
        # never opens. So the pane is found by the column only this table has.
        logpane = next((w for w in widgets(root)
                        if getattr(w, "_ui_reload", None) is not None
                        and any(isinstance(c, ttk.Treeview)
                                and "meaning" in (c.cget("columns") or ())
                                for c in widgets(w))), None)
        if logpane is None:
            bad("no System Log pane on the System Log section, so the "
                "row-detail popup cannot be reached")
        else:
            # The same real working size the popup group above drives, and
            # for the same reason: a row that is one drag away from not being
            # there is not what this measurement should rest on.
            was = root.winfo_geometry()
            root.geometry("1400x900")
            root.update_idletasks()
            root.update()
            close(measure("System Log Entry", dbl_first_row(logpane)))
            root.geometry(was)
            root.update_idletasks()
            root.update()

    # Send Command is the same shape, one level inside Connected Clients -
    # which is not a window since 085 and so is not measured as one. It is
    # the Clients section's pane, and a pane cannot be too small for its own
    # form: it is served whatever the console has and there is no written
    # size of its own to hold it to. What still has to be reached is the
    # dialog inside it, so the section is put on the stage the way a person
    # puts it there and Send Command is pressed open from the footer.
    #
    # `root` rather than the pane, because `press` and `select` walk down
    # from whatever they are handed and the two Treeviews and the footer row
    # on this console are all the pane's: "Log Off" is one control in one
    # place, which is what `check_the_command_controls_are_shaped_right`
    # holds.
    if show_section(tk, root, "Clients"):
        select(root, "any")
        close(measure("Send Command", press(root, "Log Off")))
    else:
        bad("the Clients section is not on the bar, so Send Command cannot "
            "be reached and this is measuring nothing")

    # The status card's chips open dialogs of their own, and a chip is a
    # bound frame rather than a pill, so the loop above cannot see it.
    # Clicking every bound chip also puts a chip added later under this check
    # without anybody remembering to add it. Database Location used to be the
    # one this sentence named and is reached from Server Administration since
    # 066, so what is left here is whatever chips the band still carries.
    def bound(w):
        try:
            return w.winfo_class() == "Frame" and "<Button-1>" in w.bind()
        except tk.TclError:          # repainted out from under us
            return False

    # A chip binds the click on its own frame and on each frame inside it, so
    # the chip is the outermost bound frame - taking them all would open the
    # same dialog four times over. Three kinds of bound frame on this window
    # are **not** chips, and each says so itself rather than being told apart
    # by where it sits, so this loop still catches a chip nobody remembered
    # to name: a `ui_kit.ListPane` row, which selects rather than opens
    # (`check_a_feed_row_opens_that_record` drives that one); a section
    # entry, which the walk above opens by its own section; and a
    # `ui_kit.SectionBar` cell, which opens nothing at all - it swaps what is
    # on the stage, and clicking all six here reported six windows that never
    # opened.
    def stamped(w):
        return (getattr(w, "_ui_list_row", None)
                or getattr(w, "_ui_section_row", None)
                or getattr(w, "_ui_section_cell", None))

    chips = [w for w in widgets(root)
             if bound(w) and not bound(w.master) and not stamped(w)]
    # The same walk, keeping what the line above drops. 076 is what made the
    # two lists different: until then the feed rows were the only bound frames
    # this walk found, and they passed the `if not chips` below by being
    # mistaken for chips - the band has carried no chip of its own since 066
    # moved Database Location into Server Administration. So the assertion is
    # what it can honestly be, which is that the walk still finds *something*
    # bound: a window where nothing binds a click on a frame is a window where
    # this loop measures nothing and a chip added later goes with it.
    rows = [w for w in widgets(root)
            if bound(w) and not bound(w.master) and stamped(w)]
    if not chips and not rows:
        bad("nothing on this window binds a click on a frame - neither a "
            "status chip nor a list row, so this loop is measuring nothing "
            "and would go on reporting green over a chip added later")
    elif not chips:
        ok("the status band carries no chip of its own; the %d bound frames "
           "here are list rows, section entries and the bar's own cells, and "
           "none of the three is a door this loop should be pressing"
           % len(rows))
    for i, chip in enumerate(chips):
        if not bound(chip):          # an earlier chip repainted this panel
            continue
        close(measure("status chip %d" % (i + 1),
                      lambda c=chip: c.event_generate("<Button-1>", x=3, y=3)))

    try:
        root.destroy()
    except Exception:
        pass


def check_a_form_with_no_bound_scrolls_and_keeps_its_footer():
    """Three console windows grew a form nothing bounds, and each now scrolls.

    Manage Users is a card per Engineer, Capability Passwords a card per
    capability and Notification Rules a card per rule - none of the three has
    an upper bound this window can impose, and all three are fixed on both
    axes, so past `ui_kit.fit`'s clamp there is nothing to drag open. What the
    clamp costs is not the tail of a list somebody can scroll to: `pack` gives
    the shortfall to whatever it served last, so what went was the rows
    themselves, and at 24 rules Notification Rules asked for 1794px against a
    screen with 1080.

    Three things per window, and each is a different way the answer fails:

    * there **is** a region, found the way `measure_scrolled_body` in
      `tools/client-checks.py` finds one - a `Frame` whose master is a
      `tk.Canvas` - so a window that quietly stops scrolling is a failure
      rather than a group that has nothing left to measure. The canvas has to
      carry a `create_window` item, because every window here stands on a
      `ui_kit.Surface` depth layer that is itself a Canvas;
    * the region **reaches** the form: its `scrollregion` covers what the body
      asks for, or what does not fit is unreachable rather than scrolled to,
      which is the same loss one layer further in and invisible to the size
      group above - the window is exactly as tall as it asked to be either way;
    * the footer is **outside** the region, mapped, button-sized and on the
      screen. A Close inside the scrolling body is a Close that can be scrolled
      away from, which is the window's only exit.

    Skipped rather than failed where Tk has no display, like every group here
    that opens a window.
    """
    head("a form with no bound scrolls, and its footer stays outside it")
    tk = tk_or_skip()
    if tk is None:
        return

    # 24 rules, which is past what a 1080p screen holds and is the count the
    # measurement behind #199 was taken at.
    write_server_cfg({"notify_rules": [{"event": "update.failed",
                                        "to": "it@example.com",
                                        "level": "error"}
                                       for _ in range(24)]})
    fresh_db()
    root = gui_root(tk)
    M._CONSOLE_UNLOCKED[0] = True

    def region_of(dlg):
        """The scrolling body and the canvas it is windowed into, or None."""
        for cv in widgets(dlg):
            if not isinstance(cv, tk.Canvas):
                continue
            held = [cv.itemcget(i, "window") for i in cv.find_all()
                    if cv.type(i) == "window"]
            if not held:
                continue
            for body in widgets(dlg):
                if str(body) in held and body.winfo_class() == "Frame" \
                        and body.master is cv:
                    return cv, body
        return None, None

    def bottom_control(dlg, body):
        """The lowest clickable thing that is **outside** the scrolling body.

        Sorting every control by where it sits stops being the right question
        the moment the form scrolls: the lowest widget in Manage Users at four
        Engineers is the last card's own Clear button, a thousand pixels down
        a body the canvas is clipping, and asking whether that is on the
        screen is asking whether a scroll region scrolls. What this group is
        about is the footer, which is the control pinned outside the region -
        so the region's own children are dropped first and what is left is
        the window's exit. Nothing left means there is no pinned footer at
        all, which is the failure this returns None for.
        """
        out = []
        for x in widgets(dlg):
            if x.winfo_class() == "Button" or getattr(x, "_ui_row", None):
                out.append(x)
            elif isinstance(x, tk.Canvas) and x.master is not None \
                    and getattr(x.master, "_ui_row", None):
                out.append(x)
        if body is not None:
            out = [x for x in out
                   if not str(x).startswith(str(body) + ".")]
        if not out:
            return None
        return sorted(out, key=lambda x: (x.winfo_rooty(), x.winfo_rootx()))[-1]

    def scrolls(label, opener):
        before = {str(w) for w in widgets(root) if isinstance(w, tk.Toplevel)}
        try:
            opener()
        except Exception as ex:
            bad("%s raised %s: %s" % (label, type(ex).__name__, ex))
            return
        root.update_idletasks()
        root.update()
        new = [w for w in widgets(root)
               if isinstance(w, tk.Toplevel) and str(w) not in before]
        if not new:
            bad("%s opened no window" % label)
            return
        dlg = new[-1]
        dlg.update_idletasks()
        cv, body = region_of(dlg)
        if cv is None:
            bad("%s has no scroll region at all - its form has no bound and "
                "what does not fit the screen is lost rather than scrolled to"
                % label)
        else:
            needs = body.winfo_reqheight()
            got = str(cv.cget("scrollregion")).split()
            reach = int(float(got[3])) if len(got) == 4 else 0
            if reach >= needs:
                ok("%s: %dpx of scroll for a form asking %dpx, so every row of "
                   "it is reachable" % (label, reach, needs))
            else:
                bad("%s: the scroll region stops at %dpx and the form asks for "
                    "%dpx, so what does not fit is unreachable rather than "
                    "scrolled to" % (label, reach, needs))
        btn = bottom_control(dlg, body)
        if btn is None:
            bad("%s has no control outside the scrolling body, so the window's "
                "own exit is inside it and can be scrolled away from" % label)
        elif not btn.winfo_ismapped():
            bad("%s: its bottom control is not mapped" % label)
        elif btn.winfo_height() < 20:
            bad("%s: its bottom control is %dpx, which is not a button"
                % (label, btn.winfo_height()))
        elif (btn.winfo_rooty() - dlg.winfo_rooty()) + btn.winfo_height() \
                > dlg.winfo_height():
            bad("%s: its bottom control ends below the bottom edge" % label)
        else:
            ok("%s: its footer is outside that region, mapped and on the "
               "screen" % label)
        try:
            dlg.grab_release()
        except Exception:
            pass
        dlg.destroy()
        root.update_idletasks()
        root.update()

    scrolls("Capability Passwords", lambda: M.capability_passwords(root))
    scrolls("Manage Users", lambda: M.manage_users(root))
    scrolls("Notification Rules at 24 rules",
            lambda: M.notification_rules(root))

    try:
        root.destroy()
    except Exception:
        pass


def check_the_theme_reaches_a_combobox_popdown():
    """A combobox's dropdown list must follow the theme, before and after.

    The list is a plain Tk listbox in a Toplevel that ttk builds the first time
    the arrow is clicked. It is not a ttk style, and it is not a child of the
    combobox in the tree the retint walk follows, so both of the mechanisms
    that repaint this window miss it: `option_add` alone reaches only the
    popdowns that do not exist yet, which left a combobox that had been opened
    once carrying its old colours for the rest of the session.

    Skipped rather than failed when Tk cannot open a display.
    """
    head("a combobox dropdown follows the theme")
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as ex:
        skip("tkinter unavailable (%s)" % ex)
        return
    try:
        tk.Tk().destroy()
    except Exception as ex:
        skip("no display for Tk (%s)" % ex)
        return

    was = M.THEME.mode
    root = tk.Tk()
    root.withdraw()
    M.THEME.set("dark")
    M.THEME.register(root)
    cb = ttk.Combobox(root, values=["Laptop", "Screen"])
    cb.pack()
    # What clicking the arrow does - this is what creates the popdown.
    lb = root.tk.eval("ttk::combobox::PopdownWindow %s" % cb) + ".f.l"
    root.update_idletasks()

    def bg():
        return str(root.tk.call(lb, "cget", "-background")).lower()

    eq("a popdown is born in the live palette", bg(), GM.INPUT_BG.lower())
    M.THEME.set("light")
    root.update_idletasks()
    eq("and follows a switch it was already open for", bg(),
       GM.INPUT_BG.lower())
    dark_again = ttk.Combobox(root, values=["Laptop"])
    lb2 = root.tk.eval("ttk::combobox::PopdownWindow %s" % dark_again) + ".f.l"
    root.update_idletasks()
    eq("one built after the switch is born right",
       str(root.tk.call(lb2, "cget", "-background")).lower(),
       GM.INPUT_BG.lower())
    M.THEME.set("dark")
    root.update_idletasks()
    eq("and back", bg(), GM.INPUT_BG.lower())
    try:
        root.destroy()
    except Exception:
        pass
    M.THEME.set(was)          # the module globals are shared with every check


def check_admin_cfg_merges_over_defaults():
    """A file written before a key existed must still load.

    admin_config.json was handed back verbatim, so the first build to read a new
    key would raise on every install that already exists - and this file is
    never rewritten unless the admin changes their password.
    """
    head("admin config merges over the defaults")

    write_admin_cfg(json.dumps({"password_hash": stored_form("hunter2")}))
    cfg = M.load_admin_cfg()
    eq("a key absent from the file comes from the defaults",
       cfg.get("first_run"), True)
    eq("the file's own value is not overwritten by the default",
       cfg.get("password_hash"), stored_form("hunter2"))

    write_admin_cfg(json.dumps({"password_hash": stored_form("hunter2"),
                                "first_run": False,
                                "capability_hashes": {"ssl_cert": "abc"}}))
    cfg = M.load_admin_cfg()
    eq("first_run from the file wins", cfg.get("first_run"), False)
    eq("a key the defaults do not know is kept",
       cfg.get("capability_hashes"), {"ssl_cert": "abc"})

    # The install-time default is built only when the key is absent, since
    # hashing is deliberately slow (ADR-0008) and this runs at import. Keyed on
    # absent rather than falsy: a file saying "password_hash": "" is saying
    # nothing opens this server, and the default would hand it back to "admin".
    write_admin_cfg(json.dumps({"first_run": False}))
    cfg = M.load_admin_cfg()
    eq("a file with no hash at all falls back to the install-time default",
       M.password_matches("admin", cfg["password_hash"]), True)
    write_admin_cfg(json.dumps({"password_hash": "", "first_run": False}))
    cfg = M.load_admin_cfg()
    eq("an empty hash is kept as it was", cfg["password_hash"], "")
    keep = M.ADMIN_CFG
    M.ADMIN_CFG = cfg
    eq("  and nothing opens the server, least of all the default password",
       [M._admin_password_ok("admin"), M._admin_password_ok("")],
       [False, False])
    M.ADMIN_CFG = keep


def check_admin_cfg_refuses_a_malformed_file():
    """A corrupt admin config must raise, not fall back to the default password.

    Falling back would reset the only credential this server has to its
    install-time value on a bad read, and nothing in the GUI would say so.
    """
    head("admin config refuses a malformed file")
    write_admin_cfg("{ this is not json")
    try:
        M.load_admin_cfg()
    except Exception as ex:
        ok("a malformed file raises (%s)" % type(ex).__name__)
    else:
        bad("a malformed admin_config.json loaded anyway - the admin password "
            "may have silently reverted to its install-time value")
    write_admin_cfg(json.dumps({"password_hash": stored_form("admin"),
                                "first_run": False}))
    M.ADMIN_CFG = M.load_admin_cfg()
