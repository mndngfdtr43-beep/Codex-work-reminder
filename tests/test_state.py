import pytest
from bridge.state import ButtonGate, ChatController, Controller, GuardError, Snapshot, State


def snap(**changes):
    return Snapshot(**dict(dict(chat="test", running=False, foreground=True), **changes))


def test_stop_only_becomes_paused_after_observed_completion():
    c = Controller("test")
    assert c.action_for(snap(running=True)) == "stop"
    c.requested("stop")
    assert c.observe(snap(running=True)) == State.PENDING
    assert not c.paused
    assert c.observe(snap()) == State.PAUSED
    assert c.action_for(snap()) == "resume"
    c.requested("resume")
    assert c.observe(snap()) == State.PENDING
    assert c.observe(snap(running=True)) == State.RUNNING
    assert not c.paused


@pytest.mark.parametrize("s", [snap(chat="other"), snap(foreground=False), snap(waiting=True)])
def test_no_control_of_other_chat_background_or_approval(s):
    c = Controller("test")
    with pytest.raises(GuardError):
        c.action_for(s)


def test_idle_empty_never_repeats_completed_task():
    c = Controller("test")
    assert c.observe(snap()) == State.IDLE
    with pytest.raises(GuardError):
        c.action_for(snap())
    assert c.action_for(snap(draft="A task typed by the user")) == "send_draft"


def test_existing_draft_takes_precedence_over_resume_text():
    c = Controller("test")
    c.paused = True
    assert c.action_for(snap(draft="user draft")) == "send_draft"


def test_pending_request_blocks_double_click_and_timeout_does_not_fake_success():
    c = Controller("test")
    c.requested("stop")
    with pytest.raises(GuardError):
        c.action_for(snap(running=True))
    c.timed_out()
    assert c.observe(snap(running=True)) == State.RUNNING


def test_switching_chat_does_not_confirm_stop():
    c = Controller("test")
    c.requested("stop")
    assert c.observe(snap(chat="other")) == State.UNKNOWN
    assert not c.paused
    assert c.pending == "stop"


def test_button_duplicate_bounce_and_device_reboot():
    g = ButtonGate()
    assert not g.accept("a", 1, 0)
    g.ready("a")
    assert g.accept("a", 1, 1)
    g.ready("a")  # repeated handshake must not reset replay protection
    assert not g.accept("a", 1, 2)
    assert not g.accept("a", 2, 1.1)
    assert not g.accept("a", 2, 3)
    assert g.accept("a", 3, 3)
    g.ready("b")
    assert not g.accept("a", 4, 4)
    assert g.accept("b", 1, 4)


def test_follow_another_chat_then_return_to_its_own_paused_state():
    c = ChatController()
    a = snap(chat="A", key="row-a", running=True)
    b = snap(chat="B", key="row-b")
    assert c.observe(a, 1) == State.RUNNING
    c.requested("stop", a, 2)
    a = snap(chat="A", key="row-a")
    assert c.observe(a, 3) == State.PAUSED
    assert c.observe(b, 4) == State.IDLE
    with pytest.raises(GuardError):
        c.action_for(b)  # B must not inherit A's resume message.
    assert c.observe(a, 5) == State.PAUSED
    assert c.action_for(a) == "resume"


def test_pending_operation_in_one_chat_does_not_block_another():
    c = ChatController()
    a, b = snap(key="a", running=True), snap(key="b", running=True)
    c.observe(a, 0)
    c.requested("stop", a, 1)
    assert c.observe(b, 2) == State.RUNNING
    assert c.action_for(b) == "stop"
    with pytest.raises(GuardError):
        c.action_for(a)  # A stale observation cannot act on the selected B.
    assert not c.sessions["a"].paused
    assert c.observe(snap(key="a"), 3) == State.PAUSED


def test_request_expires_while_another_chat_is_displayed():
    c = ChatController()
    a = snap(key="a", running=True)
    c.observe(a, 0)
    c.requested("stop", a, 1)
    assert c.observe(snap(key="b"), 5) == State.IDLE
    # Coming back later must not treat an unrelated completion as our stop.
    assert c.observe(snap(key="a"), 20) == State.ERROR
    assert c.observe(snap(key="a"), 21) == State.IDLE
    with pytest.raises(GuardError):
        c.action_for(snap(key="a"))


def test_new_chat_draft_and_first_running_turn_need_no_restart():
    c = ChatController()
    empty = snap(chat="新聊天", key="new-editor", new_chat=True)
    assert c.observe(empty, 0) == State.IDLE
    with pytest.raises(GuardError):
        c.action_for(empty)
    draft = snap(chat="新聊天", key="new-editor", new_chat=True, draft="用户写好的新任务")
    assert c.action_for(draft) == "send_draft"
    c.requested("send_draft", draft, 1)
    created = snap(chat="新任务标题", key="new-sidebar-row", running=True)
    assert c.observe(created, 2) == State.RUNNING
    assert c.action_for(created) == "stop"


def test_equal_titles_with_different_sidebar_rows_keep_states_separate():
    c = ChatController()
    a, b = snap(key="project-one-row"), snap(key="project-two-row")
    c.observe(a, 0)
    c.requested("stop", a, 1)
    assert c.observe(a, 2) == State.PAUSED
    assert c.observe(b, 3) == State.IDLE
    with pytest.raises(GuardError):
        c.action_for(b)


def test_new_page_cannot_inherit_an_automatic_resume():
    c = Controller("new")
    c.paused = True
    with pytest.raises(GuardError):
        c.action_for(snap(key="new", new_chat=True))
