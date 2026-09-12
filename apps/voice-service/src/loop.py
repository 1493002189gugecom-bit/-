"""Minimal wake-once continuous local voice loop for Phase A7/A8.

Behavior:
- Explicitly uses the physical Realtek microphone, not Windows' virtual default.
- Standby listens only for one of the configured wake words.
- After waking, VAD segments continuous utterances and SenseVoice transcribes.
- The active session returns to standby after 20 seconds without a completed
  utterance, or immediately when the user says "退出"/"结束对话".
- Microphone blocks are discarded while TTS is playing, preventing playback
  from triggering recognition.

This is a local validation loop, not the cloud Agent. It does not control any
home device and only speaks a fixed acknowledgement.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import queue
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import audio_utils
import config
import voice_models

BLOCK_SIZE = 512
IDLE_TIMEOUT_SECONDS = 20.0
MAX_UTTERANCE_SECONDS = 15.0
PRE_ROLL_BLOCKS = 10


def should_idle_timeout(state: str, in_speech: bool, now: float, deadline: float) -> bool:
    """Return whether an active, currently silent session has expired."""
    return state == "active" and not in_speech and now >= deadline


def deadline_after_reply(
    idle_timeout: float,
    play_reply: Callable[[], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> float:
    """Run optional playback, then start the full user waiting window."""
    if play_reply is not None:
        play_reply()
    return clock() + idle_timeout


def enqueue_if_enabled(q: queue.Queue, block: np.ndarray, enabled: bool) -> bool:
    """Queue one microphone block unless playback/processing suppresses input."""
    if not enabled:
        return False
    q.put_nowait(block)
    return True


def should_exit(transcript: str) -> bool:
    return "退出" in transcript or "结束对话" in transcript


def drain(q: queue.Queue) -> None:
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


def play(
    samples: np.ndarray,
    sample_rate: int,
    output_device: int,
    on_stream_started: Callable[[float], None] | None = None,
) -> None:
    with sd.OutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=output_device,
        blocksize=0,
    ) as stream:
        if on_stream_started is not None:
            on_stream_started(float(stream.latency))
        stream.write(np.asarray(samples, dtype=np.float32).reshape(-1, 1))


def wake_tone(sample_rate: int = 24000) -> np.ndarray:
    """Return a short, low-amplitude two-note wake acknowledgement."""
    part = int(0.08 * sample_rate)
    t = np.arange(part, dtype=np.float32) / sample_rate
    first = 0.12 * np.sin(2 * np.pi * 660 * t)
    second = 0.12 * np.sin(2 * np.pi * 880 * t)
    gap = np.zeros(int(0.03 * sample_rate), dtype=np.float32)
    return np.concatenate([first, gap, second]).astype(np.float32)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keywords-file", type=Path, default=Path("tools/voice-check/cases/wake-keywords.txt"))
    parser.add_argument("--input-contains", "--input-device", dest="input_contains", default=config.DEFAULT_INPUT_DEVICE)
    parser.add_argument("--output-contains", "--output-device", dest="output_contains", default=config.DEFAULT_OUTPUT_DEVICE)
    parser.add_argument("--idle-timeout", type=float, default=IDLE_TIMEOUT_SECONDS)
    parser.add_argument("--log-file", type=Path, default=Path("docs/superpowers/reports/artifacts/loop-session.log"))
    parser.add_argument("--speaker-id", type=int, default=47)
    parser.add_argument("--no-tts", action="store_true", help="print only; useful for diagnostics")
    parser.add_argument("--startup-check", action="store_true", help="validate devices/models, then exit without opening the microphone")
    parser.add_argument("--run-seconds", type=float, default=0.0, help="diagnostic: stop automatically after N seconds")
    args = parser.parse_args()

    input_device = audio_utils.select_input_device(args.input_contains, config.SAMPLE_RATE)
    output_device = None if args.no_tts else audio_utils.select_output_device(args.output_contains, 24000)
    print(f"input : #{input_device.index} {input_device.name} [{input_device.hostapi}]")
    if output_device:
        print(f"output: #{output_device.index} {output_device.name} [{output_device.hostapi}]")
    print(f"model root: {config.models_dir()}")
    print("loading KWS/VAD/ASR" + (" ..." if args.no_tts else "/TTS ..."))

    kws = voice_models.create_kws(args.keywords_file)
    vad = voice_models.create_vad()
    asr = voice_models.create_asr()
    tts = None if args.no_tts else voice_models.create_tts()
    if args.startup_check:
        print("startup check OK: devices and all requested models initialized")
        return 0

    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    log_handle = args.log_file.open("a", encoding="utf-8", buffering=1)

    def log_event(event: str, **fields) -> None:
        record = {
            "timestamp": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="milliseconds"),
            "event": event,
            **fields,
        }
        log_handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=128)
    accept_input = True
    overflow_count = 0

    def callback(indata, frames, time_info, status):  # noqa: ANN001
        nonlocal overflow_count
        if status:
            print(f"audio status: {status}", file=sys.stderr)
            log_event("audio_status", status=str(status))
        block = np.asarray(indata[:, 0], dtype=np.float32).copy()
        try:
            enqueue_if_enabled(audio_queue, block, accept_input)
        except queue.Full:
            overflow_count += 1

    state = "standby"
    kws_stream = kws.create_stream()
    active_deadline = 0.0
    pre_roll: collections.deque[np.ndarray] = collections.deque(maxlen=PRE_ROLL_BLOCKS)
    utterance: list[np.ndarray] = []
    in_speech = False

    print("ready: 请说“小屋小屋”或“你好小屋”（Ctrl+C 退出）")
    log_event(
        "ready",
        state=state,
        input_device=input_device.name,
        output_device=output_device.name if output_device else None,
        idle_timeout_seconds=args.idle_timeout,
    )
    run_deadline = time.monotonic() + args.run_seconds if args.run_seconds > 0 else None
    try:
        with sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            device=input_device.index,
            channels=1,
            dtype="float32",
            callback=callback,
        ):
            while True:
                now = time.monotonic()
                if run_deadline is not None and now >= run_deadline:
                    print("diagnostic run complete")
                    break
                # InputStream continuously queues blocks, even for silence, so
                # the idle deadline must be checked on every iteration rather
                # than only when queue.get() times out.
                if should_idle_timeout(state, in_speech, now, active_deadline):
                    print(f"[timeout] {args.idle_timeout:g} 秒无新语音，回到待唤醒")
                    log_event("idle_timeout", state="standby", idle_timeout_seconds=args.idle_timeout)
                    state = "standby"
                    kws_stream = kws.create_stream()
                    vad.reset()
                    pre_roll.clear()
                    utterance.clear()
                try:
                    block = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if state == "standby":
                    kws_stream.accept_waveform(config.SAMPLE_RATE, block)
                    while kws.is_ready(kws_stream):
                        kws.decode_stream(kws_stream)
                        keyword = kws.get_result(kws_stream)
                        if keyword:
                            print(f"[wake] {keyword}；进入连续对话")
                            log_event("wake", state="active", keyword=keyword)
                            kws.reset_stream(kws_stream)
                            accept_input = False
                            drain(audio_queue)
                            if output_device is not None:
                                play(wake_tone(), 24000, output_device.index)
                            drain(audio_queue)
                            accept_input = True
                            state = "active"
                            active_deadline = time.monotonic() + args.idle_timeout
                            vad.reset()
                            pre_roll.clear()
                            utterance.clear()
                            in_speech = False
                            break
                    continue

                speech = vad.is_speech(block)
                if not in_speech:
                    pre_roll.append(block)
                    if speech:
                        utterance = list(pre_roll)
                        pre_roll.clear()
                        in_speech = True
                elif speech:
                    utterance.append(block)
                    if len(utterance) * BLOCK_SIZE >= MAX_UTTERANCE_SECONDS * config.SAMPLE_RATE:
                        speech = False

                if in_speech and not speech:
                    samples = np.concatenate(utterance) if utterance else np.empty(0, dtype=np.float32)
                    utterance.clear()
                    pre_roll.clear()
                    in_speech = False
                    vad.reset()
                    if len(samples) < int(0.35 * config.SAMPLE_RATE):
                        continue

                    accept_input = False
                    drain(audio_queue)
                    transcript = ""
                    try:
                        t0 = time.perf_counter()
                        transcript = voice_models.transcribe(asr, samples, config.SAMPLE_RATE)
                        asr_seconds = time.perf_counter() - t0
                        print(f"[asr {asr_seconds:.2f}s] {transcript or '<empty>'}")
                        log_event("asr", state=state, transcript=transcript, seconds=round(asr_seconds, 3))
                        if should_exit(transcript):
                            print("[exit] 回到待唤醒")
                            log_event("exit_command", state="standby", transcript=transcript)
                            state = "standby"
                            kws_stream = kws.create_stream()
                        elif transcript:
                            def play_fixed_reply() -> None:
                                if tts is None:
                                    return
                                # Do not echo the transcript: it could contain a wake word.
                                tts_started = time.perf_counter()
                                reply, sr = voice_models.synthesize(tts, "收到。", args.speaker_id)
                                synth_seconds = time.perf_counter() - tts_started
                                print("[tts] 播放期间暂停识别")
                                log_event("tts_start", state=state, text="收到。", synth_seconds=round(synth_seconds, 3))

                                def record_first_output(portaudio_latency: float) -> None:
                                    submitted = time.perf_counter() - tts_started
                                    log_event(
                                        "tts_first_output_estimate",
                                        state=state,
                                        seconds=round(submitted + portaudio_latency, 3),
                                        synthesis_seconds=round(synth_seconds, 3),
                                        portaudio_latency_seconds=round(portaudio_latency, 3),
                                        estimated=True,
                                    )

                                play(reply, sr, output_device.index, record_first_output)
                                print("[tts] 播放结束，恢复识别")
                                log_event("tts_end", state=state, text="收到。")

                            # Processing and playback do not consume the user's
                            # waiting window. The full timeout starts now, after
                            # the fixed reply has completed.
                            active_deadline = deadline_after_reply(
                                args.idle_timeout,
                                play_fixed_reply if tts is not None else None,
                            )
                    except Exception as exc:
                        # A model/playback failure must not leave recognition
                        # permanently disabled. Start a fresh waiting window
                        # after the visible error feedback.
                        print(f"[voice error] {type(exc).__name__}: {exc}", file=sys.stderr)
                        log_event("voice_error", state=state, error_type=type(exc).__name__, message=str(exc))
                        if state == "active" and transcript:
                            active_deadline = deadline_after_reply(args.idle_timeout)
                    finally:
                        drain(audio_queue)
                        accept_input = True

    except KeyboardInterrupt:
        print("\nstopped")
        log_event("keyboard_interrupt", state=state)
    finally:
        print(f"audio queue overflows: {overflow_count}")
        log_event("stopped", state=state, audio_queue_overflows=overflow_count)
        log_handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
