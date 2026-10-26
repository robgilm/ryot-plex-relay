FROM python:3.12-alpine
RUN adduser -D -u 10001 relay
WORKDIR /app
COPY relay.py .
USER relay
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import os, socket; socket.create_connection(('127.0.0.1', int(os.environ.get('LISTEN_PORT', '8080'))), 2)"
CMD ["python", "relay.py"]
