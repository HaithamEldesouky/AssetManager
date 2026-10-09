"""Source-mode entry point for the Notifier. See applaunch.py.

.pyw so a double-click and the Desktop shortcut both use pythonw.exe and the
tray app gets no console window. The shortcut names pythonw.exe explicitly
anyway, because the .pyw association is per-user and not guaranteed.
"""

import applaunch

applaunch.bootstrap("notifier_app.py")
