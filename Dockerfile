FROM python:3.13-slim

COPY . /app/
WORKDIR /app/

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates bash ffmpeg git zip build-essential python3-dev libssl-dev libffi-dev pkg-config \
    && pip3 install --no-cache-dir -U -r requirements.txt \
    && apt-get remove -y --purge build-essential python3-dev libssl-dev libffi-dev pkg-config \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

CMD ["bash", "start"]
