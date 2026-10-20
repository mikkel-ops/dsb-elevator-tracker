# Provisioned capacity on purpose: DynamoDB's always-free tier covers
# 25 RCU / 25 WCU of *provisioned* capacity, not on-demand requests.
# Table + 2 GSIs at 5/5 each = 15/15.
resource "aws_dynamodb_table" "main" {
  name                        = var.name
  billing_mode                = "PROVISIONED"
  read_capacity               = 5
  write_capacity              = 5
  hash_key                    = "PK"
  range_key                   = "SK"
  deletion_protection_enabled = true

  dynamic "attribute" {
    for_each = ["PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"]
    content {
      name = attribute.value
      type = "S"
    }
  }

  # GSI1: incidents per station. GSI2: incidents per year.
  dynamic "global_secondary_index" {
    for_each = ["GSI1", "GSI2"]
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
