import argparse
import json
import time
import uuid

import paho.mqtt.client as mqtt  # type: ignore[import-not-found]


def publish(client: mqtt.Client, topic: str, payload: str, delay: float) -> None:
    result = client.publish(topic, payload)
    result.wait_for_publish()
    print(f"Published -> {topic}: {payload}")
    if delay > 0:
        time.sleep(delay)


def run_demo_sequence(client: mqtt.Client, delay: float) -> None:
    print("Running demo sequence for room lamp + motor simulator...")

    # --- AUTO MODE ---
    # Switch to auto: lux/lamp MQTT messages are accepted.
    publish(client, "room/control/manual_override", "0", delay)
    publish(client, "room/sensors/lux", "1000", delay)
    publish(client, "room/sensors/lux", "600", delay)
    publish(client, "room/sensors/lux", "200", delay)
    publish(client, "room/sensors/lux", "0", delay)

    # In auto mode, test individual lamp control topics.
    publish(client, "room/control/lamp/lamp1", "OFF", delay)
    publish(client, "room/control/lamp/lamp1", "ON", delay)
    publish(client, "room/control/lamp/lamp2", "OFF", delay)
    publish(client, "room/control/lamp/lamp2", "ON", delay)
    publish(client, "room/control/lamp/lamp3", "OFF", delay)
    publish(client, "room/control/lamp/lamp3", "ON", delay)
    publish(client, "room/control/lamp/lamp4", "OFF", delay)
    publish(client, "room/control/lamp/lamp4", "ON", delay)

    # --- MANUAL MODE ---
    # Enter manual override: lux/lamp MQTT messages are now ignored by the app.
    # Only the UI lux slider and per-lamp buttons are active in this mode.
    publish(client, "room/control/manual_override", "1", delay)

    # These messages are gated out while manual override is ON (expected to be ignored).
    publish(client, "room/sensors/lux", "900", delay)       # ignored
    publish(client, "room/control/lamp/all", "OFF", delay)  # ignored

    # Motor commands always work regardless of mode.
    publish(client, "room/control/motor/motor1", "30", delay)
    publish(client, "room/control/motor/motor2", "75", delay)
    publish(client, "room/control/motor/all", "50", delay)

    # Switch back to auto: lux resumes driving brightness.
    publish(client, "room/control/manual_override", "0", delay)
    publish(client, "room/sensors/lux", "500", delay)

    # --- JSON PACKET ---
    payload = json.dumps(
        {
            "lux": 800,
            "manual_override": False,
            "motor1_speed": 20,
            "motor2_speed": 95,
        }
    )
    publish(client, "room/sensors/json", payload, delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="MQTT test publisher for Room Light Simulator")
    parser.add_argument("--broker", default="broker.hivemq.com", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between demo messages in seconds")
    parser.add_argument("--topic", help="Publish a single custom topic")
    parser.add_argument("--payload", help="Publish a single custom payload")
    args = parser.parse_args()

    client_id = f"room-light-pub-{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)

    print(f"Connecting to {args.broker}:{args.port} with client_id={client_id}")
    client.connect(args.broker, args.port, 60)
    client.loop_start()

    try:
        if args.topic and args.payload is not None:
            publish(client, args.topic, args.payload, 0)
        elif args.topic or args.payload is not None:
            raise SystemExit("Use both --topic and --payload for single publish mode.")
        else:
            run_demo_sequence(client, args.delay)
    finally:
        client.loop_stop()
        client.disconnect()
        print("Disconnected")


if __name__ == "__main__":
    main()
