#include "ring_buffer.h"

#include <stdio.h>
#include <assert.h>
#include <string.h>


static bridge_message_t make_msg(const char *topic,
                                  const char *payload,
                                  long        ts)
{
    bridge_message_t msg;
    strncpy(msg.topic,   topic,   sizeof(msg.topic)   - 1);
    strncpy(msg.payload, payload, sizeof(msg.payload) - 1);
    msg.topic[sizeof(msg.topic)   - 1] = '\0';
    msg.payload[sizeof(msg.payload) - 1] = '\0';
    msg.timestamp_ms = ts;
    return msg;
}


static void test_init(void)
{
    printf("\n=== Test 1: Init ===\n");

    ring_buffer_t rb;
    ring_buffer_init(&rb);

    assert(ring_buffer_empty(&rb) == 1);
    assert(ring_buffer_full(&rb)  == 0);
    assert(ring_buffer_size(&rb)  == 0);

    printf("Test 1 PASSED\n");
}


static void test_push_pop(void)
{
    printf("\n Test 2: Push and Pop \n");

    ring_buffer_t rb;
    ring_buffer_init(&rb);

    bridge_message_t in  = make_msg("home/sensor/temp",
                                     "{\"temp\":25.3}",
                                     1000);
    bridge_message_t out;

    // Push vào
    assert(ring_buffer_push(&rb, &in) == RB_OK);
    assert(ring_buffer_size(&rb) == 1);
    assert(ring_buffer_empty(&rb) == 0);

    // Pop ra
    assert(ring_buffer_pop(&rb, &out) == RB_OK);
    assert(ring_buffer_size(&rb) == 0);
    assert(ring_buffer_empty(&rb) == 1);

    // Verify dữ liệu
    assert(strcmp(out.topic,   "home/sensor/temp") == 0);
    assert(strcmp(out.payload, "{\"temp\":25.3}")   == 0);
    assert(out.timestamp_ms == 1000);

    printf("Test 2 PASSED\n");
}


static void test_fifo_order(void)
{
    printf("\n Test 3: FIFO order \n");

    ring_buffer_t rb;
    ring_buffer_init(&rb);

    // Push 3 message với timestamp khác nhau
    bridge_message_t m1 = make_msg("topic/1", "{\"v\":1}", 100);
    bridge_message_t m2 = make_msg("topic/2", "{\"v\":2}", 200);
    bridge_message_t m3 = make_msg("topic/3", "{\"v\":3}", 300);

    ring_buffer_push(&rb, &m1);
    ring_buffer_push(&rb, &m2);
    ring_buffer_push(&rb, &m3);
    assert(ring_buffer_size(&rb) == 3);

    // Pop ra phải theo đúng thứ tự push vào
    bridge_message_t out;
    ring_buffer_pop(&rb, &out);
    assert(out.timestamp_ms == 100);

    ring_buffer_pop(&rb, &out);
    assert(out.timestamp_ms == 200);

    ring_buffer_pop(&rb, &out);
    assert(out.timestamp_ms == 300);

    assert(ring_buffer_empty(&rb) == 1);

    printf("Test 3 PASSED\n");
}


static void test_full(void)
{
    printf("\n Test 4: Buffer full \n");

    ring_buffer_t rb;
    ring_buffer_init(&rb);

    bridge_message_t msg = make_msg("topic", "{}", 0);

    // Push đúng RB_CAPACITY lần
    for (int i = 0; i < RB_CAPACITY; i++) {
        assert(ring_buffer_push(&rb, &msg) == RB_OK);
    }

    assert(ring_buffer_full(&rb)  == 1);
    assert(ring_buffer_size(&rb)  == RB_CAPACITY);

    // Push thêm phải trả về RB_FULL
    assert(ring_buffer_push(&rb, &msg) == RB_FULL);

    printf("Test 4 PASSED\n");
}


static void test_empty_pop(void)
{
    printf("\n Test 5: Pop when empty \n");

    ring_buffer_t rb;
    ring_buffer_init(&rb);

    bridge_message_t out;
    assert(ring_buffer_pop(&rb, &out) == RB_EMPTY);

    printf("Test 5 PASSED\n");
}


static void test_wraparound(void)
{
    printf("\n Test 6: Wrap around \n");

    ring_buffer_t rb;
    ring_buffer_init(&rb);

    bridge_message_t msg;
    bridge_message_t out;

    // Fill gần đầy — push 60 pop 60 
    for (int i = 0; i < 60; i++) {
        msg = make_msg("topic", "{}", i);
        ring_buffer_push(&rb, &msg);
    }
    for (int i = 0; i < 60; i++) {
        ring_buffer_pop(&rb, &out);
    }

    // Lúc này head và tail đã wrap — push thêm 10 
    for (int i = 0; i < 10; i++) {
        msg = make_msg("topic", "{}", 1000 + i);
        assert(ring_buffer_push(&rb, &msg) == RB_OK);
    }

    assert(ring_buffer_size(&rb) == 10);

    // Pop ra verify timestamp đúng thứ tự
    for (int i = 0; i < 10; i++) {
        ring_buffer_pop(&rb, &out);
        assert(out.timestamp_ms == 1000 + i);
    }

    assert(ring_buffer_empty(&rb) == 1);

    printf("Test 6 PASSED\n");
}


int main(void)
{
    test_init();
    test_push_pop();
    test_fifo_order();
    test_full();
    test_empty_pop();
    test_wraparound();

    printf("\n All ring_buffer tests PASSED \n");
    return 0;
}