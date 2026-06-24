#include "matter_backend.h"
#include "logger.h"
#include <stddef.h>

#define MODULE "MatterBackendLegacy"

static matter_light_command_cb_t g_light_cb = NULL;
static void *g_light_cb_user_data = NULL;

int matter_backend_init(void)
{
    LOG_INF(MODULE, "Initialized legacy Matter WebSocket backend adapter");
    return 0;
}

int matter_backend_start(void)
{
    LOG_INF(MODULE, "Started legacy Matter WebSocket backend adapter");
    return 0;
}

int matter_backend_stop(void)
{
    LOG_INF(MODULE, "Stopped legacy Matter WebSocket backend adapter");
    return 0;
}

int matter_backend_register_light_command_callback(
    matter_light_command_cb_t cb,
    void *user_data
)
{
    g_light_cb = cb;
    g_light_cb_user_data = user_data;
    LOG_INF(MODULE, "Registered light command callback");
    return 0;
}

int matter_backend_update_light_state(bool onoff)
{
    LOG_INF(MODULE, "Matter backend update light state: %s", onoff ? "ON" : "OFF");
    return 0;
}


int matter_backend_simulate_light_command(bool onoff)
{
    LOG_INF(MODULE, "Simulated Matter command: %s", onoff ? "ON" : "OFF");

    if (!g_light_cb) {
        LOG_WRN(MODULE, "No light command callback registered");
        return -1;
    }

    g_light_cb(onoff, g_light_cb_user_data);
    return 0;
}