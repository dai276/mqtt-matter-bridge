#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L 

#include "message_queue.h"
#include "logger.h"

#include <stdio.h>
#include <assert.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>

// Helper — tạo message test nhanh
static bridge_message_t make_msg(const char *topic,
                                  const char *payload,
                                  long ts)
{
    bridge_message_t msg;
    strncpy(msg.topic,   topic,   sizeof(msg.topic)   - 1);
    strncpy(msg.payload, payload, sizeof(msg.payload) - 1);
    msg.topic[sizeof(msg.topic)   - 1] = '\0';
    msg.payload[sizeof(msg.payload) - 1] = '\0';
    msg.timestamp_ms = ts;
    return msg;
}

// Test 1: Push và pop đơn giản — 1 thread
static void test_push_pop(void)
{
    printf("\n Test 1: Push and pop \n");

    message_queue_t q;
    message_queue_init(&q);

    bridge_message_t in  = make_msg("home/sensor/temp", "{\"temp\":25.3}", 1000);
    bridge_message_t out;

    assert(message_queue_push(&q, &in) == QUEUE_OK);
    assert(message_queue_size(&q) == 1);

    assert(message_queue_pop_blocking(&q, &out) == QUEUE_OK);
    assert(message_queue_size(&q) == 0);
    assert(strcmp(out.topic, "home/sensor/temp") == 0);
    assert(out.timestamp_ms == 1000);

    message_queue_destroy(&q);
    printf("Test 1 PASSED\n");
}

// Test 2: Queue đầy — push thêm phải trả về QUEUE_FULL
static void test_queue_full(void)
{
    printf("\n Test 2: Queue full \n");

    message_queue_t q;
    message_queue_init(&q);

    bridge_message_t msg = make_msg("topic", "{}", 0);

    for (int i = 0; i < RB_CAPACITY; i++) {
        assert(message_queue_push(&q, &msg) == QUEUE_OK);
    }

    // Push thêm khi đầy phải trả về QUEUE_FULL
    assert(message_queue_push(&q, &msg) == QUEUE_FULL);

    message_queue_destroy(&q);
    printf("Test 2 PASSED\n");
}

// Argument cho test blocking
typedef struct {
    message_queue_t *q;
    bridge_message_t received;
    int              done;
} blocking_arg_t;

// Thread consumer — block chờ message
static void *consumer_thread(void *arg)
{
    blocking_arg_t *a = (blocking_arg_t *)arg;
    message_queue_pop_blocking(a->q, &a->received);
    a->done = 1;
    return NULL;
}

// Test 3: Blocking pop — consumer block, producer push sau 100ms
static void test_blocking_pop(void)
{
    printf("\n Test 3: Blocking pop \n");

    message_queue_t q;
    message_queue_init(&q);

    blocking_arg_t arg = { .q = &q, .done = 0 };

    // Start consumer thread — sẽ block ngay vì queue rỗng
    pthread_t tid;
    pthread_create(&tid, NULL, consumer_thread, &arg);

    // Chờ 100ms để chắc consumer đã block
    usleep(100000);
    assert(arg.done == 0); // Phải đang block

    // Push message — consumer phải thức dậy
    bridge_message_t msg = make_msg("home/light", "{\"onoff\":1}", 999);
    message_queue_push(&q, &msg);

    pthread_join(tid, NULL);

    assert(arg.done == 1);
    assert(strcmp(arg.received.topic, "home/light") == 0);
    assert(arg.received.timestamp_ms == 999);

    message_queue_destroy(&q);
    printf("Test 3 PASSED\n");
}

// Argument cho test shutdown
typedef struct {
    message_queue_t *q;
    int              ret;
} shutdown_arg_t;

// Thread block chờ rồi nhận shutdown signal
static void *shutdown_thread(void *arg)
{
    shutdown_arg_t   *a = (shutdown_arg_t *)arg;
    bridge_message_t  msg;
    a->ret = message_queue_pop_blocking(a->q, &msg);
    return NULL;
}

// Test 4: Shutdown — thread đang block phải thoát khi nhận signal
static void test_shutdown(void)
{
    printf("\n Test 4: Shutdown signal \n");

    message_queue_t q;
    message_queue_init(&q);

    shutdown_arg_t arg = { .q = &q, .ret = 0 };

    pthread_t tid;
    pthread_create(&tid, NULL, shutdown_thread, &arg);

    // Chờ thread block
    usleep(100000);

    // Gửi shutdown signal
    message_queue_signal_shutdown(&q);

    pthread_join(tid, NULL);

    // Thread phải thoát với QUEUE_SHUTDOWN
    assert(arg.ret == QUEUE_SHUTDOWN);

    message_queue_destroy(&q);
    printf("Test 4 PASSED\n");
}

// Argument cho test multi-thread
typedef struct {
    message_queue_t *q;
    int              count;
} mt_arg_t;

// Producer — push N message
static void *producer_thread(void *arg)
{
    mt_arg_t *a = (mt_arg_t *)arg;
    for (int i = 0; i < a->count; i++) {
        bridge_message_t msg = make_msg("topic", "{}", i);
        message_queue_push(a->q, &msg);
        usleep(1000); // 1ms giữa các lần push
    }
    return NULL;
}

// Consumer — pop N message
static void *consumer_mt_thread(void *arg)
{
    mt_arg_t        *a = (mt_arg_t *)arg;
    bridge_message_t msg;
    int              received = 0;

    while (received < a->count) {
        int ret = message_queue_pop_blocking(a->q, &msg);
        if (ret == QUEUE_SHUTDOWN) break;
        received++;
    }
    a->count = received;
    return NULL;
}

// Test 5: Multi-thread — producer push 50 message, consumer pop 50
static void test_multithread(void)
{
    printf("\n Test 5: Multi-thread producer/consumer \n");

    message_queue_t q;
    message_queue_init(&q);

    mt_arg_t prod_arg = { .q = &q, .count = 50 };
    mt_arg_t cons_arg = { .q = &q, .count = 50 };

    pthread_t prod, cons;
    pthread_create(&prod, NULL, producer_thread,    &prod_arg);
    pthread_create(&cons, NULL, consumer_mt_thread, &cons_arg);

    pthread_join(prod, NULL);

    // Producer xong thì shutdown để consumer thoát
    message_queue_signal_shutdown(&q);
    pthread_join(cons, NULL);

    assert(cons_arg.count == 50);

    message_queue_destroy(&q);
    printf("Test 5 PASSED\n");
}

int main(void)
{
    // Khởi tạo logger để thấy output
    logger_config_t cfg = {
        .min_level     = LOG_WARN, // Chỉ hiện WARN/ERROR để output gọn
        .log_file      = "",
        .log_to_stdout = 1
    };
    logger_init(&cfg);

    test_push_pop();
    test_queue_full();
    test_blocking_pop();
    test_shutdown();
    test_multithread();

    printf("\n All message_queue tests PASSED \n");

    logger_destroy();
    return 0;
}