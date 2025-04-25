import serial
import json
import time
import firebase_admin
from firebase_admin import credentials, db
from tuya_connector import TuyaOpenAPI, TuyaAPIResponse
from datetime import datetime
from typing import Dict, Any, Optional

# Constants
SERIAL_PORT = '/dev/ttyUSB0'
BAUD_RATE = 115200
FIREBASE_CREDENTIALS = "fb/google-service(1).json"
FIREBASE_DB_URL = 'https://tugas-akhir-gua-default-rtdb.asia-southeast1.firebasedatabase.app/'
TUYA_ACCESS_ID = "7khd4jcpcdwae3k7d8wj"
TUYA_ACCESS_KEY = "393c22825c704470bc7486e9ff18dbd9"
TUYA_DEVICE_ID = "YOUR_DEVICE_ID"
TEMPERATURE_THRESHOLDS = {'high': 60, 'low': 50}
POLLING_INTERVAL = 5  # seconds

class MCBController:
    def __init__(self):
        # Initialize Firebase
        self._init_firebase()
        
        # Initialize Tuya API
        self.tuya_api = TuyaOpenAPI(
            "https://openapi.tuya.com", 
            TUYA_ACCESS_ID, 
            TUYA_ACCESS_KEY
        )
        self.tuya_api.connect()
        
        # Initialize serial connection
        self.serial_conn = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        
        # State tracking
        self.last_mcb_status: Optional[bool] = None
        self.last_sensor_data: Dict[str, Any] = {}
        
        # Initial setup
        self._initialize_system()

    def _init_firebase(self):
        """Initialize Firebase connection."""
        try:
            cred = credentials.Certificate(FIREBASE_CREDENTIALS)
            firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DB_URL})
        except Exception as e:
            self._log_error(f"Firebase initialization failed: {str(e)}")
            raise

    def _initialize_system(self):
        """Initialize system state."""
        try:
            self._read_tuya_status()
            self._log_system_event("System initialized")
        except Exception as e:
            self._log_error(f"System initialization failed: {str(e)}")
            raise

    def _log_mcb_event(self, status: bool, temperature: Optional[float] = None):
        """Log MCB state changes."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        event = "MCB_ON" if status else "MCB_OFF"
        
        log_entry = {
            "timestamp": timestamp,
            "event": event,
            "details": {
                "action": "AUTO",
                "reason": "HIGH_TEMP" if not status else "LOW_TEMP",
                "temperature": temperature
            }
        }
        
        try:
            # Save to logs
            db.reference("logs/mcb_events").push().set(log_entry)
            # Save latest event
            db.reference("device/last_mcb_event").set(log_entry)
            print(f"[MCB] {timestamp} - Status changed to {event}")
        except Exception as e:
            self._log_error(f"Failed to log MCB event: {str(e)}")

    def _log_system_event(self, message: str):
        """Log system events."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.reference("logs/system_events").push().set({
            "timestamp": timestamp,
            "message": message
        })

    def _log_error(self, error_msg: str):
        """Log error messages."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_entry = {
            "timestamp": timestamp,
            "error": error_msg,
            "type": "system_error"
        }
        try:
            db.reference("logs/errors").push().set(error_entry)
            print(f"[ERROR] {timestamp} - {error_msg}")
        except Exception as e:
            print(f"CRITICAL: Failed to log error: {str(e)}")

    def _control_mcb(self, status: bool):
        """Control MCB switch state."""
        if status == self.last_mcb_status:
            return
            
        try:
            cmd = {'commands': [{'code': 'switch_1', 'value': status}]}
            response: TuyaAPIResponse = self.tuya_api.post(
                f'/v1.0/iot-03/devices/{TUYA_DEVICE_ID}/commands', 
                cmd
            )
            
            if response.get('success', False):
                self.last_mcb_status = status
                db.reference("device/mcb_status").set(status)
                self._log_mcb_event(status, self.last_sensor_data.get('rata_rata_suhu'))
            else:
                raise Exception(f"Tuya API error: {response.get('msg', 'Unknown error')}")
                
        except Exception as e:
            self._log_error(f"MCB control failed: {str(e)}")
            raise

    def _read_tuya_status(self):
        """Read current status from Tuya device."""
        try:
            response: TuyaAPIResponse = self.tuya_api.get(
                f'/v1.0/iot-03/devices/{TUYA_DEVICE_ID}/status'
            )
            
            if response.get('success', False):
                for item in response["result"]:
                    code = item["code"]
                    value = item["value"]
                    db.reference(f"tuya_status/{code}").set(value)
                    
                    if code == "switch_1":
                        self.last_mcb_status = value
        except Exception as e:
            self._log_error(f"Failed to read Tuya status: {str(e)}")
            raise

    def _process_sensor_data(self, data: Dict[str, Any]):
        """Process and store sensor data."""
        try:
            # Store sensor data
            sensor_data = {
                "temperatures": {
                    "sensor1": data["sensor1"]["celcius"],
                    "sensor2": data["sensor2"]["celcius"],
                    "sensor3": data["sensor3"]["celcius"],
                    "sensor4": data["sensor4"]["celcius"]
                },
                "averages": {
                    "temperature": data["rata_rata_suhu"],
                    "humidity": (data["dht1"]["humidity"] + data["dht2"]["humidity"]) / 2
                },
                "humidity": {
                    "dht1": data["dht1"]["humidity"],
                    "dht2": data["dht2"]["humidity"]
                }
            }
            
            db.reference("sensor").set(sensor_data)
            self.last_sensor_data = sensor_data
            
            # Automatic MCB control logic
            avg_temp = data["rata_rata_suhu"]
            if avg_temp >= TEMPERATURE_THRESHOLDS['high']:
                self._control_mcb(False)
            elif avg_temp <= TEMPERATURE_THRESHOLDS['low']:
                self._control_mcb(True)
                
        except Exception as e:
            self._log_error(f"Sensor data processing failed: {str(e)}")
            raise

    def run(self):
        """Main application loop."""
        while True:
            try:
                # Read from serial
                line = self.serial_conn.readline().decode().strip()
                
                if line.startswith("{") and line.endswith("}"):
                    try:
                        data = json.loads(line)
                        self._process_sensor_data(data)
                    except json.JSONDecodeError as e:
                        self._log_error(f"Invalid JSON data: {str(e)}")
                
                # Update Tuya status periodically
                self._read_tuya_status()
                time.sleep(POLLING_INTERVAL)
                
            except serial.SerialException as e:
                self._log_error(f"Serial communication error: {str(e)}")
                time.sleep(10)  # Wait longer before retrying
            except Exception as e:
                self._log_error(f"Unexpected error in main loop: {str(e)}")
                time.sleep(5)

if __name__ == "__main__":
    try:
        controller = MCBController()
        controller.run()
    except KeyboardInterrupt:
        print("\nApplication terminated by user")
    except Exception as e:
        print(f"Fatal error: {str(e)}")
