# Asset Manager

A lightweight internal IT asset-tracking system: a small Flask + SQLite server
with Tkinter desktop clients. It records which piece of equipment (laptops,
phones, screens, etc.) is issued to or returned by each team member, and has the
recipient confirm or reject each movement.

The apps run from source under a signed Python runtime (no PyInstaller `.exe`s);
the only binary shipped is the installer.

## Components

| App | What it is |
|-----|------------|
| **Asset Server** (`server.py`) | Flask REST API over SQLite, with a Tkinter admin console. One program, three modes: Windows Service, headless behind IIS, or interactive GUI. Runs on the server machine. |
| **Storekeeper App** (`storekeeper_app.py`) | Desktop client for logging movements in and out of the store — the form, history, Excel export and bulk/scan entry. |
| **Notifier** (`notifier_app.py`) | Each team member's system-tray client — receives a movement logged against them and Confirms or Rejects it, with a Dashboard and a remote-admin console. |
| **Installer** (`installer.py`) | Builds `AssetManager_Setup.exe`, the one binary shipped; it installs whichever component you pick and writes its `config.json`. |

The server is split into focused modules (`server_*.py`, `register_*.py`,
`gui_*.py`); the clients share one wire layer (`common.py`) and one UI kit
(`ui_kit.py`). See [CLAUDE.md](CLAUDE.md) and
[docs/reference/architecture.md](docs/reference/architecture.md) for the full map.

## Quick start

### Server
Install the **Asset Server** with `AssetManager_Setup.exe` (run as Administrator),
or run it from source. It listens on port **8081** (HTTP, or HTTPS with a
self-signed certificate). Default server URL: `https://asset-server:8081`.

Open the firewall port if needed:

```bat
netsh advfirewall firewall add rule name="AssetManager" dir=in action=allow protocol=TCP localport=8081
```

### Storekeeper App / Notifier
Run `AssetManager_Setup.exe`, choose the component, and enter the server URL when
prompted. Each Notifier is configured for one team member.

## Asset lookup

The list of known assets is held in the `assets` table and interchanged as an
`asset_lookup.xlsx` workbook (columns: **Asset Number, Serial Number, Asset Type,
Asset Model**). A fresh install seeds a small sample sheet; edit it from the
server console's **Manage Assets** window or by uploading an updated workbook.

Supported asset types: `Laptop`, `Desktop`, `Mobile`, `Tablet`, `Screen`, `UPS`,
`Server`, `Cisco Phone`, `Printer`, `Scanner`, `Switch`.

## Features

- **Auto-fill & validation** — a movement is validated against the lookup sheet on
  the server; the asset type and canonical identifiers are filled in automatically.
- **Confirm / Reject** — the team member who received an asset verifies each
  movement from the Notifier popup or Dashboard.
- **Excel export** — full transaction history with summary and charts.
- **Role-based console** — admin password plus delegable capability passwords for
  specific remote actions.
- **System Log** — every administrative act recorded, with retention bounds.
- **Backups & migrations** — point-in-time backup/restore and an idempotent
  schema-migration engine.

## Build from source

The build and release tooling lives in `tools/` (PowerShell + Python):

```powershell
py -3.12 tools\gate.py --all     # run the full verification suite
.\tools\package.ps1              # build AssetManager_Setup.exe and client packages
```

See [docs/runbooks/release.md](docs/runbooks/release.md) and
[docs/runbooks/source-mode.md](docs/runbooks/source-mode.md).

## Default credentials

| Setting | Default |
|---------|---------|
| Admin password | `admin` (change it on first login from the server console) |
| Server port | `8081` |
| Server URL | `https://asset-server:8081` |

## Documentation

Reference material, architecture decisions (ADRs), runbooks and the development
tickets are under [docs/](docs/). Start from [CLAUDE.md](CLAUDE.md).

## License

MIT
