"""Bundle matching application and static library sources beside the binary release."""
from pathlib import Path
import argparse
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--lazarus-dir", type=Path, default=ROOT/".toolchain/lazarus")
args = parser.parse_args()
version = tomllib.loads((ROOT/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
source_package = ROOT/f"dist/freeship_mcp-{version}.tar.gz"
if not source_package.is_file():
    raise SystemExit("Build the application sdist first")
output = ROOT/"dist/FreeShip-MCP-corresponding-source.tar.gz"
excluded = {".exe", ".dll", ".o", ".ppu", ".a", ".compiled", ".obj", ".or", ".dbg", ".pdb", ".zip", ".chm", ".pdf", ".log", ".lps", ".bak", ".bkp"}
trees = ["lcl", "components", "ideintf", "packager", "ide", "tools", "fpc/3.2.2/source"]
count = 0
with tarfile.open(output, "w:gz", compresslevel=6) as archive:
    archive.add(source_package, arcname="application/"+source_package.name)
    for p in args.lazarus_dir.iterdir():
        if p.is_file() and p.suffix.lower() not in excluded:
            archive.add(p, arcname="lazarus-3.2/"+p.name)
    for tree in trees:
        base = args.lazarus_dir/tree
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() in excluded:
                continue
            # Skip generated compiled-unit directories and editor backups.
            if any(part.lower() in {"backup", ".git", "__pycache__"} for part in p.relative_to(base).parts):
                continue
            archive.add(p, arcname="lazarus-3.2/"+p.relative_to(args.lazarus_dir).as_posix())
            count += 1
print(f"Corresponding source: {output.name}; {count} library source/resource files")
