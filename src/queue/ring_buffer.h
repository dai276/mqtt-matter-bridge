#ifndef RING_BUFFER_H
#define RING_BUFFER_H


#define RB_CAPACITY     64      // Số message tối đa trong buffer  
#define RB_TOPIC_SIZE   128     // Độ dài tối đa của MQTT topic    
#define RB_PAYLOAD_SIZE 512     // Độ dài tối đa của JSON payload  

//bridge_message_t — đơn vị dữ liệu lưu trong buffer
typedef struct {
    char topic[RB_TOPIC_SIZE];      // MQTT topic
    char payload[RB_PAYLOAD_SIZE];  // JSON payload từ ESP32
    long timestamp_ms;              // Thời điểm nhận — đo latency
} bridge_message_t;


typedef struct {
    bridge_message_t data[RB_CAPACITY]; // Vùng nhớ cố định         
    int              head;              // Index đọc tiếp theo       
    int              tail;              // Index ghi tiếp theo       
    int              count;             // Số message hiện có        
} ring_buffer_t;


#define RB_OK       0
#define RB_FULL    -1
#define RB_EMPTY   -2



void ring_buffer_init(ring_buffer_t *rb);


int ring_buffer_push(ring_buffer_t *rb, const bridge_message_t *msg);


int ring_buffer_pop(ring_buffer_t *rb, bridge_message_t *msg);


int ring_buffer_empty(const ring_buffer_t *rb);


int ring_buffer_full(const ring_buffer_t *rb);


int ring_buffer_size(const ring_buffer_t *rb);

#endif /* RING_BUFFER_H */