from sqlalchemy import Column, String, Float, DateTime, Integer, Index, text
from postgres_db import Base

class MetricValue(Base):
    __tablename__ = "metric_values"

    time = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    node_id = Column(String, primary_key=True, nullable=False)
    metric_id = Column(String, primary_key=True, nullable=False)
    value = Column(Float, nullable=False)
    
    # Optional: stored metadata snapshot? 
    # For now, keep it simple.
    
    # TimescaleDB requires the time column to be part of the primary key if there is one.
    # We will use a composite PK (time, node_id, metric_id).

    __table_args__ = (
        Index('idx_metric_values_node_time', 'node_id', 'time'),
    )
