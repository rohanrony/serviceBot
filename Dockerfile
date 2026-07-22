FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if required (e.g. for build tools or libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy workspace files
COPY . .

# Set default port (GCP Cloud Run defaults to PORT 8080)
ENV PORT=8080

# Execute service catalog seeding on container startup, then launch Uvicorn server
CMD exec uvicorn serviceBot.main:app --host 0.0.0.0 --port $PORT
