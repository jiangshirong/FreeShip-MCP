"""Collect licenses from the actual installed dependencies into distributable data."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
out = root / "src/freeship_mcp/licenses"
out.mkdir(exist_ok=True)
shutil.copy2(root / "LICENSE", out / "FreeShip-MCP-GPL-3.0.txt")
shutil.copy2(root / "NOTICE", out / "FreeShip-MCP-NOTICE.txt")
shutil.copy2(root / "vendor/freeship/copyright", out / "FreeShip-copyright.txt")
for line in (root / "requirements.lock").read_text().splitlines():
    if not line or line.startswith("#"):
        continue
    name, version = line.split("==")
    dist = distribution(name)
    files = list(dist.files or [])
    metadata = f"{name} {version}\nLicense: {dist.metadata.get('License-Expression') or dist.metadata.get('License', '')}\n"
    (out / f"{name}-metadata.txt").write_text(metadata, encoding="utf-8")
    for index, file in enumerate(files):
        if ".dist-info" in str(file) and any(word in file.name.lower() for word in ("license", "copying", "notice")):
            source = Path(dist.locate_file(file))
            if source.is_file():
                shutil.copy2(source, out / f"{name}-{index}-{source.name}")
for package in ("pyinstaller", "setuptools", "wheel", "pygments", "packaging"):
    dist = distribution(package)
    for index, file in enumerate(dist.files or []):
        if ".dist-info" in str(file) and any(word in file.name.lower() for word in ("license", "copying", "notice")):
            source = Path(dist.locate_file(file))
            if source.is_file():
                shutil.copy2(source, out / f"{package}-{index}-{source.name}")
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copy2(python_license, out / "Python-LICENSE.txt")
lazarus = root / ".toolchain/lazarus"
if lazarus.is_dir():
    for p in lazarus.glob("COPYING*.txt"):
        shutil.copy2(p, out / f"Lazarus-{p.name}")
    for p in (lazarus / "fpc/3.2.2/source/rtl").glob("COPYING*"):
        if p.is_file():
            shutil.copy2(p, out / f"FPC-RTL-{p.name}")
