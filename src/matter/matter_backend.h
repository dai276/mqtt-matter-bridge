#ifndef MATTER_BACKEND_H
#define MATTER_BACKEND_H

#include <stdbool.h>

typedef void (*matter_light_command_cb_t)(bool onoff, void *user_data);

int matter_backend_init(void);
int matter_backend_start(void);
int matter_backend_stop(void);

int matter_backend_register_light_command_callback(
    matter_light_command_cb_t cb,
    void *user_data
);

int matter_backend_update_light_state(bool onoff);

/*
 * Test-only helper for Phase 3. Later this will be replaced by real Matter
 * OnOff command handler.
 */
int matter_backend_simulate_light_command(bool onoff);

#endif // MATTER_BACKEND_H
