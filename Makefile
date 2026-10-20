AWS_PROFILE ?= Mikkel
export AWS_PROFILE
TF = terraform -chdir=infra
# Runtime deps for the Lambda zip (boto3 is provided by the Lambda runtime).
LAMBDA_DEPS = beautifulsoup4 fastapi mangum

.PHONY: test dev build init plan apply rebuild scrape logs

test:
	uv run pytest -q

# Local site + API on http://localhost:8000 with simulated data (no AWS, no Docker).
dev:
	uv run python -m tools.dev

# One zip for both Lambdas: arm64 wheels via uv (no Docker), reproducible bytes.
build:
	rm -rf build && mkdir -p build/lambda
	uv pip install --quiet --target build/lambda --python-platform aarch64-manylinux2014 \
		--python-version 3.12 --only-binary=:all: $(LAMBDA_DEPS)
	rsync -a --exclude __pycache__ src/elevator_tracker build/lambda/
	find build/lambda -name __pycache__ -prune -exec rm -rf {} +
	find build/lambda -exec touch -t 202001010000 {} +
	cd build/lambda && find . -type f | LC_ALL=C sort | zip -qX ../lambda.zip -@
	@du -h build/lambda.zip

# First time only: `terraform -chdir=infra/bootstrap init && ... apply` (state bucket).
init:
	$(TF) init -backend-config=backend.hcl

# Always apply exactly the plan you reviewed.
plan: build
	$(TF) plan -out=tfplan

apply:
	$(TF) apply tfplan

# Wipe the table and replay our own raw snapshots from S3 (after parsing changes).
rebuild:
	TABLE_NAME=$$($(TF) output -raw table_name) RAW_BUCKET=$$($(TF) output -raw raw_bucket) \
		uv run python -m tools.rebuild --yes

scrape:
	aws lambda invoke --function-name $$($(TF) output -raw scraper_function) --cli-read-timeout 180 /dev/stdout

logs:
	aws logs tail /aws/lambda/dsb-elevator-tracker-scraper --follow
