[CmdletBinding()]
param(
    [string]$ToolDirectory,
    [string]$OutputDirectory
)

# Local files only. This script does not connect to or flash a router.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if ([string]::IsNullOrWhiteSpace($ToolDirectory)) { $ToolDirectory = Join-Path $projectRoot 'tmp/xmir-patcher' }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = Join-Path $projectRoot 'tmp/prepared' }
$tablePath = Join-Path $ToolDirectory 'outdir/mtd_list.txt'
$infoPath = Join-Path $ToolDirectory 'outdir/mtd_info.txt'
$backupDirectory = Join-Path $ToolDirectory 'backups'
$templatePath = Join-Path $PSScriptRoot 'flash-cr8808-stock.template.sh'
foreach ($path in @($tablePath, $infoPath, $templatePath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing file: $path" }
}

$parts = @{}
$table = [IO.File]::ReadAllText($tablePath)
$pattern = '(?m)^mtd(\d+):[ \t]+([0-9a-fA-F]+)[ \t]+([0-9a-fA-F]+)[ \t]+"([^"\r\n]+)"[ \t]*\r?$'
foreach ($match in [regex]::Matches($table, $pattern)) {
    $number = [int]$match.Groups[1].Value
    if ($parts.ContainsKey($number)) { throw "Duplicate MTD entry: mtd$number" }
    $parts[$number] = [pscustomobject]@{
        Number = $number
        Bytes = [Convert]::ToInt64($match.Groups[2].Value, 16)
        EraseSize = [Convert]::ToInt64($match.Groups[3].Value, 16)
        Name = $match.Groups[4].Value
    }
}
if ($parts.Count -lt 22) { throw 'Invalid or incomplete MTD table.' }

$physical = @{}
$info = [IO.File]::ReadAllText($infoPath)
foreach ($match in [regex]::Matches($info, '(?m)^(\d+)=(\d*)\|([^|\r\n]+)\|')) {
    if ($match.Groups[3].Value -cne 'nand') { continue }
    $number = [int]$match.Groups[1].Value
    if ($physical.ContainsKey($number) -or $match.Groups[2].Value -eq '') { throw 'Invalid NAND metadata.' }
    $physical[$number] = [long]$match.Groups[2].Value
}
if ($physical.Count -ne 22) { throw 'This route requires exactly 22 physical NAND partitions.' }

$critical = @{
    1  = @('0:MIBIB', 524288)
    11 = @('0:APPSBL', 1310720)
    13 = @('0:ART', 1048576)
    18 = @('rootfs', 37748736)
    19 = @('rootfs_1', 37748736)
}
foreach ($number in $critical.Keys) {
    if (-not $parts.ContainsKey($number) -or $parts[$number].Name -cne $critical[$number][0] -or $parts[$number].Bytes -ne $critical[$number][1]) {
        throw "Unsupported partition layout at mtd$number. Do not edit the guard to force a flash."
    }
}

$records = New-Object 'System.Collections.Generic.List[object]'
$hashes = @{}
$nextOffset = [long]0
for ($number = 0; $number -lt 22; $number++) {
    if (-not $parts.ContainsKey($number) -or -not $physical.ContainsKey($number)) { throw "Missing physical partition mtd$number" }
    $part = $parts[$number]
    if ($physical[$number] -ne $nextOffset -or $part.EraseSize -ne 131072) { throw "Unexpected NAND geometry at mtd$number" }
    $nextOffset += $part.Bytes
    $safeName = [regex]::Replace($part.Name, '[^A-Za-z0-9]', '')
    $fileName = "mtd${number}_${safeName}.bin"
    $filePath = Join-Path $backupDirectory $fileName
    if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) { throw "Missing backup: $filePath" }
    if ((Get-Item -LiteralPath $filePath).Length -ne $part.Bytes) { throw "Backup length mismatch: $filePath" }
    $checksum = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $hashes[$number] = $checksum
    $records.Add([pscustomobject][ordered]@{
        mtd = $number; name = $part.Name; bytes = $part.Bytes
        offset = $physical[$number]; file = $fileName; sha256 = $checksum
    })
}
if ($nextOffset -ne 133169152) { throw 'Unexpected total NAND partition size.' }

$text = [IO.File]::ReadAllText($templatePath)
$replacements = @{
    '__MIBIB_SHA256__' = $hashes[1]
    '__APPSBL_SHA256__' = $hashes[11]
    '__ART_SHA256__' = $hashes[13]
    '__ROOTFS_SHA256__' = $hashes[18]
}
foreach ($token in $replacements.Keys) {
    if (-not $text.Contains($token)) { throw "Template token missing: $token" }
    $text = $text.Replace($token, $replacements[$token])
}
if ($text -match '__[A-Z_]+SHA256__') { throw 'Unfilled hash token in template.' }

$outputPath = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$encoding = New-Object System.Text.UTF8Encoding($false)
$manifest = [ordered]@{
    scope = '22 exposed physical NAND MTD partitions; local file length and SHA256 checks'
    physical_partition_count = 22; physical_bytes = $nextOffset
    partitions = $records.ToArray()
}
[IO.File]::WriteAllText((Join-Path $outputPath 'backup-manifest.json'), ($manifest | ConvertTo-Json -Depth 6) + "`n", $encoding)
$sumLines = ($records | ForEach-Object { $_.sha256 + '  ' + $_.file }) -join "`n"
[IO.File]::WriteAllText((Join-Path $outputPath 'SHA256SUMS'), $sumLines + "`n", $encoding)
$scriptPath = Join-Path $outputPath 'flash-current-device.sh'
[IO.File]::WriteAllText($scriptPath, $text.Replace("`r`n", "`n"), $encoding)
Write-Output 'BACKUP_OK: 22 physical partitions, 133169152 bytes (127 MiB).'
Write-Output "MANIFEST: $(Join-Path $outputPath 'backup-manifest.json')"
Write-Output "FLASH_SCRIPT: $scriptPath"
Write-Output 'Local SHA256 records created. Router preflight must still pass.'
Write-Output 'No router was contacted or flashed.'
