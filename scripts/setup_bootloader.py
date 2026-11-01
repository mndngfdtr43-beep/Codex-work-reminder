"""Prepare isolated ESP-IDF tools and build the XMC-compatible bootloader."""
import hashlib
from pathlib import Path, PurePosixPath
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"


def download(url, filename, sha256=None):
    target = TOOLS / filename
    if not target.exists():
        print("Downloading", url, flush=True)
        urllib.request.urlretrieve(url, target)
    if sha256 and hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
        raise RuntimeError(f"Checksum mismatch: {target}; remove the corrupt cache file and rerun.")
    return target


def extract(archive, destination, strip_first=False):
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            parts = PurePosixPath(item.filename).parts
            if strip_first:
                parts = parts[1:]
            if not parts or item.is_dir():
                continue
            path = destination.joinpath(*parts).resolve()
            if not path.is_relative_to(destination):
                raise RuntimeError("Unsafe path in source archive")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(z.read(item))


def main():
    TOOLS.mkdir(exist_ok=True)
    source = TOOLS / "esp-idf-5.5.5"
    archive = download("https://codeload.github.com/espressif/esp-idf/zip/refs/tags/v5.5.5",
                       "esp-idf-v5.5.5.zip", "1ac6ef6492f7a06d22e5672a346260f5eaf9ef33fd5a96e14b119d373c6c7e08")
    if not (source / "tools/cmake/project.cmake").exists():
        extract(archive, TOOLS)
    micro = source / "components/bootloader/subproject/components/micro-ecc/micro-ecc"
    archive = download("https://codeload.github.com/kmackay/micro-ecc/zip/24c60e243580c7868f4334a1ba3123481fe1aa48",
                       "micro-ecc.zip", "5c7883ae2c1f8c124442a2b859ad883ba46240ad23eb474586a5038ea80c23e1")
    if not (micro / "uECC.c").exists():
        extract(archive, micro, strip_first=True)
    constraints = download("https://dl.espressif.com/dl/esp-idf/espidf.constraints.v5.5.txt",
                           "espidf.constraints.v5.5.txt")
    python = TOOLS / "idf-venv/Scripts/python.exe"
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(TOOLS / "idf-venv")], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r",
                    str(source / "tools/requirements/requirements.core.txt"),
                    "-c", str(constraints), "cmake==3.30.9", "ninja==1.13.2"], check=True)
    subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/prepare_xmc_bootloader.py")], check=True)


if __name__ == "__main__":
    main()
