#define _POSIX_C_SOURCE 200809L

#include "config_parser.h"
#include "logger.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <cjson/cJSON.h>

#define MODULE "config_parser"

/*
Helper — đọc toàn bộ file vào buffer
Caller chịu trách nhiệm free() buffer sau khi dùng
*/
static char *read_file(const char *filepath)
{
    FILE *f = fopen(filepath, "r");
    if (!f) {
        LOG_ERR(MODULE, "Cannot open config file: %s", filepath);
        return NULL;
    }

    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    rewind(f);

    char *buf = malloc(size + 1);
    if (!buf) {
        LOG_ERR(MODULE, "malloc failed reading config file");
        fclose(f);
        return NULL;
    }

    fread(buf, 1, size, f);
    buf[size] = '\0';
    fclose(f);
    return buf;
}

//Helper — chuyển string sang log_level_t
static log_level_t parse_log_level(const char *str)
{
    if (!str)                          return LOG_INFO;
    if (strcmp(str, "DEBUG") == 0)     return LOG_DEBUG;
    if (strcmp(str, "INFO")  == 0)     return LOG_INFO;
    if (strcmp(str, "WARN")  == 0)     return LOG_WARN;
    if (strcmp(str, "ERROR") == 0)     return LOG_ERROR;
    LOG_WRN(MODULE, "Unknown log level '%s', defaulting to INFO", str);
    return LOG_INFO;
}

/*  Helper — validate và copy string từ cJSON object
 * Return: 0 nếu thành công, -1 nếu field không tồn tại*/
static int get_string(const cJSON *obj, const char *key,
                      char *dst, size_t dst_size, int required)
{
    cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsString(item) || !item->valuestring) {
        if (required)
            LOG_ERR(MODULE, "Missing required field: \"%s\"", key);
        return -1;
    }
    strncpy(dst, item->valuestring, dst_size - 1);
    dst[dst_size - 1] = '\0';
    return 0;
}

//Helper — validate và lấy integer từ cJSON object
static int get_int(const cJSON *obj, const char *key,
                   int *dst, int required)
{
    cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsNumber(item)) {
        if (required)
            LOG_ERR(MODULE, "Missing required field: \"%s\"", key);
        return -1;
    }
    *dst = item->valueint;
    return 0;
}

/* 
 * Parse một device object trong mảng "devices" */
static int parse_device(const cJSON *obj, device_rule_t *rule)
{
    memset(rule, 0, sizeof(*rule));
    if (get_string(obj, "name",             rule->name,             sizeof(rule->name),             0) != 0)
        strncpy(rule->name, "unnamed", sizeof(rule->name));

    if (get_string(obj, "type", rule->type, sizeof(rule->type), 0) != 0)
        rule->type[0] = '\0';

    if (get_int(obj, "node_id",     &rule->node_id,     1) != 0) return -1;
    if (get_int(obj, "endpoint_id", &rule->endpoint_id, 1) != 0) return -1;

    if (get_string(obj, "mqtt_topic",        rule->mqtt_topic,        sizeof(rule->mqtt_topic),        1) != 0) return -1;
    if (get_string(obj, "mqtt_command_topic", rule->mqtt_command_topic, sizeof(rule->mqtt_command_topic), 0) != 0)
        rule->mqtt_command_topic[0] = '\0';
    if (get_string(obj, "mqtt_field",        rule->mqtt_field,        sizeof(rule->mqtt_field),        1) != 0) return -1;
    if (get_string(obj, "matter_cluster",    rule->matter_cluster,    sizeof(rule->matter_cluster),    1) != 0) return -1;
    if (get_string(obj, "matter_attribute",  rule->matter_attribute,  sizeof(rule->matter_attribute),  1) != 0) return -1;

    /* transform là optional — default "none" */
    if (get_string(obj, "transform", rule->transform, sizeof(rule->transform), 0) != 0)
        strncpy(rule->transform, "none", sizeof(rule->transform));

    return 0;
}

//API 

