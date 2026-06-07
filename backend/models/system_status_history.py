"""SQLAlchemy model for compact operational system status history."""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
from postgres_db import Base


class SystemStatusSnapshot(Base):
    """Stores throttled `/api/system/status` snapshots for recent operations history."""

    __tablename__ = "system_status_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    cpu = Column(Float, nullable=True)
    ram = Column(Float, nullable=True)
    disk = Column(Float, nullable=True)

    disk_io_supported = Column(Boolean, default=False, nullable=False)
    disk_read_bytes_per_sec = Column(Float, nullable=True)
    disk_write_bytes_per_sec = Column(Float, nullable=True)
    disk_busy_percentage = Column(Float, nullable=True)

    neo4j_status = Column(String, nullable=True)
    postgres_status = Column(String, nullable=True)
    collector_status = Column(String, nullable=True)
    collector_cis_monitored = Column(Integer, nullable=True)
    collector_metrics_collected = Column(Integer, nullable=True)
    collector_metrics_failed = Column(Integer, nullable=True)
    collector_jobs_per_min = Column(Float, nullable=True)
    collector_cycle_duration = Column(Float, nullable=True)
