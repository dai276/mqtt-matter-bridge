#!/usr/bin/env python3
"""Patch CHIP examples/bridge-app/linux/main.cpp for one ESP32 OnOff light.

This intentionally patches an external connectedhomeip checkout in-place. The
shell wrapper creates a backup before invoking this script.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LIGHT_NAME = "ESP32 Living Room Light"
LOCATION = "Living Room"
MARKER = "MQTT_MATTER_BRIDGE_PHASE4B_SINGLE_LIGHT"
COMMAND_MARKER = "MQTT_MATTER_BRIDGE_PHASE4C_MQTT_COMMAND"


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Could not find expected source block for {label}")
    return text.replace(old, new, 1)


def replace_application_init_mock_setup(text: str, new_setup: str) -> str:
    """Replace the bridge-app demo device setup block robustly.

    connectedhomeip bridge-app/main.cpp changes frequently.  Older versions had
    a fixed mock-device setup block, while newer versions keep the same
    `// Setup Mock Devices` marker but add/remove lines in that block.  Patch
    from that marker to the first dynamic endpoint registration block instead
    of requiring an exact source string.
    """
    pattern = re.compile(
        r"    // Setup Mock Devices\n.*?(?=\n#if !CHIP_CONFIG_USE_ENDPOINT_UNIQUE_ID\n\s*AddDeviceEndpoint\(&Light1,)",
        re.DOTALL,
    )
    text, count = pattern.subn(new_setup, text, count=1)
    if count == 0:
        raise SystemExit(
            "Could not find ApplicationInit mock device setup region. "
            "Please share the main.cpp lines around ApplicationInit()."
        )
    return text


def add_mqtt_command_integration(text: str) -> str:
    if '#include "mqtt_light_adapter.h"' not in text:
        include_match = re.search(r'(#include\s+[<"].*?[>"].*?\n)(?!#include)', text, re.DOTALL)
        if not include_match:
            raise SystemExit("Could not find include block in main.cpp")
        text = text[:include_match.end()] + '#include "mqtt_light_adapter.h"\n' + text[include_match.end():]

    global_adapter = f'''
// {COMMAND_MARKER}: command-only MQTT backend for ESP32 Living Room Light.
static MqttLightAdapter gMqttLightAdapter("localhost", 1883, "home/living/light/set", "home/living/light");
static bool gEsp32LightState = false;
static bool gEsp32LightStateKnown = false;

[[maybe_unused]] static void PublishEsp32LightCommandFromMatter(bool onoff)
{{
    ChipLogProgress(DeviceLayer, "Matter command received: %s", onoff ? "ON" : "OFF");
    if (gMqttLightAdapter.PublishCommand(onoff)) {{
        gEsp32LightState = onoff;
        gEsp32LightStateKnown = true;
    }}
}}

[[maybe_unused]] static void PublishEsp32LightToggleFromMatter()
{{
    if (!gEsp32LightStateKnown) {{
        ChipLogError(DeviceLayer, "Matter Toggle ignored: no cached state yet");
        return;
    }}
    PublishEsp32LightCommandFromMatter(!gEsp32LightState);
}}
'''
    if "static MqttLightAdapter gMqttLightAdapter" not in text:
        namespace_match = re.search(r'using namespace .*?;\n', text)
        insert_at = namespace_match.end() if namespace_match else 0
        text = text[:insert_at] + global_adapter + text[insert_at:]

    # This call is injected into the Phase 4B startup log block below. If the
    # file was already patched for Phase 4B, patch the existing log line.
    if "gMqttLightAdapter.Start()" not in text:
        text = text.replace(
            'ChipLogProgress(DeviceLayer, "Matter Bridge App started");',
            'ChipLogProgress(DeviceLayer, "Matter Bridge App started");\n    gMqttLightAdapter.SetStateCallback([](bool onoff) {\n        CHIP_ERROR err = PlatformMgr().ScheduleWork([](intptr_t context) {\n            const bool state = (context != 0);\n            gEsp32LightState = state;\n            gEsp32LightStateKnown = true;\n            Light1.SetOnOff(state);\n            HandleDeviceOnOffStatusChanged(&Light1, DeviceOnOff::kChanged_OnOff);\n            ChipLogProgress(DeviceLayer, "Matter OnOff attribute updated: %s", state ? "ON" : "OFF");\n        }, onoff ? 1 : 0);\n        if (err != CHIP_NO_ERROR) {\n            ChipLogError(DeviceLayer, "Failed to schedule Matter OnOff attribute update");\n        }\n    });\n    if (!gMqttLightAdapter.Start()) {\n        ChipLogError(DeviceLayer, "Failed to start MQTT light adapter");\n    }',
            1,
        )

    # Hook common bridge-app external attribute write paths for the OnOff
    # attribute. The upstream bridge app maps Matter On/Off commands to writes
    # on the bridged OnOff attribute; when that value is written, publish MQTT.
    replacements = [
        (r'(\bLight1\.SetOnOff\(\s*true\s*\)\s*;)', r'\1\n    PublishEsp32LightCommandFromMatter(true);  // ' + COMMAND_MARKER),
        (r'(\bLight1\.SetOnOff\(\s*false\s*\)\s*;)', r'\1\n    PublishEsp32LightCommandFromMatter(false);  // ' + COMMAND_MARKER),
        (r'(\b(?:dev|device|onOffDevice)->SetOnOff\(\s*(?:true|1)\s*\)\s*;)', r'\1\n            PublishEsp32LightCommandFromMatter(true);  // ' + COMMAND_MARKER),
        (r'(\b(?:dev|device|onOffDevice)->SetOnOff\(\s*(?:false|0)\s*\)\s*;)', r'\1\n            PublishEsp32LightCommandFromMatter(false);  // ' + COMMAND_MARKER),
        (r'(\b(?:dev|device|onOffDevice)->SetOnOff\(\s*(\w+)\s*\)\s*;)', r'\1\n            PublishEsp32LightCommandFromMatter(\2);  // ' + COMMAND_MARKER),
    ]

    hooked = False
    for pattern, replacement in replacements:
        text, count = re.subn(pattern, replacement, text, count=1)
        hooked = hooked or count > 0

    toggle_patterns = [
        (r'(\bLight1\.SetOnOff\(\s*!\s*Light1\.IsOn\(\)\s*\)\s*;)', r'\1\n    PublishEsp32LightToggleFromMatter();  // ' + COMMAND_MARKER),
        (r'(\b(?:dev|device|onOffDevice)->SetOnOff\(\s*!\s*(?:dev|device|onOffDevice)->IsOn\(\)\s*\)\s*;)', r'\1\n            PublishEsp32LightToggleFromMatter();  // ' + COMMAND_MARKER),
    ]
    for pattern, replacement in toggle_patterns:
        text, count = re.subn(pattern, replacement, text, count=1)
        hooked = hooked or count > 0

    if not hooked:
        text += f'''

// {COMMAND_MARKER}: Manual hook needed.
// The local connectedhomeip bridge-app OnOff command/write handler did not
// match the known upstream patterns. Wire Matter On to
// PublishEsp32LightCommandFromMatter(true), Off to
// PublishEsp32LightCommandFromMatter(false), and Toggle to
// PublishEsp32LightToggleFromMatter().
'''
        print("WARNING: Could not auto-hook OnOff command handler; inserted manual hook note")

    return text


def remove_add_device_blocks(text: str, device_names: list[str]) -> str:
    for name in device_names:
        # Remove individual AddDeviceEndpoint calls for demo devices while
        # keeping the surrounding endpoint-unique-id #if/#else structure intact.
        # Calls can span multiple lines, so consume until the terminating `);`.
        pattern = re.compile(
            rf"\n\s*AddDeviceEndpoint\(&{re.escape(name)},.*?\);",
            re.DOTALL,
        )
        text = pattern.sub(
            f"\n    // {MARKER}: disabled demo endpoint registration for {name}.",
            text,
        )
    return text


def mark_unused_demo_definitions(text: str) -> str:
    """Silence -Werror=unused-variable for demo definitions we disable.

    The upstream bridge-app keeps DataVersion arrays and dynamic endpoint
    descriptors for all demo devices near the top of main.cpp.  Once the
    overlay removes demo endpoint registration, GCC correctly reports those
    definitions as unused and CHIP builds with -Werror.  Mark only the disabled
    demo definitions as maybe_unused; keep Light1 and bridgedLightEndpoint live.
    """
    data_version_names = [
        "gLight2DataVersions",
        "gActionLight1DataVersions",
        "gActionLight2DataVersions",
        "gActionLight3DataVersions",
        "gActionLight4DataVersions",
        "gTempSensor1DataVersions",
        "gTempSensor2DataVersions",
        "gComposedDeviceDataVersions",
        "gComposedTempSensor1DataVersions",
        "gComposedTempSensor2DataVersions",
    ]
    for name in data_version_names:
        text = re.sub(
            rf"(?m)^(?!\[\[maybe_unused\]\] )(DataVersion\s+{re.escape(name)}\b)",
            r"[[maybe_unused]] \1",
            text,
        )

    endpoint_names = [
        "bridgedTempSensorEndpoint",
        "bridgedComposedDeviceEndpoint",
    ]
    for name in endpoint_names:
        text = re.sub(
            rf"(?m)^(?!\[\[maybe_unused\]\] )(DECLARE_DYNAMIC_ENDPOINT\({re.escape(name)}\b)",
            r"[[maybe_unused]] \1",
            text,
        )

    return text


def patch_main_cpp(path: Path) -> None:
    text = path.read_text()
    already_single_light = MARKER in text
    already_command = COMMAND_MARKER in text
    if already_single_light and already_command:
        print(f"Overlay markers already present in {path}; leaving file unchanged")
        return

    if not already_command:
        text = add_mqtt_command_integration(text)

    if already_single_light:
        path.write_text(text)
        print(f"Patched {path} with MQTT command integration for {LIGHT_NAME}")
        return

    text = re.sub(
        r'DeviceOnOff\s+Light1\("[^"]+",\s*"[^"]+"\);',
        f'DeviceOnOff Light1("{LIGHT_NAME}", "{LOCATION}");',
        text,
        count=1,
    )

    old_setup_start = """    // Setup Mock Devices
    Light1.SetReachable(true);
    Light2.SetReachable(true);
    Light1.SetChangeCallback(&HandleDeviceOnOffStatusChanged);
    Light2.SetChangeCallback(&HandleDeviceOnOffStatusChanged);
    TempSensor1.SetReachable(true);
    TempSensor2.SetReachable(true);
    TempSensor1.SetChangeCallback(&HandleDeviceTempSensorStatusChanged);
    TempSensor2.SetChangeCallback(&HandleDeviceTempSensorStatusChanged);

    // Setup devices for action cluster tests
    ActionLight1.SetReachable(true);
    ActionLight2.SetReachable(true);
    ActionLight3.SetReachable(true);
    ActionLight4.SetReachable(true);
    ActionLight1.SetChangeCallback(&HandleDeviceOnOffStatusChanged);
    ActionLight2.SetChangeCallback(&HandleDeviceOnOffStatusChanged);
    ActionLight3.SetChangeCallback(&HandleDeviceOnOffStatusChanged);
    ActionLight4.SetChangeCallback(&HandleDeviceOnOffStatusChanged);

    gComposedDevice.SetReachable(true);
    ComposedTempSensor1.SetReachable(true);
    ComposedTempSensor2.SetReachable(true);
    ComposedPowerSource.SetReachable(true);
    ComposedPowerSource.SetBatChargeLevel(58);
    ComposedTempSensor1.SetChangeCallback(&HandleDeviceTempSensorStatusChanged);
    ComposedTempSensor2.SetChangeCallback(&HandleDeviceTempSensorStatusChanged);
    ComposedPowerSource.SetChangeCallback(&HandleDevicePowerSourceStatusChanged);
"""
    new_setup_start = f"""    // {MARKER}: expose exactly one bridged OnOff light backed by ESP32 MQTT.
    ChipLogProgress(DeviceLayer, \"Matter Bridge App started\");
    gMqttLightAdapter.SetStateCallback([](bool onoff) {{
        CHIP_ERROR err = PlatformMgr().ScheduleWork([](intptr_t context) {{
            const bool state = (context != 0);
            gEsp32LightState = state;
            gEsp32LightStateKnown = true;
            Light1.SetOnOff(state);
            HandleDeviceOnOffStatusChanged(&Light1, DeviceOnOff::kChanged_OnOff);
            ChipLogProgress(DeviceLayer, \"Matter OnOff attribute updated: %s\", state ? \"ON\" : \"OFF\");
        }}, onoff ? 1 : 0);
        if (err != CHIP_NO_ERROR) {{
            ChipLogError(DeviceLayer, \"Failed to schedule Matter OnOff attribute update\");
        }}
    }});
    if (!gMqttLightAdapter.Start()) {{
        ChipLogError(DeviceLayer, \"Failed to start MQTT light adapter\");
    }}
    ChipLogProgress(DeviceLayer, \"Bridged device: {LIGHT_NAME}\");
    ChipLogProgress(DeviceLayer, \"Device type: OnOff Light\");

    Light1.SetReachable(true);
    Light1.SetChangeCallback(&HandleDeviceOnOffStatusChanged);
"""
    # Keep old_setup_start above as documentation for the original upstream
    # block, but do not require an exact byte-for-byte match.
    text = replace_application_init_mock_setup(text, new_setup_start)

    text = remove_add_device_blocks(
        text,
        [
            "Light2",
            "TempSensor1",
            "TempSensor2",
            "ActionLight1",
            "ActionLight2",
            "ActionLight3",
            "ActionLight4",
            "gComposedDevice",
            "ComposedPowerSource",
            "ComposedTempSensor1",
            "ComposedTempSensor2",
        ],
    )
    text = mark_unused_demo_definitions(text)

    text = text.replace(
        "    gRooms.push_back(&room1);\n    gRooms.push_back(&room2);\n    gActions.push_back(&action1);\n    gActions.push_back(&action2);\n",
        f"    // {MARKER}: demo rooms/actions disabled for single-light bridge.\n",
    )

    path.write_text(text)
    print(f"Patched {path} for single bridged OnOff light with MQTT command publishing: {LIGHT_NAME}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} /path/to/examples/bridge-app/linux/main.cpp", file=sys.stderr)
        return 2
    patch_main_cpp(Path(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))