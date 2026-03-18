# claude-2x-statusline - modular statusline for Claude Code (PowerShell)
# https://github.com/Nadav-Fux/claude-2x-statusline

$ErrorActionPreference = 'SilentlyContinue'

# ANSI
$E = [char]27
$RST="$E[0m"; $BOLD="$E[1m"; $DIM="$E[2m"
$RED="$E[31m"; $GREEN="$E[32m"; $YELLOW="$E[33m"
$BLUE="$E[34m"; $MAGENTA="$E[35m"; $CYAN="$E[36m"
$WHITE="$E[38;2;220;220;220m"
$BGG="$E[38;5;16;48;5;46m"; $BGY="$E[38;5;16;48;5;220m"
$BGR="$E[38;5;255;48;5;124m"; $BGGRAY="$E[48;5;236m"

# Tiers
$TIERS = @{
    minimal  = @('time','promo_2x','git_branch','git_dirty')
    standard = @('time','promo_2x','model','context','git_branch','git_dirty','cost','duration')
    full     = @('time','promo_2x','model','context','git_branch','git_dirty','git_ahead_behind','cost','duration','lines','rate_limits')
}

# Config
$configPath = Join-Path $env:USERPROFILE '.claude\statusline-config.json'
$config = @{ tier='standard'; separator=' | '; mode='minimal'; promo_start=20260313; promo_end=20260327 }
if (Test-Path $configPath) {
    try {
        $userCfg = Get-Content $configPath -Raw | ConvertFrom-Json
        foreach ($p in $userCfg.PSObject.Properties) { $config[$p.Name] = $p.Value }
    } catch {}
}

$tier = $config['tier']
if ($tier -eq 'custom') {
    $enabled = @($config['segments'].PSObject.Properties | Where-Object { $_.Value -eq $true } | ForEach-Object { $_.Name })
} elseif ($TIERS.ContainsKey($tier)) {
    $enabled = $TIERS[$tier]
} else {
    $enabled = $TIERS['standard']
}

# Mode
$mode = if ($config['mode']) { $config['mode'] } else { 'minimal' }
if ($args -contains '--full') { $mode = 'full' }
if ($mode -eq 'full' -and $enabled -notcontains 'rate_limits') { $enabled += 'rate_limits' }

# Stdin
$stdinData = @{}
try {
    $raw = [Console]::In.ReadToEnd()
    if ($raw.Trim()) { $stdinData = $raw | ConvertFrom-Json }
} catch {}

# Israel Time
$utc = [DateTime]::UtcNow
$mo = $utc.Month; $dy = $utc.Day
$ilOffset = if (($mo -gt 3 -or ($mo -eq 3 -and $dy -ge 27)) -and ($mo -lt 10 -or ($mo -eq 10 -and $dy -lt 25))) { 3 } else { 2 }
$il = $utc.AddHours($ilOffset)
$hour = $il.Hour; $minute = $il.Minute
$weekday = [int]$il.DayOfWeek; if ($weekday -eq 0) { $weekday = 7 }
$ilDate = [int]$il.ToString('yyyyMMdd')
$nowMins = $hour * 60 + $minute
$peakS = 14; $peakE = 20  # Israel local time (8AM-2PM ET)

# Helpers
function FmtDur($mins) { $h=[Math]::Floor($mins/60); $m=$mins%60; if($h -gt 0){"${h}h $("{0:D2}" -f $m)m"}else{"${m}m"} }
function FmtSecs($s) { $h=[Math]::Floor($s/3600); $m=[Math]::Floor(($s%3600)/60); $sec=$s%60; if($h -gt 0){"${h}h$("{0:D2}" -f $m)m"}elseif($m -gt 0){"${m}m$("{0:D2}" -f $sec)s"}else{"${sec}s"} }
function ColorPct($p) { if($p -ge 80){$script:RED}elseif($p -ge 50){$script:YELLOW}else{$script:GREEN} }
function GitCmd { param([string[]]$a) try { $r = & git @a 2>$null; if($r){$r.Trim()}else{''} } catch { '' } }

# Context
$ctx = @{ is2x=$false; isPromo=$false; gitBranch=''; usageData=$null }

# -- Segments --

function Seg_time { "${DIM}$($il.ToString('HH:mm'))${RST}" }

