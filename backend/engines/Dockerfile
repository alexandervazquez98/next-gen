FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for networking and postgres
RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install backend dependencies (includes sqlalchemy, psycopg2)
COPY ../requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install engine specific dependencies
COPY requirements.txt requirements-engine.txt
RUN pip install --no-cache-dir -r requirements-engine.txt

# Copy Codebases
COPY ../ /app/backend
COPY . /app/engines

# Set Python Path to backend so 'from repositories ...' works
ENV PYTHONPATH=/app/backend

CMD ["python", "-u", "engines/snmp_worker.py"]
