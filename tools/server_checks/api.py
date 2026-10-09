r"""The API harness itself.

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import os
from server_checks.stage import (IM, M, add_txn, eq, fresh_db, head,
                                 read_server_cfg, stored_form,
                                 write_server_cfg)



# ── the API harness itself ───────────────────────────────────────────────────

def check_api_is_reachable():
    """The seam every later ticket is tested through.

    Not a test of /health so much as proof the harness works: the app imports,
    the database is a scratch one, and a request gets a response without a
    socket or a port.
    """
    head("the API harness")
    db = fresh_db()
    add_txn(db)
    add_txn(db)
    c = M.app.test_client()

    r = c.get("/health")
    eq("GET /health answers", r.status_code, 200)
    eq("it counts the scratch database's rows", r.get_json().get("total"), 2)

    r = c.get("/stats")
    eq("GET /stats answers", r.status_code, 200)
    eq("both rows are Pending", r.get_json().get("pending"), 2)

    r = c.post("/admin/verify", json={"password": "nope"})
    eq("a wrong admin password is refused", r.get_json().get("valid"), False)


def check_server_config_endpoint():
    """POST /admin/server_config still saves, and still needs a restart.

    Its call into the save helper changed shape in this ticket. It is also the
    documented remote equivalent of the GUI's Server Settings, so the two
    have to agree about what a save does: write the file for the next start and
    leave the running server alone.

    **Driven over HTTPS since R1.** This endpoint takes the Change Host / Port
    capability password as well as the admin password now (ADR-0015), and a
    capability password is refused over plain `http://` before the password is
    examined - so the whole door is HTTPS-only, the admin password included,
    rather than being one rule for one credential and another for the other.
    `check_a_capability_password_is_never_accepted_over_http` is what asserts
    the refusal; this group asserts what the door does once it is open, so it
    knocks on the right one.
    """
    head("POST /admin/server_config")
    HTTPS = "https://localhost"
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False}
    write_server_cfg({"host": "0.0.0.0", "port": 8081, "ssl_enabled": True})
    c = M.app.test_client()
    host_before, port_before = M.HOST, M.PORT

    r = c.post("/admin/server_config", base_url=HTTPS,
               json={"password": "wrong", "host": "0.0.0.0", "port": 9000})
    eq("a wrong admin password is refused", r.status_code, 401)
    eq("and nothing was written", read_server_cfg().get("port"), 8081)

    for bad in (0, 70000):
        r = c.post("/admin/server_config", base_url=HTTPS,
                   json={"password": "admin", "host": "0.0.0.0",
                         "port": bad})
        eq("port %d is out of range and refused" % bad, r.status_code, 400)
        eq("and nothing was written", read_server_cfg().get("port"), 8081)

    # 443 was refused outright here until 2026-09-12, when it stopped being
    # blocked on this network. It is an ordinary port now, and the range bound
    # above is all that is left of the rule.
    r = c.post("/admin/server_config", base_url=HTTPS,
               json={"password": "admin", "host": "0.0.0.0", "port": 443})
    eq("port 443 is accepted", r.status_code, 200)
    eq("and it was written", read_server_cfg().get("port"), 443)

    r = c.post("/admin/server_config", base_url=HTTPS,
               json={"password": "admin", "host": "", "port": 9000})
    eq("an empty host is refused", r.status_code, 400)

    r = c.post("/admin/server_config", base_url=HTTPS,
               json={"password": "admin", "host": "192.0.2.100",
                     "port": 9000})
    eq("a valid change is accepted", r.status_code, 200)
    cfg = read_server_cfg()
    eq("the new host is saved", cfg.get("host"), "192.0.2.100")
    eq("the new port is saved", cfg.get("port"), 9000)
    eq("ssl_enabled survived the save", cfg.get("ssl_enabled"), True)
    eq("the running server is unchanged", (M.HOST, M.PORT),
       (host_before, port_before))


def check_port_change_refused_when_iis_served():
    """POST /admin/server_config refuses a port change only when undetected.

    HTTP_PLATFORM_PORT is set by HttpPlatformHandler on every IIS-fronted
    process, iis.json present or not (#267) - so it cannot be the whole
    signal. Refusing on it alone regressed 069's bind-port.ps1 flow: when
    iis.json *is* present, saving a new port is exactly how that flow starts
    (bind new beside old, hand it to clients through next_port, remove the
    old one), and the route must behave there exactly as it does on main.

    Only the undetected case - HTTP_PLATFORM_PORT set and iis.json absent,
    IIS set up by hand rather than through install-iis.ps1 - has no site on
    record to move, and only there must the route refuse with a 400 and
    /health hold next_port back (ADR-0001, ADR-0021).
    """
    head("POST /admin/server_config refuses a port change only when "
         "IIS-served and iis.json is absent")
    HTTPS = "https://localhost"
    M.ADMIN_CFG = {"password_hash": stored_form("admin"), "first_run": False}
    write_server_cfg({"host": "0.0.0.0", "port": 8081, "ssl_enabled": True})
    c = M.app.test_client()

    # Without HTTP_PLATFORM_PORT set, port change should be allowed
    r = c.post("/admin/server_config", base_url=HTTPS,
               json={"password": "admin", "host": "0.0.0.0", "port": 9000})
    eq("without HTTP_PLATFORM_PORT, port change is allowed", r.status_code, 200)
    eq("and the new port was written", read_server_cfg().get("port"), 9000)

    # Reset to 8081
    write_server_cfg({"host": "0.0.0.0", "port": 8081, "ssl_enabled": True})

    old_env = os.environ.get("HTTP_PLATFORM_PORT")
    real_iis_host = IM._iis_host
    try:
        # HTTP_PLATFORM_PORT set, iis.json absent - the undetected case.
        os.environ["HTTP_PLATFORM_PORT"] = "8081"
        IM._iis_host = lambda: None

        r = c.post("/admin/server_config", base_url=HTTPS,
                   json={"password": "admin", "host": "0.0.0.0",
                         "port": 9000})
        eq("undetected: port change is refused", r.status_code, 400)
        eq("undetected: with an error message", "error" in r.get_json(), True)
        eq("undetected: and the port was not written",
           read_server_cfg().get("port"), 8081)

        r = c.get("/health")
        eq("undetected: GET /health succeeds", r.status_code, 200)
        health = r.get_json()
        eq("undetected: does not advertise next_port",
           health.get("next_port"), None)
        eq("undetected: reports port_locked", health.get("port_locked"), True)

        # Host change should still be allowed - it does not touch the port.
        r = c.post("/admin/server_config", base_url=HTTPS,
                   json={"password": "admin", "host": "127.0.0.1",
                         "port": 8081})
        eq("undetected: host change is still allowed", r.status_code, 200)
        write_server_cfg({"host": "0.0.0.0", "port": 8081,
                          "ssl_enabled": True})

        # HTTP_PLATFORM_PORT set AND iis.json present - the 069 path. A port
        # change here must work exactly as it does off IIS: install-iis.ps1
        # having run is what makes the binding movable at all.
        IM._iis_host = lambda: {"site": "AssetManager",
                                "app_pool": "AssetManagerPool"}

        r = c.post("/admin/server_config", base_url=HTTPS,
                   json={"password": "admin", "host": "0.0.0.0",
                         "port": 9000})
        eq("069 path: port change is allowed", r.status_code, 200)
        eq("069 path: and the new port was written",
           read_server_cfg().get("port"), 9000)

        r = c.get("/health")
        eq("069 path: GET /health succeeds", r.status_code, 200)
        health = r.get_json()
        eq("069 path: advertises next_port", health.get("next_port"), 9000)
        eq("069 path: does not report port_locked",
           health.get("port_locked"), False)

    finally:
        if old_env is None:
            os.environ.pop("HTTP_PLATFORM_PORT", None)
        else:
            os.environ["HTTP_PLATFORM_PORT"] = old_env
        IM._iis_host = real_iis_host
        write_server_cfg({"host": "0.0.0.0", "port": 8081,
                          "ssl_enabled": True})
