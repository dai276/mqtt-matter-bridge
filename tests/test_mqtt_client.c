#define _POSIX_C_SOURCE 200809L

#include "mqtt_client.h"
#include "message_queue.h"
#include "config_parser.h"
#include "logger.h"

#include <stdio.h>
#include <assert.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>

// Thread chạy mqtt_client_run()
static void *mqtt_run_thread(void *arg)
{
    mqtt_client_run((mqtt_client_t *)arg);
    return NULL;
}

// Test 1: Khởi tạo client
static void test_init(void)
{
    printf("\n=== Test 1: Init ===\n");

    bridge_config_t config;
    message_queue_t queue;
    mqtt_client_t   client;

    assert(config_parser_load("config.json", &config) == 0);
    assert(message_queue_init(&queue) == QUEUE_OK);
    assert(mqtt_client_init(&client, &config, &queue) == 0);
    assert(mqtt_client_state(&client) == MQTT_DISCONNECTED);

    mqtt_client_destroy(&client);
    message_queue_destroy(&queue);
    config_parser_destroy(&config);

    printf("Test 1 PASSED\n");
}

// Test 2: Kết nối đến Mosquitto broker
// Yêu cầu Mosquitto đang chạy tại localhost:1883
static void test_connect(void)
{
    printf("\n=== Test 2: Connect to broker ===\n");

    bridge_config_t config;
    message_queue_t queue;
    mqtt_client_t   client;

    config_parser_load("config.json", &config);
    message_queue_init(&queue);
    mqtt_client_init(&client, &config, &queue);

    pthread_t tid;
    pthread_create(&tid, NULL, mqtt_run_thread, &client);

    // Chờ kết nối thành công tối đa 3 giây
    int timeout = 30;
    while (mqtt_client_state(&client) != MQTT_CONNECTED && timeout-- > 0)
        usleep(100000);

    assert(mqtt_client_state(&client) == MQTT_CONNECTED);
    printf("Connected successfully\n");

    mqtt_client_stop(&client);
    pthread_join(tid, NULL);
    mqtt_client_destroy(&client);
    message_queue_destroy(&queue);
    config_parser_destroy(&config);

    printf("Test 2 PASSED\n");
}

// Test 3: Nhận message từ mosquitto_pub và kiểm tra vào queue
// Yêu cầu Mosquitto đang chạy
static void test_receive_message(void)
{
    printf("\n=== Test 3: Receive message into queue ===\n");

    bridge_config_t config;
    message_queue_t queue;
    mqtt_client_t   client;

    config_parser_load("config.json", &config);
    message_queue_init(&queue);
    mqtt_client_init(&client, &config, &queue);

    pthread_t tid;
    pthread_create(&tid, NULL, mqtt_run_thread, &client);

    // Chờ kết nối
    int timeout = 30;
    while (mqtt_client_state(&client) != MQTT_CONNECTED && timeout-- > 0)
        usleep(100000);

    assert(mqtt_client_state(&client) == MQTT_CONNECTED);

    // Gửi message test qua mosquitto_pub
    system("mosquitto_pub -t 'home/sensor/temp' "
           "-m '{\"temp\":25.3,\"humidity\":60}' -q 1");

    // Chờ message vào queue tối đa 2 giây
    timeout = 20;
    while (message_queue_size(&queue) == 0 && timeout-- > 0)
        usleep(100000);

    assert(message_queue_size(&queue) > 0);

    // Pop và verify nội dung message
    bridge_message_t msg;
    assert(message_queue_pop_blocking(&queue, &msg) == QUEUE_OK);
    assert(strcmp(msg.topic, "home/sensor/temp") == 0);
    assert(strstr(msg.payload, "25.3") != NULL);
    assert(msg.timestamp_ms > 0);

    printf("Received: topic=%s payload=%s\n", msg.topic, msg.payload);

    mqtt_client_stop(&client);
    message_queue_signal_shutdown(&queue);
    pthread_join(tid, NULL);
    mqtt_client_destroy(&client);
    message_queue_destroy(&queue);
    config_parser_destroy(&config);

    printf("Test 3 PASSED\n");
}

int main(void)
{
    logger_config_t cfg = {
        .min_level     = LOG_INFO,
        .log_file      = "",
        .log_to_stdout = 1
    };
    logger_init(&cfg);

    test_init();
    test_connect();
    test_receive_message();

    printf("\n=== All mqtt_client tests PASSED ===\n");

    logger_destroy();
    return 0;
}