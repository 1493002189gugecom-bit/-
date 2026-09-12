"""Inspect Windows capture endpoints: name, state, and volume levels.

Windows stores DeviceState and Level:0/1/2 directly on each MMDevices endpoint
key, while the friendly name lives in the Properties subkey. Diagnostic only;
this never changes system settings.

Run: python tools/voice-check/inspect_endpoints.py [name filter ...]
"""
from __future__ import annotations

import sys
import winreg

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CAPTURE_ROOT = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
PKEY_DEVICE_DESC = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
PKEY_DEVICE_NAME = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"

STATE_LABELS = {1: "ACTIVE", 2: "DISABLED", 4: "NOT_PRESENT", 8: "UNPLUGGED"}


def decode_state(raw: int) -> str:
    low = raw & 0xFF
    return f"{STATE_LABELS.get(low, f'UNKNOWN({low})')} (raw=0x{raw:08X})"


def read_endpoint(path: str) -> dict:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
        info = {"values": {}, "properties": {}}
        for i in range(winreg.QueryInfoKey(key)[1]):
            try:
                name, value, _ = winreg.EnumValue(key, i)
            except OSError:
                continue
            info["values"][name] = value
        try:
            with winreg.OpenKey(key, "Properties") as props:
                for i in range(winreg.QueryInfoKey(props)[1]):
                    try:
                        name, value, _ = winreg.EnumValue(props, i)
                    except OSError:
                        continue
                    info["properties"][name] = value
        except FileNotFoundError:
            pass
    return info


def main() -> int:
    filters = [f.casefold() for f in (sys.argv[1:] or ["HyperX", "Realtek"])]
    printed = 0
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CAPTURE_ROOT) as root:
        for index in range(winreg.QueryInfoKey(root)[0]):
            try:
                subkey = winreg.EnumKey(root, index)
            except OSError:
                continue
            try:
                info = read_endpoint(f"{CAPTURE_ROOT}\\{subkey}")
            except OSError:
                continue

            desc = str(info["properties"].get(PKEY_DEVICE_DESC) or "")
            name = str(info["properties"].get(PKEY_DEVICE_NAME) or "")
            label = f"{name} / {desc}" if desc and name else (name or desc or "(unnamed)")
            haystack = f"{name} {desc}".casefold()
            if not any(f in haystack for f in filters):
                continue

            printed += 1
            print(label)
            print(f"    id     : {subkey}")
            state = info["values"].get("DeviceState")
            if state is None:
                print("    state  : unknown")
            else:
                print(f"    state  : {decode_state(int(state))}")
            levels = {k: v for k, v in info["values"].items() if k.startswith("Level:")}
            if levels:
                for key_name in sorted(levels):
                    print(f"    {key_name:<7}: {levels[key_name]}")
            print()

    if not printed:
        print("no capture endpoints matched the filter")
        return 2
    print("说明：Level 是 Windows 保存的该端点音量；若耳机有物理静音键或输入音量为 0，")
    print("      上面的录音就会只有噪声底。请按 Windows 设置 > 系统 > 声音 > 输入 调整。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
