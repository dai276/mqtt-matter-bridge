#!/usr/bin/env python3
"""Patch CHIP examples/bridge-app/linux/BUILD.gn for MQTT adapter files.

Adds mqtt_light_adapter.cpp/h to the bridge app sources and links libmosquitto.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "MQTT_MATTER_BRIDGE_PHASE4C_MQTT_COMMAND"


def insert_source(text: str, source: str) -> str:
    if source in text:
        return text
    match = re.search(r"sources\s*=\s*\[", text)
    if not match:
        raise SystemExit("Could not find sources = [ in BUILD.gn")
    insert_at = match.end()
    return text[:insert_at] + f'\n    "{source}",  # {MARKER}' + text[insert_at:]


def add_mosquitto_lib(text: str) -> str:
    if '"mosquitto"' in text or '"-lmosquitto"' in text:
        return text

    # Prefer appending to an existing libs list in the bridge app target.
    libs_match = re.search(r"libs\s*=\s*\[(?P<body>.*?)\]", text, re.DOTALL)
    if libs_match:
        end = libs_match.end("body")
        prefix = "" if libs_match.group("body").strip().endswith(",") or not libs_match.group("body").strip() else ","
        return text[:end] + f'{prefix}\n    "mosquitto",  # {MARKER}' + text[end:]

    # Otherwise insert a libs declaration after the sources block. GN accepts
    # libs in executable targets and links it as -lmosquitto.
    sources_match = re.search(r"sources\s*=\s*\[(?P<body>.*?)\]\n", text, re.DOTALL)
    if not sources_match:
        raise SystemExit("Could not find end of sources block in BUILD.gn")
    insert_at = sources_match.end()
    return text[:insert_at] + f'\n  libs = [ "mosquitto" ]  # {MARKER}\n' + text[insert_at:]


def patch_build_gn(path: Path) -> None:
    text = path.read_text()
    if MARKER in text and "mqtt_light_adapter.cpp" in text and "mosquitto" in text:
        print(f"BUILD.gn overlay marker already present in {path}; leaving file unchanged")
        return

    text = insert_source(text, "mqtt_light_adapter.cpp")
    text = insert_source(text, "mqtt_light_adapter.h")
    text = add_mosquitto_lib(text)
    path.write_text(text)
    print(f"Patched {path}: added MQTT adapter sources and libmosquitto")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} /path/to/examples/bridge-app/linux/BUILD.gn", file=sys.stderr)
        return 2
    patch_build_gn(Path(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))