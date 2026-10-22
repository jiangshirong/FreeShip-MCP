"""Tag the Python package for the bundled Windows x64 calculation executable."""
from pathlib import Path
import struct
from setuptools import setup
from wheel.bdist_wheel import bdist_wheel


class WindowsWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False
        self.plat_name = "win_amd64"

    def get_tag(self):
        return "py3", "none", "win_amd64"

    def run(self):
        engine = Path(__file__).parent / "src/freeship_mcp/bin/freeship-engine.exe"
        if not engine.is_file():
            raise RuntimeError("Build the native engine with scripts/build-engine.ps1 first")
        data = engine.read_bytes()
        offset = struct.unpack_from("<I", data, 0x3C)[0]
        if data[offset:offset+4] != b"PE\0\0" or struct.unpack_from("<H", data, offset+4)[0] != 0x8664:
            raise RuntimeError("The engine must be a Windows AMD64 executable")
        super().run()


setup(cmdclass={"bdist_wheel": WindowsWheel})
