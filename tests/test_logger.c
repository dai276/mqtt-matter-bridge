#include "logger.h"

#include <stdio.h>
#include <pthread.h>
#include <unistd.h>


//Test 1 — Các level cơ bản

static void test_basic_levels(void)
{
    printf("\n=== Test 1: Basic levels ===\n");

    LOG_DBG("test", "Debug message — chi tiet nhat");
    LOG_INF("test", "Info message  — hoat dong binh thuong");
    LOG_WRN("test", "Warn message  — can chu y");
    LOG_ERR("test", "Error message — loi nghiem trong");
}


//Test 2 — Format string với nhiều kiểu tham số
static void test_format(void)
{
    printf("\n=== Test 2: Format string ===\n");

    int port = 1883;
    float temp = 25.3f;
    const char *host = "localhost";

    LOG_INF("mqtt_client", "Connecting to %s:%d", host, port);
    LOG_DBG("mapper",      "Temperature raw value: %.2f", temp);
    LOG_DBG("mapper",      "After multiply_100: %d", (int)(temp * 100));
    LOG_ERR("matter",      "Cluster 0x%04X not found", 0x0402);
}


// Test 3 — Filter theo min_level

static void test_level_filter(void)
{
    printf("\n=== Test 3: Level filter ===\n");

    printf("-- Set min_level = WARN, DEBUG va INFO se bi loc --\n");
    logger_set_level(LOG_WARN);

    LOG_DBG("test", "KHONG HIEN — duoi min_level");
    LOG_INF("test", "KHONG HIEN — duoi min_level");
    LOG_WRN("test", "HIEN — bang min_level");
    LOG_ERR("test", "HIEN — tren min_level");

    printf("-- Restore min_level = DEBUG --\n");
    logger_set_level(LOG_DEBUG);
    LOG_DBG("test", "HIEN LAI sau khi restore");
}

 // Test 4 — Multi-thread: 2 thread ghi log cùng lúc

static void *thread_log_spam(void *arg)
{
    const char *name = (const char *)arg;
    for (int i = 0; i < 5; i++) {
        LOG_INF(name, "Thread message #%d", i);
        usleep(1000); /* 1ms */
    }
    return NULL;
}

static void test_multithread(void)
{
    printf("\n=== Test 4: Multi-thread ===\n");
    printf("-- 2 thread ghi log dong thoi, kiem tra khong bi lan lon --\n");

    pthread_t t1, t2;
    pthread_create(&t1, NULL, thread_log_spam, "thread_1");
    pthread_create(&t2, NULL, thread_log_spam, "thread_2");
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);

    printf("-- Kiem tra output: --\n");
}


int main(void)
{
    // Khoi tao logger
    logger_config_t cfg = {
        .min_level     = LOG_DEBUG,
        .log_file      = "/tmp/bridge_test.log",
        .log_to_stdout = 1
    };

    if (logger_init(&cfg) != 0) {
        fprintf(stderr, "Failed to init logger\n");
        return 1;
    }

    LOG_INF("main", "Logger initialized — bat dau test");

    test_basic_levels();
    test_format();
    test_level_filter();
    test_multithread();

    LOG_INF("main", "Tat ca test hoan thanh");
    LOG_INF("main", "Kiem tra file log tai: /tmp/bridge_test.log");

    logger_destroy();
    return 0;
}