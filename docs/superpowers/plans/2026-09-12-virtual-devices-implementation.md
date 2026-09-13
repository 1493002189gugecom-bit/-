# Virtual Devices Implementation Plan

> Execution: inline, following executing-plans; user authorized automatic execution.

Goal: four MQTT virtual devices visible in Home Assistant, with confirmed control through home-service.

Architecture: retain the legacy memory backend for regression tests; add an explicit HA backend with a mapped entity catalog. The simulator owns emulated device state; HA reports observed state. Never infer physical actuation from an HTTP acknowledgement.

## Tasks

- [x] Inspect repository and runtime; existing unrelated dac Compose owns port 8123. Preserve its resources.
- [ ] Add `apps/device-simulator/src/simulator.py`: pure device transitions, Discovery, state persistence, MQTT transport and fault controls. Test invalid commands, failed/offline commands and brightness bounds.
- [ ] Add isolated `infra/home-assistant/compose.yaml`: HA, broker, simulator, named volumes, loopback Web port; credentials generated locally. Existing deployment reuse requires explicit selection.
- [ ] Add `apps/home-service/src/ha_gateway.py`: authenticated HTTP, mapped entities, validation, serialized idempotent writes and bounded confirmation. Tests use fake HTTP; never expose tokens.
- [ ] Select backend in `server.py`; retain legacy tests and disable unsupported spatial/test mutations in HA mode.
- [ ] Exercise real MQTT discovery, HA control, simulator failure and restart; document measured results and any unverified gates.

## Verification

Run `.venv/Scripts/python.exe -m pytest apps/home-service/tests apps/voice-service/tests apps/device-simulator/tests`.
Run Docker Compose config validation before starting containers. Inspect published ports, health, HA entities and confirmed state changes. Use distinct simulator IDs to avoid overwriting existing devices.

## Semantics clarified during implementation

Timeout after submission means unconfirmed, not proof of failure. Late device completion is possible. Device state is observed via HA; retained MQTT state alone is not command acknowledgement. Same operation ID with different arguments is rejected. MQTT commands are never retained. Persistence uses atomic replacement. Fault controls remain local/admin-only and are not Agent tools.
