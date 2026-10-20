# Playwright's official image ships Chromium + all system deps; we only add
# the Lambda Runtime Interface Client. Build context is the repo root.
FROM mcr.microsoft.com/playwright/python:v1.64.0-noble

RUN pip install --no-cache-dir --break-system-packages awslambdaric boto3 playwright==1.64.0

# Lambda's filesystem is read-only except /tmp.
ENV HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /var/task
COPY screenshot/ screenshot/

ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["screenshot.handler.lambda_handler"]
