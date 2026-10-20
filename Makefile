AWS_PROFILE ?= Mikkel
export AWS_PROFILE
TF = terraform -chdir=infra

.PHONY: test build bootstrap init plan apply backfill scrape logs dev

test:
	uv run pytest -q

build:
	./scripts/build.sh

# One-time: S3 bucket for Terraform state (writes infra/backend.hcl).
bootstrap:
	terraform -chdir=infra/bootstrap init
	terraform -chdir=infra/bootstrap apply

init:
	$(TF) init -backend-config=backend.hcl

plan: build
	$(TF) plan

apply: build
	$(TF) apply

# One-time, right after the first apply and before the first hourly run.
backfill:
	TABLE_NAME=$$($(TF) output -raw table_name) RAW_BUCKET=$$($(TF) output -raw raw_bucket) \
		uv run python -m tools.backfill_wayback

# Trigger a scrape now instead of waiting for the schedule.
scrape:
	aws lambda invoke --function-name $$($(TF) output -raw scraper_function) /dev/stdout

logs:
	aws logs tail /aws/lambda/dsb-elevator-tracker-scraper --follow

# Local: DynamoDB Local + API on :8000 + site on :8080 (see tools/dev_local.py)
dev:
	docker start ddb-local 2>/dev/null || docker run -d --rm -p 8001:8000 --name ddb-local amazon/dynamodb-local
	uv run python -m tools.dev_local --demo
	@echo "Run in two terminals:"
	@echo "  LOCAL_CORS=1 AWS_ENDPOINT_URL_DYNAMODB=http://localhost:8001 AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=eu-north-1 TABLE_NAME=dsb-elevator-tracker uv run uvicorn api.app:app --port 8000"
	@echo "  python3 -m http.server 8080 -d site"
