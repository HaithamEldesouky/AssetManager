r"""The check groups tools/client-checks.py runs.

A package rather than one 8,980-line file since #238, modelled on
tools/server_checks/. stage.py builds the one staging tree and holds the
reporting helpers and the Tk helpers the window groups measure with; every
other module here is a group of check_* functions over one subject. The entry
point, tools/client-checks.py, names the order they run in - nothing in this
package imports another group.
"""
