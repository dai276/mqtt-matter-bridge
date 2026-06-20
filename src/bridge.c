#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L

#include "bridge.h"
#include <string.h>
#include <unistd.h>
#include <time.h>

#define MODULE           "bridge"
#define MONITOR_INTERVAL 30

// Lấy timestamp hiện tại tính bằng millisecond
static long now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

// Thread 1 — chạy MQTT client loop
static void *mqtt_thread_func(void *arg)
{
    bridge_t *bridge = (bridge_t *)arg;
    LOG_INF(MODULE, "MQTT thread started");
    mqtt_client_run(&bridge->mqtt);
    LOG_INF(MODULE, "MQTT thread exited");
    return NULL;
}

// Thread 2 — chạy Matter WebSocket connection loop
// Duy trì kết nối đến Matter Server liên tục
static void *matter_conn_thread_func(void *arg)
{
    bridge_t *bridge = (bridge_t *)arg;
    LOG_INF(MODULE, "Matter connection thread started");
    matter_client_run(&bridge->matter);
    LOG_INF(MODULE, "Matter connection thread exited");
    return NULL;
}

// Thread 3 — Matter dispatcher
// Pop message từ queue, dịch sang MATTER command, gửi lên Matter Server
static void *matter_dispatch_thread_func(void *arg)
{
    bridge_t *bridge = (bridge_t *)arg;
    LOG_INF(MODULE, "Matter dispatch thread started");

    while (bridge->running) {
        bridge_message_t msg;

        int ret = message_queue_pop_blocking(&bridge->queue, &msg);

        if (ret == QUEUE_SHUTDOWN) {
            LOG_INF(MODULE, "Matter dispatch thread received shutdown");
            break;
        }

        if (ret != QUEUE_OK) continue;

        bridge->metrics.received++;

        // Chờ Matter client kết nối nếu chưa sẵn sàng — tối đa 5 giây
        int timeout = 50;
        while (matter_client_state(&bridge->matter) != MATTER_CONNECTED
               && timeout-- > 0) {
            usleep(100000);
        }

        if (matter_client_state(&bridge->matter) != MATTER_CONNECTED) {
            LOG_WRN(MODULE, "Matter not connected, dropping topic=%s",
                    msg.topic);
            bridge->metrics.dropped++;
            continue;
        }

        // Dịch MQTT message sang MATTER command
        matter_command_t cmd;
        if (mapper_translate(&msg, &cmd) != 0) {
            LOG_DBG(MODULE, "No mapping for topic=%s", msg.topic);
            continue;
        }

        // Gửi command đến Matter Server
        ret = matter_client_send_command(&bridge->matter, &cmd);

        if (ret == 0) {
            long latency = now_ms() - msg.timestamp_ms;
            bridge->metrics.sent++;
            bridge->metrics.total_latency_ms += latency;
            LOG_INF(MODULE, "Sent OK topic=%s latency=%ldms",
                    msg.topic, latency);
        } else {
            bridge->metrics.errors++;
            LOG_WRN(MODULE, "Send failed for topic=%s", msg.topic);
        }
    }

    LOG_INF(MODULE, "Matter dispatch thread exited");
    return NULL;
}

// Thread 4 — Monitor
static void *monitor_thread_func(void *arg)
{
    bridge_t *bridge = (bridge_t *)arg;
    LOG_INF(MODULE, "Monitor thread started");

    while (bridge->running) {
        sleep(MONITOR_INTERVAL);
        if (!bridge->running) break;

        long avg_latency = 0;
        if (bridge->metrics.sent > 0)
            avg_latency = bridge->metrics.total_latency_ms
                          / bridge->metrics.sent;

        LOG_INF(MODULE, "=== Metrics ===");
        LOG_INF(MODULE, "  MQTT state   : %d",
                mqtt_client_state(&bridge->mqtt));
        LOG_INF(MODULE, "  Matter state : %d",
                matter_client_state(&bridge->matter));
        LOG_INF(MODULE, "  Received     : %ld", bridge->metrics.received);
        LOG_INF(MODULE, "  Sent         : %ld", bridge->metrics.sent);
        LOG_INF(MODULE, "  Dropped      : %ld", bridge->metrics.dropped);
        LOG_INF(MODULE, "  Errors       : %ld", bridge->metrics.errors);
        LOG_INF(MODULE, "  Avg latency  : %ldms", avg_latency);
        LOG_INF(MODULE, "  Queue size   : %d",
                message_queue_size(&bridge->queue));
    }

    LOG_INF(MODULE, "Monitor thread exited");
    return NULL;
}

