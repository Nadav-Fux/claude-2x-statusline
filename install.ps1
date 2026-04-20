# claude-2x-statusline installer for Windows (PowerShell)
# Usage: irm https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/install.ps1 | iex

param(
    [string]$Tier,
    [switch]$Update,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

$RepoUrl = 'https://github.com/Nadav-Fux/claude-2x-statusline.git'
$ZipUrl = 'https://github.com/Nadav-Fux/claude-2x-statusline/archive/refs/heads/main.zip'
$TelemetryUrl = 'https://statusline-telemetry.nadavf.workers.dev/ping'
$ClaudeDir = Join-Path $env:USERPROFILE '.claude'
$RepoDir = Join-Path $ClaudeDir 'cc-2x-statusline'
$SettingsFile = Join-Path $ClaudeDir 'settings.json'
$ConfigFile = Join-Path $ClaudeDir 'statusline-config.json'
$ScheduleCache = Join-Path $ClaudeDir 'statusline-schedule.json'
$TelemetryIdFile = Join-Path $ClaudeDir '.statusline-telemetry-id'
$DefaultScheduleUrl = 'https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json'
$DefaultScheduleCacheHours = 3

function Test-RepoRoot {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }

    return (Test-Path (Join-Path $Path 'statusline.sh')) -and (Test-Path (Join-Path $Path 'plugin.json'))
}

function Select-Tier {
    param([string]$Choice)

    $normalizedChoice = if ($null -eq $Choice) { '' } else { [string]$Choice }
    switch ($normalizedChoice.ToLowerInvariant()) {
        '1' { return @{ tier = 'minimal'; mode = 'minimal' } }
        'minimal' { return @{ tier = 'minimal'; mode = 'minimal' } }
        '2' { return @{ tier = 'standard'; mode = 'minimal' } }
        'standard' { return @{ tier = 'standard'; mode = 'minimal' } }
        '3' { return @{ tier = 'full'; mode = 'full' } }
        'full' { return @{ tier = 'full'; mode = 'full' } }
        '' { return @{ tier = 'full'; mode = 'full' } }
        default { throw "Unknown tier: $Choice" }
    }
}

function Read-ExistingConfig {
    if (-not (Test-Path $ConfigFile)) {
        return $null
    }

    try {
        return Get-Content $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Choose-Tier {
    if ($Tier) {
        return Select-Tier $Tier
    }

    if ($Update) {
        $existing = Read-ExistingConfig
        if ($existing -and $existing.tier) {
            $existingMode = if ($existing.mode) { [string]$existing.mode } else { 'full' }
            return @{ tier = [string]$existing.tier; mode = $existingMode }
        }
    }

    if ($Quiet) {
        return Select-Tier 'full'
    }

    Write-Host ''
    Write-Host '  Choose your tier:'
    Write-Host ''
    Write-Host '    1) Minimal   - peak status + model + git + rate limits'
    Write-Host '    2) Standard  - + cost + full context'
    Write-Host '    3) Full      - + multiline timeline + rate limit dashboard (recommended)'
    Write-Host ''
    $choice = Read-Host '  Pick a tier [1/2/3] (default: 3)'
    if ([string]::IsNullOrWhiteSpace($choice)) {
        $choice = '3'
    }
    return Select-Tier $choice
}

function Get-ExecutablePath {
    param(
        [string[]]$Names,
        [string[]]$ExtraPaths = @(),
        [switch]$RejectWindowsApps
    )

    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source) {
            if ($RejectWindowsApps -and $command.Source -match 'WindowsApps') {
                continue
            }
            return $command.Source
        }
    }

    foreach ($path in $ExtraPaths) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path $path)) {
            if ($RejectWindowsApps -and $path -match 'WindowsApps') {
                continue
            }
            return $path
        }
    }

    return $null
}

function Get-GitBashPath {
    $programFilesX86 = ${env:ProgramFiles(x86)}
    return Get-ExecutablePath -Names @('bash') -ExtraPaths @(
        (Join-Path $env:ProgramFiles 'Git\bin\bash.exe'),
        (Join-Path $env:ProgramFiles 'Git\usr\bin\bash.exe'),
        ($(if ($programFilesX86) { Join-Path $programFilesX86 'Git\bin\bash.exe' } else { $null })),
        ($(if ($programFilesX86) { Join-Path $programFilesX86 'Git\usr\bin\bash.exe' } else { $null }))
    )
}

