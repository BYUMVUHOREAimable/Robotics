import cv2
from ultralytics import YOLO
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
import os
import time
import serial
import serial.tools.list_ports
import csv
from collections import Counter
import random

# Load YOLOv8 model (same model as entry)
model = YOLO(r'best.pt')

# CSV log file
csv_file = 'plates_log.csv'

# ===== Auto-detect Arduino Serial Port =====
def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        if "Arduino" in port.description or "COM10" in port.description or "USB-SERIAL" in port.description:
            return port.device
    return None

arduino_port = detect_arduino_port()
if arduino_port:
    print(f"[CONNECTED] Arduino on {arduino_port}")
    arduino = serial.Serial(arduino_port, 9600, timeout=1)
    time.sleep(2)
else:
    print("[ERROR] Arduino not detected.")
    arduino = None

# ===== Ultrasonic Sensor (mock for now) =====
def mock_ultrasonic_distance():
    return random.choice([random.randint(10, 40)])

# ===== Check payment status in CSV =====
def is_payment_complete(plate_number):
    if not os.path.exists(csv_file):
        return False
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['Plate Number'] == plate_number and row['Payment Status'] == '1':
                return True
    return False

# ===== Webcam and Main Loop =====
cap = cv2.VideoCapture(0)
plate_buffer = []

print("[EXIT SYSTEM] Ready. Press 'q' to quit.")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    distance = mock_ultrasonic_distance()
    print(f"[SENSOR] Distance: {distance} cm")

    if distance <= 50:
        results = model(frame)

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_img = frame[y1:y2, x1:x2]

                # Preprocessing
                gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

                # OCR
                plate_text = pytesseract.image_to_string(
                    thresh, config='--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                ).strip().replace(" ", "")

                if "RA" in plate_text:
                    start_idx = plate_text.find("RA")
                    plate_candidate = plate_text[start_idx:]
                    if len(plate_candidate) >= 7:
                        plate_candidate = plate_candidate[:7]
                        prefix, digits, suffix = plate_candidate[:3], plate_candidate[3:6], plate_candidate[6]
                        if (prefix.isalpha() and prefix.isupper() and
                            digits.isdigit() and suffix.isalpha() and suffix.isupper()):
                            print(f"[VALID] Plate Detected: {plate_candidate}")
                            plate_buffer.append(plate_candidate)

                            if len(plate_buffer) >= 3:
                                most_common = Counter(plate_buffer).most_common(1)[0][0]
                                plate_buffer.clear()

                                if is_payment_complete(most_common):
                                    print(f"[ACCESS GRANTED] Payment complete for {most_common}")
                                    if arduino:
                                        arduino.write(b'1')  # Open gate
                                        print("[GATE] Opening gate (sent '1')")
                                        time.sleep(15)
                                        arduino.write(b'0')  # Close gate
                                        print("[GATE] Closing gate (sent '0')")
                                else:
                                    print(f"[ACCESS DENIED] Payment NOT complete for {most_common}")
                                    if arduino:
                                        arduino.write(b'2')  # Trigger warning buzzer
                                        print("[ALERT] Buzzer triggered (sent '2')")

                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                time.sleep(0.5)

    annotated_frame = results[0].plot() if distance <= 50 else frame
    cv2.imshow("Exit Webcam Feed", annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()