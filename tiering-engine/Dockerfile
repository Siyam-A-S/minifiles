FROM python:3.12-slim AS base
WORKDIR /srv
COPY pyproject.toml .
# the in-cluster image always ships the azure target
RUN pip install --no-cache-dir '.[azure]'
COPY app ./app
USER nobody
ENTRYPOINT ["python", "-m", "app.main"]
