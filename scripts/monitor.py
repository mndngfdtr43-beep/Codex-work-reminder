"""Start/stop only the background monitor launched by this project."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import psutil

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
RECORD = LOCAL / "monitor.json"


def current():
    if not RECORD.exists():
        return None
    try:
        saved = json.loads(RECORD.read_text("utf-8"))
        process = psutil.Process(saved["pid"])
        command = process.cmdline()
        if (abs(process.create_time() - saved["created"]) < 0.1
                and "bridge" in command and "-m" in command
                and str(ROOT).lower() in " ".join(command).lower()):
            return process
    except (psutil.Error, ValueError, KeyError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--port")
    args = parser.parse_args()
    process = current()
    if args.action == "status":
        print("后台监测正在运行。" if process else "没有本项目启动的后台监测。")
        return
    if args.action == "stop":
        if process:
            children = process.children(recursive=True)
            process.terminate()
            for child in children:
                try:
                    if "bridge" in child.cmdline():
                        child.terminate()
                except psutil.Error:
                    pass
            psutil.wait_procs([process, *children], timeout=3)
            RECORD.unlink(missing_ok=True)
            print("后台监测已停止；板载 RGB 灯在 3.5 秒内转为失联蓝闪。")
        else:
            print("没有本脚本启动的后台监测；普通终端窗口请用 Ctrl+C 退出。")
        return
    if process:
        print("后台监测已在运行。")
        return
    LOCAL.mkdir(exist_ok=True)
    command = [sys.executable, "-X", "utf8", "-u", "-m", "bridge"]
    if args.port:
        command += ["--port", args.port]
    log = LOCAL / "monitor.log"
    with log.open("w", encoding="utf-8") as output:
        child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    created = psutil.Process(child.pid).create_time()
    time.sleep(2)
    if child.poll() is not None:
        raise RuntimeError("监测未启动：\n" + log.read_text("utf-8"))
    RECORD.write_text(json.dumps({"pid": child.pid, "created": created}), encoding="utf-8")
    print("后台监测已启动。运行记录：" + str(log))


if __name__ == "__main__":
    main()
