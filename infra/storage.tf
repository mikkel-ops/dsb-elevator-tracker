# Storage: DynamoDB table, raw-archive bucket, website bucket (+ its files).

# Provisioned capacity on purpose: DynamoDB's always-free tier covers
# 25 RCU / 25 WCU of *provisioned* capacity, not on-demand requests.
# Table + 1 GSI at 5/5 each = 10/10.
resource "aws_dynamodb_table" "main" {
  name                        = var.name
  billing_mode                = "PROVISIONED"
  read_capacity               = 5
  write_capacity              = 5
  hash_key                    = "PK"
  range_key                   = "SK"
  deletion_protection_enabled = true

  dynamic "attribute" {
    for_each = ["PK", "SK", "GSI1PK", "GSI1SK"]
    content {
      name = attribute.value
      type = "S"
    }
  }

  # GSI1: incidents per station.
  dynamic "global_secondary_index" {
    for_each = ["GSI1"]
    content {
      name            = global_secondary_index.value
      projection_type = "ALL"
      read_capacity   = 5
      write_capacity  = 5

      key_schema {
        attribute_name = "${global_secondary_index.value}PK"
        key_type       = "HASH"
      }
      key_schema {
        attribute_name = "${global_secondary_index.value}SK"
        key_type       = "RANGE"
      }
    }
  }
}

resource "aws_s3_bucket" "raw" {
  bucket = "${var.name}-raw-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "site" {
  bucket = "${var.name}-site-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each                = { raw = aws_s3_bucket.raw.id, site = aws_s3_bucket.site.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "site" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

data "aws_iam_policy_document" "raw" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/*", "${aws_s3_bucket.raw.arn}/screenshots/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "raw" {
  bucket = aws_s3_bucket.raw.id
  policy = data.aws_iam_policy_document.raw.json
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site.json
}

# Static site files, uploaded by Terraform so `terraform apply` is the whole deploy.
locals {
  site_dir      = "${path.module}/../site"
  stations_json = "${path.module}/../src/elevator_tracker/stations.json"
  mime = {
    html = "text/html; charset=utf-8"
    js   = "application/javascript; charset=utf-8"
    css  = "text/css; charset=utf-8"
    json = "application/json; charset=utf-8"
    svg  = "image/svg+xml"
    png  = "image/png"
    ico  = "image/x-icon"
  }
}

resource "aws_s3_object" "site" {
  for_each      = fileset(local.site_dir, "**")
  bucket        = aws_s3_bucket.site.id
  key           = each.value
  source        = "${local.site_dir}/${each.value}"
  etag          = filemd5("${local.site_dir}/${each.value}")
  content_type  = lookup(local.mime, reverse(split(".", each.value))[0], "application/octet-stream")
  cache_control = endswith(each.value, ".html") ? "public, max-age=60" : "public, max-age=3600"
}

# Station coordinates for the map - same file the scraper uses for matching.
resource "aws_s3_object" "stations" {
  bucket        = aws_s3_bucket.site.id
  key           = "data/stations.json"
  source        = local.stations_json
  etag          = filemd5(local.stations_json)
  content_type  = "application/json; charset=utf-8"
  cache_control = "public, max-age=86400"
}

# stations.json used to be part of the site/ fileset; same S3 key, so move
# rather than delete + create (which could race and delete the new object).
moved {
  from = aws_s3_object.site["data/stations.json"]
  to   = aws_s3_object.stations
}
