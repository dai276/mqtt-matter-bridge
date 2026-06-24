#define _POSIX_C_SOURCE 200809L

#include "mapper.h"
#include "logger.h"

#include <stdio.h>
#include <assert.h>
#include <string.h>

// Helper tạo bridge_message nhanh
static bridge_message_t make_msg(const char *topic, const char *payload)
{
    bridge_message_t msg;
    strncpy(msg.topic,   topic,   sizeof(msg.topic)   - 1);
    strncpy(msg.payload, payload, sizeof(msg.payload) - 1);
    msg.topic[sizeof(msg.topic)   - 1] = '\0';
    msg.payload[sizeof(msg.payload) - 1] = '\0';
    msg.timestamp_ms = 1000;
    return msg;
}

// Test 1: Map topic đèn — onoff = true → command "on"
static void test_map_light_on(void)
{
    printf("\n=== Test 1: Map light ON ===\n");

    bridge_message_t msg = make_msg("home/living/light", "{\"onoff\":true}");
    matter_command_t cmd;

    assert(mapper_translate(&msg, &cmd) == 0);
    assert(cmd.node_id      == 8);
    assert(cmd.endpoint_id  == 1);
    assert(cmd.cluster_id   == 0x0006);
    assert(cmd.is_command   == 1);
    assert(strcmp(cmd.command_name, "On") == 0);

    printf("Test 1 PASSED\n");
}

// Test 2: Map topic đèn — onoff = false → command "off"
static void test_map_light_off(void)
{
    printf("\n=== Test 2: Map light OFF ===\n");

    bridge_message_t msg = make_msg("home/living/light", "{\"onoff\":false}");
    matter_command_t cmd;

    assert(mapper_translate(&msg, &cmd) == 0);
    assert(cmd.cluster_id == 0x0006);
    assert(cmd.is_command == 1);
    assert(strcmp(cmd.command_name, "Off") == 0);

    printf("Test 2 PASSED\n");
}

// Test 3: Sensor topics are not part of the single-light demo config.
static void test_temperature_topic_not_configured(void)

{
    printf("\n=== Test 3: Temperature topic not configured ===\n");

    bridge_message_t msg = make_msg("home/sensor/temp", "{\"temp\":25.3}");
    matter_command_t cmd;

    assert(mapper_translate(&msg, &cmd) == -1);

    printf("Test 3 PASSED\n");
}

// Test 4: Sensor topics are not part of the single-light demo config.
static void test_humidity_topic_not_configured(void)
{
    printf("\n=== Test 4: Humidity topic not configured ===\n");

    bridge_message_t msg = make_msg("home/sensor/humidity",
                                     "{\"humidity\":60.5}");
    matter_command_t cmd;

    assert(mapper_translate(&msg, &cmd) == -1);

    printf("Test 4 PASSED\n");
}

// Test 5: Topic không có rule → return -1
static void test_unknown_topic(void)
{
    printf("\n=== Test 5: Unknown topic ===\n");

    bridge_message_t msg = make_msg("unknown/topic", "{\"val\":1}");
    matter_command_t cmd;

    assert(mapper_translate(&msg, &cmd) == -1);

    printf("Test 5 PASSED\n");
}

// Test 6: JSON không hợp lệ → return -1
static void test_invalid_json(void)
{
    printf("\n=== Test 6: Invalid JSON ===\n");

    bridge_message_t msg = make_msg("home/living/light", "not_json");
    matter_command_t cmd;

    assert(mapper_translate(&msg, &cmd) == -1);

    printf("Test 6 PASSED\n");
}

// Test 7: Field không tồn tại trong JSON → return -1
static void test_missing_field(void)
{
    printf("\n=== Test 7: Missing field ===\n");

    // Topic đèn cần field "onoff" nhưng payload không có
    bridge_message_t msg = make_msg("home/living/light",
                                     "{\"brightness\":100}");
    matter_command_t cmd;

    assert(mapper_translate(&msg, &cmd) == -1);

    printf("Test 7 PASSED\n");
}

int main(void)
{
    logger_config_t cfg = {
        .min_level     = LOG_INFO,
        .log_file      = "",
        .log_to_stdout = 1
    };
    logger_init(&cfg);

    // Load config — mapper cần rules từ config.json
    bridge_config_t config;
    assert(config_parser_load("config.json", &config) == 0);
    assert(mapper_init(&config) == 0);

    test_map_light_on();
    test_map_light_off();
    test_temperature_topic_not_configured();
    test_humidity_topic_not_configured();
    test_unknown_topic();
    test_invalid_json();
    test_missing_field();

    mapper_destroy();
    config_parser_destroy(&config);

    printf("\n=== All mapper tests PASSED ===\n");

    logger_destroy();
    return 0;
}