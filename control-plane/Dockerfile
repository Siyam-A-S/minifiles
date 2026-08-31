FROM python:3.12-slim AS base
WORKDIR /srv
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY app ./app
EXPOSE 8000
USER nobody
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
