# claude-2x-statusline - modular statusline for Claude Code (PowerShell)
# v2.1 — Peak hours with auto-timezone and remote schedule
# https://github.com/Nadav-Fux/claude-2x-statusline

$ErrorActionPreference = 'Stop'

# ANSI
$E = [char]27
$RST="$E[0m"; $BOLD="$E[1m"; $DIM="$E[2m"
$RED="$E[31m"; $GREEN="$E[32m"; $YELLOW="$E[33m"
$BLUE="$E[34m"; $MAGENTA="$E[35m"; $CYAN="$E[36m"
$WHITE="$E[38;2;220;220;220m"
$BGG="$E[38;5;255;48;5;28m"; $BGY="$E[38;5;16;48;5;220m"
$BGR="$E[38;5;255;48;5;124m"; $BGGRAY="$E[48;5;236m"; $BGBLUE="$E[38;5;255;48;5;27m"

# Tiers
$TIERS = @{
    minimal  = @('peak_hours','model','context','git_branch','git_dirty','rate_limits','effort','env')
    standard = @('peak_hours','model','context','git_branch','git_dirty','cost','rate_limits','effort','env')
    full     = @('peak_hours','model','context','git_branch','git_dirty','cost','effort','env')
}

# Config
$configPath = Join-Path $env:USERPROFILE '.claude\statusline-config.json'
$config = @{ tier='full'; separator=' | '; mode='full'; schedule_url='https://raw.githubusercontent.com/Nadav-Fux/claude-2x-statusline/main/schedule.json'; schedule_cache_hours=3 }
if (Test-Path $configPath) {
    try {
        $userCfg = Get-Content $configPath -Raw | ConvertFrom-Json
        foreach ($p in $userCfg.PSObject.Properties) { $config[$p.Name] = $p.Value }
    } catch {}
}

function Get-LocalStatuslineVersion {
    $packagePath = Join-Path $PSScriptRoot 'package.json'
    if (Test-Path $packagePath) {
        try {
            return [string]((Get-Content $packagePath -Raw | ConvertFrom-Json).version)
        } catch {}
    }
    return ''
}

function Convert-ToVersionObject {
    param([string]$Value)

    if (-not $Value) { return $null }

    $core = ($Value -split '-', 2)[0]
    try {
        return [Version]$core
    } catch {
        $parts = @($core -split '\.' | ForEach-Object {
            if ($_ -match '\d+') { $Matches[0] } else { '0' }
        })
        while ($parts.Count -lt 4) {
            $parts += '0'
        }
        try {
            return [Version]::new([int]$parts[0], [int]$parts[1], [int]$parts[2], [int]$parts[3])
        } catch {
            return $null
        }
    }
}

$CurrentVersion = Get-LocalStatuslineVersion

# Schedule (remote with cache)
function Load-Schedule {
    $cachePath = Join-Path $env:USERPROFILE '.claude\statusline-schedule.json'
    $cacheHours = $config['schedule_cache_hours']
    $url = $config['schedule_url']

    # Check cache
    if (Test-Path $cachePath) {
        try {
            $age = ((Get-Date) - (Get-Item $cachePath).LastWriteTime).TotalHours
            if ($age -lt $cacheHours) {
                return Get-Content $cachePath -Raw | ConvertFrom-Json
            }
        } catch {}
    }

    # Fetch remote
    if ($url) {
        try {
            $resp = Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing
            $resp.Content | Set-Content $cachePath
            return $resp.Content | ConvertFrom-Json
        } catch {}
    }

    # Stale cache
    if (Test-Path $cachePath) {
        try { return Get-Content $cachePath -Raw | ConvertFrom-Json } catch {}
    }

    # Default
    return @{
        v=2; mode='peak_hours'; default_tier='full'
        peak=@{ enabled=$true; tz='America/Los_Angeles'; days=@(1,2,3,4,5); start=5; end=11; label_peak='Peak'; label_offpeak='Off-Peak' }
        banner=@{ text=''; expires=''; color='yellow' }
        labels=@{ five_hour='5h'; weekly='weekly' }
        features=@{ show_peak_segment=$true; show_rate_limits=$true; show_timeline=$true }
    }
}

$schedule = Load-Schedule

# Apply remote default tier if user hasn't set one
if (Test-Path $configPath) {
    try {
        $userKeys = (Get-Content $configPath -Raw | ConvertFrom-Json).PSObject.Properties.Name
        if ($userKeys -notcontains 'tier' -and $schedule.default_tier) {
            $config['tier'] = $schedule.default_tier
        }
    } catch {}
} elseif ($schedule.default_tier) {
    $config['tier'] = $schedule.default_tier
}

