<#
.SYNOPSIS
    Build a release into dist\<version>\: the server's source package, the
    client's installer, or either alone.

.DESCRIPTION
    One command, two products, both written to dist\<version>\ and nowhere
    else:

      server   AssetManager-<version>.zip - server.py, server_gui.py,
               server_cert.py, register_assets.py, register_transactions.py,
               register_engineers.py, server_mail.py, server_sync.py,
               server_clients.py, server_log.py,
               server_archive.py, server_lookup.py,
               ui_kit.py,
               run_server.py, applaunch.py, the
               vendored lib-server\, the migrations, a manifest, ssl_cert.pem
               when one can be found, and
               tools\update.ps1 with the _deploy.ps1 it dot-sources. This is
               what tools/update.ps1 installs, and the copy it installs to
               <InstallDir>\tools\ is what applies the package after it. The
               updater is never needed to OBTAIN a release, only to apply one,
               so shipping it inside the release is not circular: the install
               before this one put it there.

      client   AssetManager_Setup.exe - what an engineer runs for a first
               install, carrying a SOURCE payload: both client apps, their
               launchers, applaunch.py, common.py, ui_kit.py and the vendored
               lib-client\. installer.py decides which payload it is shipping
               by looking at what sits beside it (_payload_mode) and never by a
               flag, so the payload being source is the whole of that decision.

    Nothing else is compiled. AssetServer.exe, StorekeeperApp.exe and
    NotifierApp.exe are not built at all any more: the server ships as source
    and so does every client. PyInstaller is used for exactly one thing,
    AssetManager_Setup.exe, because a first install has to be something a
    person can double-click - there is no vendored lib\ on the machine yet to
    run a launcher against. See rule 12 and rule 14 in CLAUDE.md.

    -Component selects what gets PRODUCED, not which exes get compiled, and
    each component's inputs are checked before either is produced. Neither may
    fail on the other's: -Component server used to stop on missing client
    exes, which made a server release wait on a client build for nothing.

    The client half is bundle-client.ps1's, called with -StageTo. There is one
    implementation of "what a client install consists of" and that script holds
    it; what this one adds is PyInstaller wrapping the result in something
    double-clickable. Two copies of that list would drift the first time a
    module is added to one of them.

    The private key (ssl_key.pem) is never packaged and is never written into
    dist\ at all. A package and an installer are both copied to engineers'
    laptops, so the key there would hand out the server's identity. That used
    to rest on it simply not being in a list; it is checked - a certificate
    that carries a private key is refused, and so is any staged file named like
    a key.

    Refuses to build from a dirty working tree. The manifest's commit is the
    only record of what a deployed build actually contains, and it is worthless
    if uncommitted edits went into it. -AllowDirty exists for local testing and
    stamps the manifest so such a package is recognisable and never released.

.PARAMETER Component
    What to produce: all (default), server or client.

      server   needs lib-server\  (vendor.ps1 -Role server)
      client   needs lib-client\  (vendor.ps1 -Role client), the app sources
               and PyInstaller

.PARAMETER ServerLibDir
    The vendored server dependencies that go into the source package. Defaults
    to lib-server\ in the repo root, which is where vendor.ps1 -Role server
    writes them.

.PARAMETER ClientLibDir
    The vendored client dependencies that go inside AssetManager_Setup.exe.
    Defaults to lib-client\, which is where vendor.ps1 -Role client writes
    them. Two directories rather than the one libDir this replaces: the two
    roles pin different packages, and one key could only ever name one of them.

.PARAMETER DistDir
    The ship root. Defaults to dist\ in the repo root; everything this script
    produces goes into dist\<version>\ under it, and that directory is the
    unit that gets carried to a machine.

.PARAMETER CertPath
    The public certificate the SERVER package ships, so an install that already
    serves HTTPS keeps a working copy of its own certificate through an update.
    Defaults to ssl_cert.pem in the repo root; where nothing is there,
    <installDir>\ssl_cert.pem from deploy.json is read, and then
    GET <baseUrl>/cert is tried.

    It is best effort and never fails the build. A client with no certificate
    is not stranded any more: it fetches GET /cert on first contact, shows the
    SHA-256 fingerprint and pins only if a person accepts it (ADR-0010, rule
    1). That is why -SelfSigned and -NoCert are gone. The first minted a pair
    whose private key sat on the build machine and had to be carried to the
    server before anything could verify, which is a way to strand a fleet; the
    second was a switch for a case that is now just the absence of a file.
    install-iis.ps1 -SelfSigned still mints and binds on the server, where the
    key belongs.

    The CLIENT installer ships no certificate at all. Every Storekeeper and
    Notifier pins by confirmation on its first connection. The quiet channel is
    still there for an admin who would rather nobody read a fingerprint down a
    phone, and it is a copy of ssl_cert.pem placed next to
    AssetManager_Setup.exe, which installer.py prefers over anything built in.

