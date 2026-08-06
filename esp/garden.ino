#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <WiFiManager.h>
#include <PubSubClient.h>
#include <time.h>

#define LEAK_PIN   A0
#define PUMP_PIN   D2
#define LIGHT_PIN  D5
#define LEAK_THR   300
#define PUMP_TO    10000

const char* MQTT_HOST = "YOUR_SERVER_IP";
const int   MQTT_PORT = 1883;

WiFiClient espClient;
PubSubClient mqtt(espClient);

unsigned long lastPub = 0;
bool leak = false;
bool ntpOk = false;

struct RelayCfg {
  uint8_t mode;      // 0=off 1=schedule(start+duration) 2=countdown 3=cycle
  uint8_t hOn, mOn, hOff, mOff;
  uint32_t countSec;
  uint32_t cycleOnSec, cycleOffSec;
};

struct RelayState {
  uint8_t pin;
  bool active;       // физически включено
  bool manualOn;     // ручное управление (приоритет)
  uint32_t tStart;   // millis() последнего включения
  uint32_t tNext;    // millis() следующего переключения
  int onDay;         // день месяца последнего авто-старта (для расписания)
};

RelayCfg cfgPump = {0, 0, 0, 0, 0, 0, 0, 0};
RelayCfg cfgLight = {0, 0, 0, 0, 0, 0, 0, 0};
RelayState pump = {PUMP_PIN, false, false, 0, 0, 0};
RelayState light = {LIGHT_PIN, false, false, 0, 0, 0};

void setRelay(RelayState& rs, bool on) {
  rs.active = on;
  if (on) {
    pinMode(rs.pin, OUTPUT);
    digitalWrite(rs.pin, LOW);
    rs.tStart = millis();
  } else {
    pinMode(rs.pin, INPUT);
  }
}

void relayOn(int pin) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
}

void relayOff(int pin) {
  pinMode(pin, INPUT);
}

long jsonGetInt(const char* s, const char* key) {
  char pat[24];
  snprintf(pat, sizeof(pat), "\"%s\":", key);
  const char* p = strstr(s, pat);
  if (!p) return -1;
  p += strlen(pat);
  while (*p == ' ') p++;
  return atol(p);
}

void applyCfg(bool isPump, const char* payload) {
  RelayState& rs = isPump ? pump : light;
  RelayCfg& cfg = isPump ? cfgPump : cfgLight;
  cfg.mode = jsonGetInt(payload, "mode");
  cfg.hOn = jsonGetInt(payload, "hOn");
  cfg.mOn = jsonGetInt(payload, "mOn");
  cfg.hOff = jsonGetInt(payload, "hOff");
  cfg.mOff = jsonGetInt(payload, "mOff");
  cfg.countSec = jsonGetInt(payload, "countSec");
  cfg.cycleOnSec = jsonGetInt(payload, "cycleOnSec");
  cfg.cycleOffSec = jsonGetInt(payload, "cycleOffSec");
  rs.manualOn = false;
  if (cfg.mode == 0) {
    setRelay(rs, false);
  } else if (cfg.mode == 2) {
    setRelay(rs, true);
  } else if (cfg.mode == 3) {
    setRelay(rs, true);
  }
  Serial.printf("CFG %s mode=%d\n", isPump ? "pump" : "light", cfg.mode);
}