$tier = $config['tier']
if ($tier -eq 'custom') {
    $enabled = @($config['segments'].PSObject.Properties | Where-Object { $_.Value -eq $true } | ForEach-Object {
        if ($_.Name -eq 'promo_2x') { 'peak_hours' } else { $_.Name }
    })
} elseif ($TIERS.ContainsKey($tier)) {
    $enabled = $TIERS[$tier]
} else {
    $enabled = $TIERS['full']
}

# Mode
$mode = if ($config['mode']) { $config['mode'] } else { 'full' }
if ($args -contains '--full') { $mode = 'full' }
if ($args -contains '--minimal') { $mode = 'minimal' }

# Stdin
$stdinData = @{}
try {
    $raw = [Console]::In.ReadToEnd()
    if ($raw.Trim()) { $stdinData = $raw | ConvertFrom-Json }
} catch {}

# Timezone — auto-detect local
$now = Get-Date
$utcNow = $now.ToUniversalTime()
$localOffset = ($now - $utcNow).TotalHours
$hour = $now.Hour; $minute = $now.Minute
# PS DayOfWeek: Sunday=0; convert to ISO: Mon=1..Sun=7
$weekday = [int]$now.DayOfWeek; if ($weekday -eq 0) { $weekday = 7 }
$nowMins = $hour * 60 + $minute

# Pacific Time offset (DST-aware)
function Get-PacificOffset {
    $year = $utcNow.Year
    # Second Sunday of March
    $mar1 = [DateTime]::new($year, 3, 1)
    $dstStart = $mar1.AddDays((14 - [int]$mar1.DayOfWeek) % 7 + 7)
    $dstStartUtc = $dstStart.AddHours(10)  # 2AM PST = 10 UTC
    # First Sunday of November
    $nov1 = [DateTime]::new($year, 11, 1)
    $dstEnd = $nov1.AddDays((7 - [int]$nov1.DayOfWeek) % 7)
    $dstEndUtc = $dstEnd.AddHours(9)  # 2AM PDT = 9 UTC
    if ($utcNow -ge $dstStartUtc -and $utcNow -lt $dstEndUtc) { return -7 }
    return -8
}
$ptOffset = Get-PacificOffset

# Convert peak hours to local time
$peak = $schedule.peak
$peakStart = if ($peak.start) { [int]$peak.start } else { 5 }
$peakEnd = if ($peak.end) { [int]$peak.end } else { 11 }
$peakDays = if ($peak.days) { @($peak.days) } else { @(1,2,3,4,5) }

function Shift-Weekday {
    param([int]$Day, [int]$Delta)

    return (((($Day - 1 + $Delta) % 7) + 7) % 7) + 1
}

$rawPeakStartLocal = $peakStart - $ptOffset + $localOffset
$peakDayOffset = [Math]::Floor($rawPeakStartLocal / 24)
$peakStartLocal = (($rawPeakStartLocal % 24) + 24) % 24
$peakEndLocal = ((($peakEnd - $ptOffset + $localOffset) % 24) + 24) % 24
$effectivePeakDays = @($peakDays | ForEach-Object { Shift-Weekday -Day ([int]$_) -Delta ([int]$peakDayOffset) })

# Helpers
function FmtDur($mins) {
    $total = [Math]::Floor([double]$mins)
    $h = [Math]::Floor($total / 60)
    $m = [int]($total % 60)
    if($h -gt 0){"${h}h $("{0:D2}" -f $m)m"}else{"${m}m"}
}
function FmtSecs($s) {
    $total = [Math]::Floor([double]$s)
    $h = [Math]::Floor($total / 3600)
    $m = [Math]::Floor(($total % 3600) / 60)
    $sec = [int]($total % 60)
    if($h -gt 0){"${h}h$("{0:D2}" -f $m)m"}elseif($m -gt 0){"${m}m$("{0:D2}" -f $sec)s"}else{"${sec}s"}
}
function ColorPct($p) { if($p -ge 80){$script:RED}elseif($p -ge 50){$script:YELLOW}else{$script:GREEN} }
function GitCmd { param([string[]]$a) try { $r = & git @a 2>$null; if($r){$r.Trim()}else{''} } catch { '' } }
function FmtHour($h) {
    $normalized = (($h % 24) + 24) % 24
    $hourPart = [Math]::Floor($normalized)
    $minutePart = [Math]::Round(($normalized - $hourPart) * 60)
    if ($minutePart -eq 60) {
        $hourPart = ($hourPart + 1) % 24
        $minutePart = 0
    }
    $ampm = if($hourPart -lt 12){'am'}else{'pm'}
    $display = $hourPart % 12
    if($display -eq 0){$display=12}
    if ($minutePart -gt 0) { return "${display}:$('{0:D2}' -f $minutePart)${ampm}" }
    return "${display}${ampm}"
}

