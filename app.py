import json
import math
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Any, Optional

try:
    import paho.mqtt.client as mqtt  # type: ignore[import-not-found]
except ImportError:
    mqtt = None


@dataclass
class Lamp:
    lamp_id: str
    x: int
    y: int
    is_on: bool = False


@dataclass
class Motor:
    motor_id: str
    x: int
    y: int
    speed: int = 0
    angle: float = 0.0


class RoomSimulatorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Room Light MQTT Simulator")
        self.root.geometry("980x640")

        self.event_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self.lux = 650.0
        self.manual_override = False
        self.connection_state = "DISCONNECTED"
        self.last_animation_time = time.time()

        self.mqtt_client: Optional[Any] = None
        self.mqtt_connected = False

        self.lamps = [
            Lamp("lamp1", 150, 180),
            Lamp("lamp2", 300, 180),
            Lamp("lamp3", 450, 180),
            Lamp("lamp4", 600, 180),
        ]
        self.motors = [
            Motor("motor1", 250, 330),
            Motor("motor2", 500, 330),
        ]

        self._build_ui()
        self._start_event_loop()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=3)
        self.root.columnconfigure(1, weight=2)
        self.root.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(self.root, bg="#f5f4ef", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)

        panel = ttk.Frame(self.root, padding=12)
        panel.grid(row=0, column=1, sticky="nsew", padx=(0, 14), pady=14)
        panel.columnconfigure(0, weight=1)

        title = ttk.Label(panel, text="Controls", font=("Segoe UI", 12, "bold"))
        title.grid(row=0, column=0, sticky="w", pady=(0, 8))

        mqtt_box = ttk.LabelFrame(panel, text="MQTT")
        mqtt_box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        mqtt_box.columnconfigure(1, weight=1)

        ttk.Label(mqtt_box, text="Broker host").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.host_var = tk.StringVar(value="localhost")
        ttk.Entry(mqtt_box, textvariable=self.host_var).grid(row=0, column=1, sticky="ew", padx=8, pady=6)

        ttk.Label(mqtt_box, text="Port").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.port_var = tk.IntVar(value=1883)
        ttk.Entry(mqtt_box, textvariable=self.port_var).grid(row=1, column=1, sticky="ew", padx=8, pady=6)

        buttons = ttk.Frame(mqtt_box)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=6)
        buttons.columnconfigure((0, 1), weight=1)

        ttk.Button(buttons, text="Connect", command=self.connect_mqtt).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="Disconnect", command=self.disconnect_mqtt).grid(row=0, column=1, sticky="ew")

        self.conn_label = ttk.Label(mqtt_box, text="State: DISCONNECTED")
        self.conn_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        sensor_box = ttk.LabelFrame(panel, text="Sensor Simulation")
        sensor_box.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        sensor_box.columnconfigure(0, weight=1)

        self.lux_var = tk.DoubleVar(value=self.lux)
        ttk.Label(sensor_box, text="Lux").grid(row=0, column=0, sticky="w", padx=8)
        self.lux_scale = ttk.Scale(sensor_box, from_=0, to=1000, variable=self.lux_var, command=self.on_lux_ui)
        self.lux_scale.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
        self.lux_value_label = ttk.Label(sensor_box, text=f"{self.lux:.0f}")
        self.lux_value_label.grid(row=2, column=0, sticky="e", padx=8, pady=(0, 8))

        control_box = ttk.LabelFrame(panel, text="Actuator Control")
        control_box.grid(row=3, column=0, sticky="ew")
        control_box.columnconfigure(0, weight=1)

        self.manual_override_var = tk.BooleanVar(value=False)
        manual_toggle = ttk.Checkbutton(
            control_box,
            text="Manual Override",
            variable=self.manual_override_var,
            command=self.on_manual_override_ui,
        )
        manual_toggle.grid(row=0, column=0, sticky="w", padx=8, pady=8)

        row = ttk.Frame(control_box)
        row.grid(row=1, column=0, sticky="ew", padx=8, pady=(2, 8))
        row.columnconfigure((0, 1, 2), weight=1)

        self.all_on_button = ttk.Button(row, text="All ON", command=self.manual_all_on)
        self.all_on_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.auto_button = ttk.Button(row, text="Auto", command=self.set_auto_mode)
        self.auto_button.grid(row=0, column=1, sticky="ew", padx=2)
        self.all_off_button = ttk.Button(row, text="All OFF", command=self.manual_all_off)
        self.all_off_button.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        per_lamp_box = ttk.LabelFrame(control_box, text="Per-Lamp Manual")
        per_lamp_box.grid(row=2, column=0, sticky="ew", padx=8, pady=(2, 8))
        per_lamp_box.columnconfigure((0, 1), weight=1)

        self.lamp_toggle_buttons = []
        for index, lamp in enumerate(self.lamps):
            lamp_button = ttk.Button(
                per_lamp_box,
                text=f"{lamp.lamp_id}: OFF",
                command=lambda lamp_id=lamp.lamp_id: self.toggle_lamp_manual(lamp_id),
            )
            lamp_button.grid(row=index // 2, column=index % 2, sticky="ew", padx=4, pady=4)
            self.lamp_toggle_buttons.append(lamp_button)

        motor_box = ttk.LabelFrame(panel, text="Motor Control")
        motor_box.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        motor_box.columnconfigure(0, weight=1)

        self.motor_vars = []
        for index, motor in enumerate(self.motors):
            ttk.Label(motor_box, text=f"{motor.motor_id} speed").grid(row=index * 2, column=0, sticky="w", padx=8, pady=(8, 0))
            motor_var = tk.IntVar(value=motor.speed)
            self.motor_vars.append(motor_var)
            motor_scale = ttk.Scale(
                motor_box,
                from_=0,
                to=100,
                variable=motor_var,
                command=lambda value, idx=index: self.on_motor_speed_ui(idx, value),
            )
            motor_scale.grid(row=index * 2 + 1, column=0, sticky="ew", padx=8, pady=(0, 4))

        self.motor_value_label = ttk.Label(motor_box, text="motor1: 0%   motor2: 0%")
        self.motor_value_label.grid(row=4, column=0, sticky="e", padx=8, pady=(0, 8))

        topic_box = ttk.LabelFrame(panel, text="Subscribed Topics")
        topic_box.grid(row=5, column=0, sticky="ew", pady=(10, 0))

        topics = [
            "room/sensors/lux",
            "room/control/manual_override",
            "room/control/lamp/all",
            "room/control/lamp/<lamp_id>",
            "room/control/motor/<motor_id>",
            "room/control/motor/all",
            "room/sensors/json",
        ]
        ttk.Label(topic_box, text="\n".join(topics), justify="left").grid(row=0, column=0, sticky="w", padx=8, pady=8)

        self.update_control_states()
        self.update_lamp_toggle_labels()
        self.draw_room()

    def _start_event_loop(self) -> None:
        self.process_queued_events()

    def process_queued_events(self) -> None:
        now = time.time()
        dt = max(0.01, min(0.2, now - self.last_animation_time))
        self.last_animation_time = now

        for motor in self.motors:
            # Higher speed creates larger angular velocity for visible spinning.
            motor.angle = (motor.angle + (motor.speed * 3.6 * dt * 2.2)) % 360

        while True:
            try:
                topic, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self.handle_message(topic, payload)

        self.draw_room()
        self.root.after(100, self.process_queued_events)

    def connect_mqtt(self) -> None:
        if mqtt is None:
            self.connection_state = "MQTT LIB MISSING"
            self.update_connection_label()
            return

        if self.mqtt_connected:
            return

        host = self.host_var.get().strip() or "localhost"
        port = self.port_var.get()

        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_disconnect = self._on_disconnect
        self.mqtt_client.on_message = self._on_message

        try:
            self.mqtt_client.connect(host, int(port), keepalive=60)
            self.mqtt_client.loop_start()
            self.connection_state = "CONNECTING"
        except Exception as exc:
            self.connection_state = f"ERROR: {exc}"

        self.update_connection_label()

    def disconnect_mqtt(self) -> None:
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass

        self.mqtt_connected = False
        self.connection_state = "DISCONNECTED"
        self.update_connection_label()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            self.mqtt_connected = True
            self.connection_state = "CONNECTED"
            topics = [
                ("room/sensors/lux", 0),
                ("room/control/manual_override", 0),
                ("room/control/lamp/all", 0),
                ("room/control/lamp/+", 0),
                ("room/control/motor/+", 0),
                ("room/control/motor/all", 0),
                ("room/sensors/json", 0),
            ]
            client.subscribe(topics)
        else:
            self.connection_state = f"CONNECT FAILED ({reason_code})"

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        self.mqtt_connected = False
        self.connection_state = "DISCONNECTED"

    def _on_message(self, client, userdata, msg) -> None:
        payload = msg.payload.decode("utf-8", errors="ignore")
        self.event_queue.put((msg.topic, payload))

    def on_lux_ui(self, _) -> None:
        value = float(self.lux_var.get())
        self.lux = value
        self.lux_value_label.config(text=f"{value:.0f}")
        self.publish_if_connected("room/sensors/lux", str(int(value)))

    def on_manual_override_ui(self) -> None:
        state = self.manual_override_var.get()
        self.set_manual_override(state)
        self.publish_if_connected("room/control/manual_override", "1" if state else "0")

    def on_motor_speed_ui(self, index: int, value: str) -> None:
        speed = int(float(value))
        motor_id = self.motors[index].motor_id
        self.event_queue.put((f"room/control/motor/{motor_id}", str(speed)))
        self.publish_if_connected(f"room/control/motor/{motor_id}", str(speed))

    def manual_all_on(self) -> None:
        self.set_manual_override(True, run_auto=False)
        self.set_all_lamps(True)
        self.update_lamp_toggle_labels()
        self.publish_if_connected("room/control/lamp/all", "ON")

    def manual_all_off(self) -> None:
        self.set_manual_override(True, run_auto=False)
        self.set_all_lamps(False)
        self.update_lamp_toggle_labels()
        self.publish_if_connected("room/control/lamp/all", "OFF")

    def set_auto_mode(self) -> None:
        self.lux = 0.0
        self.lux_var.set(0.0)
        self.lux_value_label.config(text="0")
        self.set_manual_override(False, run_auto=True)
        self.publish_if_connected("room/control/lamp/all", "AUTO")
        self.publish_if_connected("room/sensors/lux", "0")

    def set_manual_override(self, state: bool, run_auto: bool = True) -> None:
        self.manual_override = state
        self.manual_override_var.set(state)
        self.update_control_states()
        if run_auto and not state:
            self.apply_auto_logic()

    def update_control_states(self) -> None:
        mode = tk.NORMAL if self.manual_override else tk.DISABLED
        self.all_on_button.config(state=mode)
        self.all_off_button.config(state=mode)
        for button in self.lamp_toggle_buttons:
            button.config(state=mode)
        self.lux_scale.config(state=mode)

    def update_lamp_toggle_labels(self) -> None:
        for lamp, button in zip(self.lamps, self.lamp_toggle_buttons):
            button.config(text=f"{lamp.lamp_id}: {'ON' if lamp.is_on else 'OFF'}")

    def toggle_lamp_manual(self, lamp_id: str) -> None:
        self.set_manual_override(True, run_auto=False)
        for lamp in self.lamps:
            if lamp.lamp_id == lamp_id:
                lamp.is_on = not lamp.is_on
                self.publish_if_connected(
                    f"room/control/lamp/{lamp_id}",
                    "ON" if lamp.is_on else "OFF",
                )
                break
        self.update_lamp_toggle_labels()

    def publish_if_connected(self, topic: str, payload: str) -> None:
        if self.mqtt_client and self.mqtt_connected:
            try:
                self.mqtt_client.publish(topic, payload)
            except Exception:
                pass

    def handle_message(self, topic: str, payload: str) -> None:
        topic = topic.strip()
        payload = payload.strip()

        if topic == "room/sensors/lux":
            if self.manual_override:
                return
            try:
                self.lux = float(payload)
            except ValueError:
                return
            self.lux_var.set(self.lux)
            self.lux_value_label.config(text=f"{self.lux:.0f}")
            return

        if topic == "room/control/manual_override":
            self.set_manual_override(payload.lower() in {"1", "true", "on", "yes"})
            return

        if topic == "room/control/lamp/all":
            if self.manual_override:
                return
            value = payload.upper()
            if value == "ON":
                self.set_manual_override(True, run_auto=False)
                self.set_all_lamps(True)
            elif value == "OFF":
                self.set_manual_override(True, run_auto=False)
                self.set_all_lamps(False)
            elif value == "AUTO":
                self.set_manual_override(False, run_auto=True)
            self.update_lamp_toggle_labels()
            return

        if topic.startswith("room/control/lamp/"):
            if self.manual_override:
                return
            lamp_id = topic.split("/")[-1]
            self.set_manual_override(True, run_auto=False)
            for lamp in self.lamps:
                if lamp.lamp_id == lamp_id:
                    lamp.is_on = payload.upper() == "ON"
            self.update_lamp_toggle_labels()
            return

        if topic == "room/control/motor/all":
            try:
                speed = max(0, min(100, int(float(payload))))
            except ValueError:
                return
            for index, motor in enumerate(self.motors):
                motor.speed = speed
                self.motor_vars[index].set(speed)
            self.update_motor_value_label()
            return

        if topic.startswith("room/control/motor/"):
            motor_id = topic.split("/")[-1]
            try:
                speed = max(0, min(100, int(float(payload))))
            except ValueError:
                return

            for index, motor in enumerate(self.motors):
                if motor.motor_id == motor_id:
                    motor.speed = speed
                    self.motor_vars[index].set(speed)
            self.update_motor_value_label()
            return

        if topic == "room/sensors/json":
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return

            if "lux" in data:
                try:
                    self.lux = float(data["lux"])
                except (TypeError, ValueError):
                    pass
                self.lux_var.set(self.lux)
                self.lux_value_label.config(text=f"{self.lux:.0f}")
            if "manual_override" in data:
                self.set_manual_override(bool(data["manual_override"]), run_auto=False)
            if "motor1_speed" in data:
                self._set_motor_speed_by_id("motor1", data["motor1_speed"])
            if "motor2_speed" in data:
                self._set_motor_speed_by_id("motor2", data["motor2_speed"])


    def _set_motor_speed_by_id(self, motor_id: str, value: Any) -> None:
        try:
            speed = max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            return

        for index, motor in enumerate(self.motors):
            if motor.motor_id == motor_id:
                motor.speed = speed
                self.motor_vars[index].set(speed)
        self.update_motor_value_label()

    def apply_auto_logic(self) -> None:
        # Auto: lamps are always ON; lux drives only visual brightness.
        if self.manual_override:
            return

        self.set_all_lamps(True)
        self.update_lamp_toggle_labels()

    def set_all_lamps(self, state: bool) -> None:
        for lamp in self.lamps:
            lamp.is_on = state

    def update_connection_label(self) -> None:
        self.conn_label.config(text=f"State: {self.connection_state}")

    def update_motor_value_label(self) -> None:
        m1 = self.motors[0].speed
        m2 = self.motors[1].speed
        self.motor_value_label.config(text=f"motor1: {m1}%   motor2: {m2}%")

    def draw_room(self) -> None:
        self.update_connection_label()
        self.canvas.delete("all")

        width = self.canvas.winfo_width() or 680
        height = self.canvas.winfo_height() or 560

        room_left = 50
        room_right = width - 50
        room_top = 70
        room_bottom = height - 70

        self.canvas.create_rectangle(room_left, room_top, room_right, room_bottom, fill="#fffef7", outline="#b7b7b7", width=2)
        self.canvas.create_text(width // 2, 40, text="Room Visualization", font=("Segoe UI", 15, "bold"), fill="#2a2a2a")

        lamp_y = 180
        lamp_left = room_left + 80
        lamp_spacing = max(120, (room_right - room_left - 160) // max(1, len(self.lamps) - 1))
        for index, lamp in enumerate(self.lamps):
            lamp.x = lamp_left + index * lamp_spacing
            lamp.y = lamp_y

        motor_y = 330
        motor_left = room_left + 150
        motor_spacing = 200
        for index, motor in enumerate(self.motors):
            motor.x = motor_left + index * motor_spacing
            motor.y = motor_y

        for lamp in self.lamps:
            self.draw_lamp(lamp)

        for motor in self.motors:
            self.draw_motor(motor)

        lux_text = f"Lux: {self.lux:.0f}"
        self.canvas.create_rectangle(90, height - 125, 350, height - 85, fill="#eefce8", outline="#72b564")
        self.canvas.create_text(220, height - 105, text=lux_text, font=("Segoe UI", 10, "bold"), fill="#2d6c21")

        mode_text = "Manual\nOverride" if self.manual_override else "Auto Mode"
        mode_fill = "#ffe9e6" if self.manual_override else "#efeafd"
        mode_outline = "#df6a5a" if self.manual_override else "#7c6bcc"
        self.canvas.create_rectangle(380, height - 125, width - 90, height - 85, fill=mode_fill, outline=mode_outline)
        self.canvas.create_text((380 + width - 90) // 2, height - 105, text=mode_text, font=("Segoe UI", 9, "bold"), justify="center")

    def draw_lamp(self, lamp: Lamp) -> None:
        # Room background used as the "off" color so lux=0 blends into the wall.
        room_bg = "#fffef7"
        brightness = self.get_lamp_brightness()
        glow_color = self.color_by_brightness(room_bg, "#ffe78a", brightness) if lamp.is_on else "#dddddd"
        bulb_color = self.color_by_brightness(room_bg, "#ffc933", brightness) if lamp.is_on else "#a8a8a8"

        self.canvas.create_line(lamp.x, 90, lamp.x, lamp.y - 20, fill="#666", width=2)

        if lamp.is_on and brightness > 0.02:
            self.canvas.create_oval(lamp.x - 42, lamp.y - 42, lamp.x + 42, lamp.y + 42, fill=glow_color, outline="")

        self.canvas.create_oval(lamp.x - 18, lamp.y - 18, lamp.x + 18, lamp.y + 18, fill=bulb_color, outline="#5a5a5a")
        self.canvas.create_text(lamp.x, lamp.y + 30, text=lamp.lamp_id, font=("Segoe UI", 9), fill="#333")

    def get_lamp_brightness(self) -> float:
        # 0 lux -> fully transparent, 1000 lux -> full yellow.
        return max(0.0, min(1000.0, self.lux)) / 1000.0

    def color_by_brightness(self, dark_hex: str, bright_hex: str, ratio: float) -> str:
        ratio = max(0.0, min(1.0, ratio))

        def to_rgb(hex_color: str) -> tuple[int, int, int]:
            h = hex_color.lstrip("#")
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        dark = to_rgb(dark_hex)
        bright = to_rgb(bright_hex)
        mixed = tuple(int(dark[i] + (bright[i] - dark[i]) * ratio) for i in range(3))
        return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"

    def draw_motor(self, motor: Motor) -> None:
        radius = 34
        self.canvas.create_oval(
            motor.x - radius,
            motor.y - radius,
            motor.x + radius,
            motor.y + radius,
            fill="#f0f5fa",
            outline="#7f8fa0",
            width=2,
        )

        blade_length = 22
        for blade_index in range(3):
            angle_deg = motor.angle + blade_index * 120
            angle_rad = math.radians(angle_deg)
            x2 = motor.x + blade_length * math.cos(angle_rad)
            y2 = motor.y + blade_length * math.sin(angle_rad)
            self.canvas.create_line(motor.x, motor.y, x2, y2, fill="#3e5f7a", width=4)

        self.canvas.create_oval(motor.x - 6, motor.y - 6, motor.x + 6, motor.y + 6, fill="#2d3f52", outline="")
        self.canvas.create_text(motor.x, motor.y + 48, text=f"{motor.motor_id} {motor.speed}%", font=("Segoe UI", 9), fill="#2f3d48")


def main() -> None:
    root = tk.Tk()
    app = RoomSimulatorApp(root)

    def on_close() -> None:
        app.disconnect_mqtt()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
