<#
.SYNOPSIS
    Stage what a client install consists of - as a zip an engineer unpacks, or
    into a directory for package.ps1 to build AssetManager_Setup.exe around.

.DESCRIPTION
    One list of files, two ways out of here. The list is the payload: the app's
    sources, applaunch.py, common.py, ui_kit.py, the launcher and the vendored
    lib\. Nothing in it is an executable of ours - what Windows runs is a
    signed pythonw.exe with a .pyw file as its argument (rule 12).

    -App <name>   writes dist\<version>\<App>-<version>.zip, which also
                  carries installer.py and run_installer.pyw so the unpacked
                  folder can install itself, plus a manifest and a README.
                  Left out, it writes that zip for BOTH apps - a release
                  needs both and asking for them one at a time is a step to
                  forget, which is a server advertising a client package it
                  does not hold. Each zip is still one app's: the member
                  list is built per zip, not once and shared.

    -StageTo <dir>  copies both client apps' payloads into <dir> and stops
                  there: no zip, no manifest, no README, and none of the
                  vehicle above. package.ps1 calls this and hands the result to
                  PyInstaller as AssetManager_Setup.exe's data, which is the
                  first-install channel - the exe IS the installer, so
                  installer.py inside its own payload would be a second copy of
                  itself.

    Both apps rather than one on a -StageTo run because installer.py picks
    which to install by looking at what sits beside it (_payload_mode), so one
    installer offering a choice needs both sets present.

    This is the only implementation of that list. package.ps1 calls it rather
    than holding a copy, because a module added to one copy and not the other
    is a client that installs and then cannot import.

    No certificate is shipped, by either route. A client with no ssl_cert.pem
    fetches GET /cert on first contact, shows the SHA-256 fingerprint and pins
    it only if a person accepts it (ADR-0010, rule 1). The quiet channel is
    still there for an admin who would rather nobody read a fingerprint down a
    phone: a copy of ssl_cert.pem placed next to the installer, which
    installer.py prefers over anything built in - so it is a file an admin
    drops beside a release rather than a decision taken at build time on a
    machine that may be holding an older copy than the server binds.

    Run tools/vendor.ps1 -Role client first. It is not run from here so that
    one vendored lib can be reused across both routes and a slow pip install is
    not repeated per app.

    The server is deliberately not here. A source-mode server is installed by
    install-iis.ps1 and updated by update.ps1; the Windows Service verbs need
    pywin32's pythonservice.exe, which is an unsigned executable that vendor.ps1
    strips out on purpose, and IIS is the supported host regardless (ADR-0001).

.PARAMETER App
    notifier or storekeeper. The zip route. Omitted, both are bundled, one
    zip each.

.PARAMETER StageTo
    A directory to copy both apps' payloads into instead of building a zip. It
    must not already hold anything: a leftover module from an older pin merged
    into a fresh payload is exactly the sort of thing that only shows up on an
    engineer's laptop.

.PARAMETER LibDir
    The vendored client dependencies. Defaults to lib-client\ in the repo root,
    which is where vendor.ps1 -Role client writes them.

.PARAMETER DistDir
    The ship root for the zip route. Defaults to dist\ in the repo root; the
    zip is written to dist\<version>\ under it, the version being this app's
    own APP_VERSION.

.PARAMETER AllowDirty
    Stage from a dirty tree. Local testing only; a zip's manifest is marked.

.EXAMPLE
    .\vendor.ps1 -Role client -Clean
    .\bundle-client.ps1 -App notifier
.EXAMPLE
    .\bundle-client.ps1
.EXAMPLE
    .\bundle-client.ps1 -StageTo C:\Temp\payload
