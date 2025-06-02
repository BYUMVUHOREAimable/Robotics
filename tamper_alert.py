import time
import csv
from datetime import datetime
import os
import json
from flask_socketio import SocketIO
import threading

class TamperAlertSystem:
    def __init__(self, socketio):
        self.socketio = socketio
        self.incident_log_file = "incident_log.csv"
        self.initialize_log_file()
        self.running = False
        self.alert_thread = None

    def initialize_log_file(self):
        """Initialize the incident log file if it doesn't exist"""
        if not os.path.exists(self.incident_log_file):
            with open(self.incident_log_file, "w", newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Plate", "Location", "Reason", "Timestamp"])

    def is_manual_tampering_detected(self):
        """Simulate or detect manual tampering"""
        # TODO: Replace with actual GPIO or serial logic from Arduino
        return False

    def log_incident(self, plate, location, reason):
        """Log an incident to the CSV file and emit socket event"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Log to CSV
        with open(self.incident_log_file, "a", newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                plate if plate else "UNKNOWN",
                location,
                reason,
                timestamp
            ])
        
        # Emit socket event
        self.socketio.emit('new_incident', {
            'plate': plate if plate else "UNKNOWN",
            'location': location,
            'reason': reason,
            'timestamp': timestamp
        })
        
        print(f"[ALERT] Logged: {plate}, {location}, {reason}")

    def activate_buzzer(self):
        """Activate the alarm buzzer"""
        print("[BUZZER] Manual tampering detected! Activating alarm...")
        # TODO: Replace with Arduino serial/buzzer control
        # e.g., arduino.write(b'2')
        
        # Emit socket event for buzzer activation
        self.socketio.emit('buzzer_activated', {
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    def log_unauthorized_exit(self, plate):
        """Log an unauthorized exit attempt"""
        self.log_incident(plate, "EXIT", "Unauthorized Exit")
        self.activate_buzzer()

    def start_monitoring(self):
        """Start the tampering monitoring thread"""
        if not self.running:
            self.running = True
            self.alert_thread = threading.Thread(target=self._monitor_loop)
            self.alert_thread.daemon = True
            self.alert_thread.start()

    def stop_monitoring(self):
        """Stop the tampering monitoring thread"""
        self.running = False
        if self.alert_thread:
            self.alert_thread.join()

    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            if self.is_manual_tampering_detected():
                self.log_incident(None, "ENTRY", "Manual Gate Tampering")
                self.activate_buzzer()
                time.sleep(10)  # Prevent multiple triggers
            time.sleep(1)

    def get_incidents(self, limit=100):
        """Get recent incidents from the log file"""
        incidents = []
        if os.path.exists(self.incident_log_file):
            with open(self.incident_log_file, 'r') as f:
                reader = csv.reader(f)
                next(reader)  # Skip header
                incidents = list(reader)[-limit:]  # Get last 'limit' incidents
        return incidents 