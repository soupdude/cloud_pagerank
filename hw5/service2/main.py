import json
from google.cloud import pubsub_v1

PROJECT = "project-f131ec20-0df6-4cfa-bf0"


subscriber = pubsub_v1.SubscriberClient()

def callback(msg):
    info = json.loads(msg.data)
    line = f"FORBIDDEN request from {info['country']} for {info['path']}\n"
    print(line, end="", flush=True)
    msg.ack()

path = subscriber.subscription_path(PROJECT, "forbidden-sub")
print("Listening on", path, flush=True)
subscriber.subscribe(path, callback=callback).result()