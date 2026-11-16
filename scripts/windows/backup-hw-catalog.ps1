[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SourceRoot,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$DestinationRoot,
    [Parameter(Mandatory = $true)]
    [switch]$ConfirmBackendStopped
)
$ErrorActionPreference = "Stop"

if (-not $ConfirmBackendStopped) {
    throw "Сначала штатно останови HW Catalog и повтори запуск с -ConfirmBackendStopped."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BackendDir = Join-Path $RepoRoot "backend"
$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "SourceRoot не существует или недоступен."
}
$DestinationRoot = [System.IO.Path]::GetFullPath($DestinationRoot)

if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot "DEVICE_INFO.json") -PathType Leaf)) {
    throw "В SourceRoot не найден DEVICE_INFO.json."
}
if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot "DATABASE\catalog.db") -PathType Leaf)) {
    throw "В SourceRoot не найден DATABASE\catalog.db."
}

# Fail closed if a PID record still points to this storage and its process is alive.
$LocalStateDir = Join-Path $env:LOCALAPPDATA "HW-Catalog"
if (Test-Path -LiteralPath $LocalStateDir -PathType Container) {
    foreach ($PidFile in Get-ChildItem -LiteralPath $LocalStateDir -Filter "backend-*.json" -File) {
        try {
            $Record = Get-Content -LiteralPath $PidFile.FullName -Raw | ConvertFrom-Json
            $RecordedRoot = [System.IO.Path]::GetFullPath([string]$Record.storage_root)
            if ($RecordedRoot.TrimEnd("\") -ieq $SourceRoot.TrimEnd("\")) {
                $ProcessId = [int]$Record.process_id
                $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
                if ($Process) {
                    throw "Найдена активная PID-запись для этого хранилища (PID $ProcessId). Останови backend штатно."
                }
            }
        }
        catch {
            if ($_.Exception.Message -like "*активная PID-запись*") { throw }
            throw "Не удалось безопасно проверить PID-файл $($PidFile.FullName): $($_.Exception.Message)"
        }
    }
}

# Also detect a manually-started uvicorn backend without a PID record.
$RunningBackend = Get-CimInstance Win32_Process -ErrorAction Stop |
    Where-Object {
        $_.CommandLine -match 'uvicorn' -and
        $_.CommandLine -match 'app\.main:app'
    }
if ($RunningBackend) {
    $Ids = ($RunningBackend | ForEach-Object { $_.ProcessId }) -join ", "
    throw "Обнаружен работающий процесс HW Catalog (PID: $Ids). Backup отменён."
}

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $PythonCommand) { throw "Python не найден." }
    $PythonExe = $PythonCommand.Source
}

Push-Location $BackendDir
try {
    & $PythonExe -m app.backup_restore backup --source $SourceRoot --destination $DestinationRoot --confirm-backend-stopped
    if ($LASTEXITCODE -ne 0) { throw "Backup завершился с ошибкой (код $LASTEXITCODE)." }
}
finally { Pop-Location }
