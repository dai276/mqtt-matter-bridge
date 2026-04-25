#define _POSIX_C_SOURCE 200809L

#include "bridge.h"
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>

// Bridge instance global để signal handler truy cập được
static bridge_t g_bridge;

// Signal handler — gọi bridge_stop() khi nhận SIGTERM hoặc SIGINT
static void signal_handler(int sig)
{
    printf("\nReceived signal %d, shutting down...\n", sig);
    bridge_stop(&g_bridge);
}

int main(int argc, char *argv[])
{
    // Đọc đường dẫn config từ argument — mặc định config.json
    const char *config_path = "config.json";
    if (argc >= 2)
        config_path = argv[1];

    printf("MQTT-MATTER Bridge Daemon\n");
    printf("Config: %s\n\n", config_path);

    // Đăng ký signal handler để shutdown graceful
    signal(SIGINT,  signal_handler);
    signal(SIGTERM, signal_handler);

    // Khởi tạo bridge
    if (bridge_init(&g_bridge, config_path) != 0) {
        fprintf(stderr, "Failed to initialize bridge\n");
        return 1;
    }

    // Start tất cả threads
    if (bridge_start(&g_bridge) != 0) {
        fprintf(stderr, "Failed to start bridge\n");
        bridge_destroy(&g_bridge);
        return 1;
    }

    printf("Bridge running — press Ctrl+C to stop\n\n");

    // Chờ signal shutdown — pause() ngủ cho đến khi có signal
    while (g_bridge.running)
        pause();

    // Dọn dẹp và thoát
    bridge_destroy(&g_bridge);
   
 printf("Bridge stopped cleanly\n");
    return 0;
}