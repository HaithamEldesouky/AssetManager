<#
.SYNOPSIS
    Install and configure the Asset Manager server under IIS using HttpPlatformHandler.

.DESCRIPTION
    Hosts AssetServer.exe as an IIS site (see docs/adr/0001). IIS owns the process
    lifetime and terminates TLS; the exe runs headless via its "serve" argument and
    binds the loopback port IIS assigns in %HTTP_PLATFORM_PORT%.

    This DISABLES the AssetManagerServer Windows service. Both host the same Flask
    app on the same configured port, and the exclusive-bind probe in server.py exists
    precisely to stop two listeners fighting over 8081. Under IIS the service must not
    run; use -KeepService only if you have moved the service to a different port.

.PARAMETER ConfigPath
    A JSON file supplying any of these settings, so a cutover is not a long command
    line retyped from a runbook. Defaults to deploy.json next to this script, then
    deploy.json in the repo root. See tools/deploy.example.json. A parameter passed
    on the command line always wins over the file.

.PARAMETER InstallDir
    Directory holding AssetServer.exe. Also where the database (unless db_path
    moves it), admin_config.json and
    the lookup sheet live, so the app pool identity needs write access to it.
    Required: from the command line, the config file, or answered at the
    prompt on an interactive run.

.PARAMETER Port
    HTTPS port for the IIS site binding.
    Required: from the command line, the config file, or answered at the
    prompt on an interactive run.

.PARAMETER SiteName
    Name of the IIS site. Defaults to AssetManager, and is offered as a prompt on
    an interactive run so the operator is not left to find it in IIS Manager
    later.

.PARAMETER AppPoolName
    Name of the application pool. Defaults to AssetManagerPool, and is offered as
    a prompt for the same reason as SiteName.

.PARAMETER SelfSigned
    Generate the certificate here instead of supplying one. Not needed on a
    first-time setup: where no source is given at all, InstallDir holds no
    ssl_cert.pem and the site has nothing bound, one is generated anyway and
    the run says so. An existing certificate is never regenerated, so any of
    those three failing leaves the "Give a certificate source" refusal standing
    -- passing this switch is what asks for a new one over an old one, and it
    warns naming both fingerprints when it does. This is what the server
    already does -- the clients pin ssl_cert.pem rather than trusting a CA -- so it
    needs no IT involvement. The generated certificate carries CA:TRUE and both DNS
    and IP SANs, because each client loads it as its own trust anchor and urllib3
    still asserts the SAN. Names come from -CertDnsNames/-CertIpAddress, from
    certDnsNames/certIpAddress in the config file, or from the prompt on an
    interactive run, and default to this machine's own identity.

.PARAMETER CertDnsNames
    DNS names for the -SelfSigned certificate: the SANs, and the first of them is
    also the subject. Defaults to this machine's computer name, its FQDN where it
    has a domain suffix, and localhost -- not to one deployment's literals, because
    a certificate minted for somebody else's server carries a SAN urllib3 asserts
    and the client that pinned it then fails closed. Offered as a prompt on an
    interactive -SelfSigned run. Ignored without -SelfSigned.

.PARAMETER CertIpAddress
    The IPAddress SAN for the -SelfSigned certificate. Defaults to this machine's
    own IPv4 and is offered as a prompt for the same reason. Where none can be
    determined, or it is passed or answered empty, no IPAddress SAN is written at
    all: an absent one costs a client configured by address, a wrong one costs
    every client. Ignored without -SelfSigned.

.PARAMETER PythonExe
    The interpreter to host with on a source install - the one whose run_server.py
    is in InstallDir. Ignored when AssetServer.exe is present. Read from
    pythonExe in deploy.json; defaults to whatever `python` resolves to. The
    resolved full path goes into web.config, because the app pool identity does
    not necessarily share this shell's PATH.

.PARAMETER CertThumbprint
    Thumbprint of a certificate already in LocalMachine\My. Use this in preference to
    -PfxPath so the private key is never handled in the clear.

.PARAMETER PfxPath
    A .pfx to import into LocalMachine\My first. You will be prompted for its password
    interactively; it is never taken as a parameter, so it cannot land in the console
    history or a transcript. Under -WhatIf nothing is imported, so nothing is asked;
    where there is no console to ask on, this fails rather than hanging, and the answer
    is to import the .pfx by hand and pass -CertThumbprint.

.EXAMPLE
    .\install-iis.ps1 -SelfSigned                    # everything else from deploy.json

.EXAMPLE
    .\install-iis.ps1 -InstallDir C:\AssetManager -Port 8443 -CertThumbprint AB12...

.EXAMPLE
    .\install-iis.ps1 -InstallDir C:\AssetManager -Port 8443 -PfxPath C:\certs\sd.pfx -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    # Not Mandatory: any of these may come from the config file instead. They are
    # resolved and checked below, so a missing value still stops the script before
    # anything on the machine is touched.
    [string] $InstallDir,
    [int]    $Port,
    [string] $ConfigPath,
    [string] $PythonExe,
    [string] $CertThumbprint,
    [string] $PfxPath,
    [switch] $SelfSigned,
    [string[]] $CertDnsNames,
    [string] $CertIpAddress,
    [string] $SiteName,
    [string] $AppPoolName,
    [switch] $KeepService
)

$ErrorActionPreference = "Stop"

