#include "config_parser.h"
#include "logger.h"

#include <stdio.h>
#include <assert.h>
#include <string.h>

/* ============================================================
 * Test 1 — Load file hợp lệ
 * ============================================================ */
static void test_valid_config(void)
{
    printf("\n=== Test 1: Valid config ===\n");

    bridge_config_t config;
    int ret = config_parser_load("config.json", &config);

    assert(ret == 0);
    assert(strcmp(config.mqtt_broker, "localhost") == 0);
    assert(config.mqtt_port == 1883);
    assert(strcmp(config.matter_server, "ws://localhost:5580/ws") == 0);
    assert(config.device_count == 3);

    /* Kiểm tra device 0 — đèn */
    assert(strcmp(config.devices[0].name, "Living Room Light") == 0);
    assert(config.devices[0].node_id == 1);
    assert(config.devices[0].endpoint_id == 1);
    assert(strcmp(config.devices[0].mqtt_topic, "home/living/light") == 0);
    assert(strcmp(config.devices[0].mqtt_field, "onoff") == 0);
    assert(strcmp(config.devices[0].matter_cluster, "onoff") == 0);
    assert(strcmp(config.devices[0].transform, "none") == 0);

    /* Kiểm tra device 1 — nhiệt độ */
    assert(strcmp(config.devices[1].name, "Temperature Sensor") == 0);
    assert(strcmp(config.devices[1].transform, "multiply_100") == 0);

    /* In ra để verify bằng mắt */
    config_parser_print(&config);

    config_parser_destroy(&config);
    assert(config.devices == NULL);
    assert(config.device_count == 0);

    printf("Test 1 PASSED\n");
}

/* ============================================================
 * Test 2 — File không tồn tại
 * ============================================================ */
static void test_file_not_found(void)
{
    printf("\n=== Test 2: File not found ===\n");

    bridge_config_t config;
    int ret = config_parser_load("nonexistent.json", &config);

    assert(ret == -1);
    printf("Test 2 PASSED\n");
}

/* ============================================================
 * Test 3 — JSON thiếu trường bắt buộc
 * ============================================================ */
static void test_missing_field(void)
{
    printf("\n=== Test 3: Missing required field ===\n");

    /* Tạo file JSON thiếu mqtt_broker */
    FILE *f = fopen("/tmp/invalid.json", "w");
    fprintf(f, "{\"mqtt_port\": 1883, \"matter_server\": \"ws://localhost:5580/ws\", \"devices\": [{\"node_id\":1,\"endpoint_id\":1,\"mqtt_topic\":\"t\",\"mqtt_field\":\"f\",\"matter_cluster\":\"c\",\"matter_attribute\":\"a\"}]}");
    fclose(f);

    bridge_config_t config;
    int ret = config_parser_load("/tmp/invalid.json", &config);

    assert(ret == -1);
    printf("Test 3 PASSED\n");
}

/* ============================================================
 * Test 4 — JSON không hợp lệ
 * ============================================================ */
static void test_invalid_json(void)
{
    printf("\n=== Test 4: Invalid JSON ===\n");

    FILE *f = fopen("/tmp/broken.json", "w");
    fprintf(f, "{invalid json content {{{{");
    fclose(f);

    bridge_config_t config;
    int ret = config_parser_load("/tmp/broken.json", &config);

    assert(ret == -1);
    printf("Test 4 PASSED\n");
}

/* ============================================================
 * Main
 * ============================================================ */
int main(void)
{
    /* Khởi tạo logger để thấy output */
    logger_config_t log_cfg = {
        .min_level     = LOG_DEBUG,
        .log_file      = "",
        .log_to_stdout = 1
    };
    logger_init(&log_cfg);

    test_valid_config();
    test_file_not_found();
    test_missing_field();
    test_invalid_json();

    printf("\n=== All config_parser tests PASSED ===\n");

    logger_destroy();
    return 0;
}