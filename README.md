sudo systemctl start mosquitto

# Start Matter Server
sudo docker start matter-server
sudo docker start homeassistant

rm -f /tmp/chip_kvs /tmp/chip_factory.ini /tmp/chip_config.ini /tmp/chip_counters.ini
cd ~/connectedhomeip
./out/linux-x64-light/chip-lighting-app \
  --vendor-id 0xFFF1 \
  --product-id 0x8000 \
  --discriminator 3840 \
  --passcode 20202021

34970112332


cd ~/mqtt-matter-bridge
rm -rf build
cmake -B build
cmake --build build 2>&1 | tail -20