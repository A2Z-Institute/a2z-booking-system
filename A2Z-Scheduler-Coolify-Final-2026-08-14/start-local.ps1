[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$Listen = "127.0.0.1",

    [ValidateRange(1, 65535)]
    [int]$Port = 8080,

    [switch]$LocalHttp
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$venvDirectory = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvDirectory "Scripts\python.exe"
$requirementsFile = Join-Path $PSScriptRoot "requirements.txt"
$requirementsMarker = Join-Path $venvDirectory ".a2z-requirements.sha256"
$environmentFile = Join-Path $PSScriptRoot ".env"
$environmentExample = Join-Path $PSScriptRoot ".env.example"

function Test-Python310 {
    param(
        [Parameter(Mandatory)]
        [string]$Command,

        [string[]]$PrefixArguments = @()
    )

    try {
        & $Command @PrefixArguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Find-SystemPython {
    $candidates = @(
        [pscustomobject]@{ Command = "py"; Arguments = [string[]]@("-3") },
        [pscustomobject]@{ Command = "python"; Arguments = [string[]]@() }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) {
            continue
        }

        if (Test-Python310 -Command $candidate.Command -PrefixArguments $candidate.Arguments) {
            return $candidate
        }
    }

    throw "Python 3.10 or newer is required. Install Python from https://www.python.org/downloads/ and run this launcher again."
}

function Test-VirtualEnvironment {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        return $false
    }

    return Test-Python310 -Command $venvPython
}

if (-not (Test-Path -LiteralPath $requirementsFile -PathType Leaf)) {
    throw "requirements.txt is missing from $PSScriptRoot. Re-copy the complete application folder."
}

if (-not (Test-VirtualEnvironment)) {
    if (Test-Path -LiteralPath $venvDirectory) {
        $resolvedProject = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd("\")
        $resolvedVenv = [IO.Path]::GetFullPath($venvDirectory).TrimEnd("\")
        $venvParent = (Split-Path -Parent $resolvedVenv).TrimEnd("\")

        if ($venvParent -ne $resolvedProject -or (Split-Path -Leaf $resolvedVenv) -ne ".venv") {
            throw "Refusing to replace an unexpected virtual-environment path: $resolvedVenv"
        }

        Write-Host "Replacing a virtual environment copied from another computer..."
        Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
    }

    $systemPython = Find-SystemPython
    $pythonCommand = $systemPython.Command
    $pythonArguments = @($systemPython.Arguments)

    Write-Host "Creating this computer's Python environment..."
    & $pythonCommand @pythonArguments -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0 -or -not (Test-VirtualEnvironment)) {
        throw "Python could not create the local virtual environment."
    }
}

$requirementsHash = (Get-FileHash -LiteralPath $requirementsFile -Algorithm SHA256).Hash
$installedHash = if (Test-Path -LiteralPath $requirementsMarker -PathType Leaf) {
    (Get-Content -LiteralPath $requirementsMarker -Raw).Trim()
}
else {
    ""
}

$importsAvailable = $false
try {
    & $venvPython -c "import flask, flask_login, dotenv, waitress, werkzeug" *> $null
    $importsAvailable = $LASTEXITCODE -eq 0
}
catch {
    $importsAvailable = $false
}

if (-not $importsAvailable -or $installedHash -ne $requirementsHash) {
    Write-Host "Installing A2Z Scheduler dependencies (first launch may take a few minutes)..."
    & $venvPython -m pip install --disable-pip-version-check -r $requirementsFile
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed. Check this computer's internet connection and run the launcher again."
    }

    Set-Content -LiteralPath $requirementsMarker -Value $requirementsHash -Encoding ASCII
}

if (-not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
    if (-not (Test-Path -LiteralPath $environmentExample -PathType Leaf)) {
        throw ".env and .env.example are both missing. Re-copy the complete application folder."
    }

    Copy-Item -LiteralPath $environmentExample -Destination $environmentFile
    Write-Host "Created a private .env configuration for this computer."
}

$environmentContents = Get-Content -LiteralPath $environmentFile -Raw
$environmentChanged = $false
$generatedAdminPassword = $null

if ($environmentContents -match "(?m)^A2Z_SECRET_KEY\s*=\s*CHANGE_ME[^\r\n]*$") {
    $secretKey = (& $venvPython -c "import secrets; print(secrets.token_hex(32))").Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not generate the application secret."
    }

    $environmentContents = [regex]::Replace(
        $environmentContents,
        "(?m)^A2Z_SECRET_KEY\s*=\s*CHANGE_ME[^\r\n]*$",
        "A2Z_SECRET_KEY=$secretKey"
    )
    $environmentChanged = $true
}

if ($environmentContents -match "(?m)^A2Z_ADMIN_PASSWORD\s*=\s*CHANGE_ME[^\r\n]*$") {
    $generatedAdminPassword = (& $venvPython -c "import secrets; print(secrets.token_urlsafe(18))").Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not generate the initial administrator password."
    }

    $environmentContents = [regex]::Replace(
        $environmentContents,
        "(?m)^A2Z_ADMIN_PASSWORD\s*=\s*CHANGE_ME[^\r\n]*$",
        "A2Z_ADMIN_PASSWORD=$generatedAdminPassword"
    )
    $environmentChanged = $true
}

if ($environmentChanged) {
    Set-Content -LiteralPath $environmentFile -Value $environmentContents -Encoding UTF8
}

if ($environmentContents -match "(?m)^[A-Za-z_][A-Za-z0-9_]*\s*=\s*CHANGE_ME") {
    throw "The .env file still contains an active CHANGE_ME value. Complete that setting and run the launcher again."
}

if ($LocalHttp) {
    $env:A2Z_SECURE_COOKIES = "0"
}
else {
    $env:A2Z_SECURE_COOKIES = "1"
}

Write-Host ""
try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($Listen), $Port)
    $listener.Start()
    $listener.Stop()
}
catch {
    throw "Port $Port is unavailable on $Listen. Close the program using it or run: .\start-local.cmd -Port 8090"
}

& $venvPython "backup_database.py"
if ($LASTEXITCODE -ne 0) {
    throw "The pre-start database backup failed. The scheduler was not started to protect your data."
}

Write-Host "A2Z Scheduler is starting from $PSScriptRoot"
Write-Host "Local service: http://${Listen}:$Port"

if ($LocalHttp) {
    Write-Warning "Local HTTP mode is enabled. Use it only on a trusted private network."
}
else {
    Write-Host "HTTPS-tunnel mode: secure session cookies are enabled."
    Write-Host "In a second PowerShell window, run:"
    Write-Host "  cloudflared tunnel --url http://127.0.0.1:$Port"
}

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Warning "cloudflared is not installed on this computer. Install it with: winget install --id Cloudflare.cloudflared"
}

if ($generatedAdminPassword) {
    Write-Host ""
    Write-Host "Fresh databases use this initial sign-in:"
    Write-Host "  Username: admin"
    Write-Host "  Password: $generatedAdminPassword"
    Write-Host "Store it privately. An existing transferred database keeps its existing account passwords."
}

Write-Host ""
& $venvPython -m waitress "--listen=${Listen}:$Port" "--threads=4" "wsgi:app"
