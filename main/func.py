import json
import boto3
import requests
from flask import Request
from parliament import Context
from botocore.exceptions import ClientError

def extract_s3_object_info(sns_message: dict) -> tuple[str, str]:
    """
    Wyodrębnia nazwę bucketa i klucz obiektu z powiadomienia SNS.
    """
    try:
        record = sns_message["Records"][0]
        bucket_name = record["s3"]["bucket"]["name"]
        object_key = record["s3"]["object"]["key"]
        return bucket_name, object_key
    except (KeyError, IndexError) as e:
        print(f"Błąd podczas wyodrębniania informacji z powiadomienia SNS: {e}")
        return None, None

def copy_mp3_object(bucket_name: str, object_key: str,
                    aws_access_key: str, aws_secret_key: str,
                    aws_session_token: str, aws_region: str = 'us-east-1') -> bool:

    if not object_key.lower().endswith('.mp3'):
        return False

    s3 = boto3.client(
        's3',
        region_name=aws_region,
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        aws_session_token=aws_session_token
    )

    copy_source = {
        'Bucket': bucket_name,
        'Key': object_key
    }


    new_key = f"{object_key}.copy"

    try:
        s3.copy_object(
            Bucket=bucket_name,
            CopySource=copy_source,
            Key=new_key
        )
        return True
    except ClientError as e:
        return False

def main(context: Context):

    print("Otrzymano żądanie")

    if 'request' not in context:
        print("Brak danych w żądaniu.")
        return "{}", 200

    req: Request = context.request

    # Parsowanie treści żądania
    data = req.get_json(force=True, silent=True)
    if not data:
        return "Brak danych JSON w żądaniu.", 400

    # Obsługa potwierdzenia subskrypcji SNS
    if data.get("Type") == "SubscriptionConfirmation":
        subscribe_url = data.get("SubscribeURL")
        try:
            response = requests.get(subscribe_url)
            if response.status_code == 200:
                print("Subskrypcja potwierdzona pomyślnie.")
            else:
                print(f"Błąd podczas potwierdzania subskrypcji. Status: {response.status_code}")
        except Exception as e:
            print(f"Błąd podczas potwierdzania subskrypcji: {e}")
        return "Potwierdzenie subskrypcji obsłużone.", 200

    # Obsługa powiadomienia o utworzeniu obiektu w S3
    if data.get("Type") == "Notification":
        message_str = data.get("Message")
        try:
            message = json.loads(message_str)
        except json.JSONDecodeError as e:
            print(f"Błąd podczas dekodowania wiadomości SNS: {e}")
            return "Błąd podczas dekodowania wiadomości SNS.", 400

        bucket_name, object_key = extract_s3_object_info(message)
        if not bucket_name or not object_key:
            return "Nieprawidłowe dane w wiadomości SNS.", 400

        aws_access_key = ''
        aws_secret_key = ''
        aws_session_token = ''
        aws_region = 'us-east-1'  # Zmień na odpowiedni region
        bucket_name = 'knative-video-s3'  # Zmień na nazwę swojego bucketa

        success = copy_mp3_object(bucket_name, object_key,
                                  aws_access_key, aws_secret_key,
                                  aws_session_token, aws_region)
        if success:
            return f"Plik '{object_key}' został skopiowany pomyślnie.", 200
        else:
            return f"Błąd podczas kopiowania pliku '{object_key}'.", 500

    print("Nieobsługiwany typ wiadomości SNS.")
    return "Nieobsługiwany typ wiadomości SNS.", 400