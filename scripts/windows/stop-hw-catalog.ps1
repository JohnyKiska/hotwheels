[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [ValidateRange(5, 600)]
    [int]$TimeoutSeconds = 120
)
$ErrorActionPreference = "Stop"
$LocalStateDir = Join-Path $env:LOCALAPPDATA "HW-Catalog"
$PidFile = Join-Path $LocalStateDir "backend-$Port.json"
if (-not (Test-Path -LiteralPath $PidFile -PathType Leaf)) {
    Write-Host "Файл состояния не найден. Возможно, HW Catalog уже остановлен."
    exit 0
}
try {
    $Record = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    $ProcessId = [int]$Record.process_id
}
catch {
    Write-Error "Не удалось прочитать файл состояния: $PidFile"
    exit 1
}
$ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
if (-not $ProcessInfo) {
    Remove-Item -LiteralPath $PidFile -Force
    Write-Host "Backend уже остановлен. Файл состояния очищен."
    exit 0
}
if ($ProcessInfo.CommandLine -notmatch "uvicorn" -or $ProcessInfo.CommandLine -notmatch "app.main:app") {
    Write-Error "PID $ProcessId больше не принадлежит ожидаемому процессу HW Catalog. Ничего не останавливаю; проверь файл $PidFile вручную."
    exit 1
}
Write-Host "Найден backend HW Catalog (PID $ProcessId, порт $Port)."
Write-Host "Переключись в отдельное окно backend и нажми там Ctrl+C."
Write-Host "Скрипт дождётся штатного завершения. Принудительно завершать процесс он НЕ будет."
$Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Seconds 1
    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
} while ($ProcessInfo -and (Get-Date) -lt $Deadline)
if ($ProcessInfo) {
    Write-Warning "Backend ещё работает. Не извлекай HDD. Повтори скрипт после Ctrl+C в окне backend."
    exit 2
}
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "Backend штатно завершён. Теперь можно выполнить безопасное извлечение HDD средствами Windows."
