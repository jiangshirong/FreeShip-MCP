"""Record installed, tested runtime dependencies (Windows/Python 3.11)."""
from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

todo = ["mcp", "openpyxl", "ezdxf"]
found = {}
while todo:
    name = canonicalize_name(todo.pop())
    if name in found:
        continue
    dist = distribution(name)
    found[name] = dist.version
    for spec in dist.requires or []:
        req = Requirement(spec)
        if req.marker is None or req.marker.evaluate({"extra": ""}):
            todo.append(req.name)
root = Path(__file__).resolve().parents[1]
(root / "requirements.lock").write_text(
    "# Tested Windows x64 / Python 3.11 runtime dependency snapshot\n" +
    "\n".join(f"{name}=={version}" for name, version in sorted(found.items())) + "\n", encoding="utf-8")
