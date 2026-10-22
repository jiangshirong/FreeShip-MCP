param([string]$Python = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'))
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $projectRoot
try {
    & $Python scripts/freeze_dependencies.py
    if ($LASTEXITCODE -ne 0) { throw 'Dependency snapshot failed' }
    & $Python scripts/bundle_notices.py
    if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
    & $Python -m build --no-isolation
    if ($LASTEXITCODE -ne 0) { throw 'Python package build failed' }
    & $Python -m PyInstaller --noconfirm --clean --distpath dist/standalone --workpath .build/pyinstaller scripts/freeship-mcp.spec
    if ($LASTEXITCODE -ne 0) { throw 'Standalone package build failed' }
    Copy-Item LICENSE,NOTICE,README.md,README.zh-CN.md dist/standalone/freeship-mcp/
    Copy-Item scripts/install.ps1 dist/standalone/freeship-mcp/
    Copy-Item docs dist/standalone/freeship-mcp/ -Recurse -Force
    Compress-Archive -LiteralPath dist/standalone/freeship-mcp -DestinationPath dist/FreeShip-MCP-Windows-x64.zip -Force
    & $Python scripts/corresponding_source.py
    if ($LASTEXITCODE -ne 0) { throw 'Corresponding source archive failed' }
} finally { Pop-Location }
