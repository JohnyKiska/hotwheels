[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Snapshot,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$DestinationRoot
)
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BackendDir = Join-Path $RepoRoot "backend"
$Snapshot = [System.IO.Path]::GetFullPath($Snapshot)
if (-not (Test-Path -LiteralPath $Snapshot -PathType Container)) { throw "Snapshot не существует или недоступен." }
$DestinationRoot = [System.IO.Path]::GetFullPath($DestinationRoot)

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $PythonCommand) { throw "Python не найден." }
    $PythonExe = $PythonCommand.Source
}

Push-Location $BackendDir
try {
    & $PythonExe -m app.backup_restore restore --snapshot $Snapshot --destination $DestinationRoot
    if ($LASTEXITCODE -ne 0) { throw "Restore завершился с ошибкой (код $LASTEXITCODE)." }
}
finally { Pop-Location }
