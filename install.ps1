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
Write-Host ""
Write-Host "Done! Restart Claude Code to see the status line." -ForegroundColor Cyan
