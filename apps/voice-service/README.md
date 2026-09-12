# Voice Service — Phase A Local Validation

CPU-only local voice stack using `sherpa-onnx`:

- Open-vocabulary KWS (wake word)
- Silero VAD
- SenseVoiceSmall int8 ASR
- Kokoro v1.1 int8 TTS

Models are stored outside the repository. On this machine the default root is
`D:\smart-home-models`; override it with `SMART_HOME_MODELS_DIR`.

## Environment

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r apps/voice-service/requirements.lock.txt
```

## Verify devices and models without opening the microphone

```powershell
.\.venv\Scripts\python.exe apps/voice-service/src/loop.py --startup-check
```

The selected input must contain `Realtek`; the Windows default NetEase virtual
input is intentionally not used.

## Choose the input device

Device names change when a headset is plugged in, so the input is an ordered
preference list rather than a hard-coded name. The default order is
`HyperX, Realtek`; the first candidate that opens as mono float32 at 16 kHz wins.
If none of them work, the tool fails loudly instead of silently recording silence
from a virtual device.

Inspect what is available and what will actually be used:

```powershell
.\.venv\Scripts\python.exe tools/voice-check/record_cases.py --list-devices
```

Override the preference list for the current shell (comma-separated substrings):

```powershell
$env:SMART_HOME_INPUT_DEVICE  = "HyperX"        # record through the headset mic
$env:SMART_HOME_OUTPUT_DEVICE = "HyperX"        # play the reply through the headset
```

Before recording a whole corpus, confirm the microphone actually picks up your
voice. This measures one second and aborts if it looks silent:

```powershell
.\.venv\Scripts\python.exe tools/voice-check/record_cases.py --check-level --phrases tools/voice-check/cases/mic-smoke.txt
```

For a per-device comparison with dBFS readings and playable WAV files:

```powershell
.\.venv\Scripts\python.exe tools/voice-check/diagnose_mic.py --seconds 6 --candidates HyperX
```

Endpoint state and Windows volume levels can be read (never modified) with:

```powershell
.\.venv\Scripts\python.exe tools/voice-check/inspect_endpoints.py HyperX Realtek
```

## Record the 30 ASR cases

```powershell
.\.venv\Scripts\python.exe tools/voice-check/record_cases.py `
  --cases tools/voice-check/cases/asr-30.tsv --seconds 4
```

Then evaluate them:

```powershell
.\.venv\Scripts\python.exe tools/voice-check/check_asr.py `
  --cases tools/voice-check/cases/asr-30.tsv `
  --out docs/superpowers/reports/artifacts/asr-results.json
```

The Phase A gate is at least 27/30 cases with all required key information.

## Generate the 20 TTS samples

```powershell
.\.venv\Scripts\python.exe tools/voice-check/check_tts.py `
  --cases tools/voice-check/cases/tts-20.tsv `
  --out-dir docs/superpowers/reports/artifacts/tts
```

The WAV files require human listening; generation success is not a listening
pass. Use the interactive scorer (it resumes from saved progress). The gate is
at least 18/20, while all 20 must receive a score:

```powershell
.\.venv\Scripts\python.exe tools/voice-check/listen_tts.py
```

## Record wake-word positives

Record the two bundled 20-line candidate sets:

```powershell
.\.venv\Scripts\python.exe tools/voice-check/record_cases.py `
  --phrases tools/voice-check/cases/wake-xiaowu-20.txt `
  --out-dir tools/voice-check/cases/audio/wake/xiaowu-xiaowu `
  --seconds 3

.\.venv\Scripts\python.exe tools/voice-check/record_cases.py `
  --phrases tools/voice-check/cases/wake-nihao-20.txt `
  --out-dir tools/voice-check/cases/audio/wake/nihao-xiaowu `
  --seconds 3
```

Capture the required negative corpus and speaker-to-microphone acoustic loop:

```powershell
# Records 30 minutes locally as six five-minute files.
.\.venv\Scripts\python.exe tools/voice-check/capture_negative.py

# Audibly plays the fixed reply “收到” and records it through Realtek.
.\.venv\Scripts\python.exe tools/voice-check/capture_self_trigger.py
```

Evaluate positives, actual negative duration, and captured playback:

```powershell
.\.venv\Scripts\python.exe tools/voice-check/check_wake.py `
  --positives 20 --min-positive-hits 18 `
  --negatives-dir tools/voice-check/cases/noise-30min `
  --self-trigger-out tools/voice-check/cases/self-trigger `
  --out docs/superpowers/reports/artifacts/wake-results.json
```

Each candidate requires at least 18/20 detections. Negative audio must total at
least 1800 seconds; its false-wake count is reported without a hard threshold.
Playback captures must be non-empty and have zero KWS detections and zero ASR
forbidden-command terms.

## Run the minimal wake-once continuous loop

```powershell
.\.venv\Scripts\python.exe apps/voice-service/src/loop.py
```

Say “小屋小屋” or “你好小屋”; a short two-note prompt confirms wake-up,
then speak commands continuously. The full 20-second waiting window starts only
after the reply finishes. Microphone blocks are discarded during processing and
playback. Events are appended as timestamped JSON lines to
`docs/superpowers/reports/artifacts/loop-session.log`. This Phase A loop does
not call a cloud LLM and cannot control devices.

## Automated checks

```powershell
.\.venv\Scripts\python.exe -m pytest apps/voice-service/tests -q
.\.venv\Scripts\python.exe -m compileall -q apps/voice-service/src tools/voice-check
```

Audio, model weights, logs and `.venv` are ignored by git.
