param([string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\FreeShip-MCP'))
$ErrorActionPreference = 'Stop'
$sourceDirectory = $PSScriptRoot
if (!(Test-Path -LiteralPath (Join-Path $sourceDirectory 'freeship-mcp.exe'))) {
    throw 'Run this installer from the extracted Windows release package.'
}
if (Test-Path -LiteralPath $Destination) { throw 'Destination exists; select a new directory.' }
Copy-Item -LiteralPath $sourceDirectory -Destination $Destination -Recurse
Write-Output "Installed: $Destination\freeship-mcp.exe"
Write-Output 'Configure the MCP command with this executable and --workspace pointing to an existing model directory.'
