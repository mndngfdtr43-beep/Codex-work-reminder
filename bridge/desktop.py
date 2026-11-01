"""Windows UI Automation adapter for the installed Codex desktop application.

Only named accessibility controls are used. No screen coordinates, global
keystrokes, chat databases, browser debugging ports or injected scripts.
"""
import ctypes
import json
from collections import Counter
from dataclasses import dataclass
from .state import GuardError, Snapshot

COMPOSERS = {"和 Codex 一起工作", "Work with Codex", "向 Codex 提问", "Ask Codex"}
NEW_COMPOSERS = {"随心输入", "Ask anything"}
STOP_NAMES = {"停止", "停止生成", "Stop", "Stop generating", "Stop response"}
SEND_NAMES = {"发送", "发送消息", "提交", "Send", "Send message", "Submit"}
WAIT_NAMES = {
    "允许一次", "批准一次", "允许此会话", "批准此会话", "提交答案",
    "Allow once", "Approve once", "Allow for this session", "Submit answers",
}
CONTINUE_TEXT = "继续完成当前任务中尚未完成的工作；已完成的操作不要重复执行。"


@dataclass
class View:
    snapshot: Snapshot
    editor: object
    stop: object | None
    send: object | None


def only(items, label):
    if len(items) != 1:
        raise GuardError(f"无法唯一识别{label}（找到 {len(items)} 个）。请打开一个 Codex 聊天窗口。")
    return items[0]


def chat_row(rows, project):
    """Choose one mounted sidebar row; never merge ambiguous equal titles.

    A row is (parent list name, parent runtime ID, row runtime ID). A chat can
    appear once in its project/pinned list and once in Recents.
    """
    if project:
        scoped = [r for r in rows if r[0] == f"{project}中的已安排任务"]
        if scoped:
            return scoped[0][2] if len(scoped) == 1 else None
    if rows and max(Counter(r[1] for r in rows).values()) == 1:
        return rows[-1][2]
    return None


def same_target(actual: Snapshot, expected: Snapshot) -> bool:
    return (actual.identity == expected.identity and actual.view_id == expected.view_id
            and actual.new_chat == expected.new_chat and actual.foreground)


