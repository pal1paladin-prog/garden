import json
import logging
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database import init_db, get_session, async_session
from models import SensorLog, WateringEvent, RelayConfig, Config, EventLog
from mqtt_client import mqtt_client
from config import PUMP_DEFAULT_TIMEOUT

VALID_RELAYS = ("pump", "light")
VALID_MODES = (0, 1, 2, 3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    mqtt_client.start()
    mqtt_client.on("garden/tele/sensor", on_sensor_data)
    mqtt_client.on("garden/tele/leak", on_leak_data)
    mqtt_client.on("garden/tele/status", on_esp_status)
    await ensure_relay_configs()
    async with async_session() as session:
        await sync_all_configs_to_esp(session)
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


async def ensure_relay_configs():
    """Create default rows for pump/light if missing (idempotent)."""
    async with async_session() as session:
        for relay in VALID_RELAYS:
            existing = await session.execute(
                select(RelayConfig).where(RelayConfig.relay == relay)
            )
            if not existing.scalar_one_or_none():
                session.add(RelayConfig(relay=relay, mode=0))
        await session.commit()


async def sync_all_configs_to_esp(session: AsyncSession):
    result = await session.execute(select(RelayConfig))
    configs = result.scalars().all()
    mqtt_client.cmd_sync_all(configs)


async def on_sensor_data(topic: str, payload: str):
    try:
        data = json.loads(payload)
        async with async_session() as session:
            prev_result = await session.execute(
                select(SensorLog).order_by(desc(SensorLog.id)).limit(1)
            )
            prev = prev_result.scalar_one_or_none()

            log = SensorLog(
                leak_raw=data.get("leak_raw"),
                leak=data.get("leak"),
                pump=data.get("pump"),
                light=data.get("light"),
                rssi=data.get("rssi"),
                ssid=data.get("ssid")
            )
            session.add(log)
            await session.flush()

            if prev:
                new_pump = bool(data.get("pump"))
                new_light = bool(data.get("light"))
                new_leak = bool(data.get("leak"))

                if prev.pump != new_pump:
                    session.add(EventLog(
                        event_type="relay",
                        source="pump",
                        message="Насос ВКЛ" if new_pump else "Насос ВЫКЛ"
                    ))
                if prev.light != new_light:
                    session.add(EventLog(
                        event_type="relay",
                        source="light",
                        message="Свет ВКЛ" if new_light else "Свет ВЫКЛ"
                    ))
                if prev.leak != new_leak:
                    session.add(EventLog(
                        event_type="leak",
                        source="leak_sensor",
                        message="ПРОТЕЧКА!" if new_leak else "Протечка устранена"
                    ))

            await session.commit()
    except Exception as e:
        print(f"MQTT sensor error: {e}")


async def on_leak_data(topic: str, payload: str):
    if payload == "1":
        pass


async def on_esp_status(topic: str, payload: str):
    """When the ESP (re)connects, re-sync all relay configs to it."""
    if payload.strip().lower() == "online":
        async with async_session() as session:
            await sync_all_configs_to_esp(session)


class PumpControl(BaseModel):
    state: int


class LightControl(BaseModel):
    state: int


class RelayConfigUpdate(BaseModel):
    relay: str
    mode: int = 0
    h_on: int = 0
    m_on: int = 0
    h_off: int = 0
    m_off: int = 0
    count_sec: int = 0
    cycle_on_sec: int = 0
    cycle_off_sec: int = 0


class ConfigUpdate(BaseModel):
    leak_threshold: int | None = None


@app.get("/api/status")
async def get_status(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(SensorLog).order_by(desc(SensorLog.id)).limit(1)
    )
    latest = result.scalar_one_or_none()
    cfg = await session.get(Config, 1)
    esp_online = False
    if latest and latest.created_at:
        esp_online = (datetime.utcnow() - latest.created_at) < timedelta(seconds=15)
    return {
        "server_time": datetime.now().isoformat(timespec="seconds"),
        "esp_online": esp_online,
        "sensor": {
            "leak_raw": latest.leak_raw if latest else None,
            "leak": latest.leak if latest else None,
            "pump": latest.pump if latest else None,
            "light": latest.light if latest else None,
            "rssi": latest.rssi if latest else None,
            "ssid": latest.ssid if latest else None,
            "updated": latest.created_at.isoformat() if latest else None
        } if latest else None,
        "config": {
            "leak_threshold": cfg.leak_threshold if cfg else 512
        }
    }


@app.get("/api/logs")
async def get_logs(limit: int = 100, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(SensorLog).order_by(desc(SensorLog.id)).limit(limit)
    )
    return result.scalars().all()


@app.get("/api/events")
async def get_events(limit: int = 50, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(EventLog).order_by(desc(EventLog.id)).limit(limit)
    )
    events = result.scalars().all()
    return [{
        "id": e.id,
        "event_type": e.event_type,
        "source": e.source,
        "message": e.message,
        "created_at": e.created_at.isoformat() if e.created_at else None
    } for e in events]


@app.get("/api/waterings")
async def get_waterings(limit: int = 50, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(WateringEvent).order_by(desc(WateringEvent.id)).limit(limit)
    )
    return result.scalars().all()


@app.post("/api/pump")
async def control_pump(ctrl: PumpControl, session: AsyncSession = Depends(get_session)):
    mqtt_client.cmd_pump(ctrl.state)
    return {"status": "ok"}


@app.post("/api/light")
async def control_light(ctrl: LightControl, session: AsyncSession = Depends(get_session)):
    mqtt_client.cmd_light(ctrl.state)
    return {"status": "ok"}


@app.get("/api/relay_configs")
async def get_relay_configs(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(RelayConfig))
    return result.scalars().all()


@app.put("/api/relay_configs")
async def update_relay_config(update: RelayConfigUpdate, session: AsyncSession = Depends(get_session)):
    if update.relay not in VALID_RELAYS:
        raise HTTPException(400, "Invalid relay (must be 'pump' or 'light')")
    if update.mode not in VALID_MODES:
        raise HTTPException(400, "Invalid mode (0=off, 1=schedule, 2=countdown, 3=cycle)")

    result = await session.execute(
        select(RelayConfig).where(RelayConfig.relay == update.relay)
    )
    rcfg = result.scalar_one_or_none()
    if not rcfg:
        rcfg = RelayConfig(relay=update.relay)
        session.add(rcfg)

    rcfg.mode = update.mode
    rcfg.h_on = update.h_on
    rcfg.m_on = update.m_on
    rcfg.h_off = update.h_off
    rcfg.m_off = update.m_off
    rcfg.count_sec = update.count_sec
    rcfg.cycle_on_sec = update.cycle_on_sec
    rcfg.cycle_off_sec = update.cycle_off_sec

    await session.commit()
    await session.refresh(rcfg)

    mqtt_client.cmd_relay_cfg(rcfg)
    return rcfg


@app.put("/api/config")
async def update_config(cfg: ConfigUpdate, session: AsyncSession = Depends(get_session)):
    db_cfg = await session.get(Config, 1)
    if not db_cfg:
        db_cfg = Config(id=1)
        session.add(db_cfg)
    if cfg.leak_threshold is not None:
        db_cfg.leak_threshold = cfg.leak_threshold
    await session.commit()
    mqtt_client.cmd_config({
        "leak_thr": db_cfg.leak_threshold
    })
    return db_cfg


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