# Context
$ctx = @{ isPeak=$false; gitBranch=''; usageData=$null }

# -- Segments --

function Seg_banner {
    $badges = @()
    $release = $schedule.release
    if ($release -and $CurrentVersion) {
        $latestVersion = if ($release.latest_version) { [string]$release.latest_version } else { '' }
        $minimumVersion = if ($release.minimum_version) { [string]$release.minimum_version } else { '' }
        $command = if ($release.command) { [string]$release.command } else { '/statusline-update' }
        $targetVersion = if ($latestVersion) { $latestVersion } else { $minimumVersion }
        $currentVersionObj = Convert-ToVersionObject $CurrentVersion
        $latestVersionObj = Convert-ToVersionObject $latestVersion
        $minimumVersionObj = Convert-ToVersionObject $minimumVersion

        if ($currentVersionObj -and $minimumVersionObj -and $currentVersionObj -lt $minimumVersionObj) {
            $text = if ($release.required_text) { [string]$release.required_text } else { "Update required v$targetVersion via $command" }
            $badges += "${BGR} ${text} ${RST}"
        } elseif ($currentVersionObj -and $latestVersionObj -and $currentVersionObj -lt $latestVersionObj) {
            $text = if ($release.available_text) { [string]$release.available_text } else { "Update available v$latestVersion via $command" }
            $badges += "${BGY} ${text} ${RST}"
        }
    }

    $b = $schedule.banner
    if ($b -and $b.text) {
        $showBanner = $true
        if ($b.expires) {
            try {
                if ((Get-Date).Date -gt ([DateTime]::Parse($b.expires)).Date) { $showBanner = $false }
            } catch {}
        }
        if ($showBanner) {
            $colors = @{ yellow=$BGY; red=$BGR; green=$BGG; blue=$BGBLUE; gray=$BGGRAY }
            $bg = if ($colors[$b.color]) { $colors[$b.color] } else { $BGY }
            $badges += "${bg} $($b.text) ${RST}"
        }
    }

    return ($badges -join ' ')
}

function Seg_peak_hours {
    # mode=normal → segment disappears
    if ($schedule.mode -eq 'normal') { return '' }

    $peakEnabled = if ($peak.enabled -ne $null) { $peak.enabled } else { $true }
    if (-not $peakEnabled) { return "${BGG} Off-Peak${RST}" }

    $currentHour = $hour + $minute / 60.0
    $isPeakDay = $weekday -in $effectivePeakDays
    $prevWeekday = if ($weekday -eq 1) { 7 } else { $weekday - 1 }
    $prevWasPeak = $prevWeekday -in $effectivePeakDays

    $isPeak = $false; $minsLeft = 0; $minsUntil = 0
    $peakSMins = $peakStartLocal * 60; $peakEMins = $peakEndLocal * 60

    if ($isPeakDay -or $prevWasPeak) {
        if ($peakEMins -gt $peakSMins) {
            # Normal case
            if ($nowMins -ge $peakSMins -and $nowMins -lt $peakEMins) {
                $isPeak = $true; $minsLeft = $peakEMins - $nowMins
            } elseif ($nowMins -lt $peakSMins) {
                $minsUntil = $peakSMins - $nowMins
            } else {
                $minsUntil = MinsUntilNextPeak -CurrentHour $currentHour -CurrentWeekday $weekday -StartLocalHour $peakStartLocal -Days $effectivePeakDays
            }
        } else {
            # Crosses midnight
            if (($isPeakDay -and $nowMins -ge $peakSMins) -or ($prevWasPeak -and $nowMins -lt $peakEMins)) {
                $isPeak = $true
                $minsLeft = if ($nowMins -ge $peakSMins) { (1440 - $nowMins) + $peakEMins } else { $peakEMins - $nowMins }
            } elseif ($isPeakDay -and $nowMins -lt $peakSMins) {
                $minsUntil = $peakSMins - $nowMins
            } else {
                $minsUntil = MinsUntilNextPeak -CurrentHour $currentHour -CurrentWeekday $weekday -StartLocalHour $peakStartLocal -Days $effectivePeakDays
            }
        }
    } else {
        $minsUntil = MinsUntilNextPeak -CurrentHour $currentHour -CurrentWeekday $weekday -StartLocalHour $peakStartLocal -Days $effectivePeakDays
    }

    $ctx.isPeak = $isPeak
    $labelPeak = if ($peak.label_peak) { $peak.label_peak } else { 'Peak' }
    $labelOff = if ($peak.label_offpeak) { $peak.label_offpeak } else { 'Off-Peak' }

    if ($isPeak) {
        $t = FmtDur $minsLeft
        $bg = if ($minsLeft -le 30) { $BGG } elseif ($minsLeft -le 120) { $BGY } else { $BGR }
        $range = "${DIM}$(FmtHour $peakStartLocal)-$(FmtHour $peakEndLocal)${RST}"
        return "${bg} ${labelPeak} ${RST} ${WHITE}-> ends in ${t}${RST} ${range}"
    } else {
        if ($minsUntil -gt 0) {
            $t = FmtDur $minsUntil
            return "${BGG} ${labelOff} ${RST} ${DIM}peak in ${t}${RST}"
        }
        return "${BGG} ${labelOff} ${RST}"
    }
}

