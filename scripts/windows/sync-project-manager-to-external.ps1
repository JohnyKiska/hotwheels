[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$RepositoryRoot = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$DataRoot = 'E:\HW-CATALOG-DATA'
)

$ErrorActionPreference = 'Stop'
$expectedBranch = 'integration/catalog-foundation'
$relativeFiles = @(
    'index.html',
    'project-state.json',
    'project-state.schema.json',
    'README.md'
)

$repo = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$data = [System.IO.Path]::GetFullPath($DataRoot)

$branch = (& git -C $repo branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne $expectedBranch) {
    throw "Run this script from a clean checkout of '$expectedBranch'. Current branch: '$branch'."
}
$dirty = & git -C $repo status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect Git working tree.' }
if ($dirty) {
    throw 'Git working tree is not clean. Commit or safely stash local changes before syncing.'
}

$markerPath = Join-Path $data 'DEVICE_INFO.json'
if (-not (Test-Path -LiteralPath $data -PathType Container)) {
    throw "External storage is not mounted: $data"
}
if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
    throw "Storage identity marker is missing: $markerPath"
}
$marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
if (-not $marker.storage_id -or $marker.layout_version -ne 1) {
    throw 'External storage identity or layout version is invalid.'
}
foreach ($required in @('DATABASE', 'MEDIA', 'IMPORTS', 'EXPORTS', 'BACKUPS')) {
    if (-not (Test-Path -LiteralPath (Join-Path $data $required) -PathType Container)) {
        throw "Expected external storage directory is missing: $required"
    }
}

$source = Join-Path $repo 'docs\project-management'
$destination = Join-Path $data 'PROJECT-MANAGEMENT'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$staging = Join-Path $data "PROJECT-MANAGEMENT.__staging__.$stamp"
$previous = Join-Path $data "PROJECT-MANAGEMENT.previous.$stamp"

foreach ($name in $relativeFiles) {
    $file = Join-Path $source $name
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Required Project Manager file is missing: $file"
    }
}
if (Test-Path -LiteralPath $staging) { throw "Staging destination already exists: $staging" }
if (Test-Path -LiteralPath $previous) { throw "Backup destination already exists: $previous" }

New-Item -ItemType Directory -Path $staging | Out-Null
try {
    $manifest = @()
    foreach ($name in $relativeFiles) {
        $sourceFile = Join-Path $source $name
        $stagedFile = Join-Path $staging $name
        Copy-Item -LiteralPath $sourceFile -Destination $stagedFile
        $sourceHash = (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash
        $stagedHash = (Get-FileHash -LiteralPath $stagedFile -Algorithm SHA256).Hash
        if ($sourceHash -ne $stagedHash) {
            throw "SHA-256 mismatch while staging $name"
        }
        $manifest += [PSCustomObject]@{
            file = $name
            sha256 = $sourceHash
            bytes = (Get-Item -LiteralPath $sourceFile).Length
        }
    }

    if (Test-Path -LiteralPath $destination) {
        Move-Item -LiteralPath $destination -Destination $previous
    }
    try {
        Move-Item -LiteralPath $staging -Destination $destination
    }
    catch {
        if ((Test-Path -LiteralPath $previous) -and -not (Test-Path -LiteralPath $destination)) {
            Move-Item -LiteralPath $previous -Destination $destination
        }
        throw
    }

    foreach ($entry in $manifest) {
        $targetFile = Join-Path $destination $entry.file
        $targetHash = (Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash
        if ($targetHash -ne $entry.sha256) {
            throw "SHA-256 mismatch in final destination: $($entry.file)"
        }
    }

    Write-Host "Project Manager snapshot synchronized successfully."
    Write-Host "Storage ID: $($marker.storage_id)"
    Write-Host "Destination: $destination"
    Write-Host "Verified files: $($manifest.Count)"
    $manifest | Format-Table -AutoSize
    if (Test-Path -LiteralPath $previous) {
        Write-Host "Previous snapshot preserved at: $previous"
    }
}
finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}
