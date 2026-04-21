FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for networking and postgres
RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install backend dependencies (includes sqlalchemy, psycopg2)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install engine specific dependencies if any (merge or run separate)
COPY engines/requirements.txt requirements-engine.txt
RUN pip install --no-cache-dir -r requirements-engine.txt

# Copy Codebases
COPY backend /app/backend
COPY engines /app/engines

# Set Python Path to root to allow imports like 'from backend.postgres_db ...'
ENV PYTHONPATH=/app

CMD ["python", "-u", "engines/snmp_worker.py"]
