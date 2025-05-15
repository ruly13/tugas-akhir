#!/usr/bin/env python3

import os
import serial
import time
import json
import requests
import logging
from datetime import datetime
from tuya_connector import TuyaOpenAPI
import firebase_admin
from firebase_admin import credentials
import tkinter as tk
from tkinter import ttk

# ----------------------------------
# KONFIGURASI LOGGING
# ----------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("sensor_log.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ----------------------------------
# DETEKSI GUI
# ----------------------------------
def create_gui():
    """Membuat dan menginisialisasi GUI jika DISPLAY tersedia"""
    try:
        root = tk.Tk()
        root.title("Monitoring Sensor IoT")
        root.geometry("500x350")
        
        frame = ttk.Frame(root, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        
        style = ttk.Style()
        style.configure("TLabel", font=("Helvetica", 12))
        
        label_title = ttk.Label(frame, text="SISTEM MONITORING SENSOR IOT", font=("Helvetica", 14, "bold"))
        label_title.pack(pady=(0, 20))
        
        label_data = ttk.Label(frame, text="Menunggu data...", justify="left")
        label_data.pack(pady=10, fill=tk.X)
        
        status_frame = ttk.Frame(frame)
        status_frame.pack(fill=tk.X, pady=10)
        status_label = ttk.Label(status_frame, text="Status: ", font=("Helvetica", 10, "bold"))
        status_label.pack(side=tk.LEFT)
        conn_status = ttk.Label(status_frame, text="Terhubung", foreground="green")
        conn_status.pack(side=tk.LEFT)
        
        return root, label_data, conn_status
    except Exception as e:
        logger.error(f"Gagal menginisialisasi GUI: {e}")
        return None, None, None

# ----------------------------------
# KONFIGURASI
# ----------------------------------

# Firebase Realtime Database
FIREBASE_URL = "https://tugas-akhir-gua-default-rtdb.asia-southeast1.firebasedatabase.app"

# Tuya API Credentials (Simpan di file konfigurasi terpisah pada lingkungan produksi)
TUYA_ACCESS_ID = "7khd4jcpdcwae3k7d8wj" 
TUYA_ACCESS_KEY = "393c22825c704470bc7486e9ff18dbd9"
TUYA_DEVICE_ID = "eb74ce20a4136aaf8cgwcn"

# Serial Port (ESP32)
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200

# Interval polling (detik)
POLLING_INTERVAL = 5

# ----------------------------------
# INISIALISASI FIREBASE
# ----------------------------------
def init_firebase():
    """Inisialisasi koneksi Firebase"""
    try:
        cred = credentials.Certificate("fb/service.json")
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_URL
        })
        logger.info("Firebase berhasil diinisialisasi")
        return True
    except Exception as e:
        logger.error(f"Gagal inisialisasi Firebase: {e}")
        return False

# ----------------------------------
# FUNGSI UPDATE FIREBASE
# ----------------------------------
def update_firebase(path, data):
    """Update data ke Firebase Realtime Database"""
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        response = requests.patch(url, json=data)
        if response.status_code == 200:
            logger.info(f"Firebase berhasil diupdate di '{path}'")
            return True
        else:
            logger.error(f"Gagal update Firebase: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error update Firebase: {e}")
        return False

# ----------------------------------
# INISIALISASI TUYA OPENAPI
# ----------------------------------
def init_tuya():
    """Inisialisasi koneksi ke Tuya API"""
    try:
        openapi = TuyaOpenAPI(
            "https://openapi.tuyaus.com",  # Western America Data Center
            TUYA_ACCESS_ID,
            TUYA_ACCESS_KEY
        )
        openapi.connect()
        logger.info("Tuya API berhasil terhubung")
        return openapi
    except Exception as e:
        logger.error(f"Gagal menginisialisasi Tuya API: {e}")
        return None

def get_tuya_data(openapi):
    """Mengambil data dari perangkat Tuya"""
    if not openapi:
        logger.error("Tuya API tidak terhubung")
        return {}
        
    try:
        response = openapi.get(f"/v1.0/iot-03/devices/{TUYA_DEVICE_ID}/status")
        logger.debug(f"Raw Tuya response: {json.dumps(response, indent=2)}")  

        if "result" not in response or not response.get("success", False):
            logger.error(f"Gagal ambil data Tuya: {response}")
            return {}

        # Inisialisasi dengan nilai default
        tuya_data = {
            "add_ele": 0.0,        # Total energi (kWh)
            "cur_power": 0.0,      # Daya saat ini (W)
            "switch_1": False      # Status saklar
        }

        # Proses setiap item dari hasil
        for item in response["result"]:
            code = item.get("code")
            value = item.get("value")

            if code == "add_ele":
                # Konversi nilai total energi
                try:
                    if isinstance(value, str):
                        tuya_data[code] = float(value.replace(',', '.'))
                    elif isinstance(value, (int, float)):
                        tuya_data[code] = float(value)
                    else:
                        logger.warning(f"Tipe tidak terduga untuk add_ele: {type(value).__name__}, nilai: {value}")
                        tuya_data[code] = float(str(value).replace(',', '.'))
                except (ValueError, TypeError) as e:
                    logger.error(f"Error konversi nilai add_ele '{value}': {e}")
            
            elif code == "cur_power":
                # Konversi nilai daya saat ini
                try:
                    if isinstance(value, (int, float)):
                        # Tuya mengirimkan nilai dalam format W/10 atau W/100
                        tuya_data[code] = float(value) / 100
                    elif isinstance(value, str):
                        tuya_data[code] = float(value.replace(',', '.')) / 100
                    else:
                        logger.warning(f"Tipe tidak terduga untuk cur_power: {type(value).__name__}, nilai: {value}")
                except (ValueError, TypeError) as e:
                    logger.error(f"Error konversi nilai cur_power '{value}': {e}")
            
            elif code == "switch_1":
                tuya_data[code] = bool(value)

        logger.info(f"Data Tuya yang diproses: {tuya_data}")
        return tuya_data
    except Exception as e:
        logger.error(f"Error Tuya API: {e}")
        return {}


