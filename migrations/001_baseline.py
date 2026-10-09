"""Baseline: the schema init_db() already produces as of v2.0.0.

Both directions are deliberately empty. init_db() creates `transactions` and
`team_members` and ALTER-TABLEs in `rejection_reason`, `asset_number` and
`asset_model` for older databases, so there is nothing for an up() to do. This
migration exists only to stamp user_version = 1, giving later migrations a
known starting point instead of an unversioned database.
"""

NAME = "baseline"


def up(conn):
    pass


def down(conn):
    pass
