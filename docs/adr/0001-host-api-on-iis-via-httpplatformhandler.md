---
status: accepted
---

# Host the API on IIS via HttpPlatformHandler

The API will be hosted by IIS on `asset-server` using **HttpPlatformHandler**, which launches `AssetServer.exe serve`, assigns it a loopback port and terminates TLS itself. The motivation is centrally managed certificates and standard IIS operational tooling, not process supervision — see the correction below.

## Correction to the first version of this ADR

The original text claimed the API's lifetime was tied to an interactive desktop session. **That was wrong.** `server.py` already contains a complete Windows Service implementation: `AssetManagerService` (a `win32serviceutil.ServiceFramework`) registered as `AssetManagerServer`, whose `SvcDoRun` calls `init_db()`, `_ensure_sample_lookup()` and `_run_flask()` with no Tkinter involved, plus `install/remove/start/stop/restart/debug` commands and a `_launched_by_scm()` session-0 check so one exe serves as both the service and the double-click GUI.

Session-independent hosting, auto-start and restart-on-failure were therefore already solved by the SCM. IIS was chosen anyway, deliberately, for certificate management and ops consistency — a weaker justification than the one first recorded, and worth knowing if this is ever revisited.

The error came from `CLAUDE.md`, which described `server.py` only as "Flask REST API + SQLite + Tkinter status GUI" and never mentioned the service. That documentation gap has been fixed.

## Considered Options

- **Keep the Windows service, no IIS.** Already works, one less moving part, but no central certificate management.
- **IIS as an HTTPS reverse proxy** in front of the running service. Would give central certs with almost no change — `server.py` untouched, GUI unaffected, service keeps running. Rejected in favour of IIS owning the process.
- **wfastcgi / true WSGI under IIS.** Needs application startup rewritten around a WSGI callable, for no gain over HttpPlatformHandler here.
- **HttpPlatformHandler** — chosen. IIS owns the process and TLS while the app stays an ordinary exe that can still be run by hand.

## Consequences

- **The Windows service must be disabled.** IIS starts its own copy of the exe, and both default to the configured port. Two listeners on 8081 is exactly what the exclusive-bind probe in `server.py` exists to prevent, so `tools/install-iis.ps1` stops and disables `AssetManagerServer`. Its `-KeepService` switch only warns; it does not make the combination safe.
- **A headless entry point was required.** Launched by IIS the exe is not in session 0 and receives no service verb, so it would have fallen through to GUI mode and hit the single-instance mutex. `server.py` now accepts `serve`, which binds `127.0.0.1` on `%HTTP_PLATFORM_PORT%`, skips TLS (IIS terminates it) and never creates a Tk root. Run by hand without that variable it serves the configured host and port with TLS as before.
- **Port 443 was unavailable when this ADR was written** — permanently blocked on this network — so the IIS site bound another HTTPS port and the install script rejected 443 outright. That was a network constraint, invisible in the code. **It stopped holding on 2026-09-12**, when the block was lifted: the refusal is gone from `server.py`, `tools/install-iis.ps1` and `tools/dev-run.ps1`, and 443 is now an ordinary port bounded only by the 1–65535 range check. The consequence is recorded rather than deleted because it is what the port choice was made under; the decision itself never rested on it — HttpPlatformHandler was chosen for owning the process and TLS, not for the port it binds.
- **The GUI is now admin-only.** With IIS serving, launching `AssetServer.exe` interactively finds the port in use and runs as a monitor-only front end, which is the existing behaviour and remains the way to reach the admin actions.
- **No idle timeout or periodic recycle on the app pool.** The background jobs — 24h auto-accept and its hourly sweep — only run while the process is alive, so a recycled or idled-out pool would silently stop confirming stale transactions.
- **`start` and `stop` stop being the exe's.** The service is disabled, so `AssetServer.exe start` is refused by the SCM - usefully, and in its own words: "The service cannot be started, either because it is disabled or because it has no enabled devices associated with it." `stop` answers "The service has not been started. (1062)", which is also true, the process that is serving being IIS's. Neither message is worth replacing. What replaces the *verbs* is `Start-WebAppPool` / `Stop-WebAppPool` on the app pool `install-iis.ps1` recorded in `iis.json`; `tools/update.ps1` cycles that same pool for the same reason. The Server GUI says so rather than leaving an operator to work it out: it reads `iis.json` through `_iis_host()`, its banner names the site and the pool, its tray Quit asks whether to close the window instead of offering to stop a server it cannot stop, and Change Host / Port says the port is the site binding. **What moved that binding was `tools/install-iis.ps1`, run by hand, until 069**: it is now `tools/bind-port.ps1`, the elevated half the console spawns when an Admin saves a new port, which binds the new port beside the old one and leaves both answering long enough for every online client to record the new one (ADR-0021). `install-iis.ps1 -Port` still moves it as part of a full install.
- **Clients are unaffected at the protocol level.** Only the port in the base URL changes, which is what the port-cascade mechanism and the client-side `last_known_port` fallback absorb.
