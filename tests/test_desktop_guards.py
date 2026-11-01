from collections import deque
from unittest.mock import Mock
import pytest
from bridge.desktop import CodexDesktop, CONTINUE_TEXT, View, chat_row
from bridge.state import GuardError, Snapshot


def view(**changes):
    snapshot = Snapshot(**dict(dict(chat="bound", running=False, foreground=True), **changes))
    return View(snapshot, Mock(), Mock() if snapshot.running else None,
                None if snapshot.running else Mock())


def desktop(*views):
    d = object.__new__(CodexDesktop)
    queue = deque(views)
    d.read = lambda: queue.popleft()
    return d


def test_stop_invokes_only_observed_stop_button():
    v = view(running=True)
    desktop(v).execute("stop", v.snapshot)
    v.stop.invoke.assert_called_once_with()
    v.editor.set_edit_text.assert_not_called()


@pytest.mark.parametrize("changed", [view(chat="different"), view(foreground=False), view(waiting=True)])
def test_recheck_window_and_chat_immediately_before_stop(changed):
    expected = view(running=True).snapshot
    with pytest.raises(GuardError):
        desktop(changed).execute("stop", expected)
    changed.editor.set_edit_text.assert_not_called()
    if changed.send:
        changed.send.invoke.assert_not_called()


def test_resume_rechecks_written_text_then_invokes_send():
    before = view()
    after = view(draft=CONTINUE_TEXT)
    desktop(before, after).execute("resume", before.snapshot)
    before.editor.set_edit_text.assert_called_once_with(CONTINUE_TEXT)
    after.send.invoke.assert_called_once_with()


@pytest.mark.parametrize("after", [view(draft="unexpected"), view(chat="different", draft=CONTINUE_TEXT),
                                   view(foreground=False, draft=CONTINUE_TEXT),
                                   view(waiting=True, draft=CONTINUE_TEXT)])
def test_no_send_after_write_race_or_failed_write(after):
    before = view()
    with pytest.raises(GuardError):
        desktop(before, after).execute("resume", before.snapshot)
    after.send.invoke.assert_not_called()


def test_preserve_draft_that_changed_between_button_and_action():
    expected = view(draft="old draft").snapshot
    current = view(draft="new draft")
    with pytest.raises(GuardError):
        desktop(current).execute("send_draft", expected)
    current.editor.set_edit_text.assert_not_called()
    current.send.invoke.assert_not_called()


def test_send_existing_draft_without_overwriting_it():
    current = view(draft="a task written by the user")
    desktop(current).execute("send_draft", current.snapshot)
    current.send.invoke.assert_called_once_with()
    current.editor.set_edit_text.assert_not_called()


def test_never_overwrite_nonempty_draft_with_resume_message():
    current = view(draft="a task written by the user")
    with pytest.raises(GuardError):
        desktop(current).execute("resume", current.snapshot)
    current.editor.set_edit_text.assert_not_called()
    current.send.invoke.assert_not_called()


def test_stop_in_any_selected_chat_not_just_startup_chat():
    current = view(chat="a newly opened conversation", key="row-new", running=True)
    desktop(current).execute("stop", current.snapshot)
    current.stop.invoke.assert_called_once_with()


def test_same_title_but_different_editor_during_action_is_rejected():
    expected = view(view_id=(1, 100), running=True).snapshot
    changed = view(view_id=(1, 200), running=True)
    with pytest.raises(GuardError):
        desktop(changed).execute("stop", expected)
    changed.stop.invoke.assert_not_called()


def test_same_title_different_chat_after_writing_resume_is_not_sent():
    before = view(key="row-a")
    after = view(key="row-b", draft=CONTINUE_TEXT)
    with pytest.raises(GuardError):
        desktop(before, after).execute("resume", before.snapshot)
    after.send.invoke.assert_not_called()


def test_new_chat_sends_only_the_users_draft():
    current = view(chat="新聊天", key="new-page", new_chat=True, draft="新任务")
    desktop(current).execute("send_draft", current.snapshot)
    current.send.invoke.assert_called_once_with()
    current.editor.set_edit_text.assert_not_called()


def test_sidebar_project_row_distinguishes_same_titles_in_other_projects():
    rows = [("A中的已安排任务", (1,), (101,)),
            ("B中的已安排任务", (2,), (102,)),
            ("", (3,), (103,)), ("", (3,), (104,))]
    assert chat_row(rows, "A") == (101,)
    assert chat_row(rows, "B") == (102,)
    assert chat_row(rows, "") is None


def test_ambiguous_same_titles_are_not_merged_by_name():
    rows = [("A中的已安排任务", (1,), (101,)), ("A中的已安排任务", (1,), (102,))]
    assert chat_row(rows, "A") is None
    assert chat_row([], "A") is None


def test_one_chat_listed_in_project_and_recents_has_consistent_row():
    rows = [("A中的已安排任务", (1,), (101,)), ("", (2,), (201,))]
    assert chat_row(rows, "A") == (101,)
    assert chat_row(rows, "") == (201,)
