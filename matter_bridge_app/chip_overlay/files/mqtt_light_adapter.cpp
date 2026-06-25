#include "mqtt_light_adapter.h"

#include <cstring>
#include <lib/support/logging/CHIPLogging.h>
#include <utility>

namespace {
constexpr const char * kLogModule = "MqttLightAdapter";
}

MqttLightAdapter::MqttLightAdapter(const std::string& host,
                                   int port,
                                   const std::string& command_topic,
                                   const std::string& state_topic,
                                   const std::string& availability_topic)
    : host_(host), port_(port), command_topic_(command_topic), state_topic_(state_topic),
      availability_topic_(availability_topic)
{
}

MqttLightAdapter::~MqttLightAdapter()
{
    Stop();
}

bool MqttLightAdapter::Start()
{
    if (started_) {
        return true;
    }

    mosquitto_lib_init();
    mosq_ = mosquitto_new("chip-bridge-app-light", true, this);
    if (mosq_ == nullptr) {
        ChipLogError(AppServer, "%s: mosquitto_new failed", kLogModule);
        return false;
    }

    mosquitto_message_callback_set(mosq_, &MqttLightAdapter::OnMessage);

    const int rc = mosquitto_connect(mosq_, host_.c_str(), port_, 60);
    if (rc != MOSQ_ERR_SUCCESS) {
        ChipLogError(AppServer, "%s: MQTT connect failed: %s", kLogModule, mosquitto_strerror(rc));
        mosquitto_destroy(mosq_);
        mosq_ = nullptr;
        mosquitto_lib_cleanup();
        return false;
    }

    started_ = true;
    ChipLogProgress(AppServer, "%s: connected to %s:%d", kLogModule, host_.c_str(), port_);

    if (!SubscribeTopics()) {
        Stop();
        return false;
    }

    const int loop_rc = mosquitto_loop_start(mosq_);
    if (loop_rc != MOSQ_ERR_SUCCESS) {
        ChipLogError(AppServer, "%s: MQTT loop start failed: %s", kLogModule, mosquitto_strerror(loop_rc));
        Stop();
        return false;
    }

    return true;
}

void MqttLightAdapter::Stop()
{
    if (mosq_ != nullptr) {
        mosquitto_loop_stop(mosq_, true);
        mosquitto_disconnect(mosq_);
        mosquitto_destroy(mosq_);
        mosq_ = nullptr;
    }

    if (started_) {
        mosquitto_lib_cleanup();
        started_ = false;
    }
}

bool MqttLightAdapter::SubscribeTopics()
{
    if (!started_ || mosq_ == nullptr) {
        ChipLogError(AppServer, "%s: subscribe requested before MQTT adapter started", kLogModule);
        return false;
    }

    constexpr int qos = 1;
    int rc = mosquitto_subscribe(mosq_, nullptr, state_topic_.c_str(), qos);
    if (rc != MOSQ_ERR_SUCCESS) {
        ChipLogError(AppServer, "%s: MQTT subscribe failed for %s: %s", kLogModule, state_topic_.c_str(), mosquitto_strerror(rc));
        return false;
    }

    ChipLogProgress(AppServer, "%s: subscribed to %s", kLogModule, state_topic_.c_str());

    rc = mosquitto_subscribe(mosq_, nullptr, availability_topic_.c_str(), qos);
    if (rc != MOSQ_ERR_SUCCESS) {
        ChipLogError(AppServer, "%s: MQTT subscribe failed for %s: %s", kLogModule, availability_topic_.c_str(),
                     mosquitto_strerror(rc));
        return false;
    }

    ChipLogProgress(AppServer, "%s: subscribed to %s", kLogModule, availability_topic_.c_str());
    return true;
}

bool MqttLightAdapter::PublishCommand(bool onoff)
{
    if (!started_ || mosq_ == nullptr) {
        ChipLogError(AppServer, "%s: publish requested before MQTT adapter started", kLogModule);
        return false;
    }

    const char * payload = onoff ? "{\"onoff\":true}" : "{\"onoff\":false}";
    constexpr int qos = 1;
    constexpr bool retain = false;

    const int rc = mosquitto_publish(mosq_, nullptr, command_topic_.c_str(),
                                     static_cast<int>(std::char_traits<char>::length(payload)),
                                     payload, qos, retain);
    if (rc != MOSQ_ERR_SUCCESS) {
        ChipLogError(AppServer, "%s: MQTT publish failed: %s", kLogModule, mosquitto_strerror(rc));
        return false;
    }

    ChipLogProgress(AppServer, "MQTT command published: %s %s", command_topic_.c_str(), payload);
    return true;
}

void MqttLightAdapter::SetStateCallback(StateCallback cb)
{
    state_cb_ = std::move(cb);
}

void MqttLightAdapter::SetAvailabilityCallback(AvailabilityCallback cb)
{
    availability_cb_ = std::move(cb);
}

void MqttLightAdapter::OnMessage(struct mosquitto* mosq, void* userdata, const struct mosquitto_message* msg)
{
    (void) mosq;
    auto* adapter = static_cast<MqttLightAdapter*>(userdata);
    if (adapter != nullptr) {
        adapter->HandleMessage(msg);
    }
}

void MqttLightAdapter::HandleMessage(const struct mosquitto_message* msg)
{
    if (msg == nullptr || msg->topic == nullptr || msg->payload == nullptr || msg->payloadlen <= 0) {
        ChipLogError(AppServer, "%s: invalid MQTT state message", kLogModule);
        return;
    }

    std::string payload(static_cast<const char*>(msg->payload), static_cast<size_t>(msg->payloadlen));

    if (availability_topic_ == msg->topic) {
        bool online = false;
        if (!ParseAvailabilityPayload(payload.c_str(), &online)) {
            ChipLogError(AppServer, "%s: invalid availability payload on %s: %s", kLogModule, availability_topic_.c_str(),
                         payload.c_str());
            return;
        }

        ChipLogProgress(AppServer, "MQTT availability received: %s", online ? "online" : "offline");
        if (availability_cb_) {
            availability_cb_(online);
        }
        return;
    }

    if (state_topic_ != msg->topic) {
        return;
    }

    bool onoff = false;
    if (!ParseOnOffPayload(payload.c_str(), &onoff)) {
        ChipLogError(AppServer, "%s: invalid state payload on %s: %s", kLogModule, state_topic_.c_str(), payload.c_str());
        return;
    }

    ChipLogProgress(AppServer, "MQTT state received: %s", onoff ? "ON" : "OFF");
    if (state_cb_) {
        state_cb_(onoff);
    }
}

bool MqttLightAdapter::ParseOnOffPayload(const char* payload, bool* onoff) const
{
    if (payload == nullptr || onoff == nullptr) {
        return false;
    }

    if (std::strstr(payload, "\"onoff\":true") != nullptr ||
        std::strstr(payload, "\"onoff\" : true") != nullptr) {
        *onoff = true;
        return true;
    }

    if (std::strstr(payload, "\"onoff\":false") != nullptr ||
        std::strstr(payload, "\"onoff\" : false") != nullptr) {
        *onoff = false;
        return true;
    }

    return false;
}

bool MqttLightAdapter::ParseAvailabilityPayload(const char* payload, bool* online) const
{
    if (payload == nullptr || online == nullptr) {
        return false;
    }

    if (std::strcmp(payload, "online") == 0) {
        *online = true;
        return true;
    }

    if (std::strcmp(payload, "offline") == 0) {
        *online = false;
        return true;
    }

    return false;
}