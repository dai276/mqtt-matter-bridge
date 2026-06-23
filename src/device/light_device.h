#ifndef LIGHT_DEVICE_H
#define LIGHT_DEVICE_H

#include <stdbool.h>
#include <time.h>

typedef struct {
    bool onoff;
    bool has_state;
    time_t last_update;
} light_state_t;

void light_state_init(light_state_t *state);
void light_state_set(light_state_t *state, bool onoff);
bool light_state_get(const light_state_t *state);
bool light_state_has_value(const light_state_t *state);

#endif // LIGHT_DEVICE_H