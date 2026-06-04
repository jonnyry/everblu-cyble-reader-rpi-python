FROM mcr.microsoft.com/devcontainers/python:3.11

RUN groupadd -f spi && groupadd -f gpio

RUN printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/raspi-config \
    && chmod +x /usr/local/bin/raspi-config

RUN pip install --no-cache-dir \
    pytest \
    ruff \
    spidev \
    lgpio

WORKDIR /workspace