function MinsUntilNextPeak {
    param(
        [double]$CurrentHour,
        [int]$CurrentWeekday,
        [double]$StartLocalHour,
        [int[]]$Days
    )

    for ($offset = 1; $offset -le 7; $offset++) {
        $nextDay = (($CurrentWeekday - 1 + $offset) % 7) + 1
        if ($nextDay -in $Days) {
            return [Math]::Floor((24 - $CurrentHour) * 60) + ($offset - 1) * 1440 + [Math]::Floor($StartLocalHour * 60)
        }
    }
    return 0
}

function Seg_model { $n = $stdinData.model.display_name; if($n){ $short = ($n -split '\(')[0].Trim(); "${BLUE}${short}${RST}" }else{''} }

function Seg_context {
    $cw = $stdinData.context_window; if(-not $cw){return ''}
    $size = $cw.context_window_size; if(-not $size -or $size -eq 0){return ''}
    $u = $cw.current_usage
    $cur = [int]$u.input_tokens + [int]$u.cache_creation_input_tokens + [int]$u.cache_read_input_tokens
    $pct = [Math]::Floor($cur * 100 / $size)
    $c = ColorPct $pct
    # Write context data for VS Code extension
    try {
        $ctxDir = Join-Path $env:TEMP 'claude'
        if (-not (Test-Path $ctxDir)) { New-Item -ItemType Directory -Path $ctxDir -Force | Out-Null }
        $ctxFile = Join-Path $ctxDir 'statusline-context.json'
        $modelName = $stdinData.model.display_name
        @{ current_usage=$cur; context_window_size=$size; pct=$pct; model=$modelName; updated_at=(Get-Date -Format o) } | ConvertTo-Json | Set-Content $ctxFile
    } catch {}
    if ($tier -eq 'minimal') { return "${DIM}CTX${RST} ${c}${pct}%${RST}" }
    $curK = if ($cur -ge 1000000) { "{0:F1}M" -f ($cur/1000000) } elseif ($cur -ge 1000) { "{0}K" -f [Math]::Floor($cur/1000) } else { "$cur" }
    $sizeK = if ($size -ge 1000000) { "{0:F1}M" -f ($size/1000000) } else { "{0}K" -f [Math]::Floor($size/1000) }
    return "${c}${curK}/${sizeK}${RST} ${c}${pct}%${RST}"
}

function Seg_git_branch { $b = GitCmd 'branch','--show-current'; $ctx.gitBranch=$b; if($b){"${DIM}${b}${RST}"}else{''} }

function Seg_git_dirty {
    $p = GitCmd 'status','--porcelain'
    $uncommitted = if ($p) { @($p -split "`n" | Where-Object{$_}).Count } else { 0 }
    $unpushed = 0
    if ($ctx.gitBranch) { $a = GitCmd 'rev-list','--count','@{u}..HEAD'; if ($a -and $a -ne '0') { $unpushed = [int]$a } }
    if (-not $uncommitted -and -not $unpushed) { return "${GREEN}saved${RST}" }
    if ($uncommitted -and $unpushed) { return "${YELLOW}${uncommitted} changed, ${unpushed} unpushed${RST}" }
    if ($uncommitted) { return "${YELLOW}${uncommitted} unsaved${RST}" }
    return "${YELLOW}${unpushed} unpushed${RST}"
}

