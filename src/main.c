#define _POSIX_C_SOURCE 200809L

#include "bridge.h"
#include "matter_backend.h"
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <string.h>
#include <unistd.h>
#include <time.h>


// Bridge instance global để signal handler truy cập được
static bridge_t g_bridge;
static volatile sig_atomic_t g_shutdown = 0;

// Signal handler — gọi bridge_stop() khi nhận SIGTERM hoặc SIGINT
static void signal_handler(int sig)
{
    (void)sig;
    g_shutdown = 1;

}

static void sleep_ms(long ms)
{
    struct timespec ts = {
        .tv_sec = ms / 1000,
        .tv_nsec = (ms % 1000) * 1000000L,
    };
    nanosleep(&ts, NULL);
}

static int wait_for_mqtt_connected(bridge_t *bridge, int timeout_ms)
{
    if (!bridge) return -1;

    while (timeout_ms > 0) {
        if (mqtt_client_state(&bridge->mqtt) == MQTT_CONNECTED)
            return 0;

        sleep_ms(100);
        timeout_ms -= 100;
    }

    return -1;
}
int main(int argc, char *argv[])
{
    // Đọc đường dẫn config từ argument — mặc định config.json
    const char *config_path = "config.json";
    int simulate_light = 0;
    bool simulate_onoff = false;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--simulate-matter-on") == 0) {
            simulate_light = 1;
            simulate_onoff = true;
        } else if (strcmp(argv[i], "--simulate-matter-off") == 0) {
            simulate_light = 1;
            simulate_onoff = false;
        } else {
            config_path = argv[i];
        }
    }
    printf("MQTT-MATTER Bridge Daemon\n");
    printf("Config: %s\n", config_path);
    if (simulate_light)
        printf("Simulated Matter command: %s\n", simulate_onoff ? "ON" : "OFF");
    printf("\n");
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
    if (simulate_light) {
        if (wait_for_mqtt_connected(&g_bridge, 5000) != 0) {
            fprintf(stderr, "MQTT did not connect before simulate timeout\n");
            bridge_stop(&g_bridge);
            bridge_destroy(&g_bridge);
            return 1;
        }

        if (matter_backend_simulate_light_command(simulate_onoff) != 0) {
            fprintf(stderr, "Failed to simulate Matter light command\n");
            bridge_stop(&g_bridge);
            bridge_destroy(&g_bridge);
            return 1;
        }

        sleep_ms(750);
        bridge_stop(&g_bridge);
        bridge_destroy(&g_bridge);
        printf("Bridge stopped cleanly\n");
        return 0;
    }

    printf("Bridge running — press Ctrl+C to stop\n\n");

    // Chờ signal shutdown
    while (g_bridge.running && !g_shutdown)
        sleep(1);

    if (g_shutdown)
        bridge_stop(&g_bridge);


    // Dọn dẹp và thoát
    bridge_destroy(&g_bridge);
   
    printf("Bridge stopped cleanly\n");
    return 0;

}