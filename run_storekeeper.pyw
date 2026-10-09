"""Source-mode entry point for the Storekeeper app. See applaunch.py.

.pyw for the same reason as run_notifier.pyw: no console window behind the
Tkinter window.
"""

import applaunch

applaunch.bootstrap("storekeeper_app.py")