function Seg_cost { $c = $stdinData.cost.total_cost_usd; if ($null -eq $c) { return '' }; $f = '{0:F2}' -f [double]$c; "${MAGENTA}`$$f${RST}" }
function Seg_duration { $ms = $stdinData.cost.total_duration_ms; if (-not $ms) { return '' }; $s = [Math]::Floor([double]$ms / 1000); "${BLUE}$(FmtSecs $s)${RST}" }

function Seg_effort {
    try {
        $sp = Join-Path $env:USERPROFILE '.claude\settings.json'
        if (Test-Path $sp) {
            $s = Get-Content $sp -Raw | ConvertFrom-Json
            $level = $s.effortLevel
            if ($level) {
                $labels = @{ low='LO'; medium='MED'; high='HI' }
                $colors = @{ low=$DIM; medium=$YELLOW; high=$GREEN }
                $l = if ($labels[$level]) { $labels[$level] } else { $level.ToUpper() }
                $c = if ($colors[$level]) { $colors[$level] } else { $DIM }
                return "${c}${l}${RST}"
            }
        }
    } catch {}
    return ''
}

function Seg_env {
    if ($env:SSH_CLIENT -or $env:SSH_TTY -or $env:SSH_CONNECTION) { return "${MAGENTA}REMOTE${RST}" }
    return "${CYAN}LOCAL${RST}"
}

function Seg_rate_limits {
    $cacheDir = Join-Path $env:USERPROFILE '.claude'
    if (-not (Test-Path $cacheDir)) { New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null }
    $cacheFile = Join-Path $cacheDir 'statusline-usage-cache.json'
    $usageData = $null

    if (Test-Path $cacheFile) {
        $age = (Get-Date) - (Get-Item $cacheFile).LastWriteTime
        if ($age.TotalSeconds -lt 60) {
            try { $usageData = Get-Content $cacheFile -Raw | ConvertFrom-Json } catch {}
        }
    }
    if (-not $usageData) {
        $token = $env:CLAUDE_CODE_OAUTH_TOKEN
        if (-not $token) {
            $credsFile = Join-Path $env:USERPROFILE '.claude\.credentials.json'
            if (Test-Path $credsFile) {
                try { $creds = Get-Content $credsFile -Raw | ConvertFrom-Json; $token = $creds.claudeAiOauth.accessToken } catch {}
            }
        }
        if ($token) {
            try {
                $headers = @{ Authorization="Bearer $token"; Accept='application/json'; 'Content-Type'='application/json'; 'anthropic-beta'='oauth-2025-04-20'; 'User-Agent'='claude-code/2.1.34' }
                $resp = Invoke-RestMethod -Uri 'https://api.anthropic.com/api/oauth/usage' -Headers $headers -TimeoutSec 5
                $usageData = $resp; $resp | ConvertTo-Json -Depth 5 | Set-Content $cacheFile
            } catch {}
        }
        if (-not $usageData -and (Test-Path $cacheFile)) {
            try { $usageData = Get-Content $cacheFile -Raw | ConvertFrom-Json } catch {}
        }
    }
    if (-not $usageData) { return '' }
    $ctx.usageData = $usageData

    $fhPct = if ($usageData.five_hour.utilization) { [int]$usageData.five_hour.utilization } else { 0 }
    $peakTag = if ($ctx.isPeak) { " ${YELLOW}*${RST}" } else { '' }
    $fhColor = ColorPct $fhPct

    $labels = $schedule.labels
    $fhLabel = if ($labels.five_hour) { $labels.five_hour } else { '5h' }

    if ($tier -eq 'minimal') { return "${fhColor}${fhPct}%${RST} ${DIM}${fhLabel}${RST}${peakTag}" }

    $bw = 10; $filled = [Math]::Floor($fhPct * $bw / 100); $empty = $bw - $filled
    $bar = "${fhColor}$([string]::new([char]0x25B0, $filled))${DIM}$([string]::new([char]0x25B1, $empty))${RST}"
    return "${bar} ${fhColor}${fhPct}%${RST}${peakTag}"
}

