Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$src = "E:\DATA\ClaudeWorkspace\Yachiyo_Project\astrbot_plugin_yachiyo_manager"
$out = "E:\DATA\ClaudeWorkspace\Yachiyo_Project\yachiyo_plugin_v2.2.zip"

Remove-Item $out -Force -ErrorAction SilentlyContinue

# Use ZipArchive directly for full control over entry names and ordering
$archive = [System.IO.Compression.ZipFile]::Open($out, [System.IO.Compression.ZipArchiveMode]::Create)

# Collect all files first
$entries = @()
$dirsSet = @{}

Get-ChildItem -Path $src -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($src.Length + 1)
    # Skip unwanted files
    if ($rel -like '*__pycache__*' -or $rel -like '*.pyc' -or $rel -like 'data\*') { return }
    # Convert to forward slash
    $unixRel = $rel.Replace('\', '/')
    $entries += @{Path = $unixRel; FullPath = $_.FullName}
    # Collect all parent directories
    $parts = $unixRel.Split('/')
    for ($i = 0; $i -lt $parts.Count - 1; $i++) {
        $d = ($parts[0..$i] -join '/') + '/'
        if (-not $dirsSet.ContainsKey($d)) {
            $dirsSet[$d] = $true
        }
    }
}

# Create directory entries first (sorted for determinism)
$dirsSet.Keys | Sort-Object | ForEach-Object {
    try {
        [void]$archive.CreateEntry($_, [System.IO.Compression.CompressionLevel]::Optimal)
        Write-Host "  DIR: $_"
    } catch { }
}

# Create file entries
$entries | Sort-Object { $_.Path } | ForEach-Object {
    Write-Host "  FILE: $($_.Path)"
    $entry = $archive.CreateEntry($_.Path, [System.IO.Compression.CompressionLevel]::Optimal)
    $bytes = [System.IO.File]::ReadAllBytes($_.FullPath)
    $s = $entry.Open()
    $s.Write($bytes, 0, $bytes.Length)
    $s.Close()
}

$archive.Dispose()
Write-Host "DONE: $out ($((Get-Item $out).Length) bytes)"
