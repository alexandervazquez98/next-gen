from postgres_db import Base
from sqlalchemy import Column, DateTime, String
from sqlalchemy.sql import func


class MqttMetricSampleReceiptStatus(str):
    """Lifecycle states for mapping bridge idempotency writes."""

    PENDING_EVENT = "PENDING_EVENT"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class MqttMetricSampleReceipt(Base):
    """Idempotency ledger for MQTT->monitoring bridge writes.

    A unique row prevents duplicated Timescale writes + event retries across
    subscriber replays/restarts.
    """

    __tablename__ = "mqtt_metric_sample_receipts"

    idempotency_key = Column(String, primary_key=True)
    mapping_id = Column(String, nullable=False, index=True)
    source_device_id = Column(String, nullable=False)
    source_metric_id = Column(String, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    value_hash = Column(String, nullable=False)
    status = Column(String, nullable=False, default=MqttMetricSampleReceiptStatus.PENDING_EVENT)
    timescale_written_at = Column(DateTime(timezone=True), nullable=True)
    event_written_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )
