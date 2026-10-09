r"""admin_config.json's defaults, and the display settings it carries.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast

from server_checks.stage import (M, SRC_ALL, add_txn, bad, eq, fresh_db, head,
                                 ok, write_server_cfg)



# ── admin config ─────────────────────────────────────────────────────────────

def check_every_config_save_uses_keywords():
    """No caller of the save helper passes positionally.

    The helper took (host, port) and now takes **changes, so a call left
    positional is a TypeError at the moment the button is clicked. One of the
    two callers is a GUI callback, which is exactly where that class of bug goes
    unnoticed - the same way both Manage / Delete Records and Server Settings
    raised NameError on every click for a whole release.
    """
    head("every config save is by keyword")
    tree = ast.parse(SRC_ALL)
    bad_calls = []
    total = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_save_server_cfg"):
            total += 1
            if node.args:
                bad_calls.append("line %d" % node.lineno)
    if bad_calls:
        bad("_save_server_cfg called positionally at %s" % ", ".join(bad_calls))
    else:
        ok("all %d call(s) to _save_server_cfg pass keywords" % total)


def check_display_setting_bounds():
    """Both display settings are bounded, and refused with a reason.

    The refresh bound is the one that matters. That tick is also the liveness
    probe behind the banner, so a long interval would leave the window captioned
    LIVE over minute-old state - which is the defect this GUI was rebuilt to
    remove, reintroduced through a settings dialog.
    """
    head("display setting bounds")
    lo, hi = M.FEED_LIMIT_RANGE
    eq("feed length low bound accepted", M._validate_range(lo, lo, hi, "F")[0], lo)
    eq("feed length high bound accepted", M._validate_range(hi, lo, hi, "F")[0], hi)
    for v in (lo - 1, hi + 1, "x", "", None, 0, -5):
        n, err = M._validate_range(v, lo, hi, "Feed length")
        if err and n is None:
            ok("feed length %r refused: %s" % (v, err))
        else:
            bad("feed length %r was accepted as %r" % (v, n))

    lo, hi = M.REFRESH_SECS_RANGE
    eq("refresh low bound accepted", M._validate_range(lo, lo, hi, "R")[0], lo)
    eq("refresh high bound accepted", M._validate_range(hi, lo, hi, "R")[0], hi)
    for v in (lo - 1, hi + 1, "later"):
        n, err = M._validate_range(v, lo, hi, "Refresh interval")
        if err and n is None:
            ok("refresh %r refused: %s" % (v, err))
        else:
            bad("refresh %r was accepted as %r" % (v, n))

    if M.REFRESH_SECS_RANGE[1] <= 60:
        ok("the refresh ceiling is at most a minute (%ds)" % M.REFRESH_SECS_RANGE[1])
    else:
        bad("the refresh ceiling is %ds - long enough for the LIVE caption to lie"
            % M.REFRESH_SECS_RANGE[1])


def check_display_settings_persist():
    """They survive a restart, and do not disturb anything else."""
    head("display settings persist")
    write_server_cfg({"host": "0.0.0.0", "port": 8081, "ssl_enabled": True})
    cfg = M._load_server_cfg()
    eq("feed length defaults", cfg.get("feed_limit"), M.FEED_LIMIT_DEFAULT)
    eq("refresh defaults", cfg.get("refresh_secs"), M.REFRESH_SECS_DEFAULT)

    M._save_server_cfg(feed_limit=40, refresh_secs=15)
    cfg = M._load_server_cfg()
    eq("feed length round-trips", cfg.get("feed_limit"), 40)
    eq("refresh round-trips", cfg.get("refresh_secs"), 15)
    eq("host untouched", cfg.get("host"), "0.0.0.0")
    eq("ssl_enabled untouched", cfg.get("ssl_enabled"), True)

    M._save_server_cfg(host="192.0.2.100", port=8082)
    cfg = M._load_server_cfg()
    eq("a host/port save leaves feed length alone", cfg.get("feed_limit"), 40)
    eq("a host/port save leaves refresh alone", cfg.get("refresh_secs"), 15)


def check_feed_honours_its_limit():
    head("the feed honours its limit")
    db = fresh_db()
    for _ in range(25):
        add_txn(db)
    eq("a limit of 6 returns 6", len(M._gui_snapshot(6)[0]), 6)
    eq("a limit of 20 returns 20", len(M._gui_snapshot(20)[0]), 20)
    eq("a limit above the row count returns every row",
       len(M._gui_snapshot(200)[0]), 25)
