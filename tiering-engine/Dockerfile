FROM python:3.12-slim AS base
WORKDIR /srv
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY app ./app
USER nobody
ENTRYPOINT ["python", "-m", "app.main"]
