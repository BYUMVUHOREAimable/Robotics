import serial
import time
import csv
from datetime import datetime
# Configure the serial port (adjust 'COM14' to your Arduino's port)
ser = serial.Serial('COM10', 9600, timeout=1)
time.sleep(2)  # Wait for serial to initialize
def print_boxed_message(message, border_char="=", width=50):
    """Helper function to print a message in a boxed format."""
    border = border_char * width
    padding = " " * ((width - len(message) - 2) // 2)
    print(border)
    print(f"|{padding}{message}{padding}{' ' if len(message) % 2 else ''}|")
    print(border)
def get_timestamp():
    """Return the current timestamp in a formatted string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def read_last_unpaid_entry(plate):
    """Read the last unpaid entry (Payment Status = 0) for a given plate from plates_log.csv."""
    try:
        with open('plates_log.csv', 'r') as file:
            reader = csv.DictReader(file)
            entries = [row for row in reader if row['Plate Number'] == plate and row['Payment Status'] == '0']
            if not entries:
                return None
            return entries[-1]  # Return the last unpaid entry
    except FileNotFoundError:
        print_boxed_message("Error: File Not Found", "!")
        print(f"[{get_timestamp()}] plates_log.csv not found. Creating a new one.\n")
        with open('plates_log.csv', 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Plate Number', 'Payment Status', 'Timestamp', 'Payment Timestamp'])
        return None
    except Exception as e:
        print_boxed_message("Error: CSV Read Failed", "!")
        print(f"[{get_timestamp()}] {e}\n")
        return None
def update_payment_status(plate, entry_timestamp):
    """Update the Payment Status to 1 and log the payment timestamp."""
    try:
        rows = []
        payment_time = get_timestamp()  # Exact time of payment
        with open('plates_log.csv', 'r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row['Plate Number'] == plate and row['Timestamp'] == entry_timestamp and row['Payment Status'] == '0':
                    row['Payment Status'] = '1'
                    row['Payment Timestamp'] = payment_time
                rows.append(row)
        with open('plates_log.csv', 'w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=['Plate Number', 'Payment Status', 'Timestamp', 'Payment Timestamp'])
            writer.writeheader()
            writer.writerows(rows)
        return payment_time
    except Exception as e:
        print_boxed_message("Error: CSV Update Failed", "!")
        print(f"[{get_timestamp()}] {e}\n")
        return None
try:
    print_boxed_message("Python Parking System Ready", "=")
    print(f"[{get_timestamp()}] Waiting for Arduino data...\n")
    while True:
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8').strip()
            if line.startswith("DATA:"):
                print(line)
                # Parse the data
                plate, cash = line[5:].split(',')
                cash = int(cash)
                # Display received data
                print_boxed_message("Data Received from Arduino", "-")
                print(f"[{get_timestamp()}] Details:")
                print(f"  License Plate: {plate}")
                print(f"  Current Balance: {cash} units\n")
                # Check if cash is more than 200
                if cash <= 200:
                    print_boxed_message("Error: Insufficient Balance", "!")
                    print(f"[{get_timestamp()}] Balance ({cash} units) must be > 200 units.\n")
                    continue
                # Read the last unpaid entry for the plate
                last_entry = read_last_unpaid_entry(plate)
                if last_entry is None:
                    print_boxed_message("Warning: No Unpaid Entry Found", "!")
                    print(f"[{get_timestamp()}] No unpaid entry for plate {plate}. Assuming 0 hours.\n")
                    hours = 0
                else:
                    entry_time = datetime.strptime(last_entry['Timestamp'], "%Y-%m-%d %H:%M:%S")
                    current_time = datetime.now()
                    time_diff = current_time - entry_time
                    hours = time_diff.total_seconds() / 3600  # Convert to hours
                # Calculate charge (100 units per 30 min after first 30 min)
                minutes = hours * 60
                charge = 0
                if minutes > 30:
                    charge = ((minutes - 30 + 29) // 30) * 100
                if charge > cash:
                    print_boxed_message("Error: Charge Exceeds Balance", "!")
                    print(f"[{get_timestamp()}] Charge ({charge} units) exceeds balance ({cash} units).\n")
                    continue
                # Send charge to Arduino
                ser.write(f"CHARGE:{charge}\n".encode())
                print_boxed_message("Data Sent to Arduino", "-")
                print(f"[{get_timestamp()}] Transaction Details:")
                print(f"  License Plate: {plate}")
                print(f"  Parking Duration: {hours:.2f} hours")
                print(f"  Charge Amount: {charge} units\n")
                # Wait for DONE signal
                response = ser.readline().decode('utf-8').strip()
                if response == "DONE":
                    if last_entry:
                        payment_time = update_payment_status(plate, last_entry['Timestamp'])
                        if payment_time:
                            print_boxed_message("Payment Processed", "-")
                            print(f"[{get_timestamp()}] Payment Details:")
                            print(f"  Payment Timestamp: {payment_time}")
                            print(f"  Updated Balance: {cash - charge} units\n")
                    print_boxed_message("Transaction Successful", "=")
                    print(f"[{get_timestamp()}] Gate is opening...\n")
                else:
                    print_boxed_message("Error: Arduino Response", "!")
                    print(f"[{get_timestamp()}] Unexpected response: {response}\n")
        time.sleep(0.1)  # Small delay to prevent overwhelming the loop
except KeyboardInterrupt:
    print("\n" + "=" * 50)
    print(f"[{get_timestamp()}] Program terminated by user.")
    print("=" * 50)
    ser.close()
except Exception as e:
    print("\n" + "=" * 50)
    print(f"[{get_timestamp()}] An error occurred: {e}")
    print("=" * 50)
    ser.close()
finally:
    ser.close()