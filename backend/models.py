from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from database import Base

class SensorLog(Base):
    __tablename__ = "sensor_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    leak_raw = Column(Integer)
    leak = Column(Boolean, default=False)
    pump = Column(Boolean, default=False)
    light = Column(Boolean, default=False)
    rssi = Column(Integer, nullable=True)
    ssid = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class WateringEvent(Base):
    __tablename__ = "watering_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    duration = Column(Integer)
    source = Column(String(32))
    created_at = Column(DateTime, default=datetime.utcnow)

class RelayConfig(Base):
    """Один режим на реле: off / schedule(start+duration) / countdown / cycle."""
    __tablename__ = "relay_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    relay = Column(String(8), unique=True, nullable=False)
    mode = Column(Integer, default=0)
    h_on = Column(Integer, default=0)
    m_on = Column(Integer, default=0)
    h_off = Column(Integer, default=0)
    m_off = Column(Integer, default=0)
    count_sec = Column(Integer, default=0)
    cycle_on_sec = Column(Integer, default=0)
    cycle_off_sec = Column(Integer, default=0)

class Config(Base):
    __tablename__ = "config"
    id = Column(Integer, primary_key=True, default=1)
    leak_threshold = Column(Integer, default=512)

class EventLog(Base):
    __tablename__ = "event_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(16))
    source = Column(String(16))
    message = Column(String(128))
    created_at = Column(DateTime, default=datetime.utcnow)
