[CmdletBinding()]
param(
    [string]$Destination
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $PSScriptRoot "A2Z-Scheduler-Portable.zip"
}

$destinationPath = [IO.Path]::GetFullPath($Destination)
$stagingRoot = Join-Path ([IO.Path]::GetTempPath()) ("A2Z-Scheduler-" + [guid]::NewGuid().ToString("N"))

$excludedDirectoryNames = @(
    ".agents",
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    ".venv",
    ".vscode",
    "__pycache__",
    "backups",
    "data",
    "env",
    "tests",
    "venv"
)

function Test-PackagePathExcluded {
    param(
        [Parameter(Mandatory)]
        [string]$RelativePath
    )

    $normalisedPath = $RelativePath.Replace("\", "/")
    $segments = $normalisedPath.Split("/")
    foreach ($segment in $segments) {
        if ($excludedDirectoryNames -contains $segment) {
            return $true
        }
    }

    $fileName = [IO.Path]::GetFileName($normalisedPath)
    $lowerName = $fileName.ToLowerInvariant()
    if (
        $lowerName -eq ".env" -or
        $lowerName -eq ".flaskenv" -or
        ($lowerName.StartsWith(".env.") -and $lowerName -ne ".env.example") -or
        $lowerName -eq ".coverage" -or
        $lowerName -eq ".ds_store" -or
        $lowerName -eq "desktop.ini" -or
        $lowerName -eq "thumbs.db"
    ) {
        return $true
    }

    if (
        $lowerName -match "\.(db|sqlite|sqlite3)(-(wal|shm))?$" -or
        $lowerName -match "\.(log|pyc|pyo|zip)$"
    ) {
        return $true
    }

    return $false
}

function Copy-PackageDirectory {
    param(
        [Parameter(Mandatory)]
        [string]$DirectoryName
    )

    $source = Join-Path $PSScriptRoot $DirectoryName
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Required package folder is missing: $DirectoryName"
    }

    $sourcePath = (Resolve-Path -LiteralPath $source).Path
    $sourcePrefix = $sourcePath
    if (-not $sourcePrefix.EndsWith([IO.Path]::DirectorySeparatorChar)) {
        $sourcePrefix += [IO.Path]::DirectorySeparatorChar
    }

    $targetRoot = Join-Path $stagingRoot $DirectoryName
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null

    $copiedFiles = 0
    foreach ($sourceFile in Get-ChildItem -LiteralPath $sourcePath -File -Recurse -Force) {
        $fullSourcePath = [IO.Path]::GetFullPath($sourceFile.FullName)
        if (-not $fullSourcePath.StartsWith($sourcePrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to package a file outside $DirectoryName`: $fullSourcePath"
        }

        $relativePath = $fullSourcePath.Substring($sourcePrefix.Length)
        if (Test-PackagePathExcluded -RelativePath $relativePath) {
            continue
        }

        $targetPath = Join-Path $targetRoot $relativePath
        $targetParent = Split-Path -Parent $targetPath
        if (-not (Test-Path -LiteralPath $targetParent -PathType Container)) {
            New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
        }

        Copy-Item -LiteralPath $fullSourcePath -Destination $targetPath
        $copiedFiles += 1
    }

    if ($copiedFiles -eq 0) {
        throw "Required package folder contains no distributable files: $DirectoryName"
    }
}

$files = @(
    ".env.example",
    ".gitignore",
    "README.md",
    "requirements.txt",
    "start-local.cmd",
    "start-local.ps1",
    "create-share-package.cmd",
    "create-share-package.ps1",
    "app.py",
    "wsgi.py",
    "database.py",
    "conflict_checker.py",
    "free_slots.py",
    "notifications.py"
)

$directories = @(
    "static",
    "templates"
)

try {
    New-Item -ItemType Directory -Path $stagingRoot | Out-Null

    foreach ($file in $files) {
        $source = Join-Path $PSScriptRoot $file
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required package file is missing: $file"
        }

        Copy-Item -LiteralPath $source -Destination (Join-Path $stagingRoot $file)
    }

    foreach ($directory in $directories) {
        Copy-PackageDirectory -DirectoryName $directory
    }

    foreach ($stagedFile in Get-ChildItem -LiteralPath $stagingRoot -File -Recurse -Force) {
        $relativePath = $stagedFile.FullName.Substring($stagingRoot.Length).TrimStart("\", "/")
        if (
            $relativePath -ne ".env.example" -and
            (Test-PackagePathExcluded -RelativePath $relativePath)
        ) {
            throw "Refusing to package a secret, runtime file or development artefact: $relativePath"
        }
    }

    $destinationParent = Split-Path -Parent $destinationPath
    if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    }

    if (Test-Path -LiteralPath $destinationPath -PathType Leaf) {
        Remove-Item -LiteralPath $destinationPath -Force
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory(
        $stagingRoot,
        $destinationPath,
        [IO.Compression.CompressionLevel]::Optimal,
        $false
    )
    Write-Host "Portable package created:"
    Write-Host "  $destinationPath"
    Write-Host ""
    Write-Host "It contains no .env, passwords, database, backups, virtual environment, Git data, caches or logs."
}
finally {
    if (Test-Path -LiteralPath $stagingRoot -PathType Container) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
