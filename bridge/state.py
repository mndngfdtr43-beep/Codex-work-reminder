"""Pure state logic. A button request never proves that Codex stopped."""
from dataclasses import dataclass
from collections import OrderedDict
from enum import Enum


class State(str, Enum):
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING = "waiting"
    PENDING = "pending"
    ERROR = "error"


@dataclass(frozen=True)
class Snapshot:
    chat: str
    running: bool
    waiting: bool = False
    draft: str = ""
    foreground: bool = False
    key: str = ""
    view_id: tuple = ()
    new_chat: bool = False

    @property
    def identity(self) -> str:
        return self.key or self.chat


class GuardError(RuntimeError):
    pass


class Controller:
    def __init__(self, chat: str):
        self.chat = chat
        self.paused = False
        self.pending: str | None = None
        self.pending_since = 0.0

    def observe(self, snap: Snapshot, now: float | None = None) -> State:
        if snap.identity != self.chat:
            return State.UNKNOWN
        if self.pending and now is not None and now - self.pending_since > 8:
            self.timed_out()
            return State.ERROR
        if self.pending == "stop" and not snap.running:
            self.pending = None
            self.paused = True
        elif self.pending == "start" and snap.running:
            self.pending = None
            self.paused = False
        if self.pending:
            return State.PENDING
        if snap.waiting:
            return State.WAITING
        if snap.running:
            self.paused = False
            return State.RUNNING
        return State.PAUSED if self.paused else State.IDLE

    def action_for(self, snap: Snapshot) -> str:
        if snap.identity != self.chat:
            raise GuardError("当前聊天已切换，请在新页面稳定后再按 BOOT。")
        if not snap.foreground:
            raise GuardError("请先把要控制的 Codex 聊天切到前台，再按 BOOT。")
        if self.pending:
            raise GuardError("上一条操作还在等待 Codex 确认，请稍后再按。")
        if snap.waiting:
            raise GuardError("Codex 正在等待确认，请在电脑上处理；BOOT 不代替批准。")
        if snap.running:
            return "stop"
        if snap.draft.strip():
            return "send_draft"
        if self.paused and not snap.new_chat:
            return "resume"
        raise GuardError("当前没有待启动的任务。先在 Codex 输入框写好任务，再按 BOOT。")

    def requested(self, action: str, now: float = 0.0):
        self.pending = "stop" if action == "stop" else "start"
        self.pending_since = now

    def timed_out(self):
        self.pending = None


class ChatController:
    """Follow the displayed chat while keeping each chat's requests separate."""

    def __init__(self):
        self.sessions: OrderedDict[str, Controller] = OrderedDict()
        self.active: str | None = None

    def observe(self, snap: Snapshot, now: float) -> State:
        key = snap.identity
        if key not in self.sessions:
            self.sessions[key] = Controller(key)
        self.sessions.move_to_end(key)
        while len(self.sessions) > 256:
            self.sessions.popitem(last=False)
        self.active = key
        return self.sessions[key].observe(snap, now)

    def action_for(self, snap: Snapshot) -> str:
        if snap.identity != self.active:
            raise GuardError("当前聊天已切换，请在新页面稳定后再按 BOOT。")
        return self.sessions[self.active].action_for(snap)

    def requested(self, action: str, snap: Snapshot, now: float):
        # Navigation after sending must not attach the request to the next chat.
        self.sessions[snap.identity].requested(action, now)


class ButtonGate:
    """Reject stale/replayed events and rapid repeated presses."""
    def __init__(self):
        self.boot: str | None = None
        self.last_seq = -1
        self.last_time = -10.0

    def ready(self, boot: str):
        if self.boot != boot:
            self.boot = boot
            self.last_seq = -1

    def accept(self, boot: str, seq: int, now: float) -> bool:
        if boot != self.boot or seq <= self.last_seq or seq < 1:
            return False
        self.last_seq = seq
        if now - self.last_time < 0.8:
            return False
        self.last_time = now
        return True
