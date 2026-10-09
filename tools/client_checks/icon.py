r"""The app icon, on every client window and on the source-mode shortcut.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
import os

from client_checks.stage import (IN, NT, SK, STAGE, eq, head, quiesce, skip,
                                 tk_or_skip)


def check_every_client_window_carries_the_app_icon():
    """Each app's window is given the icon, and lets go of it when it closes.

    Every size goes over rather than one: Windows asks a window for a small
    icon and a large one and takes the nearest of what it was handed, and what
    it does with a single image is scale it with no filtering - which is what
    a title bar showing a crushed 64px icon looked like.

    What is asserted is the reference the window parks, because there is no
    `wm iconphoto` query form in Tk to read the icon back with - and that
    reference is the load-bearing half anyway. Tk does not own a PhotoImage:
    one nothing else holds is collected, the title bar goes blank a moment
    after it was set, and what the engineer reports is an icon that never
    worked rather than one that went.

    The release is asserted for the reason it was written. Held past
    `destroy()` the image outlives the Tcl interpreter, and the delete inside
    `tkinter.Image.__del__` then runs during interpreter shutdown, where
    `TclError` has been torn down to None and the `except` clause raises in its
    place: an "Exception ignored" traceback printed after this file's last
    line, which reads like a failure and is not one. It is exactly what this
    group ran into on the way in.

    Skipped where there is no pillow, which is the degradation rather than a
    gap: `app_icon` answering None is what lets an app with no pillow start.
    """
    head("every client window carries the app icon")
    tk = tk_or_skip()
    if tk is None:
        return
    import ui_kit

    if not ui_kit.HAS_PIL:
        skip("pillow is not installed - the icon degrades to none by design")
        return

    want = [(s, s) for s in ui_kit.ICON_WINDOW_SIZES]

    def held(win):
        photos = getattr(win, "_app_icon", None)
        return photos is not None and [(p.width(), p.height()) for p in photos]

    root = tk.Tk()
    SK.StorekeeperApp(root)
    eq("the Storekeeper window holds one image per window size", held(root),
       want)
    quiesce(root)
    eq("and lets them go with the window", getattr(root, "_app_icon", "unset"),
       None)

    app = NT.NotifierApp()
    eq("the Notifier's root holds them", held(app.root), want)
    quiesce(app.root)

    root = tk.Tk()
    IN.InstallerApp(root)
    eq("the installer window holds them", held(root), want)
    quiesce(root)

    # The badge is the Notifier's only way of saying something is waiting while
    # its popup is behind another window, so it has to be a different picture.
    eq("the Notifier's badge is not the plain icon",
       ui_kit.app_icon(64, badge=True).tobytes()
       != ui_kit.app_icon(64).tobytes(), True)

    real = ui_kit.HAS_PIL
    root = tk.Tk()
    try:
        ui_kit.HAS_PIL = False
        eq("with no pillow the drawing answers None", ui_kit.app_icon(64), None)
        eq("and the window is left with Tk's own icon rather than no window",
           ui_kit.set_window_icon(root), None)
        eq("and every window size is one the .ico carries, so the two agree",
           [s for s in ui_kit.ICON_WINDOW_SIZES
            if s not in ui_kit.ICO_SIZES], [])
    finally:
        ui_kit.HAS_PIL = real
        quiesce(root)


def check_the_source_mode_shortcut_carries_the_app_icon():
    """The Desktop shortcut gets an icon, and only where it needs one.

    A shortcut takes its icon from the exe it points at, so exe mode wants no
    file and no IconLocation. Source mode points at a signed pythonw.exe
    (rule 12), so with nothing said the engineer's Desktop carries Python's
    feather for an app that is not Python's - the one place that rule is
    visible to the person using it.

    The script is **read** rather than run: cscript would put a real shortcut
    on the Desktop of whatever machine runs this gate, and reading it is the
    check worth having anyway. It is one VBScript string literal per value, a
    single unescaped quote closes one early and fails the whole file to
    compile, and that failure is silent from where the installer stands -
    which is how source mode went release after release without ever creating
    a shortcut while the window said it had.
    """
    head("the source-mode shortcut carries the app icon")
    import ui_kit

    exe = IN._shortcut_vbs("C:\\App\\NotifierApp.exe", "Asset Notifier", "",
                           "C:\\App")
    eq("an exe-mode shortcut sets no IconLocation", "IconLocation" in exe,
       False)

    source = IN._shortcut_vbs("C:\\Py\\pythonw.exe",
                              "Asset Notifier \u2014 Brian Dawson",
                              '"C:\\App\\run_notifier.pyw"', "C:\\App",
                              "C:\\App\\app.ico")
    eq("a source-mode one points at the .ico beside the app",
       'oShortcut.IconLocation = "C:\\App\\app.ico,0"' in source, True)
    eq("and still carries the target, the argument and the directory",
       [line for line in source.splitlines()
        if line.startswith("oShortcut.Target")
        or line.startswith("oShortcut.Arguments")
        or line.startswith("oShortcut.Working")],
       ['oShortcut.TargetPath = "C:\\Py\\pythonw.exe"',
        'oShortcut.Arguments = """C:\\App\\run_notifier.pyw"""',
        'oShortcut.WorkingDirectory = "C:\\App"'])

    # The path is a value like any other here, and a directory may hold a
    # quote: unescaped it would close the literal and take the whole script
    # down with it, which is the failure this helper exists to have seen.
    odd = IN._shortcut_vbs("C:\\App\\a.exe", "App", "", "C:\\App",
                           'C:\\O"dd\\app.ico')
    eq("and the icon path is quoted like every other value",
       'oShortcut.IconLocation = "C:\\O""dd\\app.ico,0"' in odd, True)

    if not ui_kit.HAS_PIL:
        skip("pillow is not installed - the installer degrades to no icon")
        return

    from PIL import Image
    path = os.path.join(STAGE, "app.ico")
    eq("the installer's .ico is written", ui_kit.write_ico(path), True)
    with Image.open(path) as im:
        eq("carrying every size Windows asks an .ico for",
           sorted(im.ico.sizes()), [(s, s) for s in ui_kit.ICO_SIZES])

    real = ui_kit.HAS_PIL
    try:
        ui_kit.HAS_PIL = False
        eq("with no pillow it answers False rather than raising, so the "
           "install carries on with a plain shortcut",
           ui_kit.write_ico(os.path.join(STAGE, "none.ico")), False)
    finally:
        ui_kit.HAS_PIL = real


def check_the_tray_helper_builds_no_menu_without_pystray():
    """`run_tray_icon` (#271) degrades the way every pillow reader here does.

    `HAS_TRAY` forced False is the shape a machine with no `pystray` is in,
    the same override `HAS_PIL` gets above rather than an uninstall this gate
    cannot perform. What is asserted is that the helper returns `None` and
    touches none of its arguments - no `pystray.Menu`, no `on_ready`, no
    `icon.run()` - so a caller that skips its own tray thread on this same
    flag never reaches a blocking call at all.
    """
    head("the tray helper builds no menu without pystray")
    import ui_kit

    real = ui_kit.HAS_TRAY
    ready = []
    try:
        ui_kit.HAS_TRAY = False
        result = ui_kit.run_tray_icon(
            root=None, name="x", tooltip="x", image=None,
            items=[("caption", None), None, ("item", lambda: None)],
            on_ready=lambda icon: ready.append(icon))
        eq("returns None rather than a pystray.Icon", result, None)
        eq("and never calls on_ready", ready, [])
    finally:
        ui_kit.HAS_TRAY = real
