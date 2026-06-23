#include "light_device.h"

void light_state_init(light_state_t *state)
{
    if (!state) return;

    state->onoff = false;
    state->has_state = false;
    state->last_update = 0;
}

void light_state_set(light_state_t *state, bool onoff)
{
    if (!state) return;

    state->onoff = onoff;
    state->has_state = true;
    state->last_update = time(NULL);
}

bool light_state_get(const light_state_t *state)
{
    return state ? state->onoff : false;
}

bool light_state_has_value(const light_state_t *state)
{
    return state ? state->has_state : false;
}