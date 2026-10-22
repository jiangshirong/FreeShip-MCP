"""Record installed, tested runtime dependencies (Windows/Python 3.11)."""
from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

todo = [(name, set()) for name in ("mcp", "openpyxl", "ezdxf")]
found = {}
visited = set()
while todo:
    requested_name, extras = todo.pop()
    name = canonicalize_name(requested_name)
    visit_key = (name, frozenset(extras))
    if visit_key in visited:
        continue
    visited.add(visit_key)
    dist = distribution(name)
    found[name] = dist.version
    for spec in dist.requires or []:
        req = Requirement(spec)
        if req.marker is None or any(req.marker.evaluate({"extra": extra}) for extra in extras | {""}):
            todo.append((req.name, set(req.extras)))
root = Path(__file__).resolve().parents[1]
(root / "requirements.lock").write_text(
    "# Tested Windows x64 / Python 3.11 runtime dependency snapshot\n" +
    "\n".join(f"{name}=={version}" for name, version in sorted(found.items())) + "\n", encoding="utf-8")
