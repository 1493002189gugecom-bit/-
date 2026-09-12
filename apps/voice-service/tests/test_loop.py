from __future__ import annotations

import queue

import numpy as np

import loop


def test_active_silent_session_times_out_at_deadline():
    assert loop.should_idle_timeout("active", False, now=20.0, deadline=20.0)


def test_continuous_silence_blocks_do_not_disable_timeout():
    # Regression: InputStream queues blocks continuously, so timeout cannot be
    # tied to queue.Empty.
    assert loop.should_idle_timeout("active", False, now=25.0, deadline=20.0)


def test_speech_in_progress_is_not_cut_off_by_idle_deadline():
    assert not loop.should_idle_timeout("active", True, now=25.0, deadline=20.0)


def test_standby_never_uses_active_deadline():
    assert not loop.should_idle_timeout("standby", False, now=25.0, deadline=20.0)


def test_waiting_window_starts_after_reply_playback():
    now = [100.0]

    def fake_play():
        now[0] += 6.25  # synthesis + playback time

    deadline = loop.deadline_after_reply(20.0, fake_play, lambda: now[0])
    assert deadline == 126.25
    assert deadline - now[0] == 20.0


def test_playback_suppression_drops_microphone_block():
    q = queue.Queue()
    accepted = loop.enqueue_if_enabled(q, np.ones(512, dtype=np.float32), enabled=False)
    assert not accepted
    assert q.empty()


def test_enabled_microphone_block_is_queued():
    q = queue.Queue()
    accepted = loop.enqueue_if_enabled(q, np.ones(512, dtype=np.float32), enabled=True)
    assert accepted
    assert q.qsize() == 1


def test_exit_phrases_reset_session():
    assert loop.should_exit("退出连续对话")
    assert loop.should_exit("请结束对话")
    assert not loop.should_exit("继续聊天")
