# Slim image: Python + Chromium headless shell only (no Firefox/WebKit),
# plus the Lambda Runtime Interface Client. Build context: screenshot/.
FROM python:3.12-slim-bookworm

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp
RUN pip install --no-cache-dir awslambdaric boto3 playwright==1.64.0 \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/* /root/.cache

WORKDIR /var/task
COPY handler.py .

ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["handler.handler"]
