# PyInstaller build; the optional upstream SDK CLI is deliberately excluded.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

root = Path(SPECPATH).parent
hidden = collect_submodules('mcp', filter=lambda name: not name.startswith('mcp.cli'))
datas = collect_data_files('mcp') + collect_data_files('freeship_mcp')
for package in ('mcp', 'mcp-types', 'pydantic', 'ezdxf', 'openpyxl'):
    datas += copy_metadata(package)
a = Analysis([str(root / 'scripts/frozen_entry.py')], pathex=[str(root / 'src')],
    binaries=[(str(root / 'src/freeship_mcp/bin/freeship-engine.exe'), 'freeship_mcp/bin')],
    datas=datas, hiddenimports=hidden, excludes=['mcp.cli'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='freeship-mcp',
    debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='freeship-mcp')
