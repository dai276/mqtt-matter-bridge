#define _POSIX_C_SOURCE 200809L

#include "matter_client.h"
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>

#define MODULE        "matter_client"
#define RETRY_DELAY_S 3

// WebSocket callback — libwebsockets gọi hàm này cho mọi event
static int ws_callback(struct lws              *wsi,
                        enum lws_callback_reasons reason,
                        void *user, void *in, size_t len)
{
    struct lws_context *ctx    = lws_get_context(wsi);
    matter_client_t    *client = (matter_client_t *)lws_context_user(ctx);

    switch (reason) {

    case LWS_CALLBACK_CLIENT_ESTABLISHED:
        // Kết nối thành công
        client->state = MATTER_CONNECTED;
        client->ws    = wsi;
        LOG_INF(MODULE, "Connected to Matter Server");
        break;

    case LWS_CALLBACK_CLIENT_RECEIVE:
        // Nhận response hoặc event từ Matter Server
        if (len > 0 && len < sizeof(client->recv_buf)) {
            memcpy(client->recv_buf, in, len);
            client->recv_buf[len] = '\0';
            client->recv_len      = (int)len;
            LOG_DBG(MODULE, "Received: %s", client->recv_buf);

            if (strstr(client->recv_buf, "\"error\""))
                LOG_WRN(MODULE, "Matter Server error: %s", client->recv_buf);
        }
        break;

    case LWS_CALLBACK_CLIENT_WRITEABLE:
        // Gửi command đang chờ nếu có
        if (client->send_pending) {
            int payload_len = strlen(client->send_buf + LWS_PRE);
            int sent = lws_write(wsi,
                                 (unsigned char *)(client->send_buf + LWS_PRE),
                                 payload_len,
                                 LWS_WRITE_TEXT);
            if (sent < 0)
                LOG_ERR(MODULE, "lws_write failed");
            else
                LOG_DBG(MODULE, "Sent %d bytes", sent);

            client->send_pending = 0;
        }
        break;

    case LWS_CALLBACK_CLIENT_CONNECTION_ERROR:
        LOG_WRN(MODULE, "Connection error: %s",
                in ? (char *)in : "unknown");
        client->state = MATTER_RECONNECTING;
        client->ws    = NULL;
        break;

    case LWS_CALLBACK_CLIENT_CLOSED:
        LOG_WRN(MODULE, "Connection closed — reconnecting");
        client->state = MATTER_RECONNECTING;
        client->ws    = NULL;
        break;

    default:
        break;
    }

    return 0;
}

// Bảng protocol cho libwebsockets — phần tử NULL kết thúc bắt buộc
static struct lws_protocols protocols[] = {
    {
        .name                  = "matter-protocol",
        .callback              = ws_callback,
        .per_session_data_size = 0,
        .rx_buffer_size        = 4096,
    },
    { NULL, NULL, 0, 0 }
};

// Tạo kết nối WebSocket đến Matter Server
// Parse URL dạng ws://localhost:5580/ws
static int do_connect(matter_client_t *client)
{
    char host[128] = "localhost";
    int  port      = 5580;
    char path[128] = "/ws";

    const char *url = client->config->matter_server;
    if (strncmp(url, "ws://", 5) == 0)
        sscanf(url + 5, "%127[^:/]:%d%127s", host, &port, path);

    struct lws_client_connect_info info = {
        .context        = client->ws_context,
        .address        = host,
        .port           = port,
        .path           = path,
        .host           = host,
        .origin         = host,
        .protocol       = protocols[0].name,
        .ssl_connection = 0,
    };

    client->state = MATTER_CONNECTING;
    LOG_INF(MODULE, "Connecting to %s:%d%s...", host, port, path);

    struct lws *wsi = lws_client_connect_via_info(&info);
    if (!wsi) {
        LOG_WRN(MODULE, "Connect failed — retry in %ds", RETRY_DELAY_S);
        client->state = MATTER_RECONNECTING;
        return -1;
    }

    return 0;
}