function Seg_promo_2x {
    $ps = $config['promo_start']; $pe = $config['promo_end']
    if ($ilDate -lt $ps -or $ilDate -gt $pe) { return "${DIM}Promo ended${RST}" }
    $ctx.isPromo = $true

    $pkS = $peakS * 60; $pkE = $peakE * 60
    $doubled = $false; $reason = ''; $minsLeft = 0; $minsUntil = 0

    if ($weekday -eq 6 -and $nowMins -ge 540) { $doubled=$true; $reason='weekend'; $minsLeft=(1440-$nowMins)+1440+540 }
    elseif ($weekday -eq 7) { $doubled=$true; $reason='weekend'; $minsLeft=(1440-$nowMins)+540 }
    elseif ($weekday -eq 1 -and $nowMins -lt 540) { $doubled=$true; $reason='weekend'; $minsLeft=540-$nowMins }
    elseif ($nowMins -ge $pkE) { $doubled=$true; $reason='off-peak'; $minsLeft=(1440-$nowMins)+$pkS }
    elseif ($nowMins -lt $pkS) { $doubled=$true; $reason='off-peak'; $minsLeft=$pkS-$nowMins }

    if (-not $doubled) { $minsUntil = $pkE - $nowMins }
    $ctx.is2x = $doubled

    # Days remaining (proper date diff, safe across month boundaries)
    $endDate = [DateTime]::new([int]($pe / 10000), [int](($pe % 10000) / 100), [int]($pe % 100))
    $daysLeft = ($endDate.Date - $il.Date).Days
    $daysTag = if ($daysLeft -gt 0 -and $daysLeft -le 14) { " ${DIM}${daysLeft}d left${RST}" } else { '' }

    if ($doubled) {
        $t = FmtDur $minsLeft
        $bg = if($minsLeft -gt 180){$BGG}elseif($minsLeft -gt 60){$BGY}else{$BGR}
        $wk = if($reason -eq 'weekend'){" ${DIM}weekend${RST}"}else{''}
        return "${bg} 2x ACTIVE ${RST} ${WHITE}$t left${RST}${wk}${daysTag}"
    } else {
        $t = FmtDur $minsUntil
        return "${BGGRAY} PEAK ${RST} ${DIM}-> 2x in ${t}${RST}${daysTag}"
    }
}

function Seg_model { $n = $stdinData.model.display_name; if($n){"${BLUE}${n}${RST}"}else{''} }

function Seg_context {
    $cw = $stdinData.context_window; if(-not $cw){return ''}
    $size = $cw.context_window_size; if(-not $size -or $size -eq 0){return ''}
    $u = $cw.current_usage
    $cur = [int]$u.input_tokens + [int]$u.cache_creation_input_tokens + [int]$u.cache_read_input_tokens
    $pct = [Math]::Floor($cur * 100 / $size)
    $c = ColorPct $pct
    return "${c}${pct}%${RST}"
}

function Seg_git_branch { $b = GitCmd 'branch','--show-current'; $ctx.gitBranch=$b; if($b){"${DIM}${b}${RST}"}else{''} }
function Seg_git_dirty { $p = GitCmd 'status','--porcelain'; if(-not $p){return ''}; $c=@($p -split "`n" | Where-Object{$_}).Count; "${DIM}+${c}${RST}" }

function Seg_git_ahead_behind {
    if(-not $ctx.gitBranch){return ''}
    $a = GitCmd 'rev-list','--count','@{u}..HEAD'
    $b = GitCmd 'rev-list','--count','HEAD..@{u}'
    $p = ''
    if ($a -and $a -ne '0') { $p += "^$a" }
    if ($b -and $b -ne '0') { $p += "v$b" }
    if ($p) { "${DIM}${p}${RST}" } else { '' }
}

function Seg_cost {
    $c = $stdinData.cost.total_cost_usd
    if ($null -eq $c) { return '' }
    $f = '{0:F3}' -f [double]$c
    return "${MAGENTA}`$$f${RST}"
}

function Seg_duration {
    $ms = $stdinData.cost.total_duration_ms
    if (-not $ms) { return '' }
    $s = [Math]::Floor([double]$ms / 1000)
    return "${BLUE}$(FmtSecs $s)${RST}"
}

function Seg_lines {
    $a = [int]$stdinData.cost.total_lines_added
    $r = [int]$stdinData.cost.total_lines_removed
    if (-not $a -and -not $r) { return '' }
    return "${GREEN}+${a}${RST}/${RED}-${r}${RST}"
}

