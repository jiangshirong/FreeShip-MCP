"""Verify the committed vendor snapshot and unchanged numerical method bodies."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "vendor-manifest.json").read_text(encoding="utf-8"))
for item in manifest["files"]:
    path = ROOT / "vendor/freeship" / item["path"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise SystemExit(f"Vendor snapshot drift: {item['path']}")
for name in ("FreeHydrostaticCalc.inc", "FreeIntersection.inc", "FreeSubdivisionSurface.inc", "FreeSpline.inc"):
    item = next(v for v in manifest["files"] if v["path"] == f"Units/{name}")
    if item["sha256"] != item["upstream_sha256"]:
        raise SystemExit(f"Numerical source changed: {name}")
print(f"Verified {len(manifest['files'])} vendor files and unchanged native numerical methods")
