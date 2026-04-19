param(
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

$RepoUrl = 'https://github.com/Nadav-Fux/claude-2x-statusline.git'
$ZipUrl = 'https://github.com/Nadav-Fux/claude-2x-statusline/archive/refs/heads/main.zip'
$RepoDir = Join-Path $env:USERPROFILE '.claude\cc-2x-statusline'

if (-not (Test-Path (Join-Path $RepoDir 'install.ps1'))) {
    throw "Install dir not found at $RepoDir"
}

$git = Get-Command git -ErrorAction SilentlyContinue
if ($git -and (Test-Path (Join-Path $RepoDir '.git'))) {
    Write-Host 'Updating existing git install...' -ForegroundColor Cyan
    & $git.Source -C $RepoDir pull --ff-only | Out-Host
    & (Join-Path $RepoDir 'install.ps1') -Update -Quiet:$true
    exit $LASTEXITCODE
}

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("cc-2x-statusline-update-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    if ($git) {
        Write-Host 'Bootstrapping latest source via git clone...' -ForegroundColor Cyan
        $cloneDir = Join-Path $tempDir 'claude-2x-statusline'
        & $git.Source clone --depth 1 $RepoUrl $cloneDir | Out-Host
        & (Join-Path $cloneDir 'install.ps1') -Update -Quiet:$true
        exit $LASTEXITCODE
    }

    Write-Host 'Bootstrapping latest source via zip download...' -ForegroundColor Cyan
    $zipPath = Join-Path $tempDir 'repo.zip'
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $tempDir -Force
    $sourceDir = Get-ChildItem $tempDir -Directory | Where-Object { $_.Name -like 'claude-2x-statusline-*' } | Select-Object -First 1
    if (-not $sourceDir) {
        throw 'Could not unpack update source.'
    }
    & (Join-Path $sourceDir.FullName 'install.ps1') -Update -Quiet:$true
    exit $LASTEXITCODE
} finally {
    if (Test-Path $tempDir) {
        Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}