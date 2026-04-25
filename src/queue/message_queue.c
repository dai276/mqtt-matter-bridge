#define _POSIX_C_SOURCE 200809L

#include "message_queue.h"
#include "logger.h"
#include <string.h>

#define MODULE "message_queue"

int message_queue_init(message_queue_t *q)
{
    if (!q) return QUEUE_FULL;

    ring_buffer_init(&q->rb);
    q->shutdown = 0;

    if (pthread_mutex_init(&q->mutex, NULL) != 0) {
        LOG_ERR(MODULE, "Failed to init mutex");
        return QUEUE_FULL;
    }

    if (pthread_cond_init(&q->cond, NULL) != 0) {
        LOG_ERR(MODULE, "Failed to init condition variable");
        pthread_mutex_destroy(&q->mutex);
        return QUEUE_FULL;
    }

    LOG_INF(MODULE, "Queue initialized, capacity=%d", RB_CAPACITY);
    return QUEUE_OK;
}

int message_queue_push(message_queue_t *q, const bridge_message_t *msg)
{
    if (!q || !msg) return QUEUE_FULL;

    pthread_mutex_lock(&q->mutex);

    // Không push khi đang shutdown
    if (q->shutdown) {
        pthread_mutex_unlock(&q->mutex);
        return QUEUE_SHUTDOWN;
    }

    int ret = ring_buffer_push(&q->rb, msg);

    if (ret == RB_FULL) {
        LOG_WRN(MODULE, "Queue full, dropping message topic=%s", msg->topic);
        pthread_mutex_unlock(&q->mutex);
        return QUEUE_FULL;
    }

    // Báo cho Matter thread biết có message mới
    pthread_cond_signal(&q->cond);

    LOG_DBG(MODULE, "Pushed topic=%s size=%d", msg->topic,
            ring_buffer_size(&q->rb));

    pthread_mutex_unlock(&q->mutex);
    return QUEUE_OK;
}

int message_queue_pop_blocking(message_queue_t *q, bridge_message_t *msg)
{
    if (!q || !msg) return QUEUE_EMPTY;

    pthread_mutex_lock(&q->mutex);

    // Ngủ khi queue rỗng và chưa shutdown
    // pthread_cond_wait tự nhả mutex khi ngủ, lấy lại khi thức
    while (ring_buffer_empty(&q->rb) && !q->shutdown) {
        pthread_cond_wait(&q->cond, &q->mutex);
    }

    // Thức dậy do shutdown và queue vẫn rỗng
    if (q->shutdown && ring_buffer_empty(&q->rb)) {
        pthread_mutex_unlock(&q->mutex);
        return QUEUE_SHUTDOWN;
    }

    int ret = ring_buffer_pop(&q->rb, msg);

    LOG_DBG(MODULE, "Popped topic=%s size=%d", msg->topic,
            ring_buffer_size(&q->rb));

    pthread_mutex_unlock(&q->mutex);
    return (ret == RB_OK) ? QUEUE_OK : QUEUE_EMPTY;
}

void message_queue_signal_shutdown(message_queue_t *q)
{
    if (!q) return;

    pthread_mutex_lock(&q->mutex);
    q->shutdown = 1;
    // Wake up tất cả thread đang chờ tại pop_blocking
    pthread_cond_broadcast(&q->cond);
    pthread_mutex_unlock(&q->mutex);

    LOG_INF(MODULE, "Shutdown signal sent");
}

int message_queue_size(message_queue_t *q)
{
    if (!q) return 0;

    pthread_mutex_lock(&q->mutex);
    int size = ring_buffer_size(&q->rb);
    pthread_mutex_unlock(&q->mutex);

    return size;
}

void message_queue_destroy(message_queue_t *q)
{
    if (!q) return;

    pthread_mutex_destroy(&q->mutex);
    pthread_cond_destroy(&q->cond);

    LOG_INF(MODULE, "Queue destroyed");
}