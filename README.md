# Garden — умный полив и свет на ESP8266

Система автоматического полива и управления светом на базе **ESP8266** + **MQTT** + **FastAPI** + веб-панели.

## Состав

```
esp/garden.ino            Прошивка ESP8266 (PlatformIO, board d1_mini)
backend/                  Backend FastAPI + MQTT-мост + SQLAlchemy
web/index.html            Веб-панель (SPA, без сборки)
```

## Возможности

- Управление насосом и светом вручную из веб-панели
- 4 режима работы реле:
  - **0** — выключено
  - **1** — время старта + длительность (полив раз в день)
  - **2** — обратный отсчёт (включить и отключить через N минут)
  - **3** — цикличный таймер (вкл X сек / выкл Y сек)
- Датчик протечки (аналоговый вход A0) — аварийное отключение насоса
- Телеметрия каждые 5 сек: состояние реле, RSSI, SSID
- Журнал событий и показаний

## Установка

### 1. Backend (Python 3.10+)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # при необходимости задать MQTT_BROKER и DATABASE_URL
uvicorn main:app --host 0.0.0.0 --port 8000
```

По умолчанию используется SQLite (`garden.db`), для PostgreSQL задайте в `.env`:

```
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
```

### 2. MQTT-брокер

Установите Mosquitto:

```bash
sudo apt install mosquitto
```

Безопаснее задать пароль на брокере; для локальной сети допустим `allow_anonymous true`.

### 3. Веб-панель

Положите `web/index.html` в любой статический веб-сервер и проксируйте `/garden/api/` на бэкенд `127.0.0.1:8000/api/`. Пример для nginx:

```nginx
location /garden/ {
    alias /path/to/web/;
    index index.html;
}
location /garden/api/ {
    proxy_pass http://127.0.0.1:8000/api/;
}
```

### 4. Прошивка ESP8266

Откройте `esp/garden.ino` в PlatformIO (board `d1_mini`, зависимости `PubSubClient`, `WiFiManager`) или Arduino IDE. Замените константы:

```cpp
const char* MQTT_HOST = "192.168.1.10";   // IP вашего сервера с бэкендом
WiFi.begin("YOUR_WIFI_SSID", "YOUR_WIFI_PASSWORD");
```

Подключение реле: `D2` — насос, `D5` — свет (активный уровень LOW). Датчик протечки — `A0` (порог `LEAK_THR`, по умолчанию 300).

## Схема MQTT

| Топик | Направление | Назначение |
|---|---|---|
| `garden/tele/sensor` | ESP → сервер | телеметрия (реле, RSSI, SSID) |
| `garden/tele/status` | ESP → сервер | `online` при подключении |
| `garden/cmd/pump` | сервер → ESP | 1/0 — управление насосом |
| `garden/cmd/light` | сервер → ESP | 1/0 — управление светом |
| `garden/cmd/cfg` | сервер → ESP | конфиг режима реле (JSON) |

## Лицензия

MIT
