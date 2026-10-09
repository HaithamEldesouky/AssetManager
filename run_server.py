"""Source-mode entry point for the server. See applaunch.py.

Plain .py, not .pyw, on purpose: this one has verbs. IIS HttpPlatformHandler
runs `python.exe run_server.py serve` and reads the child's stdout, and
tools/migrate.ps1 runs `run_server.py migrate` and reads its exit code -
pythonw.exe discards both. Launch it with pythonw.exe for the tray GUI, where
the console is the thing you do not want.

Arguments pass straight through, so every verb AssetServer.exe accepts works
here: migrate, serve, and the service verbs when pywin32 is importable.
"""

import applaunch

applaunch.bootstrap("server.py")
