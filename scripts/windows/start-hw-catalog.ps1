[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$StorageRoot,
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)
$ErrorActionPreference = "Stop"
function Fail([string]$Message) { Write-Error $Message; exit 1 }

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BackendDir = Join-Path $RepoRoot "backend"
$StorageRoot = [System.IO.Path]::GetFullPath($StorageRoot)
if (-not (Test-Path -LiteralPath $BackendDir -PathType Container)) { Fail "Не найдена папка backend: $BackendDir" }
if (-not (Test-Path -LiteralPath $StorageRoot -PathType Container)) { Fail "Внешний диск или папка хранилища недоступны: $StorageRoot" }

$MarkerPath = Join-Path $StorageRoot "DEVICE_INFO.json"
$DatabaseDir = Join-Path $StorageRoot "DATABASE"
if (-not (Test-Path -LiteralPath $MarkerPath -PathType Leaf)) { Fail "Не найден DEVICE_INFO.json. Сначала инициализируй HDD командой app.init_storage." }
if (-not (Test-Path -LiteralPath $DatabaseDir -PathType Container)) { Fail "Не найдена папка DATABASE на внешнем диске." }

try {
    $Marker = Get-Content -LiteralPath $MarkerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $StorageId = [guid]::Parse([string]$Marker.storage_id)
    if ([int]$Marker.layout_version -ne 1) { Fail "Неподдерживаемый layout_version в DEVICE_INFO.json." }
}
catch { Fail "DEVICE_INFO.json повреждён или имеет неверный формат: $($_.Exception.Message)" }

if ($env:DATABASE_URL) { Fail "Переменная DATABASE_URL задана и перекрывает внешний HDD. Удали её из окружения и повтори запуск." }

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $PythonCommand) { Fail "Python не найден. Установи Python или создай .venv в корне проекта." }
    $PythonExe = $PythonCommand.Source
}

$LocalStateDir = Join-Path $env:LOCALAPPDATA "HW-Catalog"
New-Item -ItemType Directory -Path $LocalStateDir -Force | Out-Null
$PidFile = Join-Path $LocalStateDir "backend-$Port.json"
if (Test-Path -LiteralPath $PidFile) {
    try {
        $Existing = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
        $ExistingProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($Existing.process_id)" -ErrorAction SilentlyContinue
        if ($ExistingProcess -and $ExistingProcess.CommandLine -match "uvicorn" -and $ExistingProcess.CommandLine -match "app.main:app") {
            Fail "HW Catalog уже запущен (PID $($Existing.process_id), порт $Port). Сначала останови его через stop-hw-catalog.ps1."
        }
    }
    catch { if ($_.Exception.Message -like "*HW Catalog уже запущен*") { throw } }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

$TcpListener = $null
try {
    $TcpListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $TcpListener.Start()
}
catch { Fail "Порт $Port уже занят. Проверь, не запущен ли другой экземпляр приложения." }
finally { if ($TcpListener) { $TcpListener.Stop() } }

$env:HW_CATALOG_DATA_DIR = $StorageRoot
Push-Location $BackendDir
try {
    Write-Host "Проверяю схему базы и применяю миграции..."
    & $PythonExe -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { Fail "Миграции завершились с ошибкой. Backend не запущен." }
}
finally { Pop-Location }

$LogDir = Join-Path $StorageRoot "LOGS"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$StdoutLog = Join-Path $LogDir "backend-$Port-out.log"
$StderrLog = Join-Path $LogDir "backend-$Port-error.log"
$Server = Start-Process -FilePath $PythonExe -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port $Port" -WorkingDirectory $BackendDir -PassThru -WindowStyle Normal -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog

$PidRecord = [ordered]@{
    process_id = $Server.Id
    port = $Port
    storage_id = $StorageId.ToString()
    storage_root = $StorageRoot
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    stdout_log = $StdoutLog
    stderr_log = $StderrLog
}
$PidRecord | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8

$Ready = $false
for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    Start-Sleep -Seconds 1
    if ($Server.HasExited) { break }
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
        if ($Health.status -eq "ok") { $Ready = $true; break }
    }
    catch { }
}
if (-not $Ready) {
    if ($Server.HasExited) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        Fail "Backend завершился при запуске. Проверь лог: $StderrLog"
    }
    Write-Warning "Backend запущен, но /health пока не ответил. Проверь логи: $StdoutLog и $StderrLog"
}
else { Write-Host "HW Catalog запущен: http://127.0.0.1:$Port" }

Write-Host "PID: $($Server.Id)"
Write-Host "Хранилище: $StorageRoot"
Write-Host "Для безопасной остановки запусти scripts\windows\stop-hw-catalog.ps1."
Write-Host "В открытом окне backend нажми Ctrl+C и дождись завершения процесса."