# Segment registry
$segFns = @{
    banner='Seg_banner'; peak_hours='Seg_peak_hours'; promo_2x='Seg_peak_hours'
    model='Seg_model'; context='Seg_context'; git_branch='Seg_git_branch'; git_dirty='Seg_git_dirty'
    cost='Seg_cost'; duration='Seg_duration'; rate_limits='Seg_rate_limits'; effort='Seg_effort'; env='Seg_env'
}

# Inject banner
$bannerResult = & Seg_banner
$parts = @(); $gitParts = @()
if ($bannerResult) { $parts += $bannerResult }

foreach ($name in $enabled) {
    $fn = $segFns[$name]
    if (-not $fn) { continue }
    $r = & $fn
    if (-not $r) { continue }
    if ($name -in 'git_branch','git_dirty') { $gitParts += $r }
    else { $parts += $r }
}
if ($gitParts.Count -gt 0) { $parts += ($gitParts -join ' ') }

# Flow design: colored arrows
$arrowColor = if ($ctx.isPeak) { $YELLOW } else { $GREEN }
$arrow = " ${arrowColor}$([char]0x25B8)${RST} "
$line1 = $parts -join $arrow
Write-Host $line1 -NoNewline

# Full mode: timeline + rate limits
if ($mode -eq 'full' -and $tier -eq 'full') {
    $showTimeline = if ($schedule.features -and $schedule.features.show_timeline -ne $null) { $schedule.features.show_timeline } else { $true }
    if ($showTimeline) {
        $cursorPos = $hour * 2 + $(if($minute -ge 30){1}else{0})
        $isPeakDay = $weekday -in $effectivePeakDays
        $bar = ''
        for ($i = 0; $i -lt 48; $i++) {
            $h = $i / 2.0
            if ($i -eq $cursorPos) { $bar += "${WHITE}${BOLD}o${RST}" }
            elseif (-not $isPeakDay) { $bar += "${GREEN}-${RST}" }
            else {
                $inPeak = if ($peakEndLocal -gt $peakStartLocal) { $h -ge $peakStartLocal -and $h -lt $peakEndLocal } else { $h -ge $peakStartLocal -or $h -lt $peakEndLocal }
                $bar += if ($inPeak) { "${YELLOW}-${RST}" } else { "${GREEN}-${RST}" }
            }
        }
        if (-not $isPeakDay) {
            Write-Host "`n`n${DIM}|${RST}  ${bar}  ${DIM}|${RST}  ${GREEN}-${RST}${DIM} off-peak all day${RST}" -NoNewline
        } else {
            Write-Host "`n`n${DIM}|${RST}  ${bar}  ${DIM}|${RST}  ${GREEN}-${RST}${DIM} off-peak${RST} ${YELLOW}-${RST}${DIM} peak ($(FmtHour $peakStartLocal)-$(FmtHour $peakEndLocal))${RST}" -NoNewline
        }
    }

    if ($ctx.usageData) {
        $fhPct = if($ctx.usageData.five_hour.utilization){[int]$ctx.usageData.five_hour.utilization}else{0}
        $sdPct = if($ctx.usageData.seven_day.utilization){[int]$ctx.usageData.seven_day.utilization}else{0}
        $peakTag = if($ctx.isPeak){" ${YELLOW}* peak${RST}"}else{" ${GREEN}+${RST}"}
        $fhColor = ColorPct $fhPct; $sdColor = ColorPct $sdPct

        $labels = $schedule.labels
        $fhLabel = if ($labels.five_hour) { $labels.five_hour } else { '5h' }
        $wkLabel = if ($labels.weekly) { $labels.weekly } else { 'weekly' }

        $bw = 10
        $fhFilled = [Math]::Floor($fhPct * $bw / 100); $fhEmpty = $bw - $fhFilled
        $sdFilled = [Math]::Floor($sdPct * $bw / 100); $sdEmpty = $bw - $sdFilled
        $fhBar = "${fhColor}$([string]::new([char]0x25B0, $fhFilled))${DIM}$([string]::new([char]0x25B1, $fhEmpty))${RST}"
        $sdBar = "${sdColor}$([string]::new([char]0x25B0, $sdFilled))${DIM}$([string]::new([char]0x25B1, $sdEmpty))${RST}"

        Write-Host "`n${DIM}|${RST} ${GREEN}>${RST} ${WHITE}${fhLabel}${RST} ${fhBar} ${fhColor}${fhPct}%${RST}${peakTag} ${DIM}.${RST} ${WHITE}${wkLabel}${RST} ${sdBar} ${sdColor}${sdPct}%${RST} ${DIM}|${RST}" -NoNewline
    }
}