int config_parser_load(const char *filepath, bridge_config_t *config)
{
    if (!filepath || !config) return -1;

    memset(config, 0, sizeof(bridge_config_t));

    // Đọc file vào buffer
    char *buf = read_file(filepath);
    if (!buf) return -1;

    // Parse JSON
    cJSON *root = cJSON_Parse(buf);
    free(buf);

    if (!root) {
        const char *err = cJSON_GetErrorPtr();
        LOG_ERR(MODULE, "JSON parse error near: %s", err ? err : "unknown");
        return -1;
    }

    // Đọc các trường bắt buộc 
    if (get_string(root, "mqtt_broker",   config->mqtt_broker,   sizeof(config->mqtt_broker),   1) != 0) goto fail;
    if (get_int   (root, "mqtt_port",    &config->mqtt_port,                                      1) != 0) goto fail;
    if (get_string(root, "matter_server", config->matter_server, sizeof(config->matter_server),   1) != 0) goto fail;

    // Đọc các trường optional 
    get_string(root, "log_file", config->log_file, sizeof(config->log_file), 0);

    cJSON *level_item = cJSON_GetObjectItemCaseSensitive(root, "log_level");
    config->log_level = parse_log_level(
        cJSON_IsString(level_item) ? level_item->valuestring : NULL
    );

    // Parse mảng devices 
    cJSON *devices = cJSON_GetObjectItemCaseSensitive(root, "devices");
    if (!cJSON_IsArray(devices)) {
        LOG_ERR(MODULE, "Missing or invalid \"devices\" array");
        goto fail;
    }

    config->device_count = cJSON_GetArraySize(devices);
    if (config->device_count <= 0) {
        LOG_ERR(MODULE, "\"devices\" array is empty");
        goto fail;
    }
    if (config->device_count > MAX_DEVICES) {
        LOG_WRN(MODULE, "Too many devices (%d), capping at %d",
                config->device_count, MAX_DEVICES);
        config->device_count = MAX_DEVICES;
    }

    config->devices = malloc(config->device_count * sizeof(device_rule_t));
    if (!config->devices) {
        LOG_ERR(MODULE, "malloc failed for devices array");
        goto fail;
    }

    int i = 0;
    cJSON *item;
    cJSON_ArrayForEach(item, devices) {
        if (i >= config->device_count) break;
        if (parse_device(item, &config->devices[i]) != 0) {
            LOG_ERR(MODULE, "Invalid device at index %d", i);
            free(config->devices);
            config->devices = NULL;
            goto fail;
        }
        i++;
    }

    cJSON_Delete(root);
    LOG_INF(MODULE, "Config loaded: %d device(s) from %s",
            config->device_count, filepath);
    return 0;

fail:
    cJSON_Delete(root);
    return -1;
}

void config_parser_destroy(bridge_config_t *config)
{
    if (!config) return;
    if (config->devices) {
        free(config->devices);
        config->devices = NULL;
    }
    config->device_count = 0;
}

void config_parser_print(const bridge_config_t *config)
{
    if (!config) return;

    LOG_DBG(MODULE, "=== Bridge Config ===");
    LOG_DBG(MODULE, "  mqtt_broker   : %s", config->mqtt_broker);
    LOG_DBG(MODULE, "  mqtt_port     : %d", config->mqtt_port);
    LOG_DBG(MODULE, "  matter_server : %s", config->matter_server);
    LOG_DBG(MODULE, "  log_file      : %s",
            config->log_file[0] ? config->log_file : "(none)");
    LOG_DBG(MODULE, "  device_count  : %d", config->device_count);

    for (int i = 0; i < config->device_count; i++) {
        const device_rule_t *r = &config->devices[i];
        LOG_DBG(MODULE, "  [%d] %s", i, r->name);
        LOG_DBG(MODULE, "      node_id=%d endpoint_id=%d",
                r->node_id, r->endpoint_id);
        LOG_DBG(MODULE, "      type: %s",
                r->type[0] ? r->type : "(none)");
        LOG_DBG(MODULE, "      mqtt: %s → field: %s",
                r->mqtt_topic, r->mqtt_field);
        LOG_DBG(MODULE, "      mqtt command: %s",
                r->mqtt_command_topic[0] ? r->mqtt_command_topic : "(none)");
        LOG_DBG(MODULE, "      matter: %s / %s  transform: %s",
                r->matter_cluster, r->matter_attribute, r->transform);
    }
    LOG_DBG(MODULE, "=== End Config ===");
}