FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates bash ffmpeg git zip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY . /app/
WORKDIR /app/
RUN pip3 install --no-cache-dir -U -r requirements.txt

CMD bash start
