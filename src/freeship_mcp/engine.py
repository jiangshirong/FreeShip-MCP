"""Isolated native calls with workspace confinement and transactional outputs."""
from __future__ import annotations

import asyncio
import json
import math
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Awaitable, Callable

UPSTREAM_COMMIT = "1de17e99fb2b1cc559cdf27c5cafb595a627a641"
PROTOCOL_VERSION = 3
MODEL_OUTPUT_OPERATIONS = frozenset({"save_model", "scale_model", "edit_control_net", "rebuild_hull", "generate_sections"})


def file_identity(path: Path) -> dict:
    data = path.read_bytes()
    return {"file_name": path.name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}


class EngineError(RuntimeError):
    """A native calculation or its verification failed."""


class Engine:
    def __init__(self, workspace: Path, executable: Path | None = None, timeout: float = 120):
        self.workspace = workspace.resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("Workspace must be a directory")
        self.executable = executable or Path(__file__).parent / "bin" / "freeship-engine.exe"
        self.executable = self.executable.resolve(strict=True)
        if not 0 < timeout <= 3600:
            raise ValueError("Timeout must be in (0, 3600] seconds")
        self.timeout = timeout

    def path(self, name: str, *, output: bool = False, suffixes: tuple[str, ...] = (".fbm", ".ftm")) -> Path:
        if not name or "\x00" in name:
            raise ValueError("A nonempty file path is required")
        p = Path(name)
        if not p.is_absolute():
            p = self.workspace / p
        p = p.resolve(strict=False)
        if not p.is_relative_to(self.workspace) or p == self.workspace:
            raise ValueError("File must be inside the configured workspace")
        if p.suffix.lower() not in suffixes:
            raise ValueError(f"Expected one of: {', '.join(suffixes)}")
        if output:
            if not p.parent.is_dir():
                raise ValueError("Output parent directory must already exist")
            if p.exists():
                raise FileExistsError("Output exists; choose a new filename")
        elif not p.is_file() or p.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("Input must be a regular file of at most 256 MiB")
        return p

    async def raw(self, request: dict[str, Any], progress: Callable[[float, str], Awaitable[None]] | None = None) -> dict:
        # The engine is a console binary. No desktop application or UI API is used.
        proc = await asyncio.create_subprocess_exec(
            str(self.executable), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=self.workspace, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            if progress:
                await progress(0, "Native engine started")
            payload = (json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
            async def communicate():
                errors = []
                async def read_errors():
                    while line := await proc.stderr.readline():
                        message = line.decode("utf-8", errors="replace").strip()
                        if message.startswith("FS_PROGRESS "):
                            _, fraction, text = message.split(" ", 2)
                            if progress:
                                await progress(min(1, max(0, float(fraction))), text)
                        else:
                            errors.append(message[-2000:])
                            del errors[:-10]
                err_task = asyncio.create_task(read_errors())
                try:
                    proc.stdin.write(payload)
                    try:
                        await proc.stdin.drain()
                    except (ConnectionResetError, BrokenPipeError):
                        pass
                    proc.stdin.close()
                    stdout = await proc.stdout.read()
                    await proc.wait()
                    await err_task
                    return stdout, "\n".join(errors)
                finally:
                    if not err_task.done():
                        err_task.cancel()
            stdout, stderr = await asyncio.wait_for(communicate(), self.timeout)
            try:
                result = json.loads(stdout)
            except (ValueError, UnicodeDecodeError) as exc:
                raise EngineError(f"Invalid native response (exit {proc.returncode})") from exc
            if proc.returncode != 0 or not result.get("ok"):
                raise EngineError(result.get("error") or stderr[-2000:])
            if progress:
                await progress(1, "Native calculation completed")
            return result
        except TimeoutError as exc:
            raise EngineError(f"Native calculation exceeded {self.timeout:g} seconds") from exc
        finally:
            if proc.returncode is None:
                proc.kill()
                await asyncio.shield(proc.wait())

    async def check(self) -> dict:
        info = await self.raw({"operation": "engine_info"})
        if info.get("protocol_version") != PROTOCOL_VERSION or info.get("upstream_commit") != UPSTREAM_COMMIT or not info.get("headless"):
            raise EngineError("Incompatible engine; reinstall a matching Windows package")
        return info

    async def call(self, operation: str, model_path: str, *, output_path: str | None = None,
                   progress=None, encoding: str = "cp1252", **params) -> dict:
        if encoding not in {"cp1251", "cp1252", "utf8"}:
            raise ValueError("encoding must be cp1251, cp1252, or utf8")
        model = self.path(model_path)
        if operation in MODEL_OUTPUT_OPERATIONS:
            version = params.setdefault("output_version", 335)
            if type(version) is not int or version not in (0, 335, 462):
                raise ValueError("output_version must be 0 (preserve), 335, or 462")
        identity = file_identity(model)
        expected = params.get("expected_model_sha256")
        if expected is not None and expected != identity["sha256"]:
            raise EngineError("Model snapshot hash mismatch; inspect current indices before editing")
        executable_identity = file_identity(self.executable)
        provenance = {"schema_version": 1, "model": identity,
                      "engine": executable_identity, "protocol_version": PROTOCOL_VERSION,
                      "upstream_commit": UPSTREAM_COMMIT,
                      "request": {"operation": operation, "encoding": encoding, **params}}

        def verified(result):
            if file_identity(model) != identity:
                raise EngineError("Input model changed during calculation; retry using a stable model file")
            if file_identity(self.executable) != executable_identity:
                raise EngineError("Engine changed during calculation; restart with a matching package")
            result["provenance"] = provenance
            return result

        request = dict(operation=operation, model_path=str(model), encoding=encoding, **params)
        if output_path is None:
            return verified(await self.raw(request, progress))
        target = self.path(output_path, output=True)
        if target == model:
            raise ValueError("Input cannot be overwritten")
        # Temporary output retains the format extension for the native loader.
        fd, temporary = tempfile.mkstemp(prefix=".freeship-", suffix=target.suffix, dir=target.parent)
        os.close(fd)
        temp = Path(temporary)
        try:
            request["output_path"] = str(temp)
            result = await self.raw(request, progress)
            saved = await self.raw(dict(operation="inspect_model", model_path=str(temp), encoding=encoding,
                                        include_control_net=operation == "edit_control_net"))
            if operation == "edit_control_net":
                for key in ("control_net_points", "control_net_edges", "control_net_faces"):
                    if result[key] != saved[key]:
                        raise EngineError("Edited control net changed during native save/reload; output rejected")
            result["output_format_version"] = saved["format_version"]
            passthrough = operation == "save_model" and model.suffix.lower() == target.suffix.lower() and not params.get("output_version")
            identical = operation == "save_model" and model.read_bytes() == temp.read_bytes()
            if passthrough and not identical:
                raise EngineError("Unmodified native write is not byte-identical; refusing a potentially lossy save")
            verified(result)
            provenance["output_model"] = {**file_identity(temp), "file_name": target.name}
            # Windows rename fails rather than overwriting if another call won the name.
            temp.rename(target)
            result["output_path"] = str(target)
            result["byte_identical_native_roundtrip"] = identical
            return result
        finally:
            temp.unlink(missing_ok=True)


def finite(value: float, name: str, *, positive: bool = False) -> float:
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return value


def positions(values: list[float] | None, interval: list[float] | None, name: str) -> list[float]:
    """Expand an explicit [start, end, step] grid without inventing an off-grid endpoint."""
    if values is not None and interval is not None:
        raise ValueError(f"Provide either {name} positions or its range, not both")
    if interval is not None:
        if len(interval) != 3:
            raise ValueError(f"{name} range must be [start_m, end_m, step_m]")
        start, end, step = interval
        finite(start, "start_m"); finite(end, "end_m"); finite(step, "step_m", positive=True)
        if end < start:
            raise ValueError("Range end must be at least its start")
        intervals = (end-start)/step
        if not math.isfinite(intervals) or intervals >= 1000:
            raise ValueError("At most 1000 positions are allowed")
        count = math.floor(intervals + 1e-10) + 1
        if count > 1000:
            raise ValueError("At most 1000 positions are allowed")
        values = [start + i*step for i in range(count)]
    result = [] if values is None else values
    if len(result) > 1000 or len(set(result)) != len(result):
        raise ValueError(f"At most 1000 unique {name} positions are allowed")
    for value in result:
        finite(value, name)
    return result