.PARAMETER AllowDirty
    Package from a dirty tree. Local testing only; the package is marked dirty
    and update.ps1 refuses to deploy it without its own override.

.PARAMETER ConfigPath
    A JSON file supplying DistDir, the two lib directories and CertPath.
    Defaults to deploy.json next to this script, then deploy.json in the repo
    root. See tools/deploy.example.json. A parameter passed on the command line
    always wins over the file. installDir and baseUrl are read from the file
    only - they describe a server, and this runs on the build machine.
    AllowDirty is deliberately not settable from the file: a forgotten line in
    a config would quietly make every package unreleasable.

.EXAMPLE
    .\vendor.ps1 -Role server -Clean
    .\vendor.ps1 -Role client -Clean
    .\package.ps1
.EXAMPLE
    .\package.ps1 -Component server
.EXAMPLE
    .\package.ps1 -Component client
#>
[CmdletBinding()]
param(
    [ValidateSet("all", "server", "client")]
    [string] $Component = "all",
    [string] $ServerLibDir,
    [string] $ClientLibDir,
    [string] $DistDir,
    [string] $CertPath,
    [switch] $AllowDirty,
    [string] $ConfigPath
)

$ErrorActionPreference = "Stop"

$Root       = Split-Path -Parent $PSScriptRoot
$MigrateDir = Join-Path $Root "migrations"

$VersionedSources = @("server.py", "storekeeper_app.py", "notifier_app.py", "installer.py")

# What the server package ships. No client app: an engineer's laptop is served
# by AssetManager_Setup.exe, and a headless IIS worker has no use for pystray
# or a Tkinter form.
$SourceFiles = @("server.py", "server_gui.py", "server_cert.py", "register_assets.py", "register_transactions.py", "register_engineers.py", "server_mail.py", "server_sync.py", "server_clients.py", "server_log.py", "server_archive.py", "server_lookup.py", "server_iis.py", "gui_assets.py", "gui_backup.py", "gui_clients.py", "gui_log.py", "gui_mail.py", "gui_proposals.py", "gui_records.py", "gui_settings.py", "gui_users.py", "ui_kit.py", "run_server.py", "applaunch.py")
# And nothing beside them. config.json was staged here as an "extra" until #108:
# a gitignored, per-machine *client* file - server_url, current_user, client_id -
# that the server never reads at all. Being ignored, git status does not report
# it, so the dirty-tree refusal below cannot see it either, and a payload with it
# in is not the one the manifest's commit describes; two machines building one
# version produced two different zips stamped the same. Every name staged into a
# package is a file git tracks, which cascade-audit.py holds both scripts to.
# ssl_cert.pem has a step of its own below, and ssl_key.pem never travels.

# The updater travels with the release it will be used to apply. _deploy.ps1 is
# not optional beside it: update.ps1 dot-sources it for Resolve-Setting,
# Resolve-ServerRunner, Resolve-DbPath, Test-CanPrompt and the JSON helpers, and
# a server has no checkout to find it in. Nothing else from tools\ ships -
# install-iis.ps1 is run once by hand from a copied tools\ directory, and
# migrate.ps1 is a wrapper round a verb server.py carries anyway.
$ToolFiles   = @("tools/update.ps1", "tools/_deploy.ps1")

$ProduceServer = ($Component -eq "all" -or $Component -eq "server")
$ProduceClient = ($Component -eq "all" -or $Component -eq "client")

