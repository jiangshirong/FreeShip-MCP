param([string]$LazarusDir = (Join-Path $PSScriptRoot '..\.toolchain\lazarus'))
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$lazarusRoot = (Resolve-Path $LazarusDir).Path
# Lazarus 3.2's command-line path validation is not Unicode-safe on all Windows
# ANSI code pages. Compile through ASCII junctions without relocating source.
$hasher = [System.Security.Cryptography.SHA256]::Create()
$digest = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot))).Replace('-','').Substring(0,12)
$hasher.Dispose()
$buildAlias = Join-Path $env:TEMP "freeship-mcp-$digest"
$toolsAlias = Join-Path $env:TEMP "freeship-tools-$digest"
foreach ($pair in @(@($buildAlias,$projectRoot),@($toolsAlias,$lazarusRoot))) {
    if (!(Test-Path -LiteralPath $pair[0])) {
        New-Item -ItemType Junction -Path $pair[0] -Target $pair[1] | Out-Null
    } elseif ((Get-Item -LiteralPath $pair[0]).Target -ne $pair[1]) {
        throw "Build alias already exists with a different target: $($pair[0])"
    }
}
$lazbuild = Join-Path $toolsAlias 'lazbuild.exe'
$compiler = Join-Path $toolsAlias 'fpc\3.2.2\bin\x86_64-win64\fpc.exe'
if (!(Test-Path -LiteralPath $compiler)) { throw 'Free Pascal 3.2.2 x64 is required.' }
New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot 'src\freeship_mcp\bin'),(Join-Path $projectRoot '.build\lazarus-config') | Out-Null
& $lazbuild --lazarusdir="$toolsAlias" --compiler="$compiler" --pcp="$buildAlias\.build\lazarus-config" --ws=nogui --cpu=x86_64 --os=win64 "$buildAlias\engine\freeship_engine.lpi"
if ($LASTEXITCODE -ne 0) { throw "Engine build failed ($LASTEXITCODE)." }