class CodexDesktop:
    def __init__(self):
        self.hwnd = None
        self.window = None
        self._select_window()

    def _select_window(self):
        from pywinauto import Desktop
        import psutil
        candidates = []
        for window in Desktop(backend="uia").windows():
            try:
                exe = psutil.Process(window.process_id()).exe().lower()
                # The current Codex package uses ChatGPT.exe as its UI process.
                if ("openai.codex_" in exe or "\\openai\\codex\\" in exe) and window.is_visible():
                    if any(d.element_info.automation_id == "RootWebArea"
                           for d in window.descendants(control_type="Document")):
                        candidates.append(window)
            except (psutil.Error, RuntimeError):
                continue
        foreground = ctypes.windll.user32.GetForegroundWindow()
        focused = [w for w in candidates if w.handle == foreground]
        previous = [w for w in candidates if w.handle == self.hwnd]
        self.window = only(focused or previous or candidates, "Codex 主窗口")
        self.hwnd = self.window.handle

    def read(self) -> View:
        self._select_window()
        if not self.window.is_visible() or self.window.is_minimized():
            raise GuardError("Codex 窗口已关闭或最小化，请恢复窗口。")
        document = only([d for d in self.window.descendants(control_type="Document")
                         if d.element_info.automation_id == "RootWebArea"], "聊天文档")
        raw_chat = document.window_text().strip()
        editors = [e for e in document.descendants(control_type="Edit")
                   if e.element_info.name in COMPOSERS | NEW_COMPOSERS
                   and e.is_visible() and e.is_enabled()]
        editor = only(editors, "Codex 输入框")
        composer = editor.parent()
        buttons = [b for b in composer.descendants(control_type="Button")
                   if b.is_visible() and b.is_enabled()]
        new_chat = editor.element_info.name in NEW_COMPOSERS
        if new_chat:
            # The generic new-chat placeholder also exists outside Codex mode.
            names = {b.window_text() for b in document.descendants(control_type="Button")}
            if ("切换模式，当前模式：Codex" not in names
                    and "选择聊天的运行位置" not in names):
                raise GuardError("请切换到 Codex 模式的新聊天。")
        chat = "新聊天" if new_chat else raw_chat
        if not chat:
            raise GuardError("无法读取当前聊天标题。")
        stops = [b for b in buttons if b.window_text() in STOP_NAMES]
        sends = [b for b in buttons if b.window_text() in SEND_NAMES]
        if len(stops) > 1 or len(sends) > 1:
            raise GuardError("输入框中存在多个停止/发送控件，暂不操作。")
        try:
            draft = (editor.get_value() or "").rstrip("\r\n")
        except Exception as exc:
            raise GuardError("无法读取输入框内容，暂不执行按键操作。") from exc
        # Chromium may expose the placeholder as Value for an empty editor.
        if draft.strip() in COMPOSERS | NEW_COMPOSERS:
            draft = ""
        view_id = (self.hwnd, self.window.process_id(), *editor.element_info.runtime_id)
        project = ""
        for toolbar in document.descendants(control_type="ToolBar"):
            for icon in toolbar.descendants(control_type="Image"):
                name = icon.window_text()
                for prefix in ("项目：", "Project: "):
                    if name.startswith(prefix):
                        project = name[len(prefix):]
        rows = []
        if not new_chat:
            for row in document.descendants(control_type="ListItem"):
                if row.window_text().strip() == chat:
                    parent = row.parent()
                    rows.append((parent.window_text(), tuple(parent.element_info.runtime_id),
                                 tuple(row.element_info.runtime_id)))
        row_id = chat_row(rows, project)
        if row_id:
            key = "sidebar:" + json.dumps((self.hwnd, self.window.process_id(), row_id, chat))
        else:
            # No durable chat ID is exposed by UIA. Scope ambiguous/missing
            # sidebar identities to this mounted editor, not a shared title.
            key = ("new:" if new_chat else "view:") + json.dumps((view_id, chat))
        waiting = any(b.window_text() in WAIT_NAMES and b.is_visible() and b.is_enabled()
                      for b in document.descendants(control_type="Button"))
        foreground = ctypes.windll.user32.GetForegroundWindow() == self.hwnd
        if document.window_text().strip() != raw_chat:
            raise GuardError("页面正在切换，稍后重读。")
        return View(Snapshot(chat, bool(stops), waiting, draft, foreground,
                             key, view_id, new_chat),
                    editor, stops[0] if stops else None, sends[0] if sends else None)

    def execute(self, action: str, expected: Snapshot):
        # Fresh observation immediately before every UI mutation.
        view = self.read()
        snap = view.snapshot
        if not same_target(snap, expected):
            raise GuardError("聊天或前台窗口已变化，已取消此次 BOOT 操作。")
        if snap.waiting:
            raise GuardError("请在电脑上处理待确认事项。")
        if action == "stop":
            if view.stop is None:
                raise GuardError("任务已结束，无需停止。")
            view.stop.invoke()
            return
        if snap.running or snap.draft != expected.draft:
            raise GuardError("AI 状态或输入框内容发生变化，已取消发送。")
        if action == "resume":
            if snap.draft:
                raise GuardError("输入框已有草稿，不覆盖草稿。")
            view.editor.set_edit_text(CONTINUE_TEXT)
            # A failed send is not retried automatically; the draft stays visible.
            view = self.read()
            if (not same_target(view.snapshot, expected)
                    or view.snapshot.running or view.snapshot.waiting
                    or view.snapshot.draft != CONTINUE_TEXT):
                raise GuardError("继续指令未能可靠写入，已停止操作，请检查输入框。")
        elif action != "send_draft" or not snap.draft.strip():
            raise GuardError("没有可发送的任务。")
        if view.send is None:
            raise GuardError("找不到可用的发送按钮，请在电脑上确认输入框。")
        view.send.invoke()