function Info ($m) { Write-Host "  $m" }
function Warn ($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Step ($m) { Write-Host "`n[*] $m" -ForegroundColor Cyan }
function Fail ($m) { Write-Host "`n[X] $m" -ForegroundColor Red; exit 1 }

function Ensure-Vendored ([string] $dir, [string] $role) {
    <#
        Vendors $role where $dir holds nothing vendor.ps1 produced, so a first
        build on a fresh checkout is one command rather than a refusal naming
        the command to run next. Get-VendoredPyVer printed that command
        already; this runs it.

        Absent or unstamped only. A lib that is there and carries its PYVER is
        left exactly alone, because vendoring is deliberately not folded into
        packaging - bundle-client.ps1 says why, one vendored lib serving both
        client bundles and pip being slow - and there is no staleness check
        here to decide a present one has gone out of date. So an ordinary
        release run costs what it always cost: nothing.

        -Clean, because the state this repairs other than an absent directory
        is a half-written one, which is what an interrupted pip run leaves and
        what pip installing over the top of would keep.

        A stray .exe is deliberately NOT repaired, though vendor.ps1 would
        strip it: a lib that has grown an executable is a directory something
        other than vendor.ps1 wrote into, and rule 12's refusal is a thing to
        be read rather than a build step to be re-run past. Get-VendoredPyVer
        still makes that one.

        Which roles reach here is $ProduceServer / $ProduceClient, so
        -Component server never vendors the client and never fails on it.
    #>
    if ((Test-Path $dir) -and (Test-Path (Join-Path $dir "PYVER"))) { return }

    Info "no vendored lib at $dir - vendoring $role first"
    & (Join-Path $PSScriptRoot "vendor.ps1") -Role $role -OutDir $dir -Clean
    if ($LASTEXITCODE -ne 0) {
        Fail "vendor.ps1 -Role $role failed with exit code $LASTEXITCODE"
    }
    # Not trusted beyond that: a .ps1 that returns without calling exit leaves
    # $LASTEXITCODE at whatever the last native command set. What holds the
    # result is Get-VendoredPyVer at the call site, which is the same check
    # every other caller of a vendored lib here is held to.
}

# -- Settings ------------------------------------------------------------
Step "Resolving settings"

. (Join-Path $PSScriptRoot "_deploy.ps1")
Initialize-DeploySettings $ConfigPath $PSBoundParameters $PSScriptRoot

$DistDir      = Resolve-Setting "DistDir"      $DistDir      (Join-Path $Root "dist")         "distDir"
$CertPath     = Resolve-Setting "CertPath"     $CertPath     (Join-Path $Root "ssl_cert.pem") "certPath"
$ServerLibDir = Resolve-Setting "ServerLibDir" $ServerLibDir (Join-Path $Root "lib-server")   "serverLibDir"
$ClientLibDir = Resolve-Setting "ClientLibDir" $ClientLibDir (Join-Path $Root "lib-client")   "clientLibDir"
Info "component : $Component"
Info "distDir   : $DistDir"

# Keys this script used to read and no longer does. A deploy.json still
# carrying one would have it read by nothing and say nothing about it, which is
# a build quietly writing somewhere - or reading from something - other than
# what the file in front of you says.
$DeadKeys = [ordered]@{
    outputDir  = "distDir"
    packageDir = "distDir"
    libDir     = "serverLibDir and clientLibDir, which are two directories now"
}
foreach ($dead in $DeadKeys.Keys) {
    if ($DeployConfig -and "$($DeployConfig.$dead)".Trim()) {
        Warn "deploy.json sets $dead, which nothing reads now - it is $($DeadKeys[$dead])."
    }
}

# -- Version ------------------------------------------------------------
Step "Reading APP_VERSION"

# All four must agree: a client compares its own APP_VERSION against the
# server's /version to decide whether to prompt, so a mismatch makes some apps
# prompt forever and others never. All four are read whichever component is
# being produced, because the number is a fact about the release rather than an
# input of either half.
$versions = @{}
foreach ($src in $VersionedSources) {
    $path = Join-Path $Root $src
    if (-not (Test-Path $path)) { Fail "missing source file: $src" }
    $m = [regex]::Match((Get-Content -Raw $path), '(?m)^APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"')
    if (-not $m.Success) { Fail "no APP_VERSION found in $src" }
    $versions[$src] = $m.Groups[1].Value
}
# @() matters: Sort-Object -Unique collapses four identical strings to a bare
# string, whose .Count is 1 and whose [0] is its first character - so the
# package would be named "2" instead of "2.1.0".
$distinct = @($versions.Values | Sort-Object -Unique)
if ($distinct.Count -ne 1) {
    Fail ("APP_VERSION disagrees between sources:`n" +
         (($versions.GetEnumerator() | ForEach-Object { "    $($_.Key) = $($_.Value)" }) -join "`n"))
}
$Version = $distinct[0]
Info "version $Version (all four sources agree)"

# Everything this run produces goes here and nowhere else. It is known only
# now, because the version is part of the path - which is what makes the
# directory the unit that gets carried to a machine rather than a pile of
# builds sharing one folder.
$DistVersionDir = Join-Path $DistDir $Version
Info "writing to $DistVersionDir"

# -- Working tree ------------------------------------------------------------
Step "Checking the working tree"

$porcelain = & git -C $Root status --porcelain
if ($LASTEXITCODE -ne 0) { Fail "git failed - is $Root a repository?" }
$dirty = [bool]$porcelain
if ($dirty -and -not $AllowDirty) {
    Fail ("working tree is dirty - commit or stash before packaging so the manifest's`n" +
          "commit matches what is inside the package:`n`n" + ($porcelain -join "`n") +
          "`n`n(use -AllowDirty for a local test package that must not be released)")
}
$commit = (& git -C $Root rev-parse HEAD).Trim()
Info "commit $($commit.Substring(0,12))$(if ($dirty) { '  (DIRTY)' })"

# -- Prerequisites ------------------------------------------------------------
Step "Checking prerequisites ($Component)"

# Both halves are checked here, before either is produced, and each is checked
# only against its own inputs. A server release that stops because lib-client\
# has not been vendored is the defect this section exists to prevent: it was
# the shape of the old -Component, which narrowed a compile and then packaged
# from a directory that had to hold everything anyway.
$ServerPyVer = $null
$ClientPyVer = $null

if ($ProduceServer) {
    $missing = @($SourceFiles + $ToolFiles |
                 Where-Object { -not (Test-Path (Join-Path $Root $_)) })
    if ($missing) { Fail "missing server source file(s): $($missing -join ', ')" }
    # No staleness check, and none to miss: the package contains the very files
    # the version was read from, so it cannot claim a version its payload does
    # not have. That check existed because an exe is a build artefact that can
    # lag its source, and no exe of the server is built any more.
    Ensure-Vendored $ServerLibDir "server"
    $ServerPyVer = Get-VendoredPyVer $ServerLibDir "server"
    Info ("server : $($SourceFiles.Count) source file(s), $($ToolFiles.Count) tool(s)," +
          " python $ServerPyVer from $ServerLibDir")
}

if ($ProduceClient) {
    # The app sources themselves are checked by bundle-client.ps1 as it stages
    # them, which happens before PyInstaller is asked for anything.
    Ensure-Vendored $ClientLibDir "client"
    $ClientPyVer = Get-VendoredPyVer $ClientLibDir "client"
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Fail ("python is not on PATH, and AssetManager_Setup.exe is the one thing`n" +
              "    here that still needs a compile - PyInstaller builds it.")
    }
    Info "client : python $ClientPyVer from $ClientLibDir"
}

