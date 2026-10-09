r"""The check groups tools/server-checks.py runs.

A package rather than one 18,758-line file since #221. stage.py builds the one
staging tree and holds the reporting helpers; every other module here is a
group of check_* functions over one subject. The entry point,
tools/server-checks.py, names the order they run in - nothing in this package
imports another group.
"""
