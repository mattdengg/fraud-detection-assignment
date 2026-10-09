import json
import logging
import os
import time
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE = boto3.resource("dynamodb").Table(os.environ["FLAGGED_TABLE"])
SNS = boto3.client("sns")
TOPIC_ARN = os.environ["ALERT_TOPIC_ARN"]

REASON_TEXT = {
    "LARGE_WITHDRAWAL": "an unusually large withdrawal",
    "IMPOSSIBLE_TRAVEL": "activity from two distant locations in too short a time",
    "EXCESSIVE_FAILED_LOGINS": "several failed login attempts just before the transaction",
}


def handler(event: dict, context: object) -> dict:
    failures = []
    for record in event["Records"]:
        try:
            # parse_float=Decimal: DynamoDB rejects Python floats
            process(json.loads(record["body"], parse_float=Decimal))
        except Exception:
            logger.exception("Failed to process message %s", record["messageId"])
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def process(event: dict) -> None:
    txn = event["transaction"]
    txn_id = event["transaction_id"]

    item = {
        "transaction_id": txn_id,
        "account_id": txn["account_id"],
        "amount": Decimal(str(txn["amount"])),
        "transaction_type": txn["transaction_type"],
        "location": txn["location"],
        "transaction_timestamp": txn["timestamp"],
        "reasons": event["reasons"],
        "evaluated_at": event["evaluated_at"],
        "flagged_at_ms": int(time.time() * 1000),
        "notified": False,
    }

    try:
        TABLE.put_item(Item=item, ConditionExpression="attribute_not_exists(transaction_id)")
    except ClientError as err:
        if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        existing = TABLE.get_item(Key={"transaction_id": txn_id}, ConsistentRead=True).get("Item", {})
        if existing.get("notified"):
            logger.info("Duplicate delivery for %s, already notified; skipping", txn_id)
            return

    notify(event)
    TABLE.update_item(
        Key={"transaction_id": txn_id},
        UpdateExpression="SET notified = :t",
        ExpressionAttributeValues={":t": True},
    )


def notify(event: dict) -> None:
    txn = event["transaction"]
    loc = txn["location"]
    reasons = "; ".join(REASON_TEXT.get(r, r) for r in event["reasons"])

    message = (
        f"We flagged a {txn['transaction_type']} of ${txn['amount']} on account "
        f"{txn['account_id']} in {loc['city']}, {loc['country']} at {txn['timestamp']}.\n\n"
        f"Why: {reasons}.\n\n"
        "If this wasn't you, contact your bank immediately."
    )
    SNS.publish(TopicArn=TOPIC_ARN, Subject="Suspicious activity on your account", Message=message)

    logger.warning(
        json.dumps(
            {
                "alert": "FRAUD_FLAGGED",
                "transaction_id": event["transaction_id"],
                "account_id": txn["account_id"],
                "reasons": event["reasons"],
            }
        )
    )