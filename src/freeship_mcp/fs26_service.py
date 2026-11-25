"""Private, revision-checked transport for the FS26 native document service."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryFile
from uuid import uuid4

from anyio import CancelScope

from .engine import EngineError

MAX_REQUEST_BYTES = 1024 * 1024


class DocumentService:
    def __init__(self, process: asyncio.subprocess.Process, directory: Path, stderr):
        self.process = process
        self.directory = directory
        self.stderr = stderr
        self.request_id = 0
        self.document_id = None
        self.revision = 0

    def error_log(self) -> str:
        size = self.stderr.seek(0, os.SEEK_END)
        self.stderr.seek(max(0, size - 1000))
        return self.stderr.read().decode("utf-8", errors="replace").strip()

    async def request(self, method: str, **parameters) -> dict:
        self.request_id += 1
        message = {"id": self.request_id, "method": method, **parameters}
        payload = json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(payload) > MAX_REQUEST_BYTES:
            raise ValueError("FS26 request exceeds 1 MiB")
        try:
            self.process.stdin.write(payload + b"\n")
            await self.process.stdin.drain()
            while line := await self.process.stdout.readline():
                if line.lstrip().startswith(b"{"):
                    break
            else:
                raise EngineError(f"FS26 document service closed its output: {self.error_log()}")
            response = json.loads(line)
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise EngineError(f"FS26 document service closed its input: {self.error_log()}") from exc
        except (ValueError, UnicodeError) as exc:
            raise EngineError("Invalid JSON response from FS26 document service") from exc
        if response.get("id") != self.request_id or response.get("document_engine") != "cpp-document":
            raise EngineError("Unexpected FS26 document service response")
        if response.get("ok") is not True:
            raise EngineError(str(response.get("error") or f"FS26 {method} failed"))
        return response

    def _output(self) -> str:
        path = self.directory / f"request-{self.request_id + 1}"
        path.mkdir()
        return str(path)

    async def open_document(self, method: str, **parameters) -> dict:
        document_id = str(uuid4())
        response = await self.request(method, document_id=document_id, output=self._output(),
                                      native_linesplan=True, **parameters)
        if response.get("document_id") != document_id or response.get("revision") != 1:
            raise EngineError("FS26 did not publish a new document at revision 1")
        self.document_id, self.revision = document_id, 1
        return response

    async def current(self, method: str, *, edit: bool = False, **parameters) -> dict:
        response = await self.request(method, expected_document_id=self.document_id,
                                      expected_revision=self.revision, output=self._output(),
                                      native_linesplan=True, **parameters)
        revision = response.get("revision")
        allowed = (self.revision, self.revision + 1) if edit else (self.revision,)
        if response.get("document_id") != self.document_id or type(revision) is not int or revision not in allowed:
            raise EngineError("FS26 response belongs to a different document or revision")
        self.revision = revision
        return response

    def artifact_path(self, response: dict, key: str) -> Path:
        name = response.get(key)
        if not isinstance(name, str) or not name:
            raise EngineError(f"Missing FS26 {key} artifact")
        path = Path(name).resolve()
        if not path.is_relative_to(self.directory) or not path.is_file():
            raise EngineError(f"Invalid location for FS26 {key} artifact")
        return path

    def artifact_json(self, response: dict, key: str) -> dict:
        try:
            artifact = json.loads(self.artifact_path(response, key).read_bytes())
        except (ValueError, UnicodeError) as exc:
            raise EngineError(f"Invalid FS26 {key} artifact") from exc
        if not isinstance(artifact, dict):
            raise EngineError(f"Invalid FS26 {key} structure")
        if artifact.get("document_id") != response["document_id"] or artifact.get("revision") != response["revision"]:
            raise EngineError(f"FS26 {key} belongs to a different document or revision")
        return artifact


@asynccontextmanager
async def run_document_service(executable: Path, directory: Path, timeout: float):
    with TemporaryFile(mode="w+b", dir=directory) as stderr:
        process = await asyncio.create_subprocess_exec(
            str(executable), "--serve", str(os.getpid()), cwd=directory,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            limit=MAX_REQUEST_BYTES,
        )
        service = DocumentService(process, directory, stderr)
        try:
            async with asyncio.timeout(timeout):
                yield service
                await service.request("quit")
                await process.wait()
            if process.returncode != 0:
                raise EngineError(f"FS26 document service exited with code {process.returncode}: {service.error_log()}")
        except TimeoutError as exc:
            raise EngineError(f"FS26 document service exceeded {timeout:g} seconds") from exc
        finally:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
                # The MCP client can cancel through AnyIO. Reap the child before deleting its files.
                with CancelScope(shield=True):
                    await process.communicate()
