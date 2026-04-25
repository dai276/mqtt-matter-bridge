#ifndef MATTER_CLIENT_H
#define MATTER_CLIENT_H

#include "message_queue.h"
#include "config_parser.h"
#include "logger.h"
#include <libwebsockets.h>

// Trạng thái kết nối Matter Server
typedef enum {
    MATTER_DISCONNECTED = 0,
    MATTER_CONNECTING   = 1,
    MATTER_CONNECTED    = 2,
    MATTER_RECONNECTING = 3
} matter_state_t;

// Command gửi đến Matter Server
typedef struct {
    int  node_id;           // MATTER node ID
    int  endpoint_id;       // MATTER endpoint ID
    int  cluster_id;        // MATTER cluster ID (số hex)
    char command_name[64];  // Tên command: on, off, toggle
    char attribute[64];     // Tên attribute cần write
    int  value_int;         // Giá trị integer (nhiệt độ, độ ẩm)
    int  value_bool;        // Giá trị boolean (on/off)
    int  is_command;        // 1 = gửi command, 0 = write attribute
} matter_command_t;

// Cấu trúc quản lý Matter client
typedef struct {
    struct lws_context *ws_context; // libwebsockets context
    struct lws         *ws;         // WebSocket connection handle
    message_queue_t    *queue;      // Queue pop message từ MQTT
    bridge_config_t    *config;     // Config đọc từ file
    matter_state_t      state;      // Trạng thái kết nối
    int                 running;    // Flag vòng lặp chính
    int                 msg_id;     // Counter tạo message_id duy nhất

    // Buffer nhận response từ Matter Server
    char recv_buf[4096];
    int  recv_len;

    // Buffer gửi command — libwebsockets cần LWS_PRE bytes đệm trước payload
    char send_buf[LWS_PRE + 1024];
    int  send_pending; // 1 nếu có data chờ gửi
} matter_client_t;

// Khởi tạo matter client — gọi trước khi start thread
// Return: 0 nếu thành công, -1 nếu lỗi
int matter_client_init(matter_client_t *client,
                       bridge_config_t *config,
                       message_queue_t *queue);

// Vòng lặp chính — chạy trong Thread 2
// Pop message từ queue, dịch sang MATTER command, gửi đến Matter Server
void matter_client_run(matter_client_t *client);

// Gửi một command đến Matter Server
// Return: 0 nếu thành công, -1 nếu lỗi
int matter_client_send_command(matter_client_t      *client,
                                const matter_command_t *cmd);

// Báo hiệu dừng vòng lặp
void matter_client_stop(matter_client_t *client);

// Dọn dẹp tài nguyên
void matter_client_destroy(matter_client_t *client);

// Lấy trạng thái kết nối hiện tại
matter_state_t matter_client_state(const matter_client_t *client);

#endif // MATTER_CLIENT_H