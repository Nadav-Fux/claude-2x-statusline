# claude-2x-statusline installer for Windows (PowerShell)
# Usage: irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex

$ErrorActionPreference = 'Stop'

$claudeDir = "$env:USERPROFILE\.claude"
$binDir = "$claudeDir\bin"
$settingsFile = "$claudeDir\settings.json"

# Create bin directory
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir -Force | Out-Null }

# Download statusline.ps1
$scriptUrl = "https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/statusline.ps1"
$scriptPath = "$binDir\statusline.ps1"
Invoke-WebRequest -Uri $scriptUrl -OutFile $scriptPath
Write-Host "Downloaded statusline.ps1 to $scriptPath" -ForegroundColor Green

# Update settings.json
if (Test-Path $settingsFile) {
    $settings = Get-Content $settingsFile -Raw | ConvertFrom-Json
} else {
    $settings = [PSCustomObject]@{}
}

$settings | Add-Member -NotePropertyName 'statusLine' -NotePropertyValue @{
    type = "command"
    command = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
} -Force

$settings | ConvertTo-Json -Depth 10 | Set-Content $settingsFile -Encoding UTF8
Write-Host "Updated $settingsFile" -ForegroundColor Green

# VS Code / forks extension
$editors = @(
    @{ name='VS Code';      cmd='code' },
    @{ name='Cursor';       cmd='cursor' },
    @{ name='Windsurf';     cmd='windsurf' },
    @{ name='Antigravity';  cmd='agy' }
)
$detected = @()
foreach ($ed in $editors) {
    if (Get-Command $ed.cmd -ErrorAction SilentlyContinue) { $detected += $ed }
}

if ($detected.Count -gt 0) {
    $names = ($detected | ForEach-Object { $_.name }) -join ', '
    Write-Host ""
    Write-Host "Detected: $names. Building statusline extension..." -ForegroundColor Cyan

    $vscodeDir = "$binDir\vscode-extension"
    if (-not (Test-Path $vscodeDir)) { New-Item -ItemType Directory -Path $vscodeDir -Force | Out-Null }

    $baseUrl = "https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/vscode"
    @('extension.ts', 'package.json', 'package-lock.json', 'tsconfig.json', 'icon.png', 'LICENSE') | ForEach-Object {
        Invoke-WebRequest -Uri "$baseUrl/$_" -OutFile "$vscodeDir\$_"
    }

    Push-Location $vscodeDir
    $built = $false
    try {
        npm install --silent 2>$null
        npm run compile --silent 2>$null
        npx @vscode/vsce package --allow-missing-repository --out claude-statusline.vsix 2>$null
        $built = $true
    } catch {
        Write-Host "Extension build failed (optional). You can build manually from vscode/ folder." -ForegroundColor Yellow
    }

    if ($built) {
        foreach ($ed in $detected) {
            try {
                & $ed.cmd --install-extension claude-statusline.vsix --force 2>$null
                Write-Host "  Installed in $($ed.name)!" -ForegroundColor Green
            } catch {
                Write-Host "  Could not install in $($ed.name) (install manually via VSIX)." -ForegroundColor Yellow
            }
        }
    }
    Pop-Location
} else {
    Write-Host ""
    Write-Host "No supported editors detected (VS Code, Cursor, Windsurf, Antigravity)." -ForegroundColor Yellow
    Write-Host "To install later: clone the repo and run 'npm run package' in the vscode/ folder." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Done! Restart Claude Code to see the status line." -ForegroundColor Cyan
