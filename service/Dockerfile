FROM python:3.13-alpine
WORKDIR /app
COPY server.py /app/server.py
RUN mkdir -p /data && chown -R nobody:nogroup /data /app
USER nobody
ENV DATABASE_PATH=/data/night-city.db PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=3s --start-period=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["python", "/app/server.py"]
