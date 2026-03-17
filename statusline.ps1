# claude-2x-statusline — Israel-timezone 2X promotion tracker for Claude Code
# PowerShell native version — no Python/bash needed
# https://github.com/Nadav-Fux/claude-2x-statusline

$ErrorActionPreference = 'SilentlyContinue'

# ── Israel timezone (auto DST) ──────────────────────────────────────────────
$utc = [DateTime]::UtcNow
$m = $utc.Month; $d = $utc.Day

# Israel DST 2026: ~March 27 → ~October 25
if (($m -gt 3 -or ($m -eq 3 -and $d -ge 27)) -and ($m -lt 10 -or ($m -eq 10 -and $d -lt 25))) {
    $ilOffset = 3  # IDT (summer)
} else {
    $ilOffset = 2  # IST (winter)
}

$il = $utc.AddHours($ilOffset)
$hour = $il.Hour; $minute = $il.Minute
$weekday = [int]$il.DayOfWeek  # 0=Sun, 1=Mon ... 6=Sat
# Convert to ISO: 1=Mon ... 7=Sun
if ($weekday -eq 0) { $weekday = 7 }
$ilDate = [int]$il.ToString("yyyyMMdd")
$ilTime = $il.ToString("HH:mm")

# ── Promotion window ────────────────────────────────────────────────────────
$PROMO_START = 20260313
$PROMO_END   = 20260327
$promoActive = ($ilDate -ge $PROMO_START) -and ($ilDate -le $PROMO_END)

$peakStart = 12 + $ilOffset
$peakEnd   = 18 + $ilOffset
$nowMins   = $hour * 60 + $minute

# ── Determine 2X status ─────────────────────────────────────────────────────
$doubled = $false; $reason = ""; $minsLeft = 0; $minsUntil = 0

if ($promoActive) {
    # Weekend: Saturday (6) 09:00 IL → Monday (1) 09:00 IL
    if ($weekday -eq 6 -and $nowMins -ge 540) {
        $doubled = $true; $reason = "weekend"; $minsLeft = (1440 - $nowMins) + 1440 + 540
    } elseif ($weekday -eq 7) {
        $doubled = $true; $reason = "weekend"; $minsLeft = (1440 - $nowMins) + 540
    } elseif ($weekday -eq 1 -and $nowMins -lt 540) {
        $doubled = $true; $reason = "weekend"; $minsLeft = 540 - $nowMins
    }
    # Off-peak weekday
    elseif ($nowMins -ge ($peakEnd * 60)) {
        $doubled = $true; $reason = "off-peak"; $minsLeft = (1440 - $nowMins) + ($peakStart * 60)
    } elseif ($nowMins -lt ($peakStart * 60)) {
        $doubled = $true; $reason = "off-peak"; $minsLeft = ($peakStart * 60) - $nowMins
    }
}

if (-not $doubled -and $promoActive) {
    $minsUntil = ($peakEnd * 60) - $nowMins
}

# ── Format helpers ───────────────────────────────────────────────────────────
function Fmt($m) {
    $h = [Math]::Floor($m / 60)
    $rm = $m % 60
    if ($h -gt 0) { return "${h}h $("{0:D2}" -f $rm)m" } else { return "${rm}m" }
}

$ESC = [char]27
$RST  = "$ESC[0m"
$BOLD = "$ESC[1m"
$DIM  = "$ESC[2m"

# ── Build status string ─────────────────────────────────────────────────────
if (-not $promoActive) {
    $status = "${DIM}Promotion ended${RST}"
} elseif ($doubled) {
    $t = Fmt $minsLeft
    if ($minsLeft -gt 180) {
        $bg = "$ESC[38;5;16;48;5;46m"       # green
    } elseif ($minsLeft -gt 60) {
        $bg = "$ESC[38;5;16;48;5;220m"      # yellow
    } else {
        $bg = "$ESC[38;5;255;48;5;124m"     # red
    }
    $wknd = if ($reason -eq "weekend") { " ${DIM}weekend${RST}" } else { "" }
    $status = "${bg}${BOLD} 2x ACTIVE ${RST} ${bg} $t left ${RST}${wknd}"
} else {
    $t = Fmt $minsUntil
    $status = "${DIM}$ESC[48;5;236m PEAK ${RST} $ESC[38;5;87m2x returns in ${t}${RST}"
}

# ── Git info ─────────────────────────────────────────────────────────────────
$gitInfo = ""
try {
    $branch = (git branch --show-current 2>$null).Trim()
    if ($branch) {
        $dirty = @(git status --porcelain 2>$null).Count
        $gitInfo = " ${DIM}|${RST} ${DIM}${branch}${RST}"
        if ($dirty -gt 0) { $gitInfo += "${DIM} +${dirty}${RST}" }
    }
} catch {}

Write-Host "${DIM}${ilTime}${RST} ${status}${gitInfo}"
