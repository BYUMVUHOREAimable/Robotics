import csv
import serial
import time
import serial.tools.list_ports
import platform
from datetime import datetime

CSV_FILE = 'plates_log.csv'
RATE_PER_MINUTE = 5  # Amount charged per minute


def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    system = platform.system()
    for port in ports:
        if system == "Linux":
            if "ttyUSB" in port.device or "ttyACM" in port.device:
                return port.device
        elif system == "Darwin":
            if "usbmodem" in port.device or "usbserial" in port.device:
                return port.device
        elif system == "Windows":
            if "COM12" in port.device:
                return port.device
    return None


def parse_arduino_data(line):
    try:
        parts = line.strip().split(',')
        print(f"[ARDUINO] Parsed parts: {parts}")
        if len(parts) != 2:
            return None, None
        plate = parts[0].strip()

        # Clean the balance string by removing non-digit characters
        balance_str = ''.join(c for c in parts[1] if c.isdigit())
        print(f"[ARDUINO] Cleaned balance: {balance_str}")

        if balance_str:
            balance = int(balance_str)
            return plate, balance
        else:
            return None, None
    except ValueError as e:
        print(f"[ERROR] Value error in parsing: {e}")
        return None, None


def process_payment(plate, balance, ser):
    try:
        with open(CSV_FILE, 'r') as f:
            rows = list(csv.reader(f))

        header = rows[0]
        entries = rows[1:]
        found = False

        for i, row in enumerate(entries):
            if row[0] == plate and row[1] == '0':
                found = True
                entry_time_str = row[2]
                entry_time = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
                exit_time = datetime.now()
                minutes_spent = int((exit_time - entry_time).total_seconds() / 60) + 1
                amount_due = minutes_spent * RATE_PER_MINUTE

                #Ensure the row has 4 columns (including the Payment Timestamp)
                if len(entries[i]) < 4:
                    entries[i].append(exit_time.strftime('%Y-%m-%d %H:%M:%S'))
                else:
                    entries[i][3] = exit_time.strftime('%Y-%m-%d %H:%M:%S')


                if balance < amount_due:
                    print("[PAYMENT] Insufficient balance")
                    ser.write(b'I\n')
                    return
                else:
                    new_balance = balance - amount_due

                    # Wait for Arduino to send "READY"
                    print("[WAIT] Waiting for Arduino to be READY...")
                    start_time = time.time()
                    while True:
                        if ser.in_waiting:
                            arduino_response = ser.readline().decode().strip()
                            print(f"[ARDUINO] {arduino_response}")
                            if arduino_response == "READY":
                                break
                        if time.time() - start_time > 5:
                            print("[ERROR] Timeout waiting for Arduino READY")
                            return

                    # Send new balance
                    ser.write(f"{new_balance}\r\n".encode())  # more universal
                    print(f"[PAYMENT] Sent new balance {new_balance}")

                    # Wait for confirmation with timeout
                    start_time = time.time()
                    print("[WAIT] Waiting for Arduino confirmation...")
                    while True:
                        if ser.in_waiting:
                            confirm = ser.readline().decode().strip()
                            print(f"[ARDUINO] {confirm}")
                            if "DONE" in confirm:
                                print("[ARDUINO] Write confirmed")
                                entries[i][1] = '1'
                                break

                        # Add timeout condition
                        if time.time() - start_time > 10:
                            print("[ERROR] Timeout waiting for confirmation")
                            break

                        # Small delay to avoid CPU spinning
                        time.sleep(0.1)

                break

        if not found:
            print("[PAYMENT] Plate not found or already paid.")
            return

        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(entries)

    except Exception as e:
        print(f"[ERROR] Payment processing failed: {e}")


def main():
    port = detect_arduino_port()
    if not port:
        print("[ERROR] Arduino not found")
        return

    try:
        ser = serial.Serial(port, 9600, timeout=1)
        print(f"[CONNECTED] Listening on {port}")
        time.sleep(2)

        # Flush any previous data
        ser.reset_input_buffer()

        while True:
            if ser.in_waiting:
                line = ser.readline().decode().strip()
                print(f"[SERIAL] Received: {line}")
                plate, balance = parse_arduino_data(line)
                if plate and balance is not None:
                    process_payment(plate, balance, ser)

    except KeyboardInterrupt:
        print("[EXIT] Program terminated")
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        if 'ser' in locals():
            ser.close()


if __name__ == "__main__":
    main()