function Get-PythonPath {
    return Get-ExecutablePath -Names @('python3', 'python') -ExtraPaths @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python39\python.exe')
    ) -RejectWindowsApps
}

function Get-NodePath {
    return Get-ExecutablePath -Names @('node') -ExtraPaths @(
        (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
        (Join-Path $env:APPDATA 'nvm\node.exe')
    ) -RejectWindowsApps
}

function Test-Python39 {
    param([string]$PythonPath)

    if (-not $PythonPath) {
        return $false
    }

    & $PythonPath -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Expand-RepoZip {
    param([string]$DestinationRoot)

    $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("cc-2x-statusline-" + [Guid]::NewGuid().ToString('N'))
    $zipPath = Join-Path $tempDir 'repo.zip'
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $tempDir -Force
    $root = Get-ChildItem $tempDir -Directory | Where-Object { $_.Name -like 'claude-2x-statusline-*' } | Select-Object -First 1
    if (-not $root) {
        throw 'Could not locate extracted repository root.'
    }
    return $root.FullName
}

function Sync-SourceTree {
    param(
        [string]$SourceDir,
        [string]$TargetDir
    )

    if ($SourceDir.TrimEnd('\') -ieq $TargetDir.TrimEnd('\')) {
        return
    }

    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    $excluded = @('.git', 'node_modules', '.wrangler')
    foreach ($item in Get-ChildItem -LiteralPath $SourceDir -Force) {
        if ($excluded -contains $item.Name) {
            continue
        }

        $destination = Join-Path $TargetDir $item.Name
        if ($item.PSIsContainer) {
            if (Test-Path $destination) {
                Remove-Item $destination -Recurse -Force -ErrorAction SilentlyContinue
            }
            Copy-Item $item.FullName $destination -Recurse -Force
        } else {
            Copy-Item $item.FullName $destination -Force
        }
    }
}

function Resolve-SourceDir {
    $sourceDir = $null
    if (Test-RepoRoot $PSScriptRoot) {
        $sourceDir = $PSScriptRoot
    }

    $gitPath = Get-ExecutablePath -Names @('git')
    if ($sourceDir -and $sourceDir.TrimEnd('\') -ieq $RepoDir.TrimEnd('\') -and $gitPath -and (Test-Path (Join-Path $RepoDir '.git'))) {
        & $gitPath -C $RepoDir pull --ff-only | Out-Host
        return $RepoDir
    }

    if (-not $sourceDir) {
        if ($gitPath -and (Test-Path (Join-Path $RepoDir '.git'))) {
            & $gitPath -C $RepoDir pull --ff-only | Out-Host
            return $RepoDir
        }

        if ($gitPath) {
            if (Test-Path $RepoDir) {
                Remove-Item $RepoDir -Recurse -Force -ErrorAction SilentlyContinue
            }
            & $gitPath clone $RepoUrl $RepoDir | Out-Host
            return $RepoDir
        }

        return Expand-RepoZip -DestinationRoot $RepoDir
    }

    return $sourceDir
}

function Format-CommandString {
    param(
        [string]$Executable,
        [string[]]$Arguments = @()
    )

    $parts = @("`"$Executable`"")
    foreach ($argument in $Arguments) {
        $parts += "`"$argument`""
    }
    return ($parts -join ' ')
}

function Convert-ToBashPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $Path
    }

    if ($Path -match '^[A-Za-z]:\\') {
        $drive = $Path.Substring(0, 1).ToLowerInvariant()
        $rest = $Path.Substring(2).Replace('\', '/')
        return "/$drive$rest"
    }

    return $Path.Replace('\', '/')
}

function Get-TelemetryId {
    try {
        if (Test-Path $TelemetryIdFile) {
            $existing = (Get-Content $TelemetryIdFile -Raw -Encoding UTF8).Trim().ToLowerInvariant()
            if ($existing -match '^[0-9a-f]{16}$') {
                return $existing
            }
        }

        $bytes = New-Object byte[] 8
        [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
        $hex = -join ($bytes | ForEach-Object { $_.ToString('x2') })
        Set-Content -Path $TelemetryIdFile -Value $hex -Encoding ASCII
        return $hex
    } catch {
        return $null
    }
}

function Send-Telemetry {
    param([hashtable]$Payload)

    if ($env:STATUSLINE_DISABLE_TELEMETRY -eq '1') {
        return
    }

    try {
        $json = $Payload | ConvertTo-Json -Depth 10 -Compress
        Invoke-WebRequest -Uri $TelemetryUrl -Method Post -Body $json -ContentType 'application/json' -TimeoutSec 5 -UseBasicParsing | Out-Null
    } catch {
    }
}

function Run-DoctorWithBash {
    param(
        [string]$BashPath,
        [string]$RepoPath
    )

    $doctorScript = Join-Path $RepoPath 'doctor\doctor.sh'
    if (-not (Test-Path $doctorScript)) {
        return @{ ok = 0; warn = 1; fail = 0; failed_ids = @('doctor_unavailable') }
    }

    try {
        $previousHome = if (Test-Path Env:HOME) { $env:HOME } else { $null }
        try {
            $env:HOME = $env:USERPROFILE
            $json = & $BashPath $doctorScript --json 2>$null
        } finally {
            if ($null -ne $previousHome) {
                $env:HOME = $previousHome
            } else {
                Remove-Item Env:HOME -ErrorAction SilentlyContinue
            }
        }
        if (-not $json) {
            return @{ ok = 0; warn = 1; fail = 0; failed_ids = @('doctor_unavailable') }
        }
        $parsed = $json | ConvertFrom-Json
        $failedIds = @()
        $checks = if ($parsed.checks) { $parsed.checks } else { @() }
        foreach ($check in $checks) {
            if ($check.status -eq 'fail' -and $check.id) {
                $failedIds += [string]$check.id
            }
        }
        return @{ ok = [int]$parsed.ok; warn = [int]$parsed.warn; fail = [int]$parsed.fail; failed_ids = $failedIds }
    } catch {
        return @{ ok = 0; warn = 1; fail = 0; failed_ids = @('doctor_unavailable') }
    }
}

function Run-MinimalPowerShellHealthCheck {
    param(
        [string]$RepoPath,
        [bool]$HooksExpected
    )

    $failedIds = @()
    $ok = 0
    $warn = 0
    $fail = 0
    $statuslinePs1 = Join-Path $RepoPath 'statusline.ps1'

    if (-not (Test-Path $SettingsFile)) {
        $fail += 1
        $failedIds += 'settings_missing'
    } else {
        $settings = Get-Content $SettingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $settings.statusLine -or -not $settings.statusLine.command) {
            $fail += 1
            $failedIds += 'statusline_missing'
        } else {
            $ok += 1
        }
    }

    try {
        $output = & $statuslinePs1 2>$null | Out-String
        if ([string]::IsNullOrWhiteSpace($output)) {
            $warn += 1
            $failedIds += 'statusline_smoke_empty'
        } else {
            $ok += 1
        }
    } catch {
        $fail += 1
        $failedIds += 'statusline_smoke_failed'
    }

    if (-not $HooksExpected) {
        $warn += 1
        $failedIds += 'narrator_unavailable'
    }

    return @{ ok = $ok; warn = $warn; fail = $fail; failed_ids = $failedIds }
}

function Install-EditorExtension {
    param([string]$RepoPath)

    $editors = @(
        @{ name = 'VS Code'; cmd = 'code' },
        @{ name = 'Cursor'; cmd = 'cursor' },
        @{ name = 'Windsurf'; cmd = 'windsurf' },
        @{ name = 'Antigravity'; cmd = 'agy' }
    )
    $detected = @()
    foreach ($editor in $editors) {
        if (Get-Command $editor.cmd -ErrorAction SilentlyContinue) {
            $detected += $editor
        }
    }

    if ($detected.Count -eq 0) {
        Write-Host ''
        Write-Host 'No supported editors detected (VS Code, Cursor, Windsurf, Antigravity).' -ForegroundColor Yellow
        return
    }

    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Host ''
        Write-Host 'npm not found; skipping extension build.' -ForegroundColor Yellow
        return
    }

    $names = ($detected | ForEach-Object { $_.name }) -join ', '
    Write-Host ''
    Write-Host "Detected: $names. Building statusline extension..." -ForegroundColor Cyan

    Push-Location (Join-Path $RepoPath 'vscode')
    try {
        npm install --silent 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw 'npm install failed'
        }
        npm run compile --silent 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw 'npm run compile failed'
        }
        if (Test-Path 'claude-statusline.vsix') {
            Remove-Item 'claude-statusline.vsix' -Force
        }
        $vsceCmd = Join-Path (Get-Location).Path 'node_modules\.bin\vsce.cmd'
        if (-not (Test-Path $vsceCmd)) {
            throw 'local vsce binary missing'
        }

        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            cmd /c "`"$vsceCmd`" package --allow-missing-repository --out claude-statusline.vsix 2>&1" | Out-Host
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        if ($LASTEXITCODE -ne 0 -or -not (Test-Path 'claude-statusline.vsix')) {
            throw 'vsce package failed'
        }
        foreach ($editor in $detected) {
            try {
                & $editor.cmd --install-extension claude-statusline.vsix --force 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  Installed in $($editor.name)!" -ForegroundColor Green
                } else {
                    Write-Host "  Could not install in $($editor.name) (install manually via VSIX)." -ForegroundColor Yellow
                }
            } catch {
                Write-Host "  Could not install in $($editor.name) (install manually via VSIX)." -ForegroundColor Yellow
            }
        }
    } catch {
        Write-Host 'Extension build failed (optional). You can build manually from vscode/ folder.' -ForegroundColor Yellow
    } finally {
        Pop-Location
    }
}

Write-Host ''
Write-Host '  claude-2x-statusline installer' -ForegroundColor Cyan
Write-Host ''

$selectedTier = Choose-Tier
$sourceDir = Resolve-SourceDir
Sync-SourceTree -SourceDir $sourceDir -TargetDir $RepoDir

. (Join-Path $RepoDir 'lib\Wire-Json.ps1')

$existingConfig = Read-ExistingConfig
$scheduleUrl = if ($existingConfig -and $existingConfig.schedule_url) { [string]$existingConfig.schedule_url } else { $DefaultScheduleUrl }
$scheduleCacheHours = if ($existingConfig -and $existingConfig.schedule_cache_hours) { [int]$existingConfig.schedule_cache_hours } else { $DefaultScheduleCacheHours }

$bashPath = Get-GitBashPath
$pythonPath = Get-PythonPath
$nodePath = Get-NodePath
$python39 = Test-Python39 -PythonPath $pythonPath

if ($bashPath) {
    Write-Host "  Runtime: Git Bash at $bashPath" -ForegroundColor Green
} else {
    Write-Host '  Runtime: pure PowerShell path (Git Bash not found)' -ForegroundColor Yellow
}
if ($pythonPath -and $python39) {
    Write-Host "  Python: $pythonPath (narrator ready)" -ForegroundColor Green
} elseif ($pythonPath) {
    Write-Host "  Python: $pythonPath (statusline works, narrator waits for Python 3.9+)" -ForegroundColor Yellow
} elseif ($nodePath) {
    Write-Host "  Node.js: $nodePath" -ForegroundColor Yellow
} else {
    Write-Host '  No Python or Node found; Bash/PowerShell fallback only.' -ForegroundColor Yellow
}

New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ClaudeDir 'commands') -Force | Out-Null

Set-SettingsEntry -TargetPath $ConfigFile -Merge @{
    tier = $selectedTier.tier
    mode = $selectedTier.mode
    schedule_url = $scheduleUrl
    schedule_cache_hours = $scheduleCacheHours
}
Write-Host "  Config saved to $ConfigFile" -ForegroundColor Green

$statuslineSh = Join-Path $RepoDir 'statusline.sh'
$statuslinePs1 = Join-Path $RepoDir 'statusline.ps1'
$hookSessionStart = Join-Path $RepoDir 'hooks\narrator-session-start.sh'
$hookPromptSubmit = Join-Path $RepoDir 'hooks\narrator-prompt-submit.sh'

if ($bashPath) {
    $statusLineCommand = Format-CommandString -Executable $bashPath -Arguments @((Convert-ToBashPath $statuslineSh))
} else {
    $statusLineCommand = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$statuslinePs1`""
}

Set-SettingsEntry -TargetPath $SettingsFile -Merge @{
    statusLine = @{
        type = 'command'
        command = $statusLineCommand
    }
}
Write-Host "  Updated $SettingsFile" -ForegroundColor Green

$hooksExpected = $false
if ($bashPath) {
    $hooksExpected = $true
    $hookSessionCommand = Format-CommandString -Executable $bashPath -Arguments @((Convert-ToBashPath $hookSessionStart))
    $hookPromptCommand = Format-CommandString -Executable $bashPath -Arguments @((Convert-ToBashPath $hookPromptSubmit))

    # Migration: strip legacy narrator entries written in the flat
    # {type, command} form by older installers. Without this, re-running
    # install leaves the broken entry alongside the new correct one.
    if (Test-Path $SettingsFile) {
        try {
            $raw = Get-Content $SettingsFile -Raw -Encoding UTF8
            $obj = $raw | ConvertFrom-Json
            $changed = $false
            if ($obj.PSObject.Properties.Name -contains 'hooks' -and $obj.hooks) {
                foreach ($event in 'SessionStart', 'UserPromptSubmit') {
                    if ($obj.hooks.PSObject.Properties.Name -contains $event) {
                        $arr = @($obj.hooks.$event)
                        $kept = @()
                        foreach ($entry in $arr) {
                            $isLegacy = $false
                            if ($entry -and $entry.PSObject.Properties.Name -contains 'command' `
                                -and -not ($entry.PSObject.Properties.Name -contains 'hooks')) {
                                $cmd = [string]$entry.command
                                if ($cmd -match 'narrator-session-start\.sh' -or $cmd -match 'narrator-prompt-submit\.sh') {
                                    $isLegacy = $true
                                }
                            }
                            if (-not $isLegacy) { $kept += ,$entry }
                        }
                        if ($kept.Count -ne $arr.Count) {
                            $obj.hooks.$event = $kept
                            $changed = $true
                        }
                    }
                }
            }
            if ($changed) {
                ($obj | ConvertTo-Json -Depth 100) | Set-Content -Path $SettingsFile -Encoding UTF8
                Write-Host '  Legacy narrator hook entries cleaned.' -ForegroundColor Green
            }
        } catch {
            # Non-fatal: proceed to wire the new entries anyway.
        }
    }

    Set-SettingsEntry -TargetPath $SettingsFile -Merge @{
        hooks = @{
            SessionStart = @(@{ hooks = @(@{ type = 'command'; command = $hookSessionCommand }) })
            UserPromptSubmit = @(@{ hooks = @(@{ type = 'command'; command = $hookPromptCommand }) })
        }
    }
    if ($python39) {
        Write-Host '  Narrator hooks wired and ready.' -ForegroundColor Green
    } else {
        Write-Host '  Narrator hooks wired. They will activate automatically once Python 3.9+ is available.' -ForegroundColor Yellow
    }
} else {
    Write-Host '  Narrator hooks skipped: Git Bash is required on Windows for hook execution.' -ForegroundColor Yellow
}

Copy-Item (Join-Path $RepoDir 'commands\*.md') (Join-Path $ClaudeDir 'commands') -Force -ErrorAction SilentlyContinue
Write-Host '  Slash commands installed.' -ForegroundColor Green

try {
    Invoke-WebRequest -Uri $scheduleUrl -OutFile $ScheduleCache -UseBasicParsing -TimeoutSec 5 | Out-Null
    Write-Host '  Schedule downloaded.' -ForegroundColor Green
} catch {
    Write-Host '  Could not fetch schedule (will use defaults).' -ForegroundColor Yellow
}

Install-EditorExtension -RepoPath $RepoDir

Write-Host ''
Write-Host '  Running post-install diagnostics...' -ForegroundColor Cyan
$doctor = if ($bashPath) {
    Run-DoctorWithBash -BashPath $bashPath -RepoPath $RepoDir
} else {
    Run-MinimalPowerShellHealthCheck -RepoPath $RepoDir -HooksExpected:$hooksExpected
}

if ($doctor.fail -gt 0 -or $doctor.warn -gt 0) {
    Write-Host "  Diagnostics: $($doctor.fail) fail, $($doctor.warn) warn" -ForegroundColor Yellow
} else {
    Write-Host '  Diagnostics: all checks passed' -ForegroundColor Green
}

$uid = Get-TelemetryId
if (-not $Update) {
    Send-Telemetry -Payload @{
        id = $uid
        v = '2.2'
        engine = 'installer'
        tier = $selectedTier.tier
        os = 'windows'
        event = 'install'
    }
}

$eventName = if ($Update) { 'update' } else { 'install_result' }
Send-Telemetry -Payload @{
    id = $uid
    v = '2.2'
    engine = 'installer'
    tier = $selectedTier.tier
    os = 'windows'
    event = $eventName
    ok = $doctor.ok
    warn = $doctor.warn
    fail = $doctor.fail
    failed_ids = $doctor.failed_ids
    ps1_only = (-not [bool]$bashPath)
    has_python = [bool]$pythonPath
    has_node = [bool]$nodePath
}

Write-Host ''
Write-Host 'Done. Restart Claude Code to see the status line.' -ForegroundColor Cyan
Write-Host 'Next: /statusline-onboarding' -ForegroundColor Cyan
Write-Host 'Update later: /statusline-update' -ForegroundColor DarkGray