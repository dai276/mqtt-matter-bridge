#define _POSIX_C_SOURCE 200809L

#include "mapper.h"
#include "logger.h"

#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <cjson/cJSON.h>

#define MODULE "mapper"

// Config được lưu static — mapper_init() gán vào đây
static bridge_config_t *g_config = NULL;

// Bảng ánh xạ tên cluster sang cluster ID số
typedef struct {
    const char *name;
    int         id;
} cluster_map_t;

static const cluster_map_t CLUSTER_MAP[] = {
    { "onoff",                       0x0006 },
    { "levelcontrol",                0x0008 },
    { "temperaturemeasurement",      0x0402 },
    { "relativehumiditymeasurement", 0x0405 },
    { "illuminancemeasurement",      0x0400 },
    { "occupancysensing",            0x0406 },
    { NULL, 0 }  // Phần tử kết thúc
};

// Chuyển tên cluster sang cluster ID
// Return: cluster ID, hoặc -1 nếu không tìm thấy
static int cluster_name_to_id(const char *name)
{
    for (int i = 0; CLUSTER_MAP[i].name != NULL; i++) {
        if (strcmp(CLUSTER_MAP[i].name, name) == 0)
            return CLUSTER_MAP[i].id;
    }
    LOG_WRN(MODULE, "Unknown cluster: %s", name);
    return -1;
}

// Kiểm tra topic có match với pattern không
// Hỗ trợ wildcard: + (một level), # (nhiều level)
static int topic_match(const char *pattern, const char *topic)
{
    // So sánh từng ký tự
    while (*pattern && *topic) {
        if (*pattern == '#') return 1; // # match tất cả phần còn lại

        if (*pattern == '+') {
            // + match đúng một level — bỏ qua đến '/' tiếp theo
            pattern++;
            while (*topic && *topic != '/') topic++;
            continue;
        }

        if (*pattern != *topic) return 0;
        pattern++;
        topic++;
    }

    // Cả hai cùng kết thúc là match
    return (*pattern == '\0' && *topic == '\0');
}

// Apply transform lên giá trị raw
// raw_str: chuỗi giá trị từ JSON (ví dụ "25.3" hoặc "true")
// transform: tên hàm transform
// out_int: kết quả dạng integer
// out_bool: kết quả dạng boolean
static void apply_transform(const char *raw_str,
                             const char *transform,
                             int        *out_int,
                             int        *out_bool)
{
    if (strcmp(transform, "multiply_100") == 0) {
        // float → int16 nhân 100 (nhiệt độ, độ ẩm)
        float val = strtof(raw_str, NULL);
        *out_int  = (int)(val * 100.0f);

    } else if (strcmp(transform, "invert") == 0) {
        // Đảo boolean
        int val  = atoi(raw_str);
        *out_bool = val ? 0 : 1;
        *out_int  = *out_bool;

    } else {
        // none — giữ nguyên giá trị
        // Thử parse boolean trước
        if (strcmp(raw_str, "true")  == 0 ||
            strcmp(raw_str, "1")     == 0) {
            *out_bool = 1;
            *out_int  = 1;
        } else if (strcmp(raw_str, "false") == 0 ||
                   strcmp(raw_str, "0")     == 0) {
            *out_bool = 0;
            *out_int  = 0;
        } else {
            // Số thực hoặc integer
            float val = strtof(raw_str, NULL);
            *out_int  = (int)val;
            *out_bool = (*out_int != 0) ? 1 : 0;
        }
    }
}

