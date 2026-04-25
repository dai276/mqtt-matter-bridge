#ifndef BRIDGE_H
#define BRIDGE_H

#include "config_parser.h"
#include "message_queue.h"
#include "mqtt_client.h"
#include "matter_client.h"
#include "mapper.h"
#include "logger.h"
#include <pthread.h>

// Metrics đo hiệu năng bridge
typedef struct {
    long received;         // Số message nhận từ MQTT
    long sent;             // Số message gửi thành công lên Matter
    long dropped;          // Số message bị drop do queue đầy
    long errors;           // Số lần gửi Matter thất bại
    long total_latency_ms; // Tổng latency để tính trung bình
} bridge_metrics_t;

// Cấu trúc trung tâm của bridge daemon — 4 threads
typedef struct {
    bridge_config_t  config;           // Config từ file
    message_queue_t  queue;            // Queue giữa MQTT và Matter
    mqtt_client_t    mqtt;             // MQTT client
    matter_client_t  matter;           // Matter client
    bridge_metrics_t metrics;          // Số liệu hiệu năng
    int              running;          // Flag điều khiển vòng lặp

    pthread_t        mqtt_thread;      // Thread 1 — MQTT listener
    pthread_t        matter_thread;    // Thread 2 — Matter WebSocket loop
    pthread_t        dispatch_thread;  // Thread 3 — pop queue + send command
    pthread_t        monitor_thread;   // Thread 4 — health check + metrics
} bridge_t;

// Khởi tạo toàn bộ bridge — đọc config, init tất cả module
// Return: 0 nếu thành công, -1 nếu lỗi
int bridge_init(bridge_t *bridge, const char *config_path);

// Spawn 4 thread và bắt đầu hoạt động
// Return: 0 nếu thành công, -1 nếu lỗi
int bridge_start(bridge_t *bridge);

// Báo hiệu dừng — gọi từ signal handler
void bridge_stop(bridge_t *bridge);

// Join tất cả thread và giải phóng tài nguyên
void bridge_destroy(bridge_t *bridge);

#endif // BRIDGE_H