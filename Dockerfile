FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY . .
COPY docker-entrypoint.py /usr/local/bin/firefly-parser-entrypoint.py

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app \
    && mkdir -p workdir logs downloads \
    && chown -R app:app /app

# Bind mounts replace the directories prepared above. The entrypoint fixes
# their ownership at runtime and drops privileges before executing the bot.
ENTRYPOINT ["python", "/usr/local/bin/firefly-parser-entrypoint.py"]

CMD ["python", "-m", "app"]
