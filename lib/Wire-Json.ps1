param(
    [string]$Path,
    [string]$MergeJson,
    [string]$GetPath
)

$ErrorActionPreference = 'Stop'

$script:WireJsonSerializerReady = $false
$script:WireJsonSerializerChecked = $false

function ConvertTo-NormalizedValue {
    param([object]$InputObject)

    if ($null -eq $InputObject) {
        return $null
    }

    if ($InputObject -is [System.Collections.IDictionary]) {
        $result = @{}
        foreach ($key in $InputObject.Keys) {
            $result[$key] = ConvertTo-NormalizedValue -InputObject $InputObject[$key]
        }
        return $result
    }

    if ($InputObject -is [pscustomobject]) {
        $result = @{}
        foreach ($property in $InputObject.PSObject.Properties) {
            $result[$property.Name] = ConvertTo-NormalizedValue -InputObject $property.Value
        }
        return $result
    }

    if ($InputObject -is [System.Collections.IEnumerable] -and -not ($InputObject -is [string])) {
        $items = @()
        foreach ($item in $InputObject) {
            $items += ,(ConvertTo-NormalizedValue -InputObject $item)
        }
        return ,$items
    }

    return $InputObject
}

function Merge-JsonValue {
    param(
        $Base,
        $Patch
    )

    if (($Base -is [System.Collections.IDictionary]) -and ($Patch -is [System.Collections.IDictionary])) {
        $merged = @{}
        foreach ($key in $Base.Keys) {
            $merged[$key] = $Base[$key]
        }
        foreach ($key in $Patch.Keys) {
            if ($merged.ContainsKey($key)) {
                $merged[$key] = Merge-JsonValue -Base $merged[$key] -Patch $Patch[$key]
            } else {
                $merged[$key] = $Patch[$key]
            }
        }
        return $merged
    }

    if (($Base -is [System.Collections.IList]) -and ($Patch -is [System.Collections.IList])) {
        $merged = @($Base)
        $seen = @{}
        foreach ($item in $merged) {
            $seen[(ConvertTo-Json $item -Depth 20 -Compress)] = $true
        }
        foreach ($item in $Patch) {
            $marker = ConvertTo-Json $item -Depth 20 -Compress
            if (-not $seen.ContainsKey($marker)) {
                $merged += ,$item
                $seen[$marker] = $true
            }
        }
        return ,$merged
    }

    return $Patch
}

function ConvertTo-WireJsonString {
    param($Value)

    if (-not $script:WireJsonSerializerChecked) {
        try {
            Add-Type -AssemblyName System.Web.Extensions -ErrorAction Stop | Out-Null
            $script:WireJsonSerializerReady = $true
        } catch {
            $script:WireJsonSerializerReady = $false
        }
        $script:WireJsonSerializerChecked = $true
    }

    if ($script:WireJsonSerializerReady) {
        $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $serializer.MaxJsonLength = [int]::MaxValue
        $serializer.RecursionLimit = 100
        return $serializer.Serialize($Value)
    }

    return ConvertTo-Json $Value -Depth 20
}

function Read-JsonDocument {
    param([string]$TargetPath)

    if (-not (Test-Path $TargetPath)) {
        return @{}
    }

    $raw = Get-Content $TargetPath -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return @{}
    }

    return ConvertTo-NormalizedValue (ConvertFrom-Json $raw)
}

function Write-JsonDocument {
    param(
        [string]$TargetPath,
        $Value
    )

    $directory = [System.IO.Path]::GetDirectoryName($TargetPath)
    if ([string]::IsNullOrEmpty($directory)) {
        $directory = (Get-Location).Path
    }
    if (-not (Test-Path $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $tempPath = Join-Path $directory ([System.IO.Path]::GetRandomFileName())
    try {
        $json = ConvertTo-WireJsonString $Value
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($tempPath, $json + [Environment]::NewLine, $utf8NoBom)
        Move-Item $tempPath $TargetPath -Force
    } catch {
        if (Test-Path $tempPath) {
            Remove-Item $tempPath -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

function Set-SettingsEntry {
    param(
        [string]$TargetPath,
        [Parameter(Mandatory = $true)]$Merge
    )

    $base = Read-JsonDocument -TargetPath $TargetPath
    $normalizedMerge = ConvertTo-NormalizedValue $Merge
    $result = Merge-JsonValue -Base $base -Patch $normalizedMerge
    Write-JsonDocument -TargetPath $TargetPath -Value $result
}

function Get-SettingsEntry {
    param(
        [string]$TargetPath,
        [string]$PropertyPath
    )

    $value = Read-JsonDocument -TargetPath $TargetPath
    foreach ($segment in ($PropertyPath -split '\.')) {
        if ([string]::IsNullOrWhiteSpace($segment)) {
            continue
        }
        if (($value -is [System.Collections.IDictionary]) -and $value.Contains($segment)) {
            $value = $value[$segment]
            continue
        }
        throw "Missing path: $PropertyPath"
    }

    if ($value -is [System.Collections.IDictionary] -or (($value -is [System.Collections.IEnumerable]) -and -not ($value -is [string]))) {
        Write-Output (ConvertTo-WireJsonString $value)
    } else {
        Write-Output $value
    }
}

if ($PSBoundParameters.ContainsKey('MergeJson')) {
    try {
        $mergeValue = ConvertTo-NormalizedValue (ConvertFrom-Json $MergeJson)
    } catch {
        Write-Error "Failed to parse MergeJson: $($_.Exception.Message)"
        exit 20
    }

    try {
        Set-SettingsEntry -TargetPath $Path -Merge $mergeValue
    } catch {
        Write-Error $_.Exception.Message
        exit 30
    }
    exit 0
}

if ($PSBoundParameters.ContainsKey('GetPath')) {
    try {
        Get-SettingsEntry -TargetPath $Path -PropertyPath $GetPath
    } catch {
        exit 1
    }
    exit 0
}