def set_tuya_status(openapi, status: bool):
    """Menghidupkan atau mematikan switch Tuya"""
    if not openapi:
        logger.error("Tuya API tidak tersedia untuk set status.")
        return False
    try:
        response = openapi.post(
            f"/v1.0/iot-03/devices/{TUYA_DEVICE_ID}/commands",
            {
                "commands": [
                    {"code": "switch_1", "value": status}
                ]
            }
        )
        if response.get("success"):
            logger.info(f"Status perangkat Tuya berhasil di-set ke {'ON' if status else 'OFF'}")
            return True
        else:
            logger.error(f"Gagal mengubah status Tuya: {response}")
            return False
    except Exception as e:
        logger.error(f"Error saat mengubah status Tuya: {e}")
        return False


# ----------------------------------
# INISIALISASI KONEKSI SERIAL
# ----------------------------------
def init_serial():
    """Inisialisasi koneksi serial ke ESP32"""
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        logger.info(f"Serial ESP32 berhasil terhubung di {SERIAL_PORT}")
        return ser
    except Exception as e:
        logger.error(f"Gagal membuka koneksi serial: {e}")
        return None

# ----------------------------------
# PROSES DATA
# ----------------------------------
def process_sensor_data(line, tuya_api):
    """Memproses data sensor dari ESP32 dan Tuya"""
    try:
        # Parse JSON
        data = json.loads(line)
        
        # Validasi data ESP32
        required_fields = [
            "suhu_1", "suhu_2", "suhu_3", "suhu_4",
            "rata_suhu", "kelembaban_1", "kelembaban_2", "rata_kelembaban"
        ]
        
        if not all(field in data for field in required_fields):
            logger.warning("Data ESP32 tidak lengkap, dilewati.")
            return None
            
        # Tambahkan timestamp
        data["timestamp"] = datetime.now().isoformat()
        
        # Tambahkan data dari Tuya
        tuya_data = get_tuya_data(tuya_api)
        data.update(tuya_data)
        
        # Status ON/OFF
        data["pengering_status"] = "ON" if tuya_data.get("switch_1") else "OFF"
        
        # Log data yang sudah lengkap
        logger.info(f"Data sensor lengkap: {json.dumps(data)}")
        
        return data
    except json.JSONDecodeError:
        logger.warning("Format JSON salah, dilewati.")
        return None
    except Exception as e:
        logger.error(f"Error saat memproses data: {e}")
        return None

# ----------------------------------
# FUNGSI UTAMA
# ----------------------------------
def main():
    """Fungsi utama program"""
    # Inisialisasi komponen
    init_firebase()
    tuya_api = init_tuya()
    ser = init_serial()
    
    if not ser:
        logger.critical("Tidak dapat melanjutkan tanpa koneksi serial!")
        return
    
    # Inisialisasi GUI jika tersedia
    use_gui = bool(os.environ.get("DISPLAY"))
    root, label_data, conn_status = (None, None, None)
    
    if use_gui:
        root, label_data, conn_status = create_gui()
        
    # Main loop
    try:
        last_update_time = 0
        while True:
            try:
                # Baca data dari serial
                line = ser.readline().decode('utf-8').strip()
                if not line:
                    continue
                
                logger.debug(f"Data dari ESP32: {repr(line)}")
                
                # Log raw data
                with open("sensor_raw_log.txt", "a") as log_file:
                    log_file.write(f"{datetime.now().isoformat()} - RAW: {line}\n")
                
                # Proses data
                data = process_sensor_data(line, tuya_api)
                if not data:
                    continue
                
                # Kirim ke Firebase
                update_firebase("sensor", data)
                
                # Update GUI jika tersedia
                if use_gui and root and label_data:
                    tampil = (
                        f"Suhu Rata-rata: {data.get('rata_suhu', '-')} °C\n"
                        f"Kelembapan Rata-rata: {data.get('rata_kelembaban', '-')} %\n"
                        f"Daya Saat Ini: {data.get('cur_power', '-')} W\n"
                        f"Total Energi: {data.get('add_ele', '-')} kWh\n"
                        f"Status Pengering: {data.get('pengering_status', '-')}\n"
                        f"Waktu Update: {datetime.now().strftime('%H:%M:%S')}"
                    )
                    label_data.config(text=tampil)
                    root.update_idletasks()
                
                # Update GUI
                if use_gui and root:
                    root.update()
                
                # Throttle untuk mencegah terlalu banyak polling
                current_time = time.time()
                if current_time - last_update_time < POLLING_INTERVAL:
                    time.sleep(0.1)
                else:
                    last_update_time = current_time
                    time.sleep(POLLING_INTERVAL)
                    
            except json.JSONDecodeError:
                logger.warning("Format JSON salah, dilewati.")
            except Exception as e:
                logger.error(f"Error saat memproses data: {e}")
                time.sleep(1)
                
    except KeyboardInterrupt:
        logger.info("Program dihentikan oleh pengguna.")
    finally:
        # Pembersihan resources
        if ser:
            ser.close()
            logger.info("Koneksi serial ditutup.")
        
        if tuya_api:
            set_tuya_status(tuya_api, False)  # 🔌 Matikan Tuya saat keluar
        
        if use_gui and root:
            root.quit()
            logger.info("GUI ditutup.")

# ----------------------------------
# EKSEKUSI PROGRAM
# ----------------------------------
if __name__ == "__main__":
    logger.info("Memulai program monitoring sensor IoT")
    main()
