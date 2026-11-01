"""Build ESP-IDF 5.5.5 bootloader with exact XMC 0x207018 support.

Source: https://github.com/espressif/esp-idf/issues/18947
Only an isolated source copy under .tools is patched, never the installed SDK.
All existing chip checks remain intact; no startup check is disabled.
"""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATCH_MARKER = "AI_STATUS_CAR_XMC_207018"


@contextmanager
def ascii_workspace():
    # A temporary drive alias keeps every actual file in this project while
    # avoiding the Xtensa linker's inability to open Unicode absolute paths.
    drive = next((x + ":" for x in "ZYXWVUTSR" if not Path(x + ":/").exists()), None)
    if drive is None:
        raise RuntimeError("No free drive letter available for the temporary build alias")
    subprocess.run(["subst", drive, str(ROOT)], check=True)
    try:
        yield Path(drive + "/")
    finally:
        subprocess.run(["subst", drive, "/D"], check=True)


def build_bootloader(root, args):
    source = args.idf / "components/bootloader_support/bootloader_flash/src/bootloader_flash.c"
    text = source.read_text(encoding="utf-8")
    anchor = "static IRAM_ATTR bool is_xmc_chip_strict(uint32_t rdid)\n{\n"
    if PATCH_MARKER not in text:
        if text.count(anchor) != 1:
            raise RuntimeError("ESP-IDF source does not match the reviewed patch location")
        text = text.replace(anchor, anchor + "    // " + PATCH_MARKER + ": exact locally verified JEDEC ID.\n"
                            "    if (rdid == 0x207018) { return true; }\n", 1)
        source.write_text(text, encoding="utf-8", newline="\n")
    idf_tools = root / ".tools/espressif"
    idf_tools.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / ".tools/espidf.constraints.v5.5.txt", idf_tools / "espidf.constraints.v5.5.txt")
    env = os.environ.copy()
    env.update(IDF_PATH=str(args.idf), IDF_TARGET="esp32s3", IDF_COMPONENT_MANAGER="0", PYTHONUTF8="1",
               IDF_PYTHON_ENV_PATH=str(args.python.parent.parent),
               IDF_TOOLS_PATH=str(root / ".tools/espressif"),
               PATH=str(args.python.parent) + os.pathsep + str(args.toolchain)
                    + os.pathsep + env.get("PATH", ""))
    # Configure the official bootloader subproject directly. No application,
    # MQTT/Wi-Fi libraries or unrelated ESP-IDF submodules are needed.
    build = root / ("build/xmc-bootloader-" + root.drive[0])
    build.mkdir(parents=True, exist_ok=True)
    defaults = root / "firmware/bootloader/sdkconfig.defaults"
    if not (build / "sdkconfig").exists():
        shutil.copyfile(defaults, build / "sdkconfig")
    components = ("bootloader esptool_py esp_hw_support esp_system freertos hal partition_table soc "
                  "bootloader_support log spi_flash efuse newlib esp_tee esp_rom esp_common "
                  "esp_app_format esp_bootloader_format xtensa esp_security").split()
    subproject = args.idf / "components/bootloader/subproject"
    dirs = [args.idf / "components" / name for name in components]
    dirs += [subproject / "components/micro-ecc", subproject / "main"]
    cmake = str(args.python.parent / "cmake.exe")
    subprocess.run([cmake, "-G", "Ninja", "-S", str(subproject), "-B", str(build),
                    "-DIDF_PATH=" + args.idf.as_posix(), "-DIDF_TARGET=esp32s3",
                    "-DPYTHON=" + args.python.as_posix(), "-DPYTHON_DEPS_CHECKED=1",
                    "-DSDKCONFIG=" + (build / "sdkconfig").as_posix(),
                    "-DSDKCONFIG_DEFAULTS=" + defaults.as_posix(),
                    "-DCOMPONENT_DIRS=" + ";".join(p.as_posix() for p in dirs)], env=env, check=True)
    subprocess.run([cmake, "--build", str(build)], env=env, check=True)
    out = root / "build/bootloader-xmc207018.bin"
    shutil.copyfile(build / "bootloader.bin", out)
    print("Patched bootloader:", out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, default=Path(os.environ.get("LOCALAPPDATA", "")) /
                        "Arduino15/packages/esp32/tools/esp-x32/2601/bin")
    args = parser.parse_args()
    with ascii_workspace() as root:
        args.idf = root / ".tools/esp-idf-5.5.5"
        args.python = root / ".tools/idf-venv/Scripts/python.exe"
        build_bootloader(root, args)


if __name__ == "__main__":
    main()
