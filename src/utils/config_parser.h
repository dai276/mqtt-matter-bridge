#ifndef CONFIG_PARSER_H
#define CONFIG_PARSER_H

#include "logger.h"

#define MAX_DEVICES         32
#define MAX_STR_SHORT       64
#define MAX_STR_MEDIUM      128
#define MAX_STR_LONG        256


//mapping rule
typedef struct {
    char name[MAX_STR_SHORT];             /* Tên thiết bị — để log      */
    char type[MAX_STR_SHORT];             /* Loại thiết bị — để log     */
    int  node_id;                         /* MATTER node ID              */
    int  endpoint_id;                     /* MATTER endpoint ID          */
    char mqtt_topic[MAX_STR_MEDIUM];      /* Topic subscribe từ MQTT     */
    char mqtt_command_topic[MAX_STR_MEDIUM]; /* Topic publish command MQTT */
    char mqtt_field[MAX_STR_SHORT];       /* Field lấy trong JSON payload*/
    char matter_cluster[MAX_STR_SHORT];   /* Tên MATTER cluster          */
    char matter_attribute[MAX_STR_SHORT]; /* Tên MATTER attribute        */
    char transform[MAX_STR_SHORT];        /* none / multiply_100 / invert*/
} device_rule_t;


//bridge_config

typedef struct {
    char           mqtt_broker[MAX_STR_MEDIUM];  /* Host Mosquitto broker  */
    int            mqtt_port;                    /* Port — thường 1883     */
    char           matter_server[MAX_STR_LONG];  /* WebSocket URL :5580    */
    char           log_file[MAX_STR_LONG];       /* Đường dẫn file log     */
    log_level_t    log_level;                    /* Min log level          */
    device_rule_t *devices;                      /* Mảng mapping rules     */
    int            device_count;                 /* Số lượng rules         */
} bridge_config_t;



/*
 * config_parser_load - Đọc và parse file config.json
 * @filepath: đường dẫn đến file config.json
 * @config:   con trỏ đến struct sẽ được điền dữ liệu
 * Return: 0 nếu thành công, -1 nếu lỗi
 */
int config_parser_load(const char *filepath, bridge_config_t *config);

/*
 * config_parser_destroy - Giải phóng bộ nhớ đã malloc
 * @config: con trỏ đến struct cần giải phóng
 */
void config_parser_destroy(bridge_config_t *config);

/**
 * config_parser_print - In toàn bộ config ra log (level DEBUG)
 * @config: con trỏ đến struct cần in
 */
void config_parser_print(const bridge_config_t *config);

#endif /* CONFIG_PARSER_H */