// Lấy giá trị string từ JSON theo field name
// Hỗ trợ nested field dùng dấu chấm: "data.temperature"
// Return: chuỗi giá trị, hoặc NULL nếu không tìm thấy
static const char *json_get_field(cJSON *root, const char *field)
{
    // Tách field theo dấu chấm
    char buf[64];
    strncpy(buf, field, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    cJSON *node = root;
    char  *token = strtok(buf, ".");

    while (token && node) {
        node  = cJSON_GetObjectItemCaseSensitive(node, token);
        token = strtok(NULL, ".");
    }

    if (!node) return NULL;

    // Trả về giá trị dạng string
    if (cJSON_IsString(node)) return node->valuestring;
    if (cJSON_IsNumber(node)) {
        // Dùng buffer static để trả về chuỗi số
        static char num_buf[32];
        snprintf(num_buf, sizeof(num_buf), "%g", node->valuedouble);
        return num_buf;
    }
    if (cJSON_IsBool(node))
        return cJSON_IsTrue(node) ? "true" : "false";

    return NULL;
}

// Xác định command name dựa vào cluster và giá trị
static void resolve_command(int cluster_id, int value_bool,
                             char *cmd_name, size_t cmd_size)
{
    if (cluster_id == 0x0006) {
        strncpy(cmd_name, value_bool ? "On" : "Off", cmd_size);
    } else {
        strncpy(cmd_name, "write", cmd_size);
    }
    cmd_name[cmd_size - 1] = '\0';
}
int mapper_init(bridge_config_t *config)
{
    if (!config) return -1;
    g_config = config;
    LOG_INF(MODULE, "Initialized with %d rule(s)", config->device_count);
    return 0;
}

int mapper_translate(const bridge_message_t *msg,
                     matter_command_t       *cmd)
{
    if (!msg || !cmd || !g_config) return -1;

    memset(cmd, 0, sizeof(matter_command_t));

    // Tìm rule phù hợp với topic
    const device_rule_t *rule = NULL;
    for (int i = 0; i < g_config->device_count; i++) {
        if (topic_match(g_config->devices[i].mqtt_topic, msg->topic)) {
            rule = &g_config->devices[i];
            break;
        }
    }

    if (!rule) {
        LOG_DBG(MODULE, "No rule for topic: %s", msg->topic);
        return -1;
    }

    // Parse JSON payload
    cJSON *root = cJSON_Parse(msg->payload);
    if (!root) {
        LOG_WRN(MODULE, "Failed to parse payload: %s", msg->payload);
        return -1;
    }

    // Lấy giá trị field cần thiết
    const char *raw = json_get_field(root, rule->mqtt_field);
    if (!raw) {
        LOG_WRN(MODULE, "Field '%s' not found in payload: %s",
                rule->mqtt_field, msg->payload);
        cJSON_Delete(root);
        return -1;
    }

    // Apply transform
    int value_int  = 0;
    int value_bool = 0;
    apply_transform(raw, rule->transform, &value_int, &value_bool);

    // Chuyển tên cluster sang ID
    int cluster_id = cluster_name_to_id(rule->matter_cluster);
    if (cluster_id < 0) {
        cJSON_Delete(root);
        return -1;
    }

    // Điền matter_command
    cmd->node_id     = rule->node_id;
    cmd->endpoint_id = rule->endpoint_id;
    cmd->cluster_id  = cluster_id;
    cmd->value_int   = value_int;
    cmd->value_bool  = value_bool;

    strncpy(cmd->attribute, rule->matter_attribute,
            sizeof(cmd->attribute) - 1);

    // OnOff cluster dùng command, các cluster khác write attribute
    if (cluster_id == 0x0006) {
        cmd->is_command = 1;
        resolve_command(cluster_id, value_bool,
                        cmd->command_name, sizeof(cmd->command_name));
    } else {
        cmd->is_command = 0;
    }

    LOG_INF(MODULE, "Mapped: %s → node=%d cluster=0x%04X val=%d cmd=%s",
            msg->topic, cmd->node_id, cmd->cluster_id,
            cmd->value_int, cmd->is_command ? cmd->command_name : "write_attr");

    cJSON_Delete(root);
    return 0;
}

void mapper_destroy(void)
{
    g_config = NULL;
    LOG_INF(MODULE, "Destroyed");
}