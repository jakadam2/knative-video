import json
import requests
from flask import Request
from parliament import Context

import os
import time
import tempfile
import boto3
import cv2 

def black_white_vid(input_path, output_path):

        cap = cv2.VideoCapture(input_path)
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v') 
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height), isColor=False)

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            out.write(gray)

        cap.release()
        out.release()

def get_vid(s3_client, bucket_name,object_key):

    with tempfile.TemporaryDirectory() as temp_dir:
        local_path = os.path.join(temp_dir, os.path.basename(object_key))
        s3_client.download_file(bucket_name, object_key, local_path)
        
        out_key = object_key.replace(os.path.splitext(object_key)[1], "_cmpl.mp4")
        out_path = os.path.join(temp_dir, os.path.basename(out_key))
        black_white_vid(local_path,out_path)
        
        s3_client.upload_file(out_path, bucket_name, out_key)
        return out_path


def main(context: Context):    
    aws_access_key=''
    aws_secret_key=''
    aws_session_token=''
    aws_region = 'us-east-1'  
    bucket_name = 'knative-video-s3'  
    print("Otrzymano żądanie")

    if 'request' not in context:
        return "{}", 200

    req: Request = context.request
    data = req.get_json(force=True, silent=True)
    if not data:
        return "Brak danych JSON w żądaniu.", 400
    
    key = data.get("key")

    
    s3 = boto3.client(
        's3',
        region_name=aws_region,
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        aws_session_token=aws_session_token
    )
    out_path = get_vid(s3, bucket_name, key)
    
    return out_path, 200
