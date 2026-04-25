#define _POSIX_C_SOURCE 200809L

#include "matter_client.h"
#include "logger.h"

#include <stdio.h>
#include <assert.h>
#include <unistd.h>
#include <pthread.h>

// Thread chạy matter_client_run()
static void *matter_run_thread(void *arg)
{
    matter_client_run((matter_client_t *)arg);
    return NULL;
}

// Test 1: Khởi tạo client
static void test_init(void)
{
    printf("\n=== Test 1: Init ===\n");

    bridge_config_t config;
    message_queue_t queue;
    matter_client_t client;

    config_parser_load("config.json", &config);
    message_queue_init(&queue);

    assert(matter_client_init(&client, &config, &queue) == 0);
    assert(matter_client_state(&client) == MATTER_DISCONNECTED);

    matter_client_destroy(&client);
    message_queue_destroy(&queue);
    config_parser_destroy(&config);

    printf("Test 1 PASSED\n");
}

// Test 2: Kết nối đến Matter Server
// Yêu cầu Matter Server đang chạy tại localhost:5580
static void test_connect(void)
{
    printf("\n=== Test 2: Connect to Matter Server ===\n");

    bridge_config_t config;
    message_queue_t queue;
    matter_client_t client;

    config_parser_load("config.json", &config);
    message_queue_init(&queue);
    matter_client_init(&client, &config, &queue);

    pthread_t tid;
    pthread_create(&tid, NULL, matter_run_thread, &client);

    // Chờ kết nối thành công tối đa 5 giây
    int timeout = 50;
    while (matter_client_state(&client) != MATTER_CONNECTED && timeout-- > 0)
        usleep(100000);

    assert(matter_client_state(&client) == MATTER_CONNECTED);
    printf("Connected to Matter Server\n");

    matter_client_stop(&client);
    message_queue_signal_shutdown(&queue);
    pthread_join(tid, NULL);
    matter_client_destroy(&client);
    message_queue_destroy(&queue);
    config_parser_destroy(&config);

    printf("Test 2 PASSED\n");
}

// Test 3: Gửi lệnh bật và tắt đèn đến Matter Server
// Yêu cầu Matter Server + chip-lighting-app đang chạy
static void test_send_command(void)
{
    printf("\n=== Test 3: Send on/off command ===\n");

    bridge_config_t config;
    message_queue_t queue;
    matter_client_t client;

    config_parser_load("config.json", &config);
    message_queue_init(&queue);
    matter_client_init(&client, &config, &queue);

    pthread_t tid;
    pthread_create(&tid, NULL, matter_run_thread, &client);

    // Chờ kết nối
    int timeout = 50;
    while (matter_client_state(&client) != MATTER_CONNECTED && timeout-- > 0)
        usleep(100000);

    assert(matter_client_state(&client) == MATTER_CONNECTED);

    // Gửi lệnh bật đèn
    matter_command_t cmd;
    memset(&cmd, 0, sizeof(cmd));
    cmd.node_id     = 1;
    cmd.endpoint_id = 1;
    cmd.cluster_id  = 6;   // OnOff cluster
    cmd.is_command  = 1;
    strncpy(cmd.command_name, "on", sizeof(cmd.command_name));

    assert(matter_client_send_command(&client, &cmd) == 0);
    printf("Sent ON command to node_id=1\n");
    usleep(1000000); // Chờ 1 giây

    // Gửi lệnh tắt đèn
    strncpy(cmd.command_name, "off", sizeof(cmd.command_name));
    matter_client_send_command(&client, &cmd);
    printf("Sent OFF command to node_id=1\n");
    usleep(500000);

    matter_client_stop(&client);
    message_queue_signal_shutdown(&queue);
    pthread_join(tid, NULL);
    matter_client_destroy(&client);
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
    test_send_command();

    printf("\n=== All matter_client tests PASSED ===\n");

    logger_destroy();
    return 0;
}