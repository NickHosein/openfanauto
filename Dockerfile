# OpenFanAuto — single-container fan controller + automation + Web UI
FROM ubuntu:22.04

LABEL maintainer="openfanauto"
LABEL version="0.1.0"
LABEL description="OpenFanAuto — unified fan controller and temperature automation"

ARG DEBIAN_FRONTEND=noninteractive

# Install Python + smartmontools (for smartctl fallback)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        smartmontools \
    && rm -rf /var/lib/apt/lists/* && apt-get clean

# Copy source
COPY src/ /opt/openfanauto/src/
COPY config/ /opt/openfanauto/config/
COPY requirements.txt /opt/openfanauto/

# Install Python dependencies
RUN pip3 install --no-cache-dir -r /opt/openfanauto/requirements.txt

WORKDIR /opt/openfanauto/src

# Default config path (override via OPENFAN_CONFIG env var or mount to /config)
VOLUME /config
EXPOSE 3211

ENV MOCK_HARDWARE=false
ENV OPENFAN_POLL_INTERVAL=10
ENV OPENFAN_RELOAD_PROFILES=false
ENV OPENFAN_PORT=3211
ENV OPENFAN_CONFIG=/config/config.yaml
ENV OPENFAN_LOG_LEVEL=info

ENTRYPOINT ["python3", "main.py"]
