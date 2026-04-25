#ifndef MQTT_CLIENT_H
#define MQTT_CLIENT_H

#include "message_queue.h"
#include "config_parser.h"
#include "logger.h"
#include <mosquitto.h>

// Trạng thái kết nối MQTT
typedef enum {
    MQTT_DISCONNECTED = 0,
    MQTT_CONNECTING   = 1,
    MQTT_CONNECTED    = 2,
    MQTT_RECONNECTING = 3
} mqtt_state_t;

// Cấu trúc quản lý MQTT client
typedef struct {
    struct mosquitto *mosq;    // Mosquitto client handle
    message_queue_t  *queue;   // Queue để push message vào
    bridge_config_t  *config;  // Config đọc từ file
    volatile int      state;   // Trạng thái kết nối hiện tại
    int               running; // Flag điều khiển vòng lặp chính
} mqtt_client_t;

// Khởi tạo mqtt client — gọi trước khi start thread
// Return: 0 nếu thành công, -1 nếu lỗi
int mqtt_client_init(mqtt_client_t   *client,
                     bridge_config_t *config,
                     message_queue_t *queue);

// Vòng lặp chính — chạy trong Thread 1 cho đến khi shutdown
// Tự động reconnect khi mất kết nối
void mqtt_client_run(mqtt_client_t *client);

// Báo hiệu dừng vòng lặp — gọi từ signal handler khi shutdown
void mqtt_client_stop(mqtt_client_t *client);

// Dọn dẹp tài nguyên — gọi sau khi thread đã join
void mqtt_client_destroy(mqtt_client_t *client);

// Lấy trạng thái kết nối hiện tại
mqtt_state_t mqtt_client_state(const mqtt_client_t *client);

#endif // MQTT_CLIENT_H