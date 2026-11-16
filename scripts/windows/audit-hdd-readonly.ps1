[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$StorageRoot,

    [Parameter(Mandatory = $false)]
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,

    [Parameter(Mandatory = $false)]
    [string]$ReportPath = (Join-Path $env:TEMP ("hw-catalog-audit-{0}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss")))
)

$ErrorActionPreference = "Stop"

function Get-FolderStats {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return [pscustomobject]@{ exists = $false; file_count = 0; total_bytes = 0 }
    }

    $count = 0
    [int64]$bytes = 0
    Get-ChildItem -LiteralPath $Path -File -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $count++
        $bytes += [int64]$_.Length
    }

    [pscustomobject]@{ exists = $true; file_count = $count; total_bytes = $bytes }
}

if (-not $StorageRoot) {
    $StorageRoot = Read-Host "Enter the external HDD storage root (for example E:\HW-CATALOG-DATA)"
}
if (-not (Test-Path -LiteralPath $StorageRoot -PathType Container)) {
    throw "Storage root does not exist or is not a directory: $StorageRoot"
}
$StorageRoot = (Resolve-Path -LiteralPath $StorageRoot).Path
$driveRoot = [System.IO.Path]::GetPathRoot($StorageRoot)
$driveLetter = $driveRoot.Substring(0,1)

$volume = Get-Volume -DriveLetter $driveLetter -ErrorAction SilentlyContinue
$partition = Get-Partition -DriveLetter $driveLetter -ErrorAction SilentlyContinue
$disk = $null
if ($partition) {
    $disk = Get-Disk -Number $partition.DiskNumber -ErrorAction SilentlyContinue
}

$deviceInfoPath = Join-Path $StorageRoot "DEVICE_INFO.json"
$deviceInfo = $null
$deviceInfoValid = $false
if (Test-Path -LiteralPath $deviceInfoPath -PathType Leaf) {
    try {
        $rawDeviceInfo = Get-Content -LiteralPath $deviceInfoPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $deviceInfo = [ordered]@{
            storage_id = $rawDeviceInfo.storage_id
            layout_version = $rawDeviceInfo.layout_version
        }
        $deviceInfoValid = $true
    } catch {
        $deviceInfo = @{ parse_error = $_.Exception.Message }
    }
}

$directoryNames = @("DATABASE", "MEDIA", "IMPORTS", "EXPORTS", "BACKUPS", "LOGS")
$directories = [ordered]@{}
foreach ($name in $directoryNames) {
    $directories[$name] = Get-FolderStats -Path (Join-Path $StorageRoot $name)
}

$databaseFolder = Join-Path $StorageRoot "DATABASE"
$databaseFiles = @()
if (Test-Path -LiteralPath $databaseFolder -PathType Container) {
    $databaseFiles = @(Get-ChildItem -LiteralPath $databaseFolder -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".db", ".sqlite", ".sqlite3") } |
        ForEach-Object {
            [pscustomobject]@{ path = $_.FullName; bytes = [int64]$_.Length; modified = $_.LastWriteTimeUtc.ToString("o") }
        })
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$pythonVersion = $null
$dbChecks = @()
if ($pythonCommand) {
    $pythonVersion = (& $pythonCommand.Source --version 2>&1 | Out-String).Trim()

    $helperPath = Join-Path $env:TEMP ("hw-sqlite-readonly-{0}.py" -f ([guid]::NewGuid().ToString("N")))
    $pythonHelper = @'
import json
import pathlib
import sqlite3
import sys

path = pathlib.Path(sys.argv[1]).resolve()
result = {"path": str(path), "integrity_check": None, "tables": [], "table_count": 0, "row_count_total": 0, "error": None}
try:
    uri = path.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        connection.execute("PRAGMA query_only = ON")
        result["integrity_check"] = connection.execute("PRAGMA integrity_check").fetchone()[0]
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for (name,) in rows:
            quoted = '"' + name.replace('"', '""') + '"'
            count = connection.execute("SELECT COUNT(*) FROM " + quoted).fetchone()[0]
            result["tables"].append({"name": name, "row_count": count})
            result["row_count_total"] += count
        result["table_count"] = len(result["tables"])
    finally:
        connection.close()
except Exception as error:
    result["error"] = str(error)
print(json.dumps(result, ensure_ascii=False))
'@

    try {
        Set-Content -LiteralPath $helperPath -Value $pythonHelper -Encoding UTF8
        foreach ($dbFile in $databaseFiles) {
            $json = & $pythonCommand.Source $helperPath $dbFile.path 2>$null
            if ($LASTEXITCODE -eq 0 -and $json) {
                $dbChecks += ($json | ConvertFrom-Json)
            } else {
                $dbChecks += [pscustomobject]@{ path = $dbFile.path; error = "Python SQLite check failed"; integrity_check = $null; tables = @() }
            }
        }
    } finally {
        Remove-Item -LiteralPath $helperPath -Force -ErrorAction SilentlyContinue
    }
} else {
    foreach ($dbFile in $databaseFiles) {
        $dbChecks += [pscustomobject]@{ path = $dbFile.path; error = "Python not found; SQLite check skipped"; integrity_check = $null; tables = @() }
    }
}

$gitInfo = $null
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path -LiteralPath (Join-Path $RepositoryRoot ".git")) {
        $branchName = (& git -C $RepositoryRoot branch --show-current 2>$null | Out-String).Trim()
        $head = (& git -C $RepositoryRoot rev-parse HEAD 2>$null | Out-String).Trim()
        $status = @(& git -C $RepositoryRoot status --short 2>$null)
        $gitInfo = [pscustomobject]@{
            repository_root = $RepositoryRoot
            branch = $branchName
            head = $head
            working_tree_change_count = $status.Count
            working_tree_changes = $status
        }
    }
}

$report = [ordered]@{
    audit_type = "read-only"
    generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    computer_name = $env:COMPUTERNAME
    storage_root = $StorageRoot
    volume = if ($volume) {
        [ordered]@{
            drive = $driveRoot
            label = $volume.FileSystemLabel
            filesystem = $volume.FileSystem
            size_bytes = [int64]$volume.Size
            free_bytes = [int64]$volume.SizeRemaining
            disk_number = if ($partition) { $partition.DiskNumber } else { $null }
            disk_model = if ($disk) { $disk.FriendlyName } else { $null }
            bus_type = if ($disk) { [string]$disk.BusType } else { $null }
        }
    } else { $null }
    device_info = [ordered]@{ exists = (Test-Path -LiteralPath $deviceInfoPath -PathType Leaf); valid_json = $deviceInfoValid; selected_fields = $deviceInfo }
    directories = $directories
    database_files = $databaseFiles
    database_checks = $dbChecks
    python_version = $pythonVersion
    git = $gitInfo
    safety = @{
        source_files_modified = $false
        database_open_mode = "read-only"
        database_content_exported = $false
        secrets_collected = $false
    }
}

$parent = Split-Path -Parent $ReportPath
if ($parent -and -not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
$report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Host ""
Write-Host "Read-only audit finished."
Write-Host ("Report: {0}" -f $ReportPath)
Write-Host "No source files or database records were intentionally modified."
