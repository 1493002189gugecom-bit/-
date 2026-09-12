"""Probe sherpa-onnx Python API surface used by the voice service."""
import sherpa_onnx as s


def fields(obj):
    return [f for f in dir(obj) if not f.startswith("_")]


print("version:", getattr(s, "__version__", "n/a"))
print("all Config classes:", [n for n in dir(s) if "Config" in n])
print()
print("VadModelConfig:", fields(s.VadModelConfig()))
print("SileroVadModelConfig:", fields(s.SileroVadModelConfig()))
print()
print("OfflineRecognizer methods:", [m for m in dir(s.OfflineRecognizer) if not m.startswith("_")])
print("OfflineTts methods:", [m for m in dir(s.OfflineTts) if not m.startswith("_")])
print("KeywordSpotter methods:", [m for m in dir(s.KeywordSpotter) if not m.startswith("_")])
print("VadModel methods:", [m for m in dir(s.VadModel) if not m.startswith("_")])
print()
for name in ("OfflineStream", "OfflineRecognizerResult"):
    cls = getattr(s, name, None)
    print(f"{name}:", [m for m in dir(cls) if not m.startswith("_")] if cls else "not exported")