function Info  ($m) { Write-Host "  $m" }
function Step  ($m) { Write-Host "`n[*] $m" -ForegroundColor Cyan }
function Warn  ($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Fail  ($m) { Write-Host "`n[X] $m" -ForegroundColor Red; exit 1 }

# -- Settings ------------------------------------------------------------
Step "Resolving settings"

. (Join-Path $PSScriptRoot "_deploy.ps1")
Initialize-DeploySettings $ConfigPath $PSBoundParameters $PSScriptRoot

$InstallDir     = Resolve-Setting "InstallDir"     $InstallDir     $null
$Port           = [int](Resolve-Setting "Port"     $Port           0)
$CertThumbprint = Resolve-Setting "CertThumbprint" $CertThumbprint ""
$PfxPath        = Resolve-Setting "PfxPath"        $PfxPath        ""
$SiteName       = Resolve-Setting "SiteName"       $SiteName       "AssetManager"
$AppPoolName    = Resolve-Setting "AppPoolName"    $AppPoolName    "AssetManagerPool"
$PythonExe      = Resolve-Setting "PythonExe"      $PythonExe      ""
$SelfSigned     = Resolve-Switch  "SelfSigned"     $SelfSigned

# Certificate identity. The clients pin this certificate by file, but urllib3
# asserts the SAN regardless, so every name or address that could appear in a
# client's server_url has to be in it.
#
# Which is why the defaults are this machine's own identity and not one
# deployment's literals: a literal default mints a certificate for somebody
# else's server on every other machine, and since the SAN is asserted and the
# clients fail closed, a client that pinned that file cannot reach its server at
# all. That is also why both are asked about on an interactive run below -- this
# is the one setting here that strands every client if it is wrong.
function Get-MachineDnsNames {
    $names = @($env:COMPUTERNAME)
    # The FQDN only where the machine actually has a domain suffix.
    # Win32_ComputerSystem reports WORKGROUP for a machine that has none, and a
    # SAN naming COMPUTERNAME.WORKGROUP is a name nothing ever resolves.
    try {
        $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
        if ($cs.PartOfDomain -and $cs.Domain) {
            $names += "$($env:COMPUTERNAME).$($cs.Domain)"
        }
    } catch { }
    return ($names + "localhost")
}

function Get-MachineIPv4 {
    # Loopback and APIPA are never an address a client dials. Where nothing is
    # left this returns "" and no IPAddress SAN is written at all, which is the
    # deliberate answer: an absent SAN costs a client that was configured by
    # address, a wrong one costs every client, because urllib3 asserts what is
    # in the certificate whatever the client asked for.
    try {
        $addrs = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" })
    } catch {
        return ""
    }
    if (-not $addrs.Count) { return "" }
    # A server with two NICs has two answers. The address on the interface
    # carrying the default route is the one a client on another subnet arrives
    # over, so it wins; anything else here would be a coin toss.
    try {
        $viaDefault = @(Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction Stop |
            Sort-Object RouteMetric)
        if ($viaDefault.Count) {
            $onRoute = @($addrs | Where-Object { $_.InterfaceIndex -eq $viaDefault[0].InterfaceIndex })
            if ($onRoute.Count) { return $onRoute[0].IPAddress }
        }
    } catch { }
    return $addrs[0].IPAddress
}

$CertDnsNames  = @(Resolve-Setting "CertDnsNames"  $CertDnsNames  (Get-MachineDnsNames))
$CertIpAddress = "$(Resolve-Setting "CertIpAddress" $CertIpAddress (Get-MachineIPv4))"

# Elevation is checked here rather than in the preflight below, because the
# guards under it are only worth reading on a run that could have worked: an
# unelevated shell with no deploy.json used to fail naming a missing InstallDir,
# which is true but is not the reason it was never going to install anything. It
# also keeps the prompts below from asking four questions before that refusal.
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Fail "Run this from an elevated PowerShell prompt." }

# A setting passed on the command line is taken as given. Anything else is
# offered with the value resolved above as its default, so whoever is standing at
# this console sees what is about to happen without having to know deploy.json
# exists and go and find the example one. Enter accepts.
#
# Nothing is asked when there is nobody to answer - see Test-CanPrompt in
# _deploy.ps1 for what "nobody" means and why UserInteractive alone does not
# answer it. Where it says no, the guards below still fail, naming the setting.
$canPrompt = Test-CanPrompt $WhatIfPreference

function Read-Setting {
    param([string] $label, [string] $current, [bool] $given)

    if (-not $canPrompt -or $given) { return $current }
    while ($true) {
        $shown  = if ($current) { " [$current]" } else { "" }
        $answer = (Read-Host "  $label$shown").Trim()
        if ($answer)  { return $answer  }
        if ($current) { return $current }
        Warn "$label is required."
    }
}

function Read-Port {
    param([int] $current, [bool] $given)

    if (-not $canPrompt -or $given) { return $current }
    while ($true) {
        $shown  = if ($current) { " [$current]" } else { "" }
        $answer = (Read-Host "  Port$shown").Trim()
        if (-not $answer) {
            if ($current) { return $current }
            Warn "Port is required."
            continue
        }
        $parsed = 0
        if (-not [int]::TryParse($answer, [ref] $parsed)) {
            Warn "Not a number: $answer"
            continue
        }
        # The same rule the preflight below enforces, asked here so a bad
        # port is refused while the operator is still typing rather than after
        # three more questions. That check stays where it is: it is what catches
        # a bad port from the command line or deploy.json, where there is no
        # prompt to refuse it.
        if ($parsed -lt 1 -or $parsed -gt 65535) {
            Warn "Out of range: $parsed"
            continue
        }
        return $parsed
    }
}