#>
[CmdletBinding(DefaultParameterSetName = "Bundle")]
param(
    # Not mandatory: no -App is "both", which is what a release wants.
    [Parameter(ParameterSetName = "Bundle")]
    [ValidateSet("notifier", "storekeeper")]
    [string] $App,

    [Parameter(Mandatory = $true, ParameterSetName = "Stage")]
    [string] $StageTo,

    [string] $LibDir,
    [string] $DistDir,
    [string] $ConfigPath,
    [switch] $AllowDirty
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

# The app-specific half. Everything else is shared. Extra is whatever that app
# imports besides its own Source - the Notifier's Pending decisions (#208) and
# its Remote Admin surface (#218), the Storekeeper's export (#219). None of
# them is in $Payload below because neither app has the other's concern, and
# the zip would carry and install a module it never imports. Source and
# Launcher stay exactly one name each: cascade-audit.py reads that pair to work
# out what a zip holds, and Extra is the list it adds to it.
$Apps = @{
    notifier = @{
        Name     = "NotifierApp"
        Source   = "notifier_app.py"
        Launcher = "run_notifier.pyw"
        Extra    = @("notifier_pending.py", "notifier_remote.py")
    }
    storekeeper = @{
        Name     = "StorekeeperApp"
        Source   = "storekeeper_app.py"
        Launcher = "run_storekeeper.pyw"
        Extra    = @("storekeeper_export.py", "storekeeper_bulk.py", "storekeeper_propose.py")
    }
}

# What an install consists of, beyond the app's own two files. common.py is the
# wire layer every client imports, ui_kit.py the shared button-and-theme kit the
# windows are built from, applaunch.py what puts lib\ on sys.path and holds a
# startup failure that pythonw.exe would otherwise swallow, and client_update.py
# what applies the NEXT zip this script writes - it has to be in this one, or an
# install can only ever be updated by running the installer again.
$Payload = @("applaunch.py", "common.py", "ui_kit.py", "client_update.py")

# How a zip installs itself - the vehicle, not the payload. An engineer unzips
# the folder and double-clicks run_installer.pyw, and installer.py copies the
# payload to the install directory. AssetManager_Setup.exe is built FROM
# installer.py, so a -StageTo run leaves these out: the exe is the vehicle.
$Vehicle = @("installer.py", "run_installer.pyw")

function Info ($m) { Write-Host "  $m" }
function Warn ($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Step ($m) { Write-Host "`n[*] $m" -ForegroundColor Cyan }
function Fail ($m) { Write-Host "`n[X] $m" -ForegroundColor Red; exit 1 }

$Staging  = [bool] $StageTo
# A staged payload serves one installer that offers both apps, so it carries
# both, in one directory. A zip is one app's - so naming no app means two
# zips rather than one zip holding two apps.
$Selected = if ($Staging -or -not $App) { @("notifier", "storekeeper") }
            else { @($App) }

# -- Settings ------------------------------------------------------------
Step "Resolving settings"

. (Join-Path $PSScriptRoot "_deploy.ps1")
Initialize-DeploySettings $ConfigPath $PSBoundParameters $PSScriptRoot

$LibDir  = Resolve-Setting "LibDir"  $LibDir  (Join-Path $Root "lib-client") "clientLibDir"
$DistDir = Resolve-Setting "DistDir" $DistDir (Join-Path $Root "dist")       "distDir"

Info "route     : $(if ($Staging) { "stage to $StageTo" }
                   else { "zip " + (($Selected | ForEach-Object { $Apps[$_].Name }) -join ', ') })"
Info "apps      : $($Selected -join ', ')"
Info "libDir    : $LibDir"

# -- Version ------------------------------------------------------------
Step "Reading APP_VERSION"

# Only what ships here and installer.py, which is either in the zip or is the
# exe being built around a staged payload. package.ps1 is what enforces that
# all four sources agree.
$versions = @{}
foreach ($src in @($Selected | ForEach-Object { $Apps[$_].Source }) + @("installer.py")) {
    $path = Join-Path $Root $src
    if (-not (Test-Path $path)) { Fail "missing source file: $src" }
    $m = [regex]::Match((Get-Content -Raw $path), '(?m)^APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"')
    if (-not $m.Success) { Fail "no APP_VERSION found in $src" }
    $versions[$src] = $m.Groups[1].Value
}
$distinct = @($versions.Values | Sort-Object -Unique)
if ($distinct.Count -ne 1) {
    Fail ("APP_VERSION disagrees:`n" +
         (($versions.GetEnumerator() | ForEach-Object { "    $($_.Key) = $($_.Value)" }) -join "`n"))
}
$Version = $distinct[0]
Info "version $Version"

# -- Working tree ------------------------------------------------------------
Step "Checking the working tree"

$porcelain = & git -C $Root status --porcelain
if ($LASTEXITCODE -ne 0) { Fail "git failed - is $Root a repository?" }
$dirty = [bool]$porcelain
if ($dirty -and -not $AllowDirty) {
    Fail ("working tree is dirty - commit or stash first so what ships matches a`n" +
          "commit:`n`n" + ($porcelain -join "`n") +
          "`n`n(use -AllowDirty for a local test build that must not be released)")
}
$commit = (& git -C $Root rev-parse HEAD).Trim()
Info "commit $($commit.Substring(0,12))$(if ($dirty) { '  (DIRTY)' })"

# -- Dependencies ------------------------------------------------------------
Step "Checking the vendored dependencies"

# The PYVER stamp and the no-.exe refusal are both in _deploy.ps1, because
# package.ps1 asks the same two questions of lib-server\ and a refusal written
# down twice is how one of the copies comes to be relaxed.
$PyVer    = Get-VendoredPyVer $LibDir "client"
$libFiles = @(Get-ChildItem $LibDir -Recurse -File)
Info "python $PyVer, $($libFiles.Count) files"

# -- Assemble ------------------------------------------------------------
Step "Assembling the payload"

# Asked once per artefact rather than built once and shared, because a zip
# is one app's: two zips off one map would each carry the other app's
# source and launcher. The staged payload is the case that takes both, one
# installer offering a choice needing both sets beside it (_payload_mode).
# $which rather than $apps for the reason $tmpDir below is not $staging:
# a variable name here is case-insensitive, so a parameter called $apps IS
# the $Apps table above, shadowed inside this function by an array of names
# that indexes to nothing.
function New-MemberMap ($which) {
    $map = [ordered]@{}
    foreach ($a in $which) {
        foreach ($f in @($Apps[$a].Launcher, $Apps[$a].Source) + $Apps[$a].Extra) {
            $p = Join-Path $Root $f
            if (-not (Test-Path $p)) { Fail "missing: $f" }
            $map[$f] = $p
        }
    }
    # The shared half, and - for a zip only - what installs it.
    foreach ($f in ($Payload + $(if ($Staging) { @() } else { $Vehicle }))) {
        $p = Join-Path $Root $f
        if (-not (Test-Path $p)) { Fail "missing: $f" }
        $map[$f] = $p
    }
    foreach ($f in $libFiles) {
        $rel = "lib/" + $f.FullName.Substring($LibDir.Length + 1).Replace('\', '/')
        $map[$rel] = $f.FullName
    }
    # Nothing named like a private key, and no executable of ours, whatever
    # gets added to the lists above later.
    foreach ($name in $map.Keys) {
        $leaf = [IO.Path]::GetFileName($name)
        if ($leaf -match '(?i)^ssl_key\.pem$|(?i)key\.pem$') {
            Fail "refusing to stage $name - a private key must never reach a client."
        }
        if ($leaf -match '(?i)\.exe$') {
            Fail "refusing to stage $name - source mode ships no executables."
        }
    }
    return $map
}

if ($Staging) {
    $members = New-MemberMap $Selected
    # A directory that already holds something is refused rather than merged
    # into: a leftover module from an older pin would be found by applaunch's
    # sys.path entry and shadow the new one, which is the sort of thing that
    # only shows up on an engineer's laptop.
    if (Test-Path $StageTo) {
        if (@(Get-ChildItem $StageTo -Force).Count) {
            Fail ("$StageTo already holds files, and a payload merged into an older`n" +
                  "    one ships whichever copy of a module was not overwritten.`n" +
                  "    Empty it or name a directory that does not exist.")
        }
    } else {
        New-Item -ItemType Directory -Path $StageTo -Force | Out-Null
    }
    foreach ($name in $members.Keys) {
        $dest = Join-Path $StageTo ($name -replace '/', '\')
        $destDir = Split-Path -Parent $dest
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
        Copy-Item $members[$name] $dest
    }
    Write-Host "`n[OK] staged $($members.Count) file(s) to $StageTo" -ForegroundColor Green
    Info "apps           : $($Selected -join ', ')"
    Info "python required: $PyVer"
    Info "version        : $Version$(if ($dirty) { '   (DIRTY - do not release)' })"
    return
}

# One artefact per selected app. The temp directory is deliberately not
# called $staging: PowerShell variable names are case-insensitive, so that
# is $Staging, and a second turn of this loop would read the path it holds
# as truthy and drop installer.py out of the payload.
foreach ($a in $Selected) {
    $Spec    = $Apps[$a]
    $members = New-MemberMap @($a)
    $tmpDir  = Join-Path ([IO.Path]::GetTempPath()) ("am-cli-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmpDir | Out-Null
    try {
        $hashes = [ordered]@{}
        foreach ($name in $members.Keys) {
            $dest = Join-Path $tmpDir ($name -replace '/', '\')
            $destDir = Split-Path -Parent $dest
            if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
            Copy-Item $members[$name] $dest
            $hashes[$name] = (Get-FileHash -Path $members[$name] -Algorithm SHA256).Hash.ToLower()
        }

        # mode and python_version are what tell a reader, and a future update
        # path, that this is not an exe package and which interpreter it needs.
        $manifest = [ordered]@{
            mode           = "source"
            app            = $a
            version        = $Version
            python_version = $PyVer
            launcher       = $Spec.Launcher
            git_commit     = $commit
            git_dirty      = $dirty
            built_at       = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            files          = $hashes
        }
        Write-JsonFile (Join-Path $tmpDir "manifest.json") $manifest

        $readme = @"
Asset Manager - $($Spec.Name) $Version

WHAT TO DO
  1. Install Python $PyVer if it is not already installed.
     Ask IT, or: winget install Python.Python.$PyVer
  2. Unzip this whole folder somewhere permanent, e.g. C:\AssetManager.
  3. Double-click run_installer.pyw and follow the prompts.
     If Windows asks which program to open it with, choose pythonw.exe.

  The installer copies these files to the folder you choose, writes
  config.json and puts a shortcut on your Desktop.

  The first time the app connects to an https server it shows you that
  server's fingerprint and asks you to confirm it. Check it against the
  value the IT team gives you before accepting; nothing is trusted until
  you do.

WHY THERE IS NO .EXE
  The apps used to ship as .exe files built with PyInstaller. They are not
  code-signed, so every build is a brand-new executable that no reputation
  service has seen, and Windows Defender's Attack Surface Reduction rules
  block or audit them. Here, the program Windows runs is pythonw.exe - part
  of your Python installation, signed by the Python Software Foundation -
  and our code is plain .py text files it reads.

IF IT DOES NOT START
  Look for launch.err.log next to run_installer.pyw. It records why.
  The usual cause is the wrong Python version: this bundle needs $PyVer
  exactly, because the bundled libraries contain compiled extensions.

  Send launch.err.log to the IT team.
"@
        Set-Content -Path (Join-Path $tmpDir "README.txt") -Value $readme -Encoding ascii

        $DistVersionDir = Join-Path $DistDir $Version
        if (-not (Test-Path $DistVersionDir)) {
            New-Item -ItemType Directory -Path $DistVersionDir | Out-Null
        }
        $dest = Join-Path $DistVersionDir "$($Spec.Name)-$Version.zip"
        if (Test-Path $dest) { Remove-Item $dest -Force }
        # [IO.Compression] rather than Compress-Archive: it handles the ~500
        # files in lib\ an order of magnitude faster and keeps the directory
        # structure.
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::CreateFromDirectory($tmpDir, $dest)

        $zipMb = [math]::Round((Get-Item $dest).Length / 1MB, 1)
        Write-Host "`n[OK] bundled $dest" -ForegroundColor Green
        Info "app            : $($Spec.Name) $Version$(if ($dirty) { '   (DIRTY - do not release)' })"
        Info "python required: $PyVer"
        Info "files          : $($members.Count)"
        Info "zip size       : $zipMb MB"
        Info "launcher       : $($Spec.Launcher)"
    }
    finally {
        Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
