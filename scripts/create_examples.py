"""Generate original synthetic test models; no third-party hull data."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import subprocess


def hull_request(output: Path) -> dict:
    points, faces = [], []
    count = 21
    for i in range(count):
        x = 40 * i / (count - 1)
        width = 0.15 + 3.85 * math.sin(math.pi * i / (count - 1)) ** 0.7
        points.extend([[x, 0, 0], [x, width * 0.7, 0], [x, width, 6]])
    for i in range(count - 1):
        a, b = 3 * i, 3 * (i + 1)
        faces.extend([[a, a + 1, b + 1, b], [a + 1, a + 2, b + 2, b + 1]])
    # End caps close only the submerged half-breadth; centerplane is mirrored.
    points.extend([[0, 0, 6], [40, 0, 6]])
    faces.append([0, len(points) - 2, 2, 1])
    end = 3 * (count - 1)
    faces.append([end, end + 1, end + 2, len(points) - 1])
    return dict(operation="create_mesh", output_path=str(output), points_m=points, faces=faces,
                length_m=40, beam_m=8, draft_m=3, density_t_m3=1.025,
                appendage_coefficient=1, crease_edges=False)


def run(engine: Path, request: dict) -> dict:
    result = subprocess.run([str(engine)], input=(json.dumps(request, ensure_ascii=False) + "\n").encode(),
                            capture_output=True, timeout=120)
    data = json.loads(result.stdout)
    if result.returncode or not data.get("ok"):
        raise RuntimeError(data)
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--engine", type=Path, default=Path(__file__).resolve().parents[1] / "src/freeship_mcp/bin/freeship-engine.exe")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run(args.engine, dict(operation="create_box", output_path=str((args.output_dir / "box.fbm").resolve())))
    print(run(args.engine, hull_request((args.output_dir / "synthetic-hull.fbm").resolve())))