void timerTick(RelayState& rs, const RelayCfg& cfg) {
  if (rs.manualOn) return;
  if (rs.pin == PUMP_PIN && leak) {
    if (rs.active) setRelay(rs, false);
    return;
  }
  if (cfg.mode == 0) {
    if (rs.active) setRelay(rs, false);
    return;
  }
  if (cfg.mode == 1) {
    if (!ntpOk) return;
    time_t now = time(nullptr);
    struct tm* t = localtime(&now);
    int cur = t->tm_hour * 60 + t->tm_min;
    int start = cfg.hOn * 60 + cfg.mOn;
    uint32_t durMs = (uint32_t)cfg.countSec * 1000UL;
    if (durMs == 0) {
      if (rs.active) setRelay(rs, false);
      return;
    }
    if (!rs.active) {
      if (cur >= start && rs.onDay != t->tm_mday) {
        setRelay(rs, true);
        rs.onDay = t->tm_mday;
      }
    } else {
      if (millis() - rs.tStart >= durMs) {
        setRelay(rs, false);
      }
    }
    return;
  }
  if (cfg.mode == 2) {
    if (rs.active && cfg.countSec > 0 &&
        millis() - rs.tStart >= (uint32_t)cfg.countSec * 1000UL) {
      setRelay(rs, false);
    }
    return;
  }
  if (cfg.mode == 3) {
    uint32_t onMs = (uint32_t)cfg.cycleOnSec * 1000UL;
    uint32_t offMs = (uint32_t)cfg.cycleOffSec * 1000UL;
    if (onMs == 0 || offMs == 0) return;
    if (rs.active && millis() - rs.tStart >= onMs) {
      setRelay(rs, false);
      rs.tNext = millis();
    } else if (!rs.active && millis() - rs.tNext >= offMs) {
      setRelay(rs, true);
    }
    return;
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("\nBOOT");
  relayOff(PUMP_PIN);
  relayOff(LIGHT_PIN);

  WiFi.begin("YOUR_WIFI_SSID", "YOUR_WIFI_PASSWORD");
  for (int i = 0; i < 20; i++) {
    if (WiFi.status() == WL_CONNECTED) break;
    delay(500);
  }
  if (WiFi.status() != WL_CONNECTED) {
    WiFiManager wm;
    wm.setConfigPortalBlocking(true);
    Serial.println("Starting AP...");
    if (!wm.autoConnect("Garden-Config")) {
      Serial.println("WiFi FAIL");
      return;
    }
  }
  Serial.printf("WiFi OK %s\n", WiFi.localIP().toString().c_str());

  configTime(4 * 3600, 0, "pool.ntp.org", "time.nist.gov");

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(callback);
  connectMQTT();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(1000);
    return;
  }
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  timerTick(pump, cfgPump);
  timerTick(light, cfgLight);
  pumpTimeoutCheck();

  if (!ntpOk && time(nullptr) > 100000) {
    ntpOk = true;
    Serial.println("NTP OK");
  }

  if (millis() - lastPub > 5000) {
    lastPub = millis();
    leakCheck();
    char buf[120];
    snprintf(buf, sizeof(buf),
      R"({"leak_raw":%d,"leak":%d,"pump":%d,"light":%d,"rssi":%d,"ssid":"%s"})",
      analogRead(LEAK_PIN), leak ? 1 : 0,
      pump.active ? 1 : 0, light.active ? 1 : 0,
      WiFi.RSSI(), WiFi.SSID().c_str());
    mqtt.publish("garden/tele/sensor", buf);
  }
}

void connectMQTT() {
  while (!mqtt.connected()) {
    if (mqtt.connect("garden-esp1")) {
      mqtt.loop();
      mqtt.subscribe("garden/cmd/pump");
      mqtt.loop();
      mqtt.subscribe("garden/cmd/light");
      mqtt.loop();
      mqtt.subscribe("garden/cmd/cfg");
      mqtt.loop();
      mqtt.publish("garden/tele/status", "online");
      mqtt.loop();
    } else {
      delay(3000);
    }
  }
}

void callback(char* topic, byte* payload, unsigned int len) {
  char msg[len + 1];
  memcpy(msg, payload, len);
  msg[len] = 0;

  if (strcmp(topic, "garden/cmd/pump") == 0) {
    if (msg[0] == '1' && !leak) {
      pump.manualOn = true;
      setRelay(pump, true);
    } else if (msg[0] == '0') {
      pump.manualOn = false;
      setRelay(pump, false);
    }
  } else if (strcmp(topic, "garden/cmd/light") == 0) {
    if (msg[0] == '1') {
      light.manualOn = true;
      setRelay(light, true);
    } else {
      light.manualOn = false;
      setRelay(light, false);
    }
  } else if (strcmp(topic, "garden/cmd/cfg") == 0) {
    applyCfg(strstr(msg, "\"relay\":\"pump\"") != NULL, msg);
  }
}

void leakCheck() {
  bool now = analogRead(LEAK_PIN) > LEAK_THR;
  if (now != leak) {
    leak = now;
    if (leak) {
      pump.manualOn = false;
      setRelay(pump, false);
    }
  }
}
void pumpTimeoutCheck() {
  if (pump.active && pump.manualOn && millis() - pump.tStart > PUMP_TO) {
    pump.manualOn = false;
    setRelay(pump, false);
  }
}