function Read-CertIp {
    param([string] $current, [bool] $given)

    # Its own read rather than Read-Setting, because an empty answer is a real
    # answer here: no IPAddress SAN at all, which is what a machine with no
    # usable IPv4 gets. Read-Setting reads an empty answer with no default as a
    # required setting still missing and asks again, which would be a question
    # with no way out of it.
    if (-not $canPrompt -or $given) { return $current }
    $shown  = if ($current) { " [$current]" } else { " [none]" }
    $answer = (Read-Host "  Certificate IP address$shown").Trim()
    if ($answer) { return $answer }
    return $current
}

$InstallDir  = Read-Setting "Install directory" $InstallDir  ($PSBoundParameters.ContainsKey("InstallDir"))
$Port        = Read-Port $Port                               ($PSBoundParameters.ContainsKey("Port"))
$SiteName    = Read-Setting "IIS site name"     $SiteName    ($PSBoundParameters.ContainsKey("SiteName"))
$AppPoolName = Read-Setting "App pool name"     $AppPoolName ($PSBoundParameters.ContainsKey("AppPoolName"))

# Asked only where a certificate is about to be generated here: on a
# -CertThumbprint or -PfxPath run these values go nowhere, and a question whose
# answer is discarded reads as one that mattered.
if ($SelfSigned) {
    $names = Read-Setting "Certificate DNS names (comma separated)" ($CertDnsNames -join ", ") `
                          ($PSBoundParameters.ContainsKey("CertDnsNames"))
    $CertDnsNames = @($names -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $CertIpAddress = Read-CertIp $CertIpAddress ($PSBoundParameters.ContainsKey("CertIpAddress"))
}

if (-not $InstallDir) { Fail "No InstallDir. Pass -InstallDir, or set installDir in deploy.json." }
if (-not $Port)       { Fail "No Port. Pass -Port, or set port in deploy.json." }
Info "installDir: $InstallDir"
Info "port      : $Port"
Info "site      : $SiteName (pool $AppPoolName)"

# -- Preflight ------------------------------------------------------------
Step "Checking prerequisites"

if ($Port -lt 1 -or $Port -gt 65535) { Fail "Port $Port is out of range." }

if (-not (Test-Path $InstallDir)) { Fail "InstallDir does not exist: $InstallDir" }
# Either build can be hosted. HttpPlatformHandler needs an executable in
# processPath, so a source install points at python.exe and passes run_server.py
# as the first argument - which is the whole point of source mode: the process
# Windows starts is a signed interpreter, not an unsigned build of ours.
# See docs/it-asr-and-signing-request.md.
$exe = Join-Path $InstallDir "AssetServer.exe"
$src = Join-Path $InstallDir "run_server.py"
if (Test-Path $exe) {
    $processPath = $exe
    $processArgs = "serve"
    Info "server: AssetServer.exe (exe install)"
} elseif (Test-Path $src) {
    if (-not $PythonExe) { $PythonExe = "python" }
    $resolved = (Get-Command $PythonExe -ErrorAction SilentlyContinue)
    if (-not $resolved) {
        Fail ("cannot find the interpreter '$PythonExe' - pass -PythonExe with the full`n" +
              "    path to python.exe, or set pythonExe in deploy.json")
    }
    # The full path, not a bare name: the IIS app pool identity has its own
    # environment and a PATH lookup that works in this shell may not work there.
    $processPath = $resolved.Source
    $processArgs = """$src"" serve"
    Info "server: run_server.py (source install)"
    Info "python: $processPath"
    if (-not (Test-Path (Join-Path $InstallDir "lib"))) {
        Warn "no lib directory in $InstallDir - a source install needs its vendored"
        Warn "dependencies. Run tools/vendor.ps1 -Role server and copy them in."
    }
} else {
    Fail "neither AssetServer.exe nor run_server.py found in $InstallDir"
}

if (-not (Get-Module -ListAvailable -Name WebAdministration)) {
    Fail "IIS PowerShell support is missing. Install the Web-Scripting-Tools feature:`n    Install-WindowsFeature Web-Scripting-Tools"
}
Import-Module WebAdministration

# HttpPlatformHandler is a separate download, not an IIS feature -- check before
# building a site that would return 500.19 with no obvious cause.
$hasHandler = $false
try {
    $handlers = (Get-WebConfiguration -Filter /system.webServer/handlers).Collection
    $hasHandler = [bool]($handlers | Where-Object { $_.name -eq "httpplatformhandler" })
} catch { }
if (-not $hasHandler -and (Test-Path "$env:SystemRoot\System32\inetsrv\httpplatformhandler.dll")) {
    $hasHandler = $true
}
if (-not $hasHandler) {
    Fail "HttpPlatformHandler is not installed. Get it from`n    https://www.iis.net/downloads/microsoft/httpplatformhandler`nthen re-run this script."
}
Info "HttpPlatformHandler present"

# URL Rewrite is a separate download too, and it is now a refusal the same
# shape as the handler above rather than a warning (#242): under
# HttpPlatformHandler every request reaches the app over a loopback hop, so
# `request.remote_addr` is 127.0.0.1 for every client there has ever been --
# which is what `clients.address` and `system_log.address` recorded, the two
# columns whose whole job is to say where something came from, on machines
# that reach this server over a VPN (#187). The rule written further down
# hands the app IIS's own REMOTE_ADDR in X-Forwarded-For; the handler adds no
# such header of its own, its configuration reference documenting exactly one
# it adds and that being X-IIS-WindowsAuthToken, which this deployment has
# off. A site that starts without it is a site that silently misreports where
# every request came from rather than one that fails loudly, which is worse.
#
# Checked here rather than at the rule, because a <rewrite> section in a
# web.config on a machine without the module is 500.19 over an unrecognised
# section -- the site would not start at all, which is exactly the failure
# the refusal below heads off before this script ever gets that far. So the
# block is written through IIS's own configuration API further down and only
# where this answered true.
$hasRewrite = $false
try {
    $hasRewrite = [bool](Get-WebGlobalModule -ErrorAction Stop |
                         Where-Object { $_.Name -eq "RewriteModule" })
} catch { }
if (-not $hasRewrite -and (Test-Path "$env:SystemRoot\System32\inetsrv\rewrite.dll")) {
    $hasRewrite = $true
}
if ($hasRewrite) {
    Info "URL Rewrite present"
} else {
    Fail "URL Rewrite is not installed. Get it from`n    https://www.iis.net/downloads/microsoft/url-rewrite`nthen re-run this script."
}

$certSources = @()
if ($CertThumbprint) { $certSources += "-CertThumbprint" }
if ($PfxPath)        { $certSources += "-PfxPath" }
if ($SelfSigned)     { $certSources += "-SelfSigned" }
if ($certSources.Count -gt 1) {
    Fail ("Give one certificate source, not " + ($certSources -join " and ") + ".")
}
if ($certSources.Count -eq 0) {
    # A first-time setup is the one run where "give a certificate source" is a
    # demand the operator has no way to satisfy: there is nothing on this
    # machine to point at yet, and this is the one place in the repo where a
    # key may be generated, because it is the machine the key stays on.
    #
    # All three conditions have to hold, because an existing certificate must
    # never be regenerated: every client pins ssl_cert.pem and fails closed
    # against anything else (rule 1), so a re-run that minted a fresh one would
    # strand the whole fleet in the middle of routine maintenance, with nothing
    # said at the time. The pem and the binding are asked about separately
    # rather than one standing in for the other - a site bound to a certificate
    # whose pem somebody deleted is still an install with a certificate, and a
    # pem beside a site that has not been bound yet is still a file clients may
    # already hold.
    #
    # It generates on a host with nobody to ask as well: this is the absence of
    # an alternative rather than a question. An explicit -SelfSigned keeps its
    # own meaning of "mint one now", warning below when it replaces a different
    # ssl_cert.pem, and an explicit -CertThumbprint or -PfxPath never reaches
    # here at all.
    #
    # The three conditions are Test-FirstTimeCertSetup in _deploy.ps1 rather
    # than three lines here, so that deploy-checks.ps1 can drive all four
    # states over them: this script stands up IIS and no gate can run it, and
    # a boolean written the wrong way round is exactly what a source check
    # cannot see.
    if (-not (Test-FirstTimeCertSetup -InstallDir $InstallDir `
                                      -SiteName $SiteName `
                                      -SourceGiven ($certSources.Count -gt 0))) {
        Fail "Give a certificate source: -SelfSigned, -CertThumbprint or -PfxPath."
    }
    $SelfSigned = $true
    Info "no certificate source given, no ssl_cert.pem in $InstallDir and"
    Info "nothing bound to $SiteName - first-time setup, so one is generated"
    Info "here, the same way -SelfSigned would."
}

# -- Certificate ------------------------------------------------------------
Step "Resolving the TLS certificate"

if ($SelfSigned) {
    $sanParts = @()
    foreach ($d in $CertDnsNames) { $sanParts += "DNS=$d" }
    if ($CertIpAddress) { $sanParts += "IPAddress=$CertIpAddress" }
    Info ("names   : " + ($sanParts -join ", "))

    if ($PSCmdlet.ShouldProcess("CN=$($CertDnsNames[0])", "Generate a self-signed certificate")) {
        # CA=true is not decoration. Each client loads this certificate as its
        # trust anchor (load_verify_locations), and OpenSSL 3 refuses a non-CA
        # certificate in that role -- a self-signed certificate is its own issuer.
        # Without it every client fails verification, and since they now fail
        # closed rather than falling back to the system store, none of them can
        # reach the server at all.
        $generated = New-SelfSignedCertificate `
            -Subject "CN=$($CertDnsNames[0])" `
            -CertStoreLocation Cert:\LocalMachine\My `
            -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 `
            -NotAfter (Get-Date).AddYears(5) `
            -KeyUsage DigitalSignature, KeyEncipherment, CertSign `
            -TextExtension @(
                ("2.5.29.17={text}" + ($sanParts -join "&")),
                "2.5.29.19={text}CA=true",
                "2.5.29.37={text}1.3.6.1.5.5.7.3.1"      # EKU: server authentication
            )
        $CertThumbprint = $generated.Thumbprint
        Info "generated, thumbprint $CertThumbprint"
        # The fingerprint rather than the thumbprint alone: that is the number
        # the Server GUI's SSL Certificate dialog shows and the one a person at
        # a client machine is read on first contact (ADR-0010), so it is what
        # the operator will be asked to compare this certificate against.
        Info "fingerprint $(Get-CertFingerprint -Der $generated.RawData)"
        Info "valid until $($generated.NotAfter.ToString('yyyy-MM-dd'))"
    }
}

if ($PfxPath) {
    if (-not (Test-Path $PfxPath)) { Fail "PFX not found: $PfxPath" }
    $pfxName = [IO.Path]::GetFileName($PfxPath)
    # Prompted, never a parameter, so the password stays out of history and
    # transcripts. Not asked for under -WhatIf: nothing is imported there, so a
    # rehearsal must not stop for a password it will never use -- and where
    # there is no console it would not stop, it would hang. The rest of the plan
    # still prints: the no-thumbprint branch below is written for exactly this.
    if ($WhatIfPreference) {
        Info "would import $pfxName; its password is asked for on a real run"
    } else {
        if (-not $canPrompt) {
            Fail ("No console here to ask for $pfxName's password on. Import it into " +
                  "LocalMachine\My by hand and pass -CertThumbprint instead.")
        }
        $pfxPass = Read-Host -AsSecureString "Password for $pfxName"
        if ($PSCmdlet.ShouldProcess($PfxPath, "Import into LocalMachine\My")) {
            $imported = Import-PfxCertificate -FilePath $PfxPath `
                -CertStoreLocation Cert:\LocalMachine\My -Password $pfxPass
            $CertThumbprint = $imported.Thumbprint
            Info "imported, thumbprint $CertThumbprint"
        }
    }
}

$CertThumbprint = $CertThumbprint -replace '\s', ''
$cert = $null
if (-not $CertThumbprint) {
    # -WhatIf: the import or the generation above was described, not run, so there
    # is no thumbprint to look up. Carry on so the rest of the plan still prints.
    Warn "no certificate yet (-WhatIf); the steps that need one are described only"
} else {
    $cert = Get-ChildItem Cert:\LocalMachine\My |
            Where-Object { $_.Thumbprint -eq $CertThumbprint }
    if (-not $cert) { Fail "No certificate with thumbprint $CertThumbprint in LocalMachine\My." }
    Info "subject : $($cert.Subject)"
    Info "expires : $($cert.NotAfter.ToString('yyyy-MM-dd'))"
    if ($cert.NotAfter -lt (Get-Date)) { Fail "That certificate expired on $($cert.NotAfter)." }
    if ($cert.NotAfter -lt (Get-Date).AddDays(30)) {
        Warn "Certificate expires in $([int]($cert.NotAfter - (Get-Date)).TotalDays) days."
    }
}

# -- Publish the public half for the clients ---------------------------------
Step "Writing ssl_cert.pem for the clients"

# Whatever certificate IIS ends up presenting, GET /cert has to serve its public
# half: that file is what every client pins, and a client holding a different one
# cannot connect at all now that they fail closed. Only the public half is written
# here -- the private key never leaves this machine.
$pemPath = Join-Path $InstallDir "ssl_cert.pem"
if (-not $cert) {
    Info "would write $pemPath"
} else {
    $b64 = [Convert]::ToBase64String($cert.RawData, "InsertLineBreaks")
    $pem = "-----BEGIN CERTIFICATE-----`r`n$b64`r`n-----END CERTIFICATE-----`r`n"

    if ((Test-Path $pemPath) -and ((Get-Content -Raw $pemPath) -ne $pem)) {
        Warn "This replaces a DIFFERENT ssl_cert.pem. Every client still holding the old"
        Warn "one will be unable to reach the server until it is reinstalled: a client"
        Warn "refreshes GET /cert over a connection its current copy has verified, and"
        Warn "that connection is exactly what stops working. Ship the new file with the"
        Warn "installer, or expect to visit each laptop."
        # Both fingerprints, for update.ps1's reason: the question at this moment
        # is whether the outgoing file is the one the clients out there actually
        # hold, and one hash on its own can be compared with nothing. It is the
        # sharper version of that question here - a -SelfSigned re-run mints a
        # new certificate every time, so this fires on every repeat run - and the
        # outgoing digest is also what identifies the backup taken below. Both go
        # through Get-CertFingerprint, the incoming one by its DER bytes because
        # the PEM being warned about has not been written yet.
        Warn "  installed: $(Get-CertFingerprint $pemPath)"
        Warn "  incoming : $(Get-CertFingerprint -Der $cert.RawData)"
        Warn "That second number is what the person at a client machine is shown on"
        Warn "first contact (ADR-0010), and what the Server GUI's SSL Certificate"
        Warn "dialog will show once this file is in place."
        $backup = "$pemPath.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        if ($PSCmdlet.ShouldProcess($backup, "Back up the outgoing certificate")) {
            Copy-Item $pemPath $backup
            Info "previous copy saved as $([IO.Path]::GetFileName($backup))"
        }
    }
    if ($PSCmdlet.ShouldProcess($pemPath, "Write the public certificate")) {
        Set-Content -Path $pemPath -Value $pem -Encoding ascii -NoNewline
        Info $pemPath
    }
}

# -- Stand down the Windows service ------------------------------------------------------------
Step "Checking the AssetManagerServer service"

$svc = Get-Service -Name AssetManagerServer -ErrorAction SilentlyContinue
if ($svc) {
    if ($KeepService) {
        Warn "Service left running at your request. If it still binds the same port as"
        Warn "this site, one of the two listeners will fail. Verify server_config.json."
    } elseif ($PSCmdlet.ShouldProcess("AssetManagerServer", "Stop and disable")) {
        if ($svc.Status -ne "Stopped") { Stop-Service AssetManagerServer -Force; Info "stopped" }
        Set-Service AssetManagerServer -StartupType Disabled
        Info "disabled -- IIS now owns the process lifetime"
    }
} else {
    Info "not installed; nothing to stand down"
}

# -- web.config ------------------------------------------------------------
Step "Writing web.config"

# stdout logging is on by default: a headless Flask under IIS is otherwise silent,
# and a crash on startup shows up only as a 502 with nothing to read.
$logDir = Join-Path $InstallDir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory $logDir | Out-Null }

function Escape-XmlAttr ([string] $value) {
    # Every value interpolated into an attribute below goes through this. Two of
    # the three carry characters XML gives its own meaning to, and neither is
    # exotic:
    #
    #   * $processArgs on a SOURCE install is `"<path>" serve` - the launcher
    #     path is quoted because it can contain spaces - and a literal quote
    #     inside a quoted attribute closes it. The emitted line read
    #     arguments=""C:\AssetManager\run_server.py" serve", which is not XML at
    #     all, so IIS refused the whole file with 500.19 and never started a
    #     process - which means httpplatform-stdout is empty, and the /health
    #     probe at the end of this script warns and names a log with nothing in
    #     it. Source mode is the only mode (rule 14) and IIS is the supported
    #     host (ADR-0001), so that was the whole supported deploy path. Exe mode
    #     passes the bare word `serve` and was never affected, which is why this
    #     went unseen.
    #   * an & anywhere in InstallDir or in the interpreter's path does the same
    #     thing more quietly, being a legal character in a Windows path and an
    #     entity reference opener here.
    #
    # & first, or the ampersands this introduces get escaped again.
    return $value.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace('"', "&quot;")
}

$xProcessPath = Escape-XmlAttr $processPath
$xProcessArgs = Escape-XmlAttr $processArgs
$xStdoutLog   = Escape-XmlAttr (Join-Path $logDir "httpplatform-stdout")

$webConfig = @"
<?xml version="1.0" encoding="utf-8"?>
<!-- Generated by tools/install-iis.ps1. Regenerate rather than hand-editing. -->
<configuration>
  <system.webServer>
    <handlers>
      <clear />
      <add name="httpplatformhandler" path="*" verb="*"
           modules="httpPlatformHandler" resourceType="Unspecified"
           requireAccess="Script" />
    </handlers>
    <!-- arguments: 'serve' selects the headless entry point in server.py, which
         binds 127.0.0.1 on %HTTP_PLATFORM_PORT% and skips the Tkinter GUI.
         forwardWindowsAuthToken is off: the app does its own admin-password auth. -->
    <httpPlatform processPath="$xProcessPath"
                  arguments="$xProcessArgs"
                  stdoutLogEnabled="true"
                  stdoutLogFile="$xStdoutLog"
                  startupTimeLimit="120"
                  startupRetryCount="3"
                  requestTimeout="00:04:00"
                  forwardWindowsAuthToken="false" />
  </system.webServer>
</configuration>
"@

$webConfigPath = Join-Path $InstallDir "web.config"
# Set-Content, and so the BOM 5.1 puts on it, deliberately: this is not one of
# the JSON files Write-JsonFile exists for. Nothing reads it with a plain
# open() -- IIS does, and its own <?xml encoding="utf-8"?> declaration is what
# makes a leading BOM something every XML parser already handles. Moving it
# would be churn with no defect behind it.
if ($PSCmdlet.ShouldProcess($webConfigPath, "Write")) {
    $webConfig | Set-Content -Path $webConfigPath -Encoding UTF8
    Info $webConfigPath
}

# -- App pool ------------------------------------------------------------
Step "Configuring app pool $AppPoolName"

if ($PSCmdlet.ShouldProcess($AppPoolName, "Create or update app pool")) {
    if (-not (Test-Path "IIS:\AppPools\$AppPoolName")) {
        New-WebAppPool -Name $AppPoolName | Out-Null
        Info "created"
    } else {
        Info "already exists -- updating"
    }
    # No managed code: nothing here is .NET. No idle timeout and no periodic
    # recycle, because the background jobs in server.py (24h auto-accept, hourly
    # sweep) only run while the process is alive.
    Set-ItemProperty "IIS:\AppPools\$AppPoolName" managedRuntimeVersion ""
    Set-ItemProperty "IIS:\AppPools\$AppPoolName" processModel.idleTimeout ([TimeSpan]::Zero)
    Set-ItemProperty "IIS:\AppPools\$AppPoolName" recycling.periodicRestart.time ([TimeSpan]::Zero)
    Set-ItemProperty "IIS:\AppPools\$AppPoolName" processModel.loadUserProfile $true
    Set-ItemProperty "IIS:\AppPools\$AppPoolName" startMode "AlwaysRunning"
    Info "no managed runtime, no idle timeout, no periodic recycle, always running"
}

# -- Site + HTTPS binding ------------------------------------------------------------
Step "Configuring site $SiteName on port $Port"

if ($PSCmdlet.ShouldProcess($SiteName, "Create or update site")) {
    if (-not (Test-Path "IIS:\Sites\$SiteName")) {
        New-Website -Name $SiteName -PhysicalPath $InstallDir -ApplicationPool $AppPoolName `
                    -Port $Port -Ssl | Out-Null
        Info "created"
    } else {
        Set-ItemProperty "IIS:\Sites\$SiteName" physicalPath $InstallDir
        Set-ItemProperty "IIS:\Sites\$SiteName" applicationPool $AppPoolName
        if (-not (Get-WebBinding -Name $SiteName -Port $Port -Protocol https -ErrorAction SilentlyContinue)) {
            New-WebBinding -Name $SiteName -Protocol https -Port $Port
        }
        Info "updated"
    }

    # Bind the cert to the port. Remove any existing binding first: re-running with a
    # renewed certificate must not leave the old one attached.
    if (-not $cert) {
        Info "no certificate resolved (-WhatIf); the SSL binding is skipped"
    } else {
        $existing = Get-Item "IIS:\SslBindings\0.0.0.0!$Port" -ErrorAction SilentlyContinue
        if ($existing) { Remove-Item "IIS:\SslBindings\0.0.0.0!$Port" -Force }
        New-Item -Path "IIS:\SslBindings\0.0.0.0!$Port" -Value $cert | Out-Null
        Info "certificate $($CertThumbprint.Substring(0,12))... bound to 0.0.0.0:$Port"
    }
}

# -- The client's own address ------------------------------------------------------------
Step "Forwarding the client address to the app"

# What the app reads as `X-Forwarded-For` (#187), and the reason it may believe
# it: `_client_addr()` in server.py takes that header **only when the peer is
# loopback**, which under this handler is every request and off IIS is none of
# them. That makes this rule the one writer of the header on the supported
# deployment -- it is set from IIS's own REMOTE_ADDR unconditionally, so a value
# a caller sent is overwritten rather than appended to, and the header the app
# believes cannot be one anybody chose. Appending would be the ordinary proxy
# convention and is wrong here: these endpoints are unauthenticated by design
# (ADR-0002, ADR-0005), so a caller that could put an entry in front of IIS's
# would be choosing what the System Log says about them.
#
# Written through the configuration API rather than into the web.config
# here-string above, because that section may not exist on this machine and a
# template carrying it would be 500.19 on every install without the module --
# the file that step writes stays one literal template with nothing conditional
# in it. Re-running this script rewrites web.config and then re-adds this, which
# is what keeps "regenerate rather than hand-editing" true of both halves.
#
# HTTP_X_FORWARDED_FOR has to be allow-listed at the machine level before a rule
# may set it; that is applicationHost.config, which is why this script is
# elevated already. Both halves are idempotent: the variable is added only where
# it is absent, and the rule is removed by name before it is added, so a re-run
# leaves one of each rather than a second copy. On a first install there is no
# rule to remove and that removal warns rather than errors, so it is silenced on
# both streams -- the warning is the expected path, not a fault.
#
# No branch on $hasRewrite here: a false answer already exited the script at
# the refusal above, so reaching this line means the module is present.
if ($PSCmdlet.ShouldProcess($SiteName, "Set X-Forwarded-For from REMOTE_ADDR")) {
    $apphost = "MACHINE/WEBROOT/APPHOST"
    $allowed = @(Get-WebConfiguration -PSPath $apphost `
                   -Filter "system.webServer/rewrite/allowedServerVariables" `
                   -ErrorAction SilentlyContinue |
                 Select-Object -ExpandProperty Collection |
                 ForEach-Object { $_.name })
    if ($allowed -notcontains "HTTP_X_FORWARDED_FOR") {
        Add-WebConfiguration -PSPath $apphost `
            -Filter "system.webServer/rewrite/allowedServerVariables" `
            -Value @{ name = "HTTP_X_FORWARDED_FOR" }
        Info "HTTP_X_FORWARDED_FOR allowed in applicationHost.config"
    } else {
        Info "HTTP_X_FORWARDED_FOR already allowed"
    }

    $sitePath = "IIS:\Sites\$SiteName"
    $ruleName = "AssetManagerClientAddress"
    Remove-WebConfigurationProperty -PSPath $sitePath `
        -Filter "system.webServer/rewrite/rules" -Name "." `
        -AtElement @{ name = $ruleName } `
        -ErrorAction SilentlyContinue -WarningAction SilentlyContinue
    Add-WebConfigurationProperty -PSPath $sitePath `
        -Filter "system.webServer/rewrite/rules" -Name "." `
        -Value @{ name = $ruleName; stopProcessing = $false }
    $rule = "system.webServer/rewrite/rules/rule[@name='$ruleName']"
    Set-WebConfigurationProperty -PSPath $sitePath -Filter "$rule/match" `
        -Name "url" -Value ".*"
    Set-WebConfigurationProperty -PSPath $sitePath -Filter "$rule/action" `
        -Name "type" -Value "None"
    Add-WebConfigurationProperty -PSPath $sitePath `
        -Filter "$rule/serverVariables" -Name "." `
        -Value @{ name = "HTTP_X_FORWARDED_FOR"; value = "{REMOTE_ADDR}"; replace = $true }
    Info "rule $ruleName sets X-Forwarded-For from REMOTE_ADDR"
}

# -- Filesystem permissions ------------------------------------------------------------
Step "Granting the app pool identity write access to $InstallDir"

# The app writes the database, admin_config.json, server_config.json, the
# lookup sheet and stdout logs into InstallDir, so read-only access produces
# confusing 500s on the first write rather than at startup.
$identity = "IIS AppPool\$AppPoolName"

function Grant-Modify([string] $folder, [string] $grantee) {
    # Inherited by what is in the folder and by what is put there later: the
    # database, the -wal and -shm files SQLite writes beside it, the configs and
    # the stdout logs are all created after this runs.
    #
    # $grantee is a parameter rather than $identity read out of the enclosing
    # scope, for the reason Test-CanPrompt takes $WhatIfPreference as one.
    # $PSCmdlet stays ambient: it is this script's cmdlet context rather than a
    # setting, and passing it reads worse than not.
    if (-not $PSCmdlet.ShouldProcess($folder, "Grant Modify to $grantee")) { return }
    $acl  = Get-Acl $folder
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $grantee, "Modify", "ContainerInherit,ObjectInherit", "None", "Allow")
    $acl.SetAccessRule($rule)
    Set-Acl -Path $folder -AclObject $acl
    Info "granted Modify to $grantee on $folder"
}

Grant-Modify $InstallDir $identity

# A database moved with db_path sits outside InstallDir, so the grant above does
# not reach it. The identity needs Modify on the folder rather than the file:
# SQLite writes -wal and -shm files beside the database, and without write
# access to the directory every submission fails with "attempt to write a
# readonly database" - long after this script has reported success.
$dbPath = Resolve-DbPath $InstallDir
$dbDir  = Split-Path -Parent $dbPath
if (-not (Test-Path $dbDir)) {
    Info "db_path names $dbDir, which does not exist - the server refuses to start until the database is there"
} elseif ((Resolve-Path $dbDir).Path -ne (Resolve-Path $InstallDir).Path) {
    Step "Granting the app pool identity write access to $dbDir"
    Grant-Modify $dbDir $identity
}

# -- Firewall ------------------------------------------------------------
Step "Firewall rule for port $Port"

$ruleName = "Asset Manager IIS ($Port)"
if ($PSCmdlet.ShouldProcess($ruleName, "Create inbound allow rule")) {
    if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
        Info "rule already present"
    } else {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort $Port | Out-Null
        Info "created"
    }
}

# -- Record what we did, for tools/update.py ------------------------------------------------------------
Step "Recording configuration"

$state = [ordered]@{
    site           = $SiteName
    app_pool       = $AppPoolName
    port           = $Port
    cert_thumbprint = $CertThumbprint
    install_dir    = $InstallDir
    configured_at  = (Get-Date).ToString("s")
}
$statePath = Join-Path $InstallDir "iis.json"
if ($PSCmdlet.ShouldProcess($statePath, "Write")) {
    # update.ps1 reads app_pool from here to know it must cycle the pool rather
    # than the Windows service, and server.py's _iis_host reads it to say so in
    # the GUI banner. Written no-BOM through the same helper as
    # server_config.json below: this file used to go out through Set-Content
    # -Encoding UTF8, which under Windows PowerShell 5.1 put a BOM on it, and
    # _iis_host decodes utf-8-sig to survive that. It keeps doing so - an
    # install made before 054 keeps its BOM until somebody re-runs this - but
    # nothing written here has carried one since.
    Write-JsonFile $statePath $state
    Info $statePath
}

# The port is one fact written down in two places, and only iis.json was getting
# it. server.py reads PORT from server_config.json at import, so an install on
# any port but the default left the two disagreeing: the GUI probed a port IIS
# does not serve and read OFFLINE over a healthy server, and - worse - found the
# default free, so its exclusive-bind probe said "nobody is serving" and it
# started a second Flask over the same database. The probe is right; the number
# it was handed was not.
$srvCfgPath = Join-Path $InstallDir "server_config.json"
if ($PSCmdlet.ShouldProcess($srvCfgPath, "Record port $Port")) {
    # Read-modify-write, never overwrite. This file also holds ssl_enabled, and
    # replacing it with a fresh one-key object turns HTTPS off on the next
    # restart with both cert files still on disk, so nothing looks wrong until a
    # client fails to verify. That is the failure _save_server_cfg exists to
    # prevent on the server's side of the same file.
    $srvCfg   = @{}
    $readable = $true
    try {
        $existingCfg = Read-JsonFile $srvCfgPath
        if ($existingCfg) {
            $existingCfg.PSObject.Properties |
                ForEach-Object { $srvCfg[$_.Name] = $_.Value }
        }
    } catch {
        # Leave an unreadable file alone rather than replacing it: every key in
        # it is a setting somebody chose, and this script knows one of them. Say
        # so, since the mismatch is otherwise invisible.
        $readable = $false
        Warn "could not read $srvCfgPath ($($_.Exception.Message))"
        Warn "leaving it alone rather than overwriting it - repair it and set port to $Port,"
        Warn "or the Server GUI will probe a port IIS does not serve"
    }
    if ($readable) {
        $srvCfg["port"] = $Port
        # No-BOM UTF-8, because server.py reads this file with a plain
        # open()/json.load - see Write-JsonFile in _deploy.ps1 for the trap.
        Write-JsonFile $srvCfgPath $srvCfg
        Info "$srvCfgPath (port $Port)"
    }
}

# -- Start ------------------------------------------------------------
Step "Starting"

if ($PSCmdlet.ShouldProcess($SiteName, "Start site and app pool")) {
    Start-WebAppPool -Name $AppPoolName -ErrorAction SilentlyContinue
    Start-Website   -Name $SiteName    -ErrorAction SilentlyContinue

    $url = "https://$($env:COMPUTERNAME):$Port/health"
    Info "probing $url"
    $ok   = $false
    $last = $null
    # Pinned on the ssl_cert.pem written above, through _deploy.ps1's one
    # implementation of that. A -SelfSigned run mints into
    # Cert:\LocalMachine\My and nothing puts a copy in LocalMachine\Root, so
    # this probe could not complete the handshake against the certificate it
    # had just bound: every correct install warned that /health had not
    # answered and sent the operator to logs showing nothing wrong, which is
    # a warning nobody reads the time it is about a real 502.
    foreach ($i in 1..10) {
        Start-Sleep -Seconds 2
        $last = Invoke-PinnedRequest -Url $url -PinPath $pemPath -TimeoutSec 5
        if ($last.StatusCode -eq 200) { $ok = $true; break }
    }
    if ($ok) {
        Write-Host "`n[OK] Serving on https://$($env:COMPUTERNAME):$Port" -ForegroundColor Green
    } else {
        Warn "/health did not answer within 20s: $($last.Error)"
        Warn "Check $logDir\httpplatform-stdout*.log -- a startup crash shows there,"
        Warn "not in the browser, which only reports a 502."
    }
}

Write-Host "`nNext: point clients at https://$($env:COMPUTERNAME):$Port" -ForegroundColor Cyan
Write-Host "The Windows service is disabled; IIS starts the server from now on.`n"