# ============================================================================
#  The server package
# ============================================================================
if ($ProduceServer) {

# -- Schema version ------------------------------------------------------------
Step "Determining the schema version"

# The newest migration number, taken from the filenames. Contiguity is enforced
# by the engine inside the server; here we only need the highest number.
$migrationFiles = @(Get-ChildItem -Path $MigrateDir -Filter "*.py" -ErrorAction SilentlyContinue |
                    Where-Object { $_.Name -match '^(\d{3})_[a-z0-9_]+\.py$' } |
                    Sort-Object Name)
$SchemaVersion = 0
if ($migrationFiles) {
    $SchemaVersion = [int]([regex]::Match($migrationFiles[-1].Name, '^(\d{3})_').Groups[1].Value)
}
Info "schema v$SchemaVersion ($($migrationFiles.Count) migration file(s))"

# -- Certificate ------------------------------------------------------------
Step "Resolving the certificate for the server package"

# Best effort, and it does not fail the build. An install that already serves
# HTTPS has its own ssl_cert.pem and an update that carried none would leave it
# alone; what this ships is a way to move a renewed certificate onto the server
# with the rest of the update, and the case where none can be found is now an
# ordinary one rather than a refusal - a client with no certificate asks a
# person to confirm the fingerprint on first contact and pins it then
# (ADR-0010, rule 1), so nothing is stranded by its absence.
#
# Nothing is minted here. A certificate generated on the build machine has its
# private key on the build machine and nowhere near the key IIS binds, so
# shipping one without that key ever reaching the server leaves every client
# that pinned it unable to connect with no verified channel left to correct it
# over. install-iis.ps1 -SelfSigned generates and binds in one run on the
# server itself, which is the only place that trade is safe.

function Assert-PublicCertificate([string] $path, [string] $origin, [string] $removeOnFail) {
    # Run on whatever is about to be packaged, wherever it came from. A private
    # key in here would be copied to every machine that takes an update.
    # Checked rather than assumed: a "combined" pem holding both halves is a
    # normal thing to make, and the file is named by whoever runs this - or
    # served by whatever answered the GET below, which was not verified.
    $text = Get-Content -Raw $path
    # Fail exits, and the temp file a fetch wrote is removed by a finally that
    # is further down and has not been entered yet - so a refused fetch would
    # leave a private key sitting in %TEMP%. Removed here instead, on the one
    # path that can be holding one.
    if ($text -match "PRIVATE KEY") {
        if ($removeOnFail) { Remove-Item $removeOnFail -Force -ErrorAction SilentlyContinue }
        Fail ("$origin contains a PRIVATE KEY.`n" +
              "    A package is copied to whatever machine takes the update, so this`n" +
              "    would hand out the server's identity. Ship the public half only -`n" +
              "    what install-iis.ps1 writes to <InstallDir>\ssl_cert.pem already is.")
    }
    if ($text -notmatch "BEGIN CERTIFICATE") {
        if ($removeOnFail) { Remove-Item $removeOnFail -Force -ErrorAction SilentlyContinue }
        Fail "$origin is not a PEM certificate (no BEGIN CERTIFICATE block)."
    }
}

function Get-CertFromServer([string] $baseUrl) {
    # GET <baseUrl>/cert into a temp file; returns the path, or $null when the
    # server did not answer with one.
    #
    # Verification is relaxed for this one GET and nowhere else. A self-signed
    # server cannot be verified before its certificate is in hand, which is the
    # whole reason this fetch exists. It is acceptable only because nothing is
    # trusted on the strength of the connection: no credential crosses it, the
    # bytes are checked to be a public certificate and nothing else, and the
    # fingerprint is printed for the human at this console to check against the
    # server before the package reaches anything.
    $url = $baseUrl.TrimEnd('/') + "/cert"
    $out = Join-Path ([IO.Path]::GetTempPath()) ("am-cert-" + [Guid]::NewGuid().ToString("N") + ".pem")
    Info "fetching   : $url"

    # 5.1 has no -SkipCertificateCheck. The obvious substitute - assigning a
    # scriptblock to ServerCertificateValidationCallback - does not work here
    # and does not fail honestly: .NET invokes it on a thread with no runspace,
    # so it throws "There is no Runspace available", which surfaces as
    # "The underlying connection was closed: An unexpected error occurred on a
    # send" and reads as the server's fault. A compiled ICertificatePolicy has
    # no such problem. Both it and the protocol set are process-wide, so both
    # are put back afterwards rather than left off for the rest of the session,
    # and 5.1's default protocols predate TLS 1.2, which is all IIS negotiates.
    $savedPolicy   = $null
    $savedCallback = [Net.ServicePointManager]::ServerCertificateValidationCallback
    $savedProtocol = [Net.ServicePointManager]::SecurityProtocol
    try {
        if ($PSVersionTable.PSVersion.Major -ge 6) {
            Invoke-WebRequest -Uri $url -TimeoutSec 15 -UseBasicParsing `
                              -SkipCertificateCheck -OutFile $out
        } else {
            if (-not ("AmCertFetchPolicy" -as [type])) {
                Add-Type -TypeDefinition @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class AmCertFetchPolicy : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert,
                                      WebRequest req, int problem) { return true; }
}
"@
            }
            $savedPolicy = [Net.ServicePointManager]::CertificatePolicy
            [Net.ServicePointManager]::CertificatePolicy = New-Object AmCertFetchPolicy
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $url -TimeoutSec 15 -UseBasicParsing -OutFile $out
        }
    } catch {
        Warn "$url did not answer with a certificate: $($_.Exception.Message)"
        Remove-Item $out -Force -ErrorAction SilentlyContinue
        return $null
    } finally {
        if ($savedPolicy) { [Net.ServicePointManager]::CertificatePolicy = $savedPolicy }
        [Net.ServicePointManager]::ServerCertificateValidationCallback = $savedCallback
        [Net.ServicePointManager]::SecurityProtocol = $savedProtocol
    }
    return $out
}

$shipCert    = $null
$certOrigin  = $null
$fetchedCert = $null        # a temp file; removed in the finally below

# Neither of these is a parameter: an install directory and a base URL describe
# a server, and this script runs on the build machine. They are read from
# deploy.json alone, where install-iis.ps1 and update.ps1 already keep them.
$srvInstallDir = Resolve-Setting "InstallDir" $null $null "installDir"
$srvBaseUrl    = Resolve-Setting "BaseUrl"    $null $null "baseUrl"
$fromInstall   = $null
if ($srvInstallDir) { $fromInstall = Join-Path $srvInstallDir "ssl_cert.pem" }

if (Test-Path $CertPath) {
    $shipCert   = (Resolve-Path $CertPath).Path
    $certOrigin = $shipCert
} else {
    Info "nothing at $CertPath"
    if ($fromInstall -and (Test-Path $fromInstall)) {
        # The certificate install-iis.ps1 actually bound. A plain file read, so
        # there is no connection here and nothing that has to be trusted.
        $shipCert   = (Resolve-Path $fromInstall).Path
        $certOrigin = $shipCert
    } elseif ($srvBaseUrl) {
        $fetchedCert = Get-CertFromServer $srvBaseUrl
        if ($fetchedCert) {
            $shipCert   = $fetchedCert
            $certOrigin = $srvBaseUrl.TrimEnd('/') + "/cert"
        }
    }
}

if ($shipCert) {
    Assert-PublicCertificate $shipCert $certOrigin $fetchedCert
    if ($fetchedCert) {
        # Nothing verified what answered that GET, so this is the check: compare
        # it with the server before the package is installed anywhere.
        Info "SHA-256    : $(Get-CertFingerprint $shipCert)"
        Info "             on the server, the same value comes from:"
        Info ("             `$c = New-Object " +
              "Security.Cryptography.X509Certificates.X509Certificate2 '<InstallDir>\ssl_cert.pem'")
        Info "             `$c.GetCertHashString('SHA256')"
    }
    Info "shipping   : $certOrigin"
} else {
    $triedInstall = if ($fromInstall) { $fromInstall } else { "(no installDir in deploy.json)" }
    $triedUrl     = if ($srvBaseUrl)  { $srvBaseUrl.TrimEnd('/') + "/cert" } else { "(no baseUrl in deploy.json)" }
    Warn "no certificate found, so this package ships none. Looked at:"
    Warn "  $CertPath"
    Warn "  $triedInstall"
    Warn "  $triedUrl"
    Warn "An install that already has ssl_cert.pem keeps it - an update writes"
    Warn "only what the package carries. A client with none asks a person to"
    Warn "confirm the fingerprint on first contact (ADR-0010). To ship one, point"
    Warn "-CertPath at the server's <InstallDir>\ssl_cert.pem, or set installDir"
    Warn "or baseUrl in deploy.json. A server with no certificate at all is what"
    Warn "install-iis.ps1 -SelfSigned is for; it mints and binds on the machine"
    Warn "clients talk to, so the key never leaves it."
}

# -- Assemble ------------------------------------------------------------
Step "Assembling the server package"

$libFiles = @(Get-ChildItem $ServerLibDir -Recurse -File)
Info "$($libFiles.Count) vendored file(s)"

$staging = Join-Path ([IO.Path]::GetTempPath()) ("am-pkg-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    $members = [ordered]@{}          # archive-relative name -> source path

    foreach ($f in $SourceFiles) { $members[$f] = Join-Path $Root $f }
    foreach ($f in $ToolFiles)   { $members[$f] = Join-Path $Root $f }
    foreach ($f in $libFiles) {
        $rel = "lib/" + $f.FullName.Substring($ServerLibDir.Length + 1).Replace('\', '/')
        $members[$rel] = $f.FullName
    }
    foreach ($f in $migrationFiles) { $members["migrations/" + $f.Name] = $f.FullName }
    if ($shipCert) { $members["ssl_cert.pem"] = $shipCert }

    # Belt and braces on the private key: the check above covers the file this
    # script was pointed at, this covers anything that ever gets added to the
    # lists above. And no executable of ours at all - rule 12, which is now the
    # whole of what a server package is rather than a mode of it.
    foreach ($name in $members.Keys) {
        $leaf = [IO.Path]::GetFileName($name)
        if ($leaf -match '(?i)^ssl_key\.pem$|(?i)key\.pem$') {
            Fail "refusing to package $name - a private key must never leave the server."
        }
        if ($leaf -match '(?i)\.exe$') {
            Fail "refusing to package $name - a server package ships no executables."
        }
    }

    $hashes = [ordered]@{}
    foreach ($name in $members.Keys) {
        $src  = $members[$name]
        $dest = Join-Path $staging ($name -replace '/', '\')
        $destDir = Split-Path -Parent $dest
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir | Out-Null }
        Copy-Item $src $dest
        $hashes[$name] = (Get-FileHash -Path $src -Algorithm SHA256).Hash.ToLower()
    }

    # mode is still written, and still read by update.ps1: an install made
    # before this ticket holds exes, and installing source over it leaves both
    # file sets in the directory, which it warns about rather than guessing at.
    $manifest = [ordered]@{
        mode           = "source"
        version        = $Version
        schema_version = $SchemaVersion
        python_version = $ServerPyVer
        git_commit     = $commit
        git_dirty      = $dirty
        built_at       = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        files          = $hashes
    }
    Write-JsonFile (Join-Path $staging "manifest.json") $manifest

    if (-not (Test-Path $DistVersionDir)) {
        New-Item -ItemType Directory -Path $DistVersionDir | Out-Null
    }
    # The -source suffix is dropped: it existed to tell this package from an
    # exe one, nothing has built an exe package since 061 (rule 14), and no
    # version number is shared between the two eras, so there is nothing left
    # for it to be distinguished from. update.ps1 still resolves the suffixed
    # name as well, for the releases written before this, and still refuses
    # when both exist for one version rather than guessing between them.
    $dest = Join-Path $DistVersionDir "AssetManager-$Version.zip"
    if (Test-Path $dest) { Remove-Item $dest -Force }
    # [IO.Compression] rather than Compress-Archive: the package carries roughly
    # a thousand small files and Compress-Archive is an order of magnitude
    # slower over them.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($staging, $dest)

    $zipMb = [math]::Round((Get-Item $dest).Length / 1MB, 1)
    Write-Host "`n[OK] packaged $dest" -ForegroundColor Green
    Info "payload        : source (python $ServerPyVer)"
    Info "version        : $Version$(if ($dirty) { '   (DIRTY - do not release)' })"
    Info "schema version : v$SchemaVersion"
    Info "commit         : $($commit.Substring(0,12))"
    Info "files          : $($members.Count)"
    Info "zip size       : $zipMb MB"
    Info "certificate    : $(if ($shipCert) { $certOrigin } else { 'none - clients pin on first contact (ADR-0010)' })"
}
finally {
    Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
    # A certificate fetched from the server was written outside the staging
    # directory, so it does not go with it.
    if ($fetchedCert) { Remove-Item $fetchedCert -Force -ErrorAction SilentlyContinue }
}

}   # end of the server package

# ============================================================================
#  The client installer
# ============================================================================
if ($ProduceClient) {

Step "Building AssetManager_Setup.exe"

# The payload is staged by bundle-client.ps1, which is the one implementation
# of what a client install consists of. Called rather than copied: the list of
# files an engineer's machine needs is the same list whether it arrives as that
# script's zip or inside this installer, and two copies of it would drift the
# first time a module is added to one.
$payload = Join-Path ([IO.Path]::GetTempPath()) ("am-payload-" + [Guid]::NewGuid().ToString("N"))
try {
    # A hashtable, because splatting an ARRAY binds positionally: the string
    # "-StageTo" would then arrive as the value of the first parameter. Only a
    # hashtable splat binds by name. And not $args: that is an automatic
    # variable in every script scope.
    $stageArgs = @{ StageTo = $payload; LibDir = $ClientLibDir }
    if ($AllowDirty) { $stageArgs["AllowDirty"] = $true }
    if ($ConfigPath) { $stageArgs["ConfigPath"] = $ConfigPath }
    & (Join-Path $PSScriptRoot "bundle-client.ps1") @stageArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "bundle-client.ps1 -StageTo failed with exit code $LASTEXITCODE"
    }
    # Checked rather than trusted to the exit code: a .ps1 that returns without
    # calling exit leaves $LASTEXITCODE at whatever the last native command set,
    # so the directory having a lib\ in it is the honest test that something
    # was staged.
    if (-not (Test-Path (Join-Path $payload "lib"))) {
        Fail "bundle-client.ps1 -StageTo left no payload at $payload"
    }

    # PyInstaller's scratch directory, in TEMP rather than in the repo: nothing
    # in it is releasable and dist\<version>\ is the only place that is. The
    # name is stable rather than per-run, because PyInstaller caches its
    # analysis here and a fresh directory every time would turn every rebuild
    # into a cold one.
    $workPath = Join-Path ([IO.Path]::GetTempPath()) "am-build"
    if (-not (Test-Path $workPath)) { New-Item -ItemType Directory -Path $workPath | Out-Null }

    # The build machine's own toolchain, not the pinned lists in
    # requirements-client.txt: that says what gets vendored into lib\ and
    # carries no pyinstaller. Only what installer.py's own imports need -
    # requests through common.py, pillow for the icon ui_kit draws - since the
    # three app exes that needed flask, pystray and pywin32 are not built here
    # any more.
    Info "dependencies"
    & python -m pip install requests pillow pyinstaller --quiet --upgrade-strategy only-if-needed
    if ($LASTEXITCODE -ne 0) { Fail "pip failed with exit code $LASTEXITCODE" }

    # The icon the exe is stamped with. Drawn from ui_kit.app_icon - the same
    # artwork the windows and the trays draw - rather than read from a committed
    # .ico, so the two cannot drift. It goes in the PyInstaller workpath because
    # it is scratch: nothing ships it, and the apps draw their own at runtime.
    $iconPath = Join-Path $workPath "app.ico"
    Info "app.ico"
    & python (Join-Path $PSScriptRoot "_devtools.py") "icon" $iconPath
    if ($LASTEXITCODE -ne 0) {
        Fail "could not draw app.ico - PyInstaller would stamp the exe with its own."
    }

    if (-not (Test-Path $DistVersionDir)) {
        New-Item -ItemType Directory -Path $DistVersionDir | Out-Null
    }

    # Every staged file at the root of the payload, and lib\ as one directory.
    # No ssl_cert.pem: a client with none pins by confirmation on first contact
    # (ADR-0010), and an admin who would rather it did not have to still puts a
    # copy next to this exe, which installer.py prefers over anything built in.
    $addData = @()
    foreach ($f in (Get-ChildItem $payload -File)) {
        $addData += @("--add-data", "$($f.FullName);.")
    }
    $addData += @("--add-data", "$(Join-Path $payload 'lib');lib")

    Info "AssetManager_Setup.exe"
    & python -m PyInstaller --noconfirm --onefile --windowed --uac-admin `
        --distpath $DistVersionDir --workpath $workPath --specpath $Root `
        --icon $iconPath --name "AssetManager_Setup" `
        @addData (Join-Path $Root "installer.py")
    if ($LASTEXITCODE -ne 0) { Fail "installer build failed with exit code $LASTEXITCODE" }

    Get-ChildItem -Path $Root -Filter "*.spec" -File -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue

    $setup = Join-Path $DistVersionDir "AssetManager_Setup.exe"
    if (-not (Test-Path $setup)) { Fail "PyInstaller reported success but $setup is not there." }
    $setupMb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
    Write-Host "`n[OK] built $setup" -ForegroundColor Green
    Info "payload        : source (python $ClientPyVer)"
    Info "version        : $Version$(if ($dirty) { '   (DIRTY - do not release)' })"
    Info "commit         : $($commit.Substring(0,12))"
    Info "staged files   : $(@(Get-ChildItem $payload -Recurse -File).Count)"
    Info "exe size       : $setupMb MB"
}
finally {
    Remove-Item $payload -Recurse -Force -ErrorAction SilentlyContinue
}

# The two client update packages, into the same dist\<version>\ this run is
# already writing. Not a step of its own for the operator to remember: what a
# client updates itself from is GET /download/client/<key>, which serves out of
# dist\ beside the installed server, and dist\<version>\ is the unit that gets
# carried to a machine - so a release directory holding the setup exe and not
# these two is a server that answers /version with `latest` and an empty
# `client_packages`, tells every client it is behind and offers it nothing but
# the browser. The runbook had this as its own step *after* the copy, which is
# the wrong order by construction: the zips were written on the build machine
# after the directory they belong in had already been carried over, and the
# step that is separate is the step that gets skipped.
#
# The same script in its other shape, which is what makes this one list rather
# than a second copy of it - and no -App, which writes both, a release needing
# both. After the exe rather than before, so a PyInstaller failure is not paid
# for after two zips have been built.
Step "Bundling the client update packages"
$zipArgs = @{ DistDir = $DistDir; LibDir = $ClientLibDir }
if ($AllowDirty) { $zipArgs["AllowDirty"] = $true }
if ($ConfigPath) { $zipArgs["ConfigPath"] = $ConfigPath }
& (Join-Path $PSScriptRoot "bundle-client.ps1") @zipArgs
if ($LASTEXITCODE -ne 0) {
    Fail "bundle-client.ps1 failed with exit code $LASTEXITCODE"
}
# Checked rather than trusted to the exit code, for the reason the staged
# payload above is: a .ps1 that returns without calling exit leaves
# $LASTEXITCODE at whatever the last native command set, and what is being
# asserted is the file sitting under the name server.py resolves it by.
foreach ($zipName in @("NotifierApp-$Version.zip", "StorekeeperApp-$Version.zip")) {
    $zipPath = Join-Path $DistVersionDir $zipName
    if (-not (Test-Path $zipPath)) {
        Fail "bundle-client.ps1 reported success but $zipPath is not there."
    }
    Info "$zipName : $([math]::Round((Get-Item $zipPath).Length / 1MB, 1)) MB"
}

}   # end of the client installer