function Seg_rate_limits {
    $cacheDir = Join-Path $env:TEMP 'claude'
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
                $headers = @{
                    Authorization = "Bearer $token"
                    Accept = 'application/json'
                    'Content-Type' = 'application/json'
                    'anthropic-beta' = 'oauth-2025-04-20'
                    'User-Agent' = 'claude-code/2.1.34'
                }
                $resp = Invoke-RestMethod -Uri 'https://api.anthropic.com/api/oauth/usage' -Headers $headers -TimeoutSec 5
                $usageData = $resp
                $resp | ConvertTo-Json -Depth 5 | Set-Content $cacheFile
            } catch {}
        }
        if (-not $usageData -and (Test-Path $cacheFile)) {
            try { $usageData = Get-Content $cacheFile -Raw | ConvertFrom-Json } catch {}
        }
    }

    if (-not $usageData) { return '' }
    $ctx.usageData = $usageData

    $fhPct = if ($usageData.five_hour.utilization) { [int]$usageData.five_hour.utilization } else { 0 }
    $frozen = if ($ctx.is2x) { " ${CYAN}*${RST}" } else { '' }
    $fhColor = ColorPct $fhPct
    return "${fhColor}${fhPct}%${RST}${frozen}"
}

# -- Assemble --
$segFns = @{
    time='Seg_time'; promo_2x='Seg_promo_2x'; model='Seg_model'; context='Seg_context'
    git_branch='Seg_git_branch'; git_dirty='Seg_git_dirty'; git_ahead_behind='Seg_git_ahead_behind'
    cost='Seg_cost'; duration='Seg_duration'; lines='Seg_lines'; rate_limits='Seg_rate_limits'
}

$sep = if ($config['separator']) { $config['separator'] } else { ' | ' }
$dimSep = "${DIM}${sep}${RST}"

$parts = @(); $gitParts = @()
foreach ($name in $enabled) {
    $fn = $segFns[$name]
    if (-not $fn) { continue }
    $r = & $fn
    if (-not $r) { continue }
    if ($name -in 'git_branch','git_dirty','git_ahead_behind') { $gitParts += $r }
    else { $parts += $r }
}
if ($gitParts.Count -gt 0) { $parts += ($gitParts -join ' ') }

$line1 = $parts -join $dimSep
Write-Host $line1 -NoNewline

# Full mode
if ($mode -eq 'full' -and $ctx.isPromo) {
    $cursorPos = $hour * 2 + $(if($minute -ge 30){1}else{0})
    $isWeekend = $weekday -ge 6
    $bar = ''
    for ($i = 0; $i -lt 48; $i++) {
        $h = [Math]::Floor($i / 2)
        if ($i -eq $cursorPos) { $bar += "${WHITE}${BOLD}o${RST}" }
        elseif ($isWeekend -or $h -lt $peakS -or $h -ge $peakE) { $bar += "${GREEN}-${RST}" }
        else { $bar += "${YELLOW}-${RST}" }
    }
    if ($isWeekend) {
        Write-Host "`n`n${DIM}|${RST}  ${bar}  ${DIM}|${RST}  ${GREEN}-${RST}${DIM} 2x all day${RST}" -NoNewline
    } else {
        Write-Host "`n`n${DIM}|${RST}  ${bar}  ${DIM}|${RST}  ${GREEN}-${RST}${DIM} 2x${RST} ${YELLOW}-${RST}${DIM} peak${RST}" -NoNewline
    }

    if ($ctx.usageData) {
        $fhPct = if($ctx.usageData.five_hour.utilization){[int]$ctx.usageData.five_hour.utilization}else{0}
        $sdPct = if($ctx.usageData.seven_day.utilization){[int]$ctx.usageData.seven_day.utilization}else{0}
        $frozen = if($ctx.is2x){" ${CYAN}*${RST}"}else{''}
        $rlSep = " ${DIM}|${RST} "
        $fhColor = ColorPct $fhPct
        $sdColor = ColorPct $sdPct
        $cur = "${WHITE}current${RST} ${fhColor}${fhPct}%${RST}"
        $wk = "${WHITE}weekly${RST} ${sdColor}${sdPct}%${RST}${frozen}"
        Write-Host "`n${cur}${rlSep}${wk}" -NoNewline
    }
}
