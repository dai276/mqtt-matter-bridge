#define _POSIX_C_SOURCE 200809L

#include "mqtt_client.h"
#include <string.h>
#include <unistd.h>
#include <time.h>

#define MODULE        "mqtt_client"
#define RETRY_DELAY_S 3

// Lấy timestamp hiện tại tính bằng millisecond
static long now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

// Callback khi kết nối thành công
// Subscribe tất cả topic được định nghĩa trong config
static void on_connect(struct mosquitto *mosq, void *userdata, int rc)
{
    mqtt_client_t *client = (mqtt_client_t *)userdata;

    if (rc != 0) {
        LOG_ERR(MODULE, "Connection refused, code=%d", rc);
        client->state = MQTT_RECONNECTING;
        return;
    }

    client->state = MQTT_CONNECTED;
    LOG_INF(MODULE, "Connected to %s:%d",
            client->config->mqtt_broker,
            client->config->mqtt_port);

    for (int i = 0; i < client->config->device_count; i++) {
        const char *topic = client->config->devices[i].mqtt_topic;
        int ret = mosquitto_subscribe(mosq, NULL, topic, 1);
        if (ret == MOSQ_ERR_SUCCESS)
            LOG_INF(MODULE, "Subscribed: %s", topic);
        else
            LOG_ERR(MODULE, "Subscribe failed: %s", topic);
    }
}

// Callback khi mất kết nối
static void on_disconnect(struct mosquitto *mosq, void *userdata, int rc)
{
    (void)mosq;
    mqtt_client_t *client = (mqtt_client_t *)userdata;
    client->state = MQTT_RECONNECTING;

    if (rc != 0)
        LOG_WRN(MODULE, "Unexpected disconnect code=%d", rc);
    else
        LOG_INF(MODULE, "Disconnected cleanly");
}

// Callback khi nhận được message từ broker
// Tạo bridge_message và push vào queue để Matter thread xử lý
static void on_message(struct mosquitto       *mosq,
                        void                  *userdata,
                        const struct mosquitto_message *msg)
{
    (void)mosq;
    mqtt_client_t *client = (mqtt_client_t *)userdata;

    if (!msg->payload || msg->payloadlen == 0) {
        LOG_WRN(MODULE, "Empty payload on topic=%s, skipping", msg->topic);
        return;
    }

    bridge_message_t bmsg;
    strncpy(bmsg.topic,   msg->topic,          sizeof(bmsg.topic)   - 1);
    strncpy(bmsg.payload, (char *)msg->payload, sizeof(bmsg.payload) - 1);
    bmsg.topic[sizeof(bmsg.topic)   - 1] = '\0';
    bmsg.payload[sizeof(bmsg.payload) - 1] = '\0';
    bmsg.timestamp_ms = now_ms();

    int ret = message_queue_push(client->queue, &bmsg);
    if (ret == QUEUE_FULL)
        LOG_WRN(MODULE, "Queue full, dropped topic=%s", msg->topic);
    else
        LOG_DBG(MODULE, "Queued topic=%s payload=%s",
                msg->topic, bmsg.payload);
}

int mqtt_client_init(mqtt_client_t   *client,
                     bridge_config_t *config,
                     message_queue_t *queue)
{
    if (!client || !config || !queue) return -1;

    memset(client, 0, sizeof(mqtt_client_t));
    client->config  = config;
    client->queue   = queue;
    client->state   = MQTT_DISCONNECTED;
    client->running = 1;

    mosquitto_lib_init();

    client->mosq = mosquitto_new("bridge-daemon", true, client);
    if (!client->mosq) {
        LOG_ERR(MODULE, "Failed to create mosquitto instance");
        return -1;
    }

    mosquitto_connect_callback_set   (client->mosq, on_connect);
    mosquitto_disconnect_callback_set(client->mosq, on_disconnect);
    mosquitto_message_callback_set   (client->mosq, on_message);

    LOG_INF(MODULE, "Initialized, broker=%s:%d",
            config->mqtt_broker, config->mqtt_port);
    return 0;
}

void mqtt_client_run(mqtt_client_t *client)
{
    if (!client) return;

    while (client->running) {

        // Kết nối nếu đang ở trạng thái chưa kết nối hoặc mất kết nối
        if (client->state == MQTT_DISCONNECTED ||
            client->state == MQTT_RECONNECTING) {

            LOG_INF(MODULE, "Connecting to %s:%d...",
                    client->config->mqtt_broker,
                    client->config->mqtt_port);

            client->state = MQTT_CONNECTING;

            int ret = mosquitto_connect(client->mosq,
                                        client->config->mqtt_broker,
                                        client->config->mqtt_port,
                                        60);
            if (ret != MOSQ_ERR_SUCCESS) {
                LOG_WRN(MODULE, "Connect failed: %s — retry in %ds",
                        mosquitto_strerror(ret), RETRY_DELAY_S);
                client->state = MQTT_RECONNECTING;
                sleep(RETRY_DELAY_S);
                continue;
            }
        }

        // Xử lý network I/O — timeout 100ms
        int ret = mosquitto_loop(client->mosq, 100, 1);

        if (ret != MOSQ_ERR_SUCCESS &&
            client->state == MQTT_CONNECTED) {
            LOG_WRN(MODULE, "Loop error: %s", mosquitto_strerror(ret));
            client->state = MQTT_RECONNECTING;
            mosquitto_reconnect(client->mosq);
        }
    }

    LOG_INF(MODULE, "Run loop exited");
}

void mqtt_client_stop(mqtt_client_t *client)
{
    if (!client) return;
    client->running = 0;
    LOG_INF(MODULE, "Stop requested");
}

void mqtt_client_destroy(mqtt_client_t *client)
{
    if (!client) return;

    if (client->mosq) {
        mosquitto_disconnect(client->mosq);
        mosquitto_destroy(client->mosq);
        client->mosq = NULL;
    }

    mosquitto_lib_cleanup();
    LOG_INF(MODULE, "Destroyed");
}

mqtt_state_t mqtt_client_state(const mqtt_client_t *client)
{
    return client ? client->state : MQTT_DISCONNECTED;
}