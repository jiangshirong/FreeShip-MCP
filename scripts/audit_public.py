"""Reviewable source allowlist; no broad git add, private course data or local binaries."""
from pathlib import Path
import argparse
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {
    ".gitignore", ".gitattributes", "LICENSE", "NOTICE", "README.md", "README.zh-CN.md",
    "UPSTREAM.json", "pyproject.toml", "setup.py", "MANIFEST.in", "requirements.lock",
    "requirements-dev.lock", "vendor-manifest.json", "PUBLIC-FILES.txt",
}
TOP_DIRS = {"engine", "scripts", "docs", "tests", "examples", "src", "vendor", ".github"}
GENERATED = {"__pycache__", ".pytest_cache", "backup", "lib"}
BAD_SUFFIX = {".pyc", ".pyo", ".ppu", ".o", ".obj", ".compiled", ".bak", ".bkp", ".lps", ".log", ".lrj", ".or", ".rsj", ".egg-info"}


def allowed(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if relative.as_posix() in TOP_FILES:
        return True
    if relative.parts[0] not in TOP_DIRS:
        return False
    if any(part in GENERATED or part.endswith(".egg-info") for part in relative.parts):
        return False
    if path.suffix.lower() in BAD_SUFFIX:
        return False
    if relative.parts[:3] == ("src", "freeship_mcp", "bin"):
        return path.suffix.lower() == ".json"
    if path.suffix.lower() in {".exe", ".dll", ".docx", ".pptx", ".xlsx", ".pdf", ".zip", ".tar", ".gz"}:
        return False
    if path.suffix.lower() in {".fbm", ".ftm"}:
        return relative.as_posix() in {"examples/box.fbm", "examples/synthetic-hull.fbm"}
    if path.suffix.lower() == ".res":
        return relative.as_posix() == "vendor/freeship/Units/cursors.res"
    return True


def candidates():
    files = []
    for name in TOP_FILES:
        if (ROOT/name).is_file():
            files.append(ROOT/name)
    for name in TOP_DIRS:
        directory = ROOT/name
        if directory.is_dir():
            files.extend(p for p in directory.rglob("*") if p.is_file() and allowed(p))
    return sorted(set(files), key=lambda p: p.relative_to(ROOT).as_posix())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--stage", action="store_true", help="Stage only the reviewed explicit manifest")
    args = parser.parse_args()
    paths = candidates()
    public = ROOT/"PUBLIC-FILES.txt"
    if args.write_manifest:
        paths = sorted(set(paths+[public]), key=lambda p: p.relative_to(ROOT).as_posix())
        public.write_text("\n".join(p.relative_to(ROOT).as_posix() for p in paths)+"\n", encoding="utf-8")
    manifest = set(public.read_text(encoding="utf-8").splitlines())
    current = {p.relative_to(ROOT).as_posix() for p in paths}
    if current != manifest:
        raise SystemExit(f"Allowlist drift: missing={sorted(current-manifest)} stale={sorted(manifest-current)}")
    # Check project-owned sources, not original upstream author notices.
    forbidden = ["wxid_", "xwechat_files"]
    for p in paths:
        rel = p.relative_to(ROOT)
        if rel.parts[0] == "vendor" or p.suffix.lower() not in {".py", ".md", ".json", ".txt", ".ps1", ".yml", ".toml", ".lock"}:
            continue
        text = p.read_text(encoding="utf-8-sig")
        # This audit necessarily contains the forbidden patterns themselves.
        if p.name == "audit_public.py":
            continue
        for pattern in forbidden:
            if pattern in text:
                raise SystemExit(f"Private pattern {pattern!r} in {rel}")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    unexpected = {p for p in tracked if p and p not in manifest}
    if unexpected:
        raise SystemExit(f"Unexpected tracked paths: {unexpected}")
    if args.stage:
        subprocess.run(["git", "--literal-pathspecs", "add", "--pathspec-from-file=PUBLIC-FILES.txt"], cwd=ROOT, check=True)
    print(json.dumps({"passed": True, "public_files": len(manifest), "staged": args.stage}))


if __name__ == "__main__":
    main()
