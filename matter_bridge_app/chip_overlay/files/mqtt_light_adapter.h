#pragma once

#include <mosquitto.h>
#include <functional>
#include <string>

class MqttLightAdapter {
public:
    using StateCallback = std::function<void(bool onoff)>;

    MqttLightAdapter(const std::string& host,
                     int port,
                     const std::string& command_topic,
                     const std::string& state_topic);
    ~MqttLightAdapter();

    bool Start();
    void Stop();

    bool PublishCommand(bool onoff);
    void SetStateCallback(StateCallback cb);
    bool SubscribeStateTopic();

private:
    static void OnMessage(struct mosquitto* mosq, void* userdata, const struct mosquitto_message* msg);
    void HandleMessage(const struct mosquitto_message* msg);
    bool ParseOnOffPayload(const char* payload, bool* onoff) const;

    std::string host_;
    int port_;
    std::string command_topic_;
    std::string state_topic_;
    bool started_ = false;
    mosquitto* mosq_ = nullptr;
    StateCallback state_cb_;
};
