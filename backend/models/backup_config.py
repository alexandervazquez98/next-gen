# backend/models/backup_config.py
"""SQLAlchemy models for backup system configuration and history."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from postgres_db import Base


class BackupConfig(Base):
    """Stores admin-configured backup schedule settings."""

    __tablename__ = "backup_config"

    id = Column(Integer, primary_key=True, index=True)
    # Schedule: "daily" or "manual"
    schedule_type = Column(String, default="daily", nullable=False)
    # For daily: HH:MM in 24h format (e.g., "06:00" for dawn)
    scheduled_time = Column(String, default="06:00", nullable=False)
    # Whether scheduled backups are enabled
    enabled = Column(Boolean, default=True, nullable=False)
    # Backup retention in days
    retention_days = Column(Integer, default=7, nullable=False)
    # Storage path for backups
    storage_path = Column(String, default="/backups", nullable=False)
    # Last modified by
    updated_by = Column(String, nullable=True)
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class BackupHistory(Base):
    """Stores history of completed backups."""

    __tablename__ = "backup_history"

    id = Column(Integer, primary_key=True, index=True)
    # Backup filename
    filename = Column(String, nullable=False)
    # Full path to the backup file
    file_path = Column(String, nullable=False)
    # Size in bytes
    size_bytes = Column(Integer, nullable=True)
    # Status: SUCCESS or FAILURE
    status = Column(String, nullable=False)
    # Error message if failure
    error_message = Column(Text, nullable=True)
    # Whether this was manual or scheduled
    backup_type = Column(String, default="scheduled", nullable=False)  # "scheduled" or "manual"
    # Who triggered (for manual backups)
    triggered_by = Column(String, nullable=True)
    # Duration in seconds
    duration_seconds = Column(Integer, nullable=True)
    # Timestamps
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)