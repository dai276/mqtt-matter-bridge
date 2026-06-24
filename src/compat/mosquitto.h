#ifndef COMPAT_MOSQUITTO_H
#define COMPAT_MOSQUITTO_H
#include <stdbool.h>
#define MOSQ_ERR_SUCCESS 0
struct mosquitto;
struct mosquitto_message { char *topic; void *payload; int payloadlen; };
struct mosquitto *mosquitto_new(const char *id, bool clean_session, void *userdata);
void mosquitto_destroy(struct mosquitto *mosq);
int mosquitto_lib_init(void);
int mosquitto_lib_cleanup(void);
void mosquitto_connect_callback_set(struct mosquitto *mosq, void (*cb)(struct mosquitto *, void *, int));
void mosquitto_disconnect_callback_set(struct mosquitto *mosq, void (*cb)(struct mosquitto *, void *, int));
void mosquitto_message_callback_set(struct mosquitto *mosq, void (*cb)(struct mosquitto *, void *, const struct mosquitto_message *));
int mosquitto_subscribe(struct mosquitto *mosq, int *mid, const char *sub, int qos);
int mosquitto_connect(struct mosquitto *mosq, const char *host, int port, int keepalive);
int mosquitto_loop(struct mosquitto *mosq, int timeout, int max_packets);
int mosquitto_reconnect(struct mosquitto *mosq);
int mosquitto_disconnect(struct mosquitto *mosq);
int mosquitto_publish(struct mosquitto *mosq, int *mid, const char *topic, int payloadlen, const void *payload, int qos, bool retain);
const char *mosquitto_strerror(int mosq_errno);
#endif
