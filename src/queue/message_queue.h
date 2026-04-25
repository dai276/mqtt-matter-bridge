#ifndef MESSAGE_QUEUE_H
#define MESSAGE_QUEUE_H

#include "ring_buffer.h"
#include <pthread.h>

// Return codes
#define QUEUE_OK        0
#define QUEUE_FULL     -1
#define QUEUE_EMPTY    -2
#define QUEUE_SHUTDOWN -3

// Cấu trúc message_queue — bọc ring_buffer với mutex và condition variable
typedef struct {
    ring_buffer_t   rb;       // Ring buffer bên trong
    pthread_mutex_t mutex;    // Bảo vệ truy cập đồng thời giữa các thread
    pthread_cond_t  cond;     // Wake up Matter thread khi có message mới
    int             shutdown; // Flag báo hiệu đang shutdown
} message_queue_t;

// Khởi tạo queue — gọi một lần khi bridge daemon start
int message_queue_init(message_queue_t *q);

// MQTT thread gọi khi nhận được message từ Mosquitto
// Không block — nếu queue đầy thì trả về QUEUE_FULL
int message_queue_push(message_queue_t *q, const bridge_message_t *msg);

// Matter thread gọi trong vòng lặp chính
// Block cho đến khi có message hoặc nhận được tín hiệu shutdown
int message_queue_pop_blocking(message_queue_t *q, bridge_message_t *msg);

// Gọi khi shutdown để wake up thread đang block tại pop_blocking
void message_queue_signal_shutdown(message_queue_t *q);

// Số message hiện có trong queue
int message_queue_size(message_queue_t *q);

// Dọn dẹp — gọi sau khi tất cả thread đã join xong
void message_queue_destroy(message_queue_t *q);

#endif // MESSAGE_QUEUE_H