import json
import asyncio
import logging
import paho.mqtt.client as mqtt
from config import MQTT_BROKER, MQTT_PORT, MQTT_TOPIC_PREFIX

logger = logging.getLogger("mqtt")

MODE_NAMES = {0: "off", 1: "range", 2: "countdown", 3: "cycle"}


class MQTTClient:
    def __init__(self):
        self.client = mqtt.Client(client_id="garden-server")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.callbacks = {}
        self._loop = None

    def start(self):
        self._loop = asyncio.get_running_loop()
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            self.client.loop_start()
            logger.info(f"MQTT connected to {MQTT_BROKER}:{MQTT_PORT}")
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        logger.info(f"MQTT connected (rc={rc})")
        client.subscribe(f"{MQTT_TOPIC_PREFIX}/tele/#")

    def _on_disconnect(self, client, userdata, rc):
        logger.warning(f"MQTT disconnected (rc={rc})")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode()
        for pattern, cb in self.callbacks.items():
            if pattern in topic:
                try:
                    if self._loop and self._loop.is_running():
                        self._loop.call_soon_threadsafe(asyncio.create_task, cb(topic, payload))
                except Exception as e:
                    logger.error(f"MQTT callback error: {e}")

    def on(self, topic_pattern, callback):
        self.callbacks[topic_pattern] = callback

    def publish(self, topic, payload):
        self.client.publish(f"{MQTT_TOPIC_PREFIX}/{topic}", payload)

    def cmd_pump(self, state: int):
        self.publish("cmd/pump", str(state))

    def cmd_light(self, state: int):
        self.publish("cmd/light", str(state))

    def cmd_config(self, config: dict):
        self.publish("cmd/config", json.dumps(config))

    def cmd_relay_cfg(self, rcfg):
        """Sync one relay config to ESP via garden/cmd/cfg.

        rcfg is a RelayConfig ORM row.
        """
        payload = json.dumps({
            "relay": rcfg.relay,
            "mode": rcfg.mode,
            "hOn": rcfg.h_on, "mOn": rcfg.m_on,
            "hOff": rcfg.h_off, "mOff": rcfg.m_off,
            "countSec": rcfg.count_sec,
            "cycleOnSec": rcfg.cycle_on_sec,
            "cycleOffSec": rcfg.cycle_off_sec,
        }, separators=(',', ':'))
        self.publish("cmd/cfg", payload)

    def cmd_sync_all(self, configs):
        """Sync all relay configs at startup (publish one cmd/cfg per relay)."""
        for rcfg in configs:
            self.cmd_relay_cfg(rcfg)


mqtt_client = MQTTClient()
