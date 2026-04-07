#include "ring_buffer.h"
#include <string.h>



void ring_buffer_init(ring_buffer_t *rb)
{
    memset(rb, 0, sizeof(ring_buffer_t));
    rb->head  = 0;
    rb->tail  = 0;
    rb->count = 0;
}

int ring_buffer_push(ring_buffer_t *rb, const bridge_message_t *msg)
{
    if (!rb || !msg)              return RB_FULL;
    if (rb->count >= RB_CAPACITY) return RB_FULL;

    // Copy message vào vị trí tail
    memcpy(&rb->data[rb->tail], msg, sizeof(bridge_message_t));

    // Advance tail theo vòng tròn
    rb->tail = (rb->tail + 1) % RB_CAPACITY;
    rb->count++;

    return RB_OK;
}

int ring_buffer_pop(ring_buffer_t *rb, bridge_message_t *msg)
{
    if (!rb || !msg)  return RB_EMPTY;
    if (rb->count <= 0) return RB_EMPTY;

    // Copy message từ vị trí head ra msg
    memcpy(msg, &rb->data[rb->head], sizeof(bridge_message_t));

    // Advance head theo vòng tròn và giảm count
    rb->head = (rb->head + 1) % RB_CAPACITY;
    rb->count--;

    return RB_OK;
}

int ring_buffer_empty(const ring_buffer_t *rb)
{
    return (!rb || rb->count == 0) ? 1 : 0;
}

int ring_buffer_full(const ring_buffer_t *rb)
{
    return (!rb || rb->count >= RB_CAPACITY) ? 1 : 0;
}

int ring_buffer_size(const ring_buffer_t *rb)
{
    return rb ? rb->count : 0;
}