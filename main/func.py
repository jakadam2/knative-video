from parliament import Context
from flask import Request
import json
import requests
import xml.etree.ElementTree as ET

def payload_print(req: Request) -> str:
    if req.method == "POST":
        # jeśli przychodzi JSON (np. SNS), to skonwertuj na string
        if req.is_json or req.content_type.startswith("text/plain"):
            try:
                return json.dumps(req.get_json(force=True)) + "\n"
            except Exception:
                pass

        # w przeciwnym razie wypisz pola form-data
        ret = "{"
        for key in req.form.keys():
            ret += f'"{key}": "{req.form[key]}", '
        return ret[:-2] + "}\n" if len(ret) > 2 else "{}"
    elif req.method == "GET":
        ret = "{"
        for key in req.args.keys():
            ret += f'"{key}": "{req.args[key]}", '
        return ret[:-2] + "}\n" if len(ret) > 2 else "{}"

def pretty_print(req: Request) -> str:
    ret = f"{req.method} {req.url} {req.host}\n"
    # użycie .items(), żeby wychwycić pary (nagłówek, wartość)
    for header, value in req.headers.items():
        ret += f"  {header}: {value}\n"
    if req.method == "POST":
        ret += "Request body:\n"
        ret += f"  {payload_print(req)}\n"
    elif req.method == "GET":
        ret += "URL Query String:\n"
        ret += f"  {payload_print(req)}\n"
    return ret

def main(context: Context):
    """
    AWS SNS-compatible Knative function z obsługą potwierdzenia subskrypcji.
    """
    print("Received request")

    if 'request' not in context:
        print("Empty request", flush=True)
        return "{}", 200

    req = context.request
    print(pretty_print(req), flush=True)

    # Wymuszone parsowanie JSON, bo SNS wysyła Content-Type: text/plain
    data = req.get_json(force=True, silent=True)
    if data and data.get("Type") == "SubscriptionConfirmation":
        subscribe_url = data.get("SubscribeURL")
        print("SNS SubscriptionConfirmation received. Confirming...", flush=True)
        print(f"SubscribeURL: {subscribe_url}", flush=True)
        try:
            resp = requests.get(subscribe_url)
            if resp.status_code == 200:
                print("Subscription confirmed successfully.", flush=True)
                # W parsowaniu XML wykorzystujemy namespace SNSa
                try:
                    root = ET.fromstring(resp.text)
                    namespace = {'ns': 'http://sns.amazonaws.com/doc/2010-03-31/'}
                    subscription_arn = root.find('.//ns:SubscriptionArn', namespace)
                    if subscription_arn is not None:
                        print(f"SubscriptionArn: {subscription_arn.text}", flush=True)
                    else:
                        print("SubscriptionArn not found in the response.", flush=True)
                except ET.ParseError as e:
                    print(f"Error parsing XML response: {e}", flush=True)
            else:
                print(f"Failed to confirm subscription. Status code: {resp.status_code}", flush=True)
                print(f"Response body: {resp.text}", flush=True)
        except Exception as e:
            print(f"Error during subscription confirmation: {e}", flush=True)
        return "Subscription confirmation handled\n", 200

    # Domyślne wypisanie payloadu dla pozostałych wiadomości SNS lub zwykłych requestów
    return payload_print(req), 200