int matter_client_init(matter_client_t *client,
                       bridge_config_t *config,
                       message_queue_t *queue)
{
    if (!client || !config || !queue) return -1;

    memset(client, 0, sizeof(matter_client_t));
    client->config  = config;
    client->queue   = queue;
    client->state   = MATTER_DISCONNECTED;
    client->running = 1;
    client->msg_id  = 1;

    // Tắt log nội bộ của libwebsockets để không làm nhiễu output
    lws_set_log_level(0, NULL);

    struct lws_context_creation_info info = {
        .port      = CONTEXT_PORT_NO_LISTEN, // Chỉ dùng client mode
        .protocols = protocols,
        .user      = client,                 // Truyền client vào callback
        .options   = LWS_SERVER_OPTION_DO_SSL_GLOBAL_INIT,
    };

    client->ws_context = lws_create_context(&info);
    if (!client->ws_context) {
        LOG_ERR(MODULE, "Failed to create lws context");
        return -1;
    }

    LOG_INF(MODULE, "Initialized, server=%s", config->matter_server);
    return 0;
}

int matter_client_send_command(matter_client_t        *client,
                                const matter_command_t *cmd)
{
    if (!client || !cmd || !client->ws)       return -1;
    if (client->state != MATTER_CONNECTED)    return -1;

    char json[1024];

    if (cmd->is_command) {
        // Gửi command (on/off/toggle) đến OnOff cluster
        snprintf(json, sizeof(json),
            "{"
            "\"message_id\":\"%d\","
            "\"command\":\"device_command\","
            "\"args\":{"
                "\"node_id\":%d,"
                "\"endpoint_id\":%d,"
                "\"cluster_id\":%d,"
                "\"command_name\":\"%s\","
                "\"payload\":{}"
            "}"
            "}",
            client->msg_id++,
            cmd->node_id,
            cmd->endpoint_id,
            cmd->cluster_id,
            cmd->command_name);
    } else {
        // Write attribute — dùng cho nhiệt độ, độ ẩm
        snprintf(json, sizeof(json),
            "{"
            "\"message_id\":\"%d\","
            "\"command\":\"write_attribute\","
            "\"args\":{"
                "\"node_id\":%d,"
                "\"endpoint_id\":%d,"
                "\"cluster_id\":%d,"
                "\"attribute_name\":\"%s\","
                "\"value\":%d"
            "}"
            "}",
            client->msg_id++,
            cmd->node_id,
            cmd->endpoint_id,
            cmd->cluster_id,
            cmd->attribute,
            cmd->value_int);
    }

    int json_len = strlen(json);
    if (json_len >= (int)(sizeof(client->send_buf) - LWS_PRE)) {
        LOG_ERR(MODULE, "Command too long: %d bytes", json_len);
        return -1;
    }

    // Copy vào send_buf với LWS_PRE offset bắt buộc của libwebsockets
    memcpy(client->send_buf + LWS_PRE, json, json_len + 1);
    client->send_pending = 1;

    // Yêu cầu libwebsockets gọi WRITEABLE callback để thực sự gửi
    lws_callback_on_writable(client->ws);

    LOG_DBG(MODULE, "Queued command: %s", json);
    return 0;
}

void matter_client_run(matter_client_t *client)
{
    if (!client) return;

    while (client->running) {

        // Kết nối nếu chưa kết nối hoặc bị mất kết nối
        if (client->state == MATTER_DISCONNECTED ||
            client->state == MATTER_RECONNECTING) {

            if (do_connect(client) != 0) {
                sleep(RETRY_DELAY_S);
                continue;
            }

            // Chờ kết nối thành công tối đa 5 giây
            int timeout = 50;
            while (client->state == MATTER_CONNECTING && timeout-- > 0)
                lws_service(client->ws_context, 100);

            if (client->state != MATTER_CONNECTED) {
                LOG_WRN(MODULE, "Connect timeout — retry");
                client->state = MATTER_RECONNECTING;
                sleep(RETRY_DELAY_S);
                continue;
            }
        }

        // Xử lý WebSocket event — timeout 100ms
        lws_service(client->ws_context, 100);
    }

    LOG_INF(MODULE, "Run loop exited");
}

void matter_client_stop(matter_client_t *client)
{
    if (!client) return;
    client->running = 0;
    LOG_INF(MODULE, "Stop requested");
}

void matter_client_destroy(matter_client_t *client)
{
    if (!client) return;

    if (client->ws_context) {
        lws_context_destroy(client->ws_context);
        client->ws_context = NULL;
    }

    LOG_INF(MODULE, "Destroyed");
}

matter_state_t matter_client_state(const matter_client_t *client)
{
    return client ? client->state : MATTER_DISCONNECTED;
}