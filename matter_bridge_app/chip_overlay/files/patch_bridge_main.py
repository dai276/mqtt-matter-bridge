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
COMMAND_TOPIC = "home/living/light/set"
STATE_TOPIC = "home/living/light"
AVAILABILITY_TOPIC = "home/living/light/availability"
MARKER = "MQTT_MATTER_BRIDGE_PHASE4B_SINGLE_LIGHT"
COMMAND_MARKER = "MQTT_MATTER_BRIDGE_PHASE4C_MQTT_COMMAND"
AVAILABILITY_MARKER = "MQTT_MATTER_BRIDGE_PHASE4D_AVAILABILITY"


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
static MqttLightAdapter gMqttLightAdapter("localhost", 1883, "{COMMAND_TOPIC}", "{STATE_TOPIC}", "{AVAILABILITY_TOPIC}");
static bool gEsp32LightState = false;
static bool gEsp32LightStateKnown = false;
static bool gUpdatingEsp32LightFromMqtt = false;

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
            'ChipLogProgress(DeviceLayer, "Matter Bridge App started");\n    gMqttLightAdapter.SetStateCallback([](bool onoff) {\n        CHIP_ERROR err = PlatformMgr().ScheduleWork([](intptr_t context) {\n            const bool state = (context != 0);\n            gEsp32LightState = state;\n            gEsp32LightStateKnown = true;\n            gUpdatingEsp32LightFromMqtt = true;\n            Light1.SetOnOff(state);\n            HandleDeviceOnOffStatusChanged(&Light1, DeviceOnOff::kChanged_OnOff);\n            gUpdatingEsp32LightFromMqtt = false;\n            ChipLogProgress(DeviceLayer, "Matter OnOff attribute updated: %s", state ? "ON" : "OFF");\n        }, onoff ? 1 : 0);\n        if (err != CHIP_NO_ERROR) {\n            ChipLogError(DeviceLayer, "Failed to schedule Matter OnOff attribute update");\n        }\n    });\n    if (!gMqttLightAdapter.Start()) {\n        ChipLogError(DeviceLayer, "Failed to start MQTT light adapter");\n    }',
            1,
        )

    return refresh_availability_integration(text)


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


def remove_level_control_from_bridged_light_endpoint(text: str) -> str:
    """Make the exposed ESP32 light a pure OnOff light.

    Upstream bridge-app examples sometimes model bridged lights with both
    OnOff and LevelControl clusters.  That makes Home Assistant expose endpoint
    2 as a dimmable light, which is not correct for the ESP32 MVP because the
    MQTT contract only carries {"onoff":true/false}.  Remove LevelControl from
    only the bridgedLightClusters definition while preserving the OnOff cluster.
    """

    def remove_level_control_cluster(block: str) -> str:
        # Macro-style connectedhomeip definitions:
        #   DECLARE_DYNAMIC_CLUSTER(LevelControl::Id, ...)
        block = re.sub(
            r"(?m)^[ \t]*DECLARE_DYNAMIC_CLUSTER(?:_EX)?\([^;\n]*LevelControl::Id[^;\n]*\),?\n",
            "",
            block,
        )

        # Array-style definitions used by some SDK revisions:
        #   { .clusterId = LevelControl::Id, ... },
        block = re.sub(
            r"(?ms)\n[ \t]*\{[^{}]*LevelControl::Id[^{}]*\},?",
            "",
            block,
        )
        return block

    dynamic_pattern = re.compile(
        r"(DECLARE_DYNAMIC_CLUSTER_LIST_BEGIN\(\s*bridgedLightClusters\s*\).*?"
        r"DECLARE_DYNAMIC_CLUSTER_LIST_END(?:\(\s*\)|;))",
        re.DOTALL,
    )

    def patch_dynamic(match: re.Match[str]) -> str:
        return remove_level_control_cluster(match.group(1))

    text, dynamic_count = dynamic_pattern.subn(patch_dynamic, text, count=1)
    if dynamic_count:
        return text

    array_pattern = re.compile(
        r"(EmberAfCluster\s+bridgedLightClusters\s*\[\s*\]\s*=\s*\{.*?\n\};)",
        re.DOTALL,
    )

    def patch_array(match: re.Match[str]) -> str:
        return remove_level_control_cluster(match.group(1))

    text, array_count = array_pattern.subn(patch_array, text, count=1)
    if array_count == 0:
        print("WARNING: Could not find bridgedLightClusters to remove LevelControl")
    return text


def availability_callback_block() -> str:
    return f'''    // {AVAILABILITY_MARKER}: map MQTT LWT availability to Matter reachability.
    gMqttLightAdapter.SetAvailabilityCallback([](bool online) {{
        CHIP_ERROR err = PlatformMgr().ScheduleWork([](intptr_t context) {{
            const bool reachable = (context != 0);
            Light1.SetReachable(reachable);
            HandleDeviceOnOffStatusChanged(&Light1, DeviceOnOff::kChanged_Reachable);
            ChipLogProgress(DeviceLayer, "Matter reachable updated: %s", reachable ? "true" : "false");
        }}, online ? 1 : 0);
        if (err != CHIP_NO_ERROR) {{
            ChipLogError(DeviceLayer, "Failed to schedule Matter reachable update");
        }}
    }});
'''


def refresh_availability_integration(text: str) -> str:
    """Ensure existing overlays use the availability topic and callback."""
    text = re.sub(
        r'static MqttLightAdapter gMqttLightAdapter\("localhost",\s*1883,\s*"[^"]+",\s*"[^"]+"(?:,\s*"[^"]+")?\);',
        f'static MqttLightAdapter gMqttLightAdapter("localhost", 1883, "{COMMAND_TOPIC}", "{STATE_TOPIC}", "{AVAILABILITY_TOPIC}");',
        text,
        count=1,
    )

    if "SetAvailabilityCallback" in text:
        return text

    anchor = "    gMqttLightAdapter.SetStateCallback([](bool onoff) {"
    index = text.find(anchor)
    if index >= 0:
        return text[:index] + availability_callback_block() + text[index:]

    print("WARNING: Could not find MQTT state callback to add availability callback")
    return text


def add_light_change_mqtt_publish_hook(text: str) -> str:
    """Publish MQTT when the active bridged light changes from Matter.

    HA On/Off commands in current bridge-app versions are handled by CHIP's
    generated/default OnOff command path, which toggles the dynamic endpoint and
    then notifies the bridge app through HandleDeviceOnOffStatusChanged().  Hook
    that callback for Light1 instead of trying to patch individual command
    handlers.  MQTT-originated state updates set gUpdatingEsp32LightFromMqtt so
    state feedback does not publish a command back to MQTT.
    """
    hook = f'''if (dev == &Light1 && !gUpdatingEsp32LightFromMqtt)
        {{
            PublishEsp32LightCommandFromMatter(dev->IsOn());  // {COMMAND_MARKER}
        }}

        '''

    if "PublishEsp32LightCommandFromMatter(dev->IsOn())" in text:
        return text

    pattern = re.compile(
        r"(if\s*\(\s*itemChangedMask\s*&\s*DeviceOnOff::kChanged_OnOff\s*\)\s*\{\s*)",
        re.DOTALL,
    )
    text, count = pattern.subn(r"\1" + hook, text, count=1)
    if count == 0:
        print("WARNING: Could not auto-hook HandleDeviceOnOffStatusChanged for MQTT publish")
    return text


def add_post_attribute_change_mqtt_publish_hook(text: str) -> str:
    """Hook CHIP attribute reports for HA-originated OnOff commands.

    Some connectedhomeip bridge-app versions handle HA On/Off commands in the
    generated ZCL path.  That path updates the dynamic endpoint attribute and
    sends ReportData without calling HandleDeviceOnOffStatusChanged().  The
    global MatterPostAttributeChangeCallback is invoked for those attribute
    changes, so hook Endpoint 2 / OnOff / OnOff there and publish MQTT unless
    the change originated from the MQTT state subscriber.
    """
    marker = f"{COMMAND_MARKER}: post-attribute-change MQTT publish hook"
    hook_body = f'''    // {marker}
    if (attributePath.mEndpointId == 2 && attributePath.mClusterId == OnOff::Id &&
        attributePath.mAttributeId == OnOff::Attributes::OnOff::Id && !gUpdatingEsp32LightFromMqtt && value != nullptr &&
        size >= 1)
    {{
        const bool onoff = (*value != 0);
        gEsp32LightState = onoff;
        gEsp32LightStateKnown = true;
        PublishEsp32LightCommandFromMatter(onoff);
    }}

'''

    if marker in text:
        return text

    existing = re.search(
        r"(void\s+MatterPostAttributeChangeCallback\s*\([^)]*\)\s*\{\s*)",
        text,
        re.DOTALL,
    )
    if existing:
        insert_at = existing.end()
        return text[:insert_at] + hook_body + text[insert_at:]

    callback = f'''
void MatterPostAttributeChangeCallback(const chip::app::ConcreteAttributePath & attributePath, uint8_t type, uint16_t size,
                                       uint8_t * value)
{{
    (void) type;
{hook_body}}}
'''

    anchor = "int AddDeviceEndpoint("
    anchor_index = text.find(anchor)
    if anchor_index >= 0:
        return text[:anchor_index] + callback + "\n" + text[anchor_index:]

    print("WARNING: Could not find insertion point for MatterPostAttributeChangeCallback")
    return text


def patch_main_cpp(path: Path) -> None:
    text = path.read_text()
    already_single_light = MARKER in text
    already_command = COMMAND_MARKER in text
    if already_single_light and already_command:
        text = refresh_availability_integration(text)
        text = add_light_change_mqtt_publish_hook(text)
        text = add_post_attribute_change_mqtt_publish_hook(text)
        text = remove_level_control_from_bridged_light_endpoint(text)
        path.write_text(text)
        print(f"Overlay markers already present in {path}; refreshed OnOff-only MQTT hooks")
        return

    if not already_command:
        text = add_mqtt_command_integration(text)

    if already_single_light:
        text = refresh_availability_integration(text)
        text = add_light_change_mqtt_publish_hook(text)
        text = add_post_attribute_change_mqtt_publish_hook(text)
        text = remove_level_control_from_bridged_light_endpoint(text)
        path.write_text(text)
        print(f"Patched {path} with OnOff-only MQTT command integration for {LIGHT_NAME}")
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
            gUpdatingEsp32LightFromMqtt = true;
            Light1.SetOnOff(state);
            HandleDeviceOnOffStatusChanged(&Light1, DeviceOnOff::kChanged_OnOff);
            gUpdatingEsp32LightFromMqtt = false;
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
    text = refresh_availability_integration(text)
    text = add_light_change_mqtt_publish_hook(text)
    text = add_post_attribute_change_mqtt_publish_hook(text)
    text = remove_level_control_from_bridged_light_endpoint(text)

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