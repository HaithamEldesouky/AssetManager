<#
.SYNOPSIS
    Report or change the schema version of an assets.db.

.DESCRIPTION
    A thin wrapper over server.py's own migrate verb, reached either as
    `AssetServer.exe migrate` or, on a source install, as
    `python run_server.py migrate`. The engine itself lives in server.py because
    PowerShell has no SQLite support - neither 5.1 nor 7 ships a provider, and
    sqlite3.exe is not present on Windows - while server.py already imports
    sqlite3 and is on every machine being updated by definition.

    Schema state is SQLite's own PRAGMA user_version, so there is no bookkeeping
    table. A database predating migrations reads 0.

    A downgrade never drops a column: every insert in server.py names its
    columns and the xlsx archive is keyed on names, so an older build ignores
    columns it does not know about. Dropping them would destroy live data to
    satisfy a number nothing reads. A down() reverses indexes, constraints and
    data changes only.

    Every run backs up the database first unless -NoBackup is given. That backup
    is the only recovery path if a migration turns out to be wrong.

.PARAMETER TargetDir
    Install directory holding AssetServer.exe (or run_server.py), the database and
    migrations\. Read from installDir in deploy.json when not passed - the same
    directory the other deployment scripts call installDir.

.PARAMETER PythonExe
    The interpreter to run run_server.py with on a source install. Ignored when
    AssetServer.exe is present. Read from pythonExe in deploy.json; defaults to
    whatever `python` resolves to.

.PARAMETER ConfigPath
    A JSON file supplying TargetDir. Defaults to deploy.json next to this script,
    then deploy.json in the repo root. See tools/deploy.example.json. A parameter
    passed on the command line always wins over the file.

.PARAMETER Target
    Schema version to move to. Omit for status only.

.EXAMPLE
    .\migrate.ps1 -TargetDir C:\AssetManager
.EXAMPLE
    .\migrate.ps1 -TargetDir C:\AssetManager -Target 2
.EXAMPLE
    .\migrate.ps1 -TargetDir C:\AssetManager -Target 1 -DryRun
#>
[CmdletBinding()]
param(
    # Not Mandatory: may come from deploy.json instead, checked below.
    [string] $TargetDir,
    [int]    $Target,
    [string] $ConfigPath,
    [string] $PythonExe,
    # Not -Db: CmdletBinding gives -Debug the alias "db", and PowerShell refuses
    # to bind a parameter whose name collides with a common parameter alias.
    [string] $DbPath,
    [string] $MigrationsDir,
    [switch] $DryRun,
    [switch] $NoBackup
)

$ErrorActionPreference = "Stop"

function Info ($m) { Write-Host "  $m" }
function Fail ($m) { Write-Host "`n[X] $m" -ForegroundColor Red; exit 1 }

. (Join-Path $PSScriptRoot "_deploy.ps1")
Initialize-DeploySettings $ConfigPath $PSBoundParameters $PSScriptRoot
$TargetDir = Resolve-Setting "TargetDir" $TargetDir $null "installDir"
$PythonExe = Resolve-Setting "PythonExe" $PythonExe ""   "pythonExe"

if (-not $TargetDir) {
    Fail "No TargetDir. Pass -TargetDir, or set installDir in deploy.json."
}
if (-not (Test-Path $TargetDir)) { Fail "no such directory: $TargetDir" }
$TargetDir = (Resolve-Path $TargetDir).Path

$runner = Resolve-ServerRunner $TargetDir $PythonExe
if (-not $runner) {
    Fail ("neither AssetServer.exe nor run_server.py is in $TargetDir - one of them`n" +
          "    runs the migrations")
}
Info "engine: $($runner.Kind)"

# Not Join-Path: the install may have moved its database with db_path in
# server_config.json, and a status report or a migration against the default
# path would then create an empty database and report on that one instead.
if (-not $DbPath)        { $DbPath        = Resolve-DbPath $TargetDir }
if (-not $MigrationsDir) { $MigrationsDir = Join-Path $TargetDir "migrations" }

if (-not $PSBoundParameters.ContainsKey('Target')) {
    # Status: the exe prints JSON so it can be consumed here rather than parsed.
    $raw = & $runner.File @($runner.Prefix +
             @("migrate", "--db", $DbPath, "--dir", $MigrationsDir, "--status"))
    if ($LASTEXITCODE -ne 0) { Fail "status failed:`n$raw" }
    $s = $raw | ConvertFrom-Json
    Write-Host "`nDatabase   : $($s.db)"
    Write-Host "Exists     : $($s.db_exists)"
    Write-Host "Schema     : $(if ($null -ne $s.schema_version) { "v$($s.schema_version)" } else { 'n/a' })"
    Write-Host "Available  : v$($s.latest_available)  (migrations: $($s.migrations -join ', '))"
    if ($s.db_exists -and $s.schema_version -lt $s.latest_available) {
        Write-Host "`nBehind by $($s.latest_available - $s.schema_version) version(s). Run with -Target $($s.latest_available)." -ForegroundColor Yellow
    }
    return
}

$verb = @("migrate", "--db", $DbPath, "--dir", $MigrationsDir, "--target", $Target)
if ($DryRun)   { $verb += "--dry-run" }
if ($NoBackup) { $verb += "--no-backup" }

& $runner.File @($runner.Prefix + $verb)
if ($LASTEXITCODE -ne 0) { Fail "migration failed (exit $LASTEXITCODE)" }
Write-Host "`n[OK] schema is at v$Target" -ForegroundColor Green
