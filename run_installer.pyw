"""Source-mode entry point for the installer. See applaunch.py.

This is what an engineer runs from a client bundle: pythonw.exe with a .pyw
argument, in place of AssetManager_Setup.exe. The installer itself decides
whether it is shipping exes or sources by looking at what sits beside it
(_payload_mode), so the same installer.py serves both.
"""

import applaunch

applaunch.bootstrap("installer.py")
