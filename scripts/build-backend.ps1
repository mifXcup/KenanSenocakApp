[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$python = Join-Path $backendRoot '.venv\Scripts\python.exe'
$expectedArtifact = Join-Path $backendRoot 'dist\ks-core\ks-core.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend sanal ortamı bulunamadı: $python"
}

Push-Location $backendRoot
try {
    & $python -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Backend bağımlılık kurulumu başarısız.' }

    & $python -m PyInstaller --noconfirm --clean --distpath dist --workpath build ks-core.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller paketi üretilemedi.' }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $expectedArtifact)) {
    throw "Beklenen sidecar bulunamadı: $expectedArtifact"
}

$artifact = Get-Item -LiteralPath $expectedArtifact
Write-Host "Sidecar hazır: $($artifact.FullName)"
Write-Host "Çalıştırılabilir dosya: $([math]::Round($artifact.Length / 1MB, 2)) MB"