int bridge_init(bridge_t *bridge, const char *config_path)
{
    if (!bridge || !config_path) return -1;

    memset(bridge, 0, sizeof(bridge_t));
    bridge->running = 1;

    if (config_parser_load(config_path, &bridge->config) != 0) {
        LOG_ERR(MODULE, "Failed to load config: %s", config_path);
        return -1;
    }

    logger_config_t log_cfg = {
        .min_level     = bridge->config.log_level,
        .log_to_stdout = 1,
    };
    strncpy(log_cfg.log_file, bridge->config.log_file,
            sizeof(log_cfg.log_file) - 1);
    logger_init(&log_cfg);

    config_parser_print(&bridge->config);

    if (message_queue_init(&bridge->queue) != QUEUE_OK) {
        LOG_ERR(MODULE, "Failed to init message queue");
        return -1;
    }

    if (mqtt_client_init(&bridge->mqtt,
                          &bridge->config,
                          &bridge->queue) != 0) {
        LOG_ERR(MODULE, "Failed to init MQTT client");
        return -1;
    }

    if (matter_client_init(&bridge->matter,
                            &bridge->config,
                            &bridge->queue) != 0) {
        LOG_ERR(MODULE, "Failed to init Matter client");
        return -1;
    }

    if (mapper_init(&bridge->config) != 0) {
        LOG_ERR(MODULE, "Failed to init mapper");
        return -1;
    }

    LOG_INF(MODULE, "Bridge initialized successfully");
    return 0;
}

int bridge_start(bridge_t *bridge)
{
    if (!bridge) return -1;

    if (pthread_create(&bridge->mqtt_thread, NULL,
                        mqtt_thread_func, bridge) != 0) {
        LOG_ERR(MODULE, "Failed to create MQTT thread");
        return -1;
    }
    bridge->mqtt_thread_created = 1;
    LOG_INF(MODULE, "MQTT thread started");

    if (pthread_create(&bridge->matter_thread, NULL,
                        matter_conn_thread_func, bridge) != 0) {
        LOG_ERR(MODULE, "Failed to create Matter connection thread");
        return -1;
    }
    bridge->matter_thread_created = 1;
    LOG_INF(MODULE, "Matter connection thread started");

    if (pthread_create(&bridge->dispatch_thread, NULL,
                        matter_dispatch_thread_func, bridge) != 0) {
        LOG_ERR(MODULE, "Failed to create Matter dispatch thread");
        return -1;
    }
    bridge->dispatch_thread_created = 1;
    LOG_INF(MODULE, "Matter dispatch thread started");

    if (pthread_create(&bridge->monitor_thread, NULL,
                        monitor_thread_func, bridge) != 0) {
        LOG_ERR(MODULE, "Failed to create Monitor thread");
        return -1;
    }
    bridge->monitor_thread_created = 1;
    LOG_INF(MODULE, "Monitor thread started");

    LOG_INF(MODULE, "All threads started");
    return 0;
}

void bridge_stop(bridge_t *bridge)
{
    if (!bridge) return;

    LOG_INF(MODULE, "Stopping bridge...");
    bridge->running = 0;

    mqtt_client_stop(&bridge->mqtt);
    matter_client_stop(&bridge->matter);
    message_queue_signal_shutdown(&bridge->queue);
}

void bridge_destroy(bridge_t *bridge)
{
    if (!bridge) return;

    LOG_INF(MODULE, "Waiting for threads to exit...");

    if (bridge->mqtt_thread_created)
        pthread_join(bridge->mqtt_thread, NULL);
    if (bridge->matter_thread_created)
        pthread_join(bridge->matter_thread, NULL);
    if (bridge->dispatch_thread_created)
        pthread_join(bridge->dispatch_thread, NULL);
    if (bridge->monitor_thread_created)
        pthread_join(bridge->monitor_thread, NULL);

    mapper_destroy();
    matter_client_destroy(&bridge->matter);
    mqtt_client_destroy(&bridge->mqtt);
    message_queue_destroy(&bridge->queue);
    config_parser_destroy(&bridge->config);

    LOG_INF(MODULE, "Bridge destroyed cleanly");
    logger_destroy();
}