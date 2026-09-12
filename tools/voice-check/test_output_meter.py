"""Measure the actual output level of the default render endpoint while playing.

Opens the default multimedia render device through IMMDeviceEnumerator and reads
IAudioMeterInformation while a tone is played by PortAudio. This distinguishes
"the system produced no audio" from "audio played but was not heard".

Run: python tools/voice-check/test_output_meter.py
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import threading
import time
from ctypes import POINTER, byref, c_float, c_void_p
from pathlib import Path

import numpy as np
import sounddevice as sd

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import audio_utils  # noqa: E402
import config  # noqa: E402

CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
IID_IAudioMeterInformation = "{C02216F6-8C67-4B5B-9D00-D008E73E0064}"

eRender = 0
eMultimedia = 1


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, text: str):
        super().__init__()
        if text.startswith("{"):
            text = text[1:-1]
        parts = text.split("-")
        self.Data1 = int(parts[0], 16)
        self.Data2 = int(parts[1], 16)
        self.Data3 = int(parts[2], 16)
        rest = parts[3] + parts[4]
        self.Data4 = (ctypes.c_ubyte * 8)(*[int(rest[i : i + 2], 16) for i in range(0, 16, 2)])


def com_method(ptr: c_void_p, index: int, restype, *argtypes):
    vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    func = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtable[index])
    return func


def default_render_meter_peak() -> tuple[c_void_p, c_void_p]:
    """Activate IMMDeviceEnumerator and return (meter_ptr, device_ptr)."""
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)

    enumerator = c_void_p()
    clsid = GUID(CLSID_MMDeviceEnumerator)
    iid_enumerator = GUID(IID_IMMDeviceEnumerator)
    hr = ole32.CoCreateInstance(
        byref(clsid),
        None,
        1,  # CLSCTX_INPROC_SERVER
        byref(iid_enumerator),
        byref(enumerator),
    )
    if hr != 0:
        raise OSError(f"CoCreateInstance failed: 0x{hr & 0xFFFFFFFF:08X}")

    device = c_void_p()
    get_default = com_method(enumerator, 4, ctypes.c_long, ctypes.c_int, ctypes.c_int, POINTER(c_void_p))
    hr = get_default(enumerator, eRender, eMultimedia, byref(device))
    if hr != 0:
        raise OSError(f"GetDefaultAudioEndpoint failed: 0x{hr & 0xFFFFFFFF:08X}")

    activate = com_method(
        device, 3, ctypes.c_long, POINTER(GUID), ctypes.c_ulong, c_void_p, POINTER(c_void_p)
    )
    meter = c_void_p()
    iid_meter = GUID(IID_IAudioMeterInformation)
    hr = activate(device, byref(iid_meter), 1, None, byref(meter))
    if hr != 0:
        raise OSError(f"Activate(IAudioMeterInformation) failed: 0x{hr & 0xFFFFFFFF:08X}")
    return meter, device


PKEY_Device_FriendlyName = GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}")


def probe_store_string(store: c_void_p, key, index: int = 2) -> str:
    """Read a string property from an IPropertyStore."""
    get_value = com_method(store, 5, ctypes.c_long, POINTER(GUID), ctypes.c_ulong, ctypes.c_void_p)
    propvariant = (ctypes.c_ubyte * 32)()
    if get_value(store, byref(key), 0, byref(propvariant)) != 0:
        return ""
    vt = ctypes.cast(propvariant, POINTER(ctypes.c_ushort)).contents.value
    if vt != 31:  # VT_LPWSTR
        return ""
    ptr = ctypes.cast(ctypes.byref(propvariant, 8), POINTER(ctypes.c_void_p)).contents.value
    return ctypes.wstring_at(ptr) if ptr else ""


def describe_default_render() -> tuple[str, str, float]:
    """Return (device id, friendly name, meter peak) for the default render endpoint."""
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    enumerator = c_void_p()
    clsid = GUID(CLSID_MMDeviceEnumerator)
    iid = GUID(IID_IMMDeviceEnumerator)
    if ole32.CoCreateInstance(byref(clsid), None, 1, byref(iid), byref(enumerator)) != 0:
        raise OSError("CoCreateInstance failed")

    device = c_void_p()
    get_default = com_method(enumerator, 4, ctypes.c_long, ctypes.c_int, ctypes.c_int, POINTER(c_void_p))
    if get_default(enumerator, eRender, eMultimedia, byref(device)) != 0:
        raise OSError("GetDefaultAudioEndpoint failed")

    # IMMDevice::GetId is vtable index 5.
    get_id = com_method(device, 5, ctypes.c_long, POINTER(ctypes.c_wchar_p))
    device_id = ctypes.c_wchar_p()
    get_id(device, byref(device_id))

    # IMMDevice::OpenPropertyStore is vtable index 4.
    store = c_void_p()
    open_store = com_method(device, 4, ctypes.c_long, ctypes.c_ulong, POINTER(c_void_p))
    name = ""
    if open_store(device, 0, byref(store)) == 0:
        name = probe_store_string(store, PKEY_Device_FriendlyName)

    meter = c_void_p()
    activate = com_method(device, 3, ctypes.c_long, POINTER(GUID), ctypes.c_ulong, c_void_p, POINTER(c_void_p))
    iid_meter = GUID(IID_IAudioMeterInformation)
    peak = -1.0
    if activate(device, byref(iid_meter), 1, None, byref(meter)) == 0:
        get_peak = com_method(meter, 3, ctypes.c_long, POINTER(c_float))
        value = c_float(0.0)
        if get_peak(meter, byref(value)) == 0:
            peak = float(value.value)
    return device_id.value or "", name, peak


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--freq", type=float, default=440.0)
    parser.add_argument("--volume", type=float, default=0.5)
    args = parser.parse_args()

    chosen = audio_utils.select_output_device(None, 24000)
    print(f"Python 将播放到: #{chosen.index} {chosen.name} [{chosen.hostapi}]")

    try:
        device_id, name, idle_peak = describe_default_render()
        print(f"Windows 默认播放设备: {name}")
        print(f"    端点 ID: {device_id}")
        print(f"    空闲电平: {idle_peak:.4f}")
        match = config.DEFAULT_OUTPUT_DEVICE.casefold() in name.casefold()
        print(f"    与 Python 播放设备是否同类: {'是' if match else '否 —— 可能播到了另一台设备'}")
    except OSError as exc:
        print(f"无法读取默认端点信息: {exc}")
        name = ""

    try:
        meter, _device = default_render_meter_peak()
    except OSError as exc:
        print(f"无法读取系统电平表: {exc}")
        meter = None

    if meter is not None:
        get_peak = com_method(meter, 3, ctypes.c_long, POINTER(c_float))
        release = com_method(meter, 2, ctypes.c_ulong)

    t = np.arange(int(args.seconds * 24000), dtype=np.float32) / 24000
    tone = (args.volume * np.sin(2 * np.pi * args.freq * t)).astype(np.float32)

    peaks: list[float] = []
    stop = threading.Event()

    def monitor() -> None:
        while not stop.is_set():
            if meter is not None:
                value = c_float(0.0)
                if get_peak(meter, byref(value)) == 0:
                    peaks.append(float(value.value))
            time.sleep(0.02)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()

    print("播放大音量测试音 3 秒……")
    with sd.OutputStream(samplerate=24000, channels=1, dtype="float32", device=chosen.index) as stream:
        stream.write(tone.reshape(-1, 1))
        time.sleep(0.4)
    stop.set()
    thread.join(timeout=1.0)

    if meter is not None:
        release(meter)

    if peaks:
        print(f"系统默认输出端点电平: 最大={max(peaks):.4f} 平均={sum(peaks)/len(peaks):.4f} 采样数={len(peaks)}")
        if max(peaks) > 0.01:
            print("=> 系统确实在输出音频。没听到就是耳机音量/线路/佩戴问题。")
        else:
            print("=> 系统电平表几乎为 0：声音没有真正送到默认输出端点。")
    else:
        print("未能采样到电平表数据。")

    print()
    print("说明：上面的电平表读的是 Windows 默认播放设备。")
    print(f"如果它与 Python 播放的设备不是同一个，会出现“有电平但听不到”或反之的错位。")
    print("请确认 设置 > 系统 > 声音 > 输出 选中的是你正在戴的耳机。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
