from parliament import Context
from flask import Request
import json
import boto3
import datetime
import os
import uuid

# Constants from env
BUCKET_NAME = "knative-video-s3"
PREFIX = os.getenv("PREFIX", "knative-video")

# S3 client
s3 = boto3.client("s3")

def parse_payload(req: Request) -> dict:
    try:
        if req.is_json:
            return req.get_json()
        else:
            return {}
    except Exception as e:
        print(f"Error parsing JSON: {e}", flush=True)
        return {}

def upload_to_s3(data: dict):
    try:
        now = datetime.datetime.utcnow().isoformat()
        unique_id = uuid.uuid4().hex
        key = f"{PREFIX}-{now}-{unique_id}.json"
        body = json.dumps(data)

        print(f"Uploading to S3 bucket '{BUCKET_NAME}' with key '{key}'", flush=True)

        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=body,
            ContentType="application/json"
        )

        print("Upload successful", flush=True)
        return key
    except Exception as e:
        print(f"Failed to upload to S3: {e}", flush=True)
        return None

def main(context: Context):
    print("🔔 Received request")

    if 'request' in context.keys():
        req = context.request
        event_data = parse_payload(req)

        print(f"Raw event data: {event_data}", flush=True)

        # If from SNS, extract the 'Message' field
        if "Type" in event_data and event_data["Type"] == "Notification":
            message_str = event_data.get("Message", "{}")
            try:
                # Try to parse nested JSON
                message_data = json.loads(message_str)
            except json.JSONDecodeError:
                message_data = {"raw_message": message_str}
        else:
            message_data = event_data

        print(f"Data to upload: {message_data}", flush=True)
        key = upload_to_s3(message_data)

        if key:
            return f"Uploaded to S3 as {key}\n", 200
        else:
            return "Failed to upload\n", 500
    else:
        print("⚠️ Empty request", flush=True)
        return "{}", 200
