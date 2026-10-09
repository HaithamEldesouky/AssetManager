r"""The server's own settings, round-tripped through server_config.json.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast

from server_checks.stage import (M, SRC_ALL, bad, eq, head, ok,
                                 read_server_cfg, write_server_cfg)



# ── server settings round-trip ───────────────────────────────────────────────

def check_settings_round_trip():
    """A save must never erase a setting some other save wrote.

    This is the failure the ticket exists to prevent: _save_server_cfg was fixed
    to host/port and the two SSL paths wrote the whole file themselves, so the
    first setting added beyond those two would have been dropped by whichever
    writer ran next. HTTPS would then be off after a restart with both cert
    files still on disk, which looks like nothing is wrong until a client fails
    to verify.
    """
    head("server settings round-trip")

    write_server_cfg({"host": "0.0.0.0", "port": 8081, "ssl_enabled": True,
                      "written_by_a_later_build": "keep me"})

    M._save_server_cfg(host="192.0.2.100", port=8082)
    cfg = read_server_cfg()
    eq("host saved", cfg.get("host"), "192.0.2.100")
    eq("port saved", cfg.get("port"), 8082)
    eq("ssl_enabled survived a host/port save", cfg.get("ssl_enabled"), True)
    eq("an unrecognised key survived a host/port save",
       cfg.get("written_by_a_later_build"), "keep me")

    M._save_server_cfg(ssl_enabled=False)
    cfg = read_server_cfg()
    eq("ssl_enabled saved", cfg.get("ssl_enabled"), False)
    eq("host survived an ssl_enabled save", cfg.get("host"), "192.0.2.100")
    eq("port survived an ssl_enabled save", cfg.get("port"), 8082)

    M._save_server_cfg(feed_limit=42)
    cfg = read_server_cfg()
    eq("an arbitrary new key can be saved", cfg.get("feed_limit"), 42)
    eq("host survived it", cfg.get("host"), "192.0.2.100")
    eq("ssl_enabled survived it", cfg.get("ssl_enabled"), False)


def check_one_writer_for_the_server_config():
    """Every write to server_config.json goes through the save helper.

    A source check, because the two paths that bypassed it were in GUI callbacks
    that no harness can reach: the certificate install and remove buttons each
    read-modify-wrote the file themselves. The behaviour check above cannot see
    a writer it never calls, so this makes a new one visible instead.
    """
    head("one writer for server_config.json")
    tree = ast.parse(SRC_ALL)
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "dump"):
            continue
        # json.dump(cfg, f) inside a `with open(SERVER_CFG_PATH...)` block
        # is only legitimate inside _save_server_cfg itself.
        for parent in ast.walk(tree):
            if not isinstance(parent, ast.FunctionDef):
                continue
            if node not in ast.walk(parent):
                continue
            if parent.name == "_save_server_cfg":
                continue
            seg = ast.get_source_segment(SRC_ALL, parent) or ""
            if "SERVER_CFG_PATH" in seg and "json.dump" in seg:
                offenders.append("%s (line %d)" % (parent.name, parent.lineno))
    offenders = sorted(set(offenders))
    if offenders:
        bad("these write server_config.json without the helper: %s"
            % ", ".join(offenders))
    else:
        ok("only _save_server_cfg writes server_config.json")
