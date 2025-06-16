import json
import requests
from flask import Request
from parliament import Context

import os
import time
import tempfile
import boto3
import cv2 

from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

def _post_chunk(url: str, key: str) -> tuple[str, int]:
    try:
        r = requests.post(url, json={"key": key}, timeout=30)
        return key, r.status_code
    except Exception:
        return key, -1

def dispatch_chunks(chunk_keys: list[str], url: str, max_workers: int = 20, overall_timeout: int = 1200) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    start = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        fut_to_key = {exe.submit(_post_chunk, url, k): k for k in chunk_keys}
        for fut in as_completed(fut_to_key, timeout=overall_timeout):
            results.append(fut.result())

    return results


def split_video_cv2(s3_client, bucket_name, object_key, local_path, frame_chunk_size=100):

    folder_name = os.path.splitext(os.path.basename(object_key))[0].replace('__process__', '')
    temp_dir = tempfile.mkdtemp()
    
    cap = cv2.VideoCapture(local_path)

    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    frame_count = 0
    chunk_index = 0
    out = None
    chunk_keys = []

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_count % frame_chunk_size == 0:
                if out:
                    out.release()
                    s3_client.upload_file(temp_chunk_path, bucket_name, chunk_key)
                    chunk_keys.append(chunk_key)

                chunk_index += 1
                chunk_filename = f"{folder_name}_part{chunk_index}.mp4".replace('__process__', '')
                chunk_key = f"{folder_name}/{chunk_filename}"
                temp_chunk_path = os.path.join(temp_dir, chunk_filename)
                out = cv2.VideoWriter(temp_chunk_path, fourcc, fps, (width, height))
            
            out.write(frame)
            frame_count += 1

        if out:
            out.release()
            s3_client.upload_file(temp_chunk_path, bucket_name, chunk_key)
            chunk_keys.append(chunk_key)
            
    finally:
        cap.release()
        for f in os.listdir(temp_dir):
            os.remove(os.path.join(temp_dir, f))
        os.rmdir(temp_dir)

    return chunk_keys, folder_name


def merge_video_cv2(s3_client, bucket_name, chunk_keys, merged_key):

    temp_dir = tempfile.mkdtemp()
 
    try:
        local_chunk_paths = []
        for idx, key in enumerate(sorted(chunk_keys), start=1):
            local_path = os.path.join(temp_dir, os.path.basename(key))
            s3_client.download_file(bucket_name, key, local_path)
            local_chunk_paths.append(local_path)

        cap_test = cv2.VideoCapture(local_chunk_paths[0])
        
        fps = int(cap_test.get(cv2.CAP_PROP_FPS))
        width = int(cap_test.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap_test.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap_test.release()
        
        merged_local_path = os.path.join(temp_dir, "merged_output.mp4").replace('__process__', '')
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(merged_local_path, fourcc, fps, (width, height))
        
        for chunk_path in local_chunk_paths:
            cap = cv2.VideoCapture(chunk_path)
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                out.write(frame)
            cap.release()
        
        out.release()

        s3_client.upload_file(merged_local_path, bucket_name, merged_key)
        
        for key in chunk_keys:
            s3_client.delete_object(Bucket=bucket_name, Key=key)
            
    finally:
        for f in os.listdir(temp_dir):
            os.remove(os.path.join(temp_dir, f))
        os.rmdir(temp_dir)


def process_video(bucket_name, object_key,
                  aws_access_key, aws_secret_key, aws_session_token,
                  region='us-east-1', frame_chunk_size=300):

    s3 = boto3.client(
        's3',
        region_name=region,
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        aws_session_token=aws_session_token
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        local_path = os.path.join(temp_dir, os.path.basename(object_key))
        s3.download_file(bucket_name, object_key, local_path)

        chunk_keys, folder_name = split_video_cv2(s3, bucket_name, object_key, local_path, frame_chunk_size)
        endpoint = "http://procvid.default.svc.cluster.local"
        responses = dispatch_chunks(chunk_keys, endpoint)
        names = [response[0].replace(".mp4", "_cmpl.mp4") for response in responses]

        merged_key = object_key.replace(os.path.splitext(object_key)[1], "_merged.mp4").replace('__process__', '')
        merge_video_cv2(s3, bucket_name, names, merged_key)
  


def extract_s3_info(sns_message: dict):
    import urllib.parse
    record = sns_message["Records"][0]
    bucket_name = record["s3"]["bucket"]["name"]
    object_key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
    return bucket_name, object_key


def main(context: Context):
    aws_access_key='ASIAR2MLUYXSPH7DBUAZ'
    aws_secret_key='PxwXuRPQvCQXF90fKLoFWsuC+Tu3Cq66AHzuKhNh'
    aws_session_token='IQoJb3JpZ2luX2VjEHcaCXVzLXdlc3QtMiJHMEUCIQCARVLtDLqv9U2CDUuDUrzgXkrALKwAJQ3q1dqpUi8T7QIgQLxA8B/94JvbmgfXyFn0Es7JhxXTWPP8aFKvjB7GdAgqpAIIYBAAGgwxMjUzODM3ODgwMDQiDH8EGMGwPZWMOz36XSqBAt0pEljk+0acG1BltrZj+W//g+7OGln+VvpGEcwEQiyApECQmKtiPMn7rE8/8SdsineNJeopRQU+YXC00MXIT1OcXA9kongrxnUZirIAEOIUE7VPUDUojardIihT2cOldrg+ThPVihTb5C77Wqq3CdFIIpo5mhIAMr8Jk7IhhMN475BU80x+heu8+F0+iLOgSZBkXu2ZbmHm5y/2P7Au6c3USeoENaybc8uS9yb5mF/zmeVVrNu8ysgsQTPnT2JU1IzPnI1AYDWfs1zKc21jHncIIs//MAUD5C9boMRw9r/94SIwGyIwz+Zq3CypyOHjEBaoZP7V8kWyDybOCFMRWNBFMIngwMIGOp0BcdgEEaGCbEEnbosclJKvAvKc0ePOwvJPngx2QwyLsczYGTlP7/yYtKrhFrEbtQvZrd26GBhJ6pSFk84lvESf+Fq7GG9Dh3rx1Lhug3ZtMDaKRSjI+IpdV0JmEV2Ag/rfCzKdeO3Bx0SjqljO4AywtRTgV1AAaJ6j1MHcUaHU+3J560eeZz6LLyP3PkwOVvlJrVyYAIPYokhuFMhtJQ=='
    aws_region = 'us-east-1'  
    bucket_name = 'knative-video-s3'

    if 'request' not in context:
        return "{}", 200

    req: Request = context.request
    data = req.get_json(force=True, silent=True)
    if not data:
        return "Unhandled request.", 400

    if data.get("Type") == "SubscriptionConfirmation":
        subscribe_url = data.get("SubscribeURL")
        try:
            response = requests.get(subscribe_url)
        except Exception as e:
            pass
        return "OK", 200

    if data.get("Type") == "Notification":
        try:
            message = json.loads(data.get("Message"))
        except json.JSONDecodeError as e:
            print(f"Błąd dekodowania wiadomości SNS: {e}")
            return "Błąd JSON SNS.", 400

        bucket_name, object_key = extract_s3_info(message)
        if not bucket_name or not object_key:
            return "Unhandled request", 400

        if 'part' not in object_key and 'mp4' in object_key and 'merged' not in object_key:
            process_video(
            bucket_name=bucket_name,
            object_key=object_key,
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
            aws_session_token=aws_session_token,
            )
  
        return f"OK", 200
  
    return "Unhandled request.", 400