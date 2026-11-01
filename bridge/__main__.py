import argparse
import json
import sys
import time
from pathlib import Path
from .state import ChatController, GuardError, State

LABELS = {
    State.DISCONNECTED: "设备未连接", State.UNKNOWN: "等待可识别的 Codex 页面",
    State.IDLE: "空闲：可在输入框写好任务，再按 BOOT 发送", State.RUNNING: "AI 工作中",
    State.PAUSED: "已停止：按 BOOT 继续", State.WAITING: "等待电脑端确认",
    State.PENDING: "等待 Codex 响应按键", State.ERROR: "操作失败，请查看提示",
}


def single_instance():
    import msvcrt
    folder = Path(__file__).resolve().parents[1] / ".local"
    folder.mkdir(exist_ok=True)
    handle = (folder / "bridge.lock").open("a+b")
    handle.seek(0)
    if not handle.read(1):
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        handle.close()
        raise GuardError("监测程序已在运行，请勿重复启动。") from exc
    return handle


def main():
    parser = argparse.ArgumentParser(description="Codex 桌面状态灯 + BOOT 控制（Windows）")
    parser.add_argument("--port", help="开发板串口，例如 COM3；省略时仅在唯一候选端口时选择")
    parser.add_argument("--inspect", action="store_true", help="只读检查 Codex 控件，不连接开发板")
    parser.add_argument("--demo", action="store_true", help="只测试灯光，BOOT 切换灯色，不控制 Codex")
    parser.add_argument("--list-ports", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("桌面控制仅支持 Windows。")
    from .serial_link import Board, candidate_ports
    ports = candidate_ports()
    if args.list_ports:
        for p in ports:
            print(f"{p.device}: {p.description}")
        return
    desktop = controller = None
    if not args.demo:
        from .desktop import CodexDesktop
        desktop = CodexDesktop()
        controller = ChatController()
        if args.inspect:
            view = desktop.read()
            print(json.dumps({"state": controller.observe(view.snapshot, time.monotonic()).value,
                              "foreground": view.snapshot.foreground,
                              "stop_control": view.stop is not None,
                              "send_control": view.send is not None,
                              "draft_empty": not view.snapshot.draft.strip(),
                              "chat_title": view.snapshot.chat,
                              "chat_key": view.snapshot.identity,
                              "new_chat": view.snapshot.new_chat}, ensure_ascii=False, indent=2))
            return
        print("自动跟随当前 Codex 聊天，包括新建会话，无需重新启动监测。")
        print("BOOT 操作前台聊天：工作时停止；已停止时继续；有草稿时发送草稿。")
    lock = single_instance()
    port = args.port
    if not port:
        if len(ports) != 1:
            raise GuardError("请用 --list-ports 查看串口，再用 --port COMxx 指定开发板。")
        port = ports[0].device
    print(f"串口：{port}。Ctrl+C 退出。" + ("灯光演示模式，不控制 Codex。" if args.demo else ""))
    board = None
    handshake_announced = False
    retry_at = next_scan = 0.0
    last_status = None
    last_chat_key = None
    status = State.UNKNOWN
    flash_until = 0.0
    demo_states = [State.IDLE, State.RUNNING, State.PAUSED, State.WAITING, State.ERROR, State.UNKNOWN]
    demo_index = 0
    try:
        while True:
            now = time.monotonic()
            if board is None and now >= retry_at:
                try:
                    board = Board(port)
                    handshake_announced = False
                    print("等待 CAR1 固件握手……")
                except OSError as exc:
                    print(f"串口连接失败：{exc}")
                    retry_at = now + 3.0
            if args.demo:
                status = demo_states[demo_index]
            elif now >= next_scan:
                try:
                    snapshot = desktop.read().snapshot
                    status = controller.observe(snapshot, time.monotonic())
                    if snapshot.identity != last_chat_key:
                        print("正在跟随聊天：" + snapshot.chat, flush=True)
                        last_chat_key = snapshot.identity
                    if status == State.ERROR:
                        flash_until = now + 3
                        print("Codex 没有在 8 秒内确认操作。请检查界面；不会自动重试。")
                except Exception as exc:
                    status = State.UNKNOWN
                    if last_status != State.UNKNOWN:
                        print(f"界面读取失败：{exc}")
                next_scan = time.monotonic() + 0.5
            if status != last_status:
                print(LABELS[status], flush=True)
                last_status = status
            if board:
                try:
                    pressed = board.poll(time.monotonic())
                    if board.ready and not handshake_announced:
                        print("CAR1 固件握手成功，状态灯通信已连接。", flush=True)
                        handshake_announced = True
                    board.send_state(State.ERROR if now < flash_until else status, time.monotonic())
                    if time.monotonic() - board.started_at > 6 and not board.ready:
                        raise OSError("没有收到 CAR1 固件心跳。检查烧录、串口占用和 USB 数据线。")
                    if pressed:
                        if args.demo:
                            demo_index = (demo_index + 1) % len(demo_states)
                        else:
                            try:
                                fresh = desktop.read().snapshot
                                controller.observe(fresh, time.monotonic())
                                action = controller.action_for(fresh)
                                # Send pending before potentially slow UIA calls.
                                board.send_state(State.PENDING, time.monotonic(), force=True)
                                desktop.execute(action, fresh)
                                controller.requested(action, fresh, time.monotonic())
                                print("已请求：" + action + "；聊天：" + fresh.chat)
                                next_scan = 0
                            except Exception as exc:
                                print(f"BOOT 操作未完成：{exc}")
                                flash_until = time.monotonic() + 3
                except OSError as exc:
                    print(f"设备离线：{exc}")
                    try:
                        board.close()
                    except OSError:
                        pass
                    board = None
                    retry_at = time.monotonic() + 3
            time.sleep(0.04)
    except KeyboardInterrupt:
        print("\n监测已退出。")
    finally:
        if board:
            try:
                board.close()
            except OSError:
                pass
        lock.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"无法启动：{exc}", file=sys.stderr)
        sys.exit(1)
