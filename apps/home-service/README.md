# Home Service — Authoritative State and Restricted Tools (Phase B)

Plain-text driven service that owns the authoritative home state and exposes
exactly **six** restricted tools. It does not use a microphone, does not talk to
Unity, and does not decide anything by itself: the Agent (Phase D) will call it.

It binds to **127.0.0.1 only**. Requests to bind anywhere else are refused,
because this service is never exposed to the LAN.

## Run

```powershell
# Print the initial snapshot and exit
.\.venv\Scripts\python.exe apps/home-service/src/server.py --print-snapshot

# Serve the JSON API on loopback
.\.venv\Scripts\python.exe apps/home-service/src/server.py --port 8765
```

## The six tools

| Tool | Kind | Notes |
| --- | --- | --- |
| `query_room_status` | read | Rooms, simulated temperature, devices |
| `query_person_location` | read | Simulated position only; never derived from camera |
| `query_device_status` | read | Device state plus version |
| `set_light` | write | `on`, `brightness` 0–100 |
| `set_ac` | write | `on`, `mode`, `target_temp` within local limits |
| `broadcast_to_room` | write | Queues an announcement task |

Every write returns the wording the Agent is allowed to repeat, for example
`已打开客厅的灯，亮度 50`. The Agent must not invent stronger wording.

## Contracts enforced server-side

- **Stable ids only.** The caller passes natural-language targets (`客厅`, `爸爸`)
  which are resolved against authoritative state; unknown rooms/devices/people
  return `not_found` rather than creating anything.
- **Range and type checks.** Brightness outside 0–100, temperature outside
  16–30 °C (from `config/comfort.json`), unknown AC modes, and light/AC mix-ups
  are rejected before any state change.
- **Offline devices never change state.** An offline device returns
  `offline` and its state is untouched, so no misoperation is recorded.
- **Optimistic concurrency.** Passing a stale `precondition_version` returns
  `version_conflict`; the caller must re-query instead of overwriting.
- **Operation ids are idempotent.** The same `operation_id` replays the stored
  outcome instead of applying the change twice — including broadcasts, which are
  not queued twice.
- **No-ops stay no-ops.** Turning off a light that is already off reports that it
  was already off instead of rewriting state.

## Broadcast state machine

```
queued ──start──▶ playing ──receipt(ok)──▶ played
                     └────receipt(bad)/fail────▶ failed
```

- The queue is owned here; only the head task may start, so **playback is never
  parallel**.
- `start_broadcast` issues a `receipt_id`; `complete_broadcast` requires it to
  match. A missing or mismatched receipt is recorded as `failed`, and the task is
  **not** replayed automatically.
- Wording is derived from state, never guessed:

| State | Wording |
| --- | --- |
| `queued` | 已安排在卧室播报 |
| `playing` | 正在卧室播报 |
| `played` | 已在卧室播报 |
| `failed` | 卧室播报失败 |

Only `played` permits "已播报". `failed` never claims success.

## Multi-target notification

`plan_notification` implements design section 7 for requests like
"叫爸爸和孩子吃饭":

- Targets in the same room are merged into **one** task.
- Different rooms are queued in mention order and played serially.
- A target whose location is unknown is reported as **not notified** and the
  caller is expected to ask ("没有爸爸的位置，未通知，需要全屋播报吗"). There is
  deliberately **no automatic whole-house broadcast**.
- Phrases never claim the target heard or arrived.

## Files

| Path | Purpose |
| --- | --- |
| `src/models.py` | Rooms, people, devices, observations, conversations, operations |
| `src/state.py` | Authoritative state, versions, increments, device writes |
| `src/tools.py` | The six tools plus server-side validation |
| `src/notify.py` | Multi-target notification planning |
| `src/server.py` | Loopback JSON API |
| `config/rooms.json` | Three rooms, six devices, three people |
| `config/comfort.json` | Temperature limits and comfort default |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest apps/home-service/tests -q
```

Covers target resolution, room dedupe, range validation, version conflicts,
operation dedupe, offline devices, partial success, broadcast receipts, duplicate
requests over HTTP, and restart behaviour.
