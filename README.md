# AssetManager

A lightweight IT asset tracking system built with Python and Tkinter.
Tracks equipment (laptops, phones, screens, etc.) as they are issued to and returned by team members.

## Components

| App | Description |
|-----|-------------|
| **AssetServer.exe** | REST API server (Flask + SQLite). Run on the server machine as Administrator. |
| **StorekeeperApp.exe** | Desktop GUI for logging asset transactions (issue / return). |
| **NotifierApp.exe** | System-tray notifier for team members — receive and confirm/reject transactions. |
| **AssetManager_Setup.exe** | Unified installer — run on any machine and choose what to install. |

## Quick Start

### 1. Server (run once on the server machine)
```
Right-click AssetServer.exe -> Run as Administrator
```
Default port: **8080**

Open firewall port:
```bat
netsh advfirewall firewall add rule name="AssetManager" dir=in action=allow protocol=TCP localport=8080
```

### 2. Storekeeper App
Run `AssetManager_Setup.exe` and choose **Storekeeper App**.
Enter the server URL when prompted: `http://asset-server:8080`

### 3. Notifier App (each team member)
Run `AssetManager_Setup.exe` and choose **Notifier App**.
Enter your name and the server URL.

## Features

- **Auto-fill** — type an asset number or serial number and the model/type fills automatically from `asset_lookup.xlsx`
- **Duplicate protection** — blocks submitting an asset that already has a pending transaction
- **Excel export** — full transaction history with charts and summary sheet
- **Engineer notifications** — real-time popup with Confirm / Reject buttons
- **Admin controls** — change password, host, and port from the server UI

## Asset Lookup File

Edit `asset_lookup.xlsx` in the server folder to add your assets:

| Asset No. | Serial No. | Model | Type |
|-----------|------------|-------|------|
| AT-1001   | SN-A1001   | Dell Latitude 5530 | Laptop |
| AT-1002   | SN-A1002   | HP EliteBook 840   | Laptop |

Supported types: `Laptop`, `Desktop`, `Mobile`, `Tablet`, `Screen`, `UPS`, `Server`, `Cisco Phone`, `Printer`, `Scanner`, `Switch`

## Build from Source

```bat
build.bat
```
Requires Python 3.10+ and PyInstaller.

## Default Credentials

| Setting | Default |
|---------|---------|
| Admin password | `admin` |
| Server port | `8080` |
| Server URL | `http://asset-server:8080` |

> Change the admin password on first login via the server UI.

## License
MIT
