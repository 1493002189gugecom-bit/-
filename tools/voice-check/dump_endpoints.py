"""Dump raw capture endpoint registry values for debugging name filters."""
from __future__ import annotations

import sys
import winreg

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ROOT) as root:
        printed = 0
        for index in range(winreg.QueryInfoKey(root)[0]):
            if printed >= limit:
                break
            try:
                subkey = winreg.EnumKey(root, index)
            except OSError:
                continue
            printed += 1
            print(f"=== {subkey}")
            try:
                with winreg.OpenKey(root, subkey) as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        name, value, vtype = winreg.EnumValue(key, i)
                        print(f"   value   {name!r} = {value!r} (type={vtype})")
                    try:
                        with winreg.OpenKey(key, "Properties") as props:
                            count = winreg.QueryInfoKey(props)[1]
                            print(f"   properties count={count}")
                            for i in range(min(count, 8)):
                                name, value, vtype = winreg.EnumValue(props, i)
                                print(f"     prop {name!r} = {value!r}")
                    except FileNotFoundError:
                        print("   no Properties subkey")
            except OSError as exc:
                print(f"   open failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
