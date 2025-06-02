from flask import Flask, render_template, jsonify, request, session
from flask_socketio import SocketIO
import sqlite3
from datetime import datetime, timedelta
import json
import pandas as pd
import os
import math
from functools import wraps
import jwt
import sys
import random
from tamper_alert import TamperAlertSystem

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Change this to a secure secret key
socketio = SocketIO(app)
alert_system = TamperAlertSystem(socketio)

# Constants
HOURLY_RATE = 500  # RWF per hour
GATE_TYPES = {
    'entry': 'Entry Gate',
    'exit': 'Exit Gate'
}

ALERT_TYPES = {
    'gate_tampering': 'Gate Tampering',
    'unauthorized_exit': 'Unauthorized Exit',
    'payment_pending': 'Payment Pending',
    'system_error': 'System Error'
}

# User roles
ROLES = {
    'admin': ['read', 'write', 'delete', 'manage_users'],
    'operator': ['read', 'write'],
    'viewer': ['read']
}

# Sample users (in production, use a proper user database)
USERS = {
    'admin': {
        'password': 'admin123',  # In production, use hashed passwords
        'role': 'admin'
    },
    'operator': {
        'password': 'operator123',
        'role': 'operator'
    },
    'viewer': {
        'password': 'viewer123',
        'role': 'viewer'
    }
}

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        try:
            token = token.split(' ')[1]  # Remove 'Bearer ' prefix
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = USERS.get(data['username'])
            if not current_user:
                return jsonify({'message': 'Invalid token!'}), 401
        except:
            return jsonify({'message': 'Invalid token!'}), 401
        return f(current_user, *args, **kwargs)
    return decorated

def role_required(required_permissions):
    def decorator(f):
        @wraps(f)
        def decorated(current_user, *args, **kwargs):
            user_role = current_user['role']
            user_permissions = ROLES.get(user_role, [])
            
            if not all(perm in user_permissions for perm in required_permissions):
                return jsonify({'message': 'Insufficient permissions!'}), 403
            return f(current_user, *args, **kwargs)
        return decorated
    return decorator

@app.route('/api/login', methods=['POST'])
def login():
    print("Login attempt...")
    auth = request.json
    if not auth or not auth.get('username') or not auth.get('password'):
        print("Missing credentials")
        return jsonify({'message': 'Could not verify!'}), 401

    user = USERS.get(auth.get('username'))
    if not user or user['password'] != auth.get('password'):
        print("Invalid credentials")
        return jsonify({'message': 'Invalid credentials!'}), 401

    token = jwt.encode({
        'username': auth.get('username'),
        'exp': datetime.utcnow() + timedelta(hours=24)
    }, app.config['SECRET_KEY'])

    print(f"Login successful for user: {auth.get('username')}")
    return jsonify({
        'token': token,
        'role': user['role']
    })

# Database setup
def init_db():
    """Initialize the database with required tables and sample data"""
    conn = None
    try:
        # Remove existing database file if it exists
        if os.path.exists('database.db'):
            os.remove('database.db')
            print("Removed existing database file")
        
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Create main logs table with all required columns
        cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT,
            entry_time TEXT,
            exit_time TEXT,
            paid INTEGER DEFAULT 0,
            payment_amount REAL DEFAULT 0,
            payment_time TEXT,
            duration_hours REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            gate_location TEXT DEFAULT 'entry'
        )''')
        
        # Create statistics table
        cursor.execute('''CREATE TABLE IF NOT EXISTS statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_vehicles INTEGER DEFAULT 0,
            current_vehicles INTEGER DEFAULT 0,
            total_revenue REAL DEFAULT 0,
            last_updated TEXT
        )''')
        
        # Create alerts table
        cursor.execute('''CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT,
            alert_type TEXT,
            timestamp TEXT,
            gate_location TEXT,
            description TEXT,
            resolved INTEGER DEFAULT 0
        )''')
        
        conn.commit()
        print("Database tables created successfully")
        
        # Create sample data
        sample_plates = ['ABC123', 'XYZ789', 'DEF456', 'GHI789', 'JKL012']
        current_time = datetime.now()
        
        # Insert sample vehicle entries
        for plate in sample_plates:
            entry_time = (current_time - timedelta(hours=random.randint(1, 5))).strftime('%Y-%m-%d %H:%M:%S')
            is_paid = random.choice([True, False])
            
            if is_paid:
                exit_time = current_time.strftime('%Y-%m-%d %H:%M:%S')
                duration = random.uniform(1, 5)
                payment_amount = math.ceil(duration) * HOURLY_RATE
                status = 'exit'
            else:
                exit_time = None
                duration = 0
                payment_amount = 0
                status = 'active'
            
            cursor.execute('''
                INSERT INTO logs 
                (plate, entry_time, exit_time, paid, payment_amount, duration_hours, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                plate,
                entry_time,
                exit_time,
                is_paid,
                payment_amount,
                duration,
                status
            ))
        
        # Create sample alerts
        alert_types = ['gate_tampering', 'unauthorized_exit', 'system_error']
        locations = ['entry', 'exit']
        
        for _ in range(3):
            alert_type = random.choice(alert_types)
            location = random.choice(locations)
            plate = random.choice(sample_plates)
            timestamp = (current_time - timedelta(minutes=random.randint(1, 60))).strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
                INSERT INTO alerts 
                (plate, alert_type, timestamp, gate_location, description, resolved)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                plate,
                alert_type,
                timestamp,
                location,
                f'Sample {alert_type} alert at {location} gate',
                random.choice([0, 1])
            ))
        
        conn.commit()
        print("Sample data created successfully")
        
        # Update statistics
        update_statistics()
        
        print("Database initialization completed successfully")
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def calculate_payment_amount(entry_time, exit_time):
    """Calculate payment amount based on duration"""
    try:
        entry = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
        exit = datetime.strptime(exit_time, '%Y-%m-%d %H:%M:%S')
        
        # Ensure exit time is after entry time
        if exit < entry:
            exit = entry + timedelta(hours=1)  # Default to 1 hour if exit time is before entry
        
        duration = exit - entry
        hours = max(1, math.ceil(duration.total_seconds() / 3600))  # Minimum 1 hour, round up
        return hours * HOURLY_RATE
    except Exception as e:
        print(f"Error calculating payment: {str(e)}")
        return HOURLY_RATE  # Return minimum payment if calculation fails

def import_csv_data():
    """Import data from CSV or create sample data"""
    conn = None
    try:
        if not os.path.exists('plates_log.csv'):
            print("CSV file not found. Creating sample data...")
            # Create sample CSV data
            sample_data = {
                'Plate Number': [],
                'Timestamp': [],
                'Payment Status': [],
                'Payment Timestamp': []
            }
            
            # Generate sample entries
            sample_plates = ['ABC123', 'XYZ789', 'DEF456', 'GHI789', 'JKL012']
            current_time = datetime.now()
            
            for plate in sample_plates:
                entry_time = current_time - timedelta(hours=random.randint(1, 5))
                is_paid = random.choice([True, False])
                payment_time = entry_time + timedelta(hours=random.randint(1, 3)) if is_paid else None
                
                sample_data['Plate Number'].append(plate)
                sample_data['Timestamp'].append(entry_time.strftime('%Y-%m-%d %H:%M:%S'))
                sample_data['Payment Status'].append(1 if is_paid else 0)
                sample_data['Payment Timestamp'].append(payment_time.strftime('%Y-%m-%d %H:%M:%S') if payment_time else None)
            
            # Create DataFrame and save to CSV
            df = pd.DataFrame(sample_data)
            df.to_csv('plates_log.csv', index=False)
            print("Sample CSV data created successfully")
        
        # Read and import CSV data
        print("Reading CSV data...")
        df = pd.read_csv('plates_log.csv')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Clear existing data
        cursor.execute("DELETE FROM logs")
        cursor.execute("DELETE FROM statistics")
        cursor.execute("DELETE FROM alerts")
        
        # Convert timestamp columns to datetime
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df['Payment Timestamp'] = pd.to_datetime(df['Payment Timestamp'], errors='coerce')
        
        # Insert data into database
        for _, row in df.iterrows():
            entry_time = row['Timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            
            # Handle payment status and timestamps
            is_paid = row['Payment Status'] == 1
            payment_time = None
            exit_time = None
            duration = 0
            payment_amount = 0
            
            if is_paid and pd.notna(row['Payment Timestamp']):
                payment_time = row['Payment Timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                exit_time = payment_time
                duration = max(0, (row['Payment Timestamp'] - row['Timestamp']).total_seconds() / 3600)
                payment_amount = max(HOURLY_RATE, math.ceil(duration) * HOURLY_RATE)
            
            # Determine status based on payment
            status = 'exit' if is_paid else 'active'
            
            cursor.execute('''
                INSERT INTO logs 
                (plate, entry_time, exit_time, payment_time, paid, payment_amount, duration_hours, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                row['Plate Number'],
                entry_time,
                exit_time,
                payment_time,
                is_paid,
                payment_amount,
                duration,
                status
            ))
        
        # Create sample alerts
        alert_types = ['gate_tampering', 'unauthorized_exit', 'system_error']
        locations = ['entry', 'exit']
        
        for _ in range(3):
            alert_type = random.choice(alert_types)
            location = random.choice(locations)
            plate = random.choice(sample_plates)
            timestamp = (current_time - timedelta(minutes=random.randint(1, 60))).strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
                INSERT INTO alerts 
                (plate, alert_type, timestamp, gate_location, description, resolved)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                plate,
                alert_type,
                timestamp,
                location,
                f'Sample {alert_type} alert at {location} gate',
                random.choice([0, 1])
            ))
        
        conn.commit()
        print("CSV data imported successfully")
        
        # Update statistics
        update_statistics()
        
    except Exception as e:
        print(f"Error importing data: {str(e)}")
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

def create_sample_data(conn, cursor):
    """Create sample data for testing"""
    try:
        # Create sample vehicle entries
        sample_plates = ['ABC123', 'XYZ789', 'DEF456', 'GHI789', 'JKL012']
        current_time = datetime.now()
        
        for plate in sample_plates:
            entry_time = (current_time - timedelta(hours=random.randint(1, 5))).strftime('%Y-%m-%d %H:%M:%S')
            is_paid = random.choice([True, False])
            
            if is_paid:
                exit_time = current_time.strftime('%Y-%m-%d %H:%M:%S')
                duration = random.uniform(1, 5)
                payment_amount = math.ceil(duration) * HOURLY_RATE
                status = 'exit'
            else:
                exit_time = None
                duration = 0
                payment_amount = 0
                status = 'active'
            
            cursor.execute('''
                INSERT INTO logs 
                (plate, entry_time, exit_time, paid, payment_amount, duration_hours, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                plate,
                entry_time,
                exit_time,
                is_paid,
                payment_amount,
                duration,
                status
            ))
        
        # Create sample alerts
        alert_types = ['gate_tampering', 'unauthorized_exit', 'system_error']
        locations = ['entry', 'exit']
        
        for _ in range(3):
            alert_type = random.choice(alert_types)
            location = random.choice(locations)
            plate = random.choice(sample_plates)
            timestamp = (current_time - timedelta(minutes=random.randint(1, 60))).strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
                INSERT INTO alerts 
                (plate, alert_type, timestamp, gate_location, description, resolved)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                plate,
                alert_type,
                timestamp,
                location,
                f'Sample {alert_type} alert at {location} gate',
                random.choice([0, 1])
            ))
        
        # Update statistics
        update_statistics()
        
        print("Sample data created successfully")
    except Exception as e:
        print(f"Error creating sample data: {str(e)}")
        raise e

def update_statistics():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get total vehicles
    cursor.execute("SELECT COUNT(*) FROM logs")
    total_vehicles = cursor.fetchone()[0]
    
    # Get currently parked vehicles
    cursor.execute("SELECT COUNT(*) FROM logs WHERE status = 'active'")
    current_vehicles = cursor.fetchone()[0]
    
    # Get total revenue
    cursor.execute("SELECT SUM(payment_amount) FROM logs WHERE paid = 1")
    total_revenue = cursor.fetchone()[0] or 0
    
    # Update statistics table
    cursor.execute('''
        INSERT INTO statistics (total_vehicles, current_vehicles, total_revenue, last_updated)
        VALUES (?, ?, ?, ?)
    ''', (total_vehicles, current_vehicles, total_revenue, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    conn.close()

def update_csv_exit_time(plate, exit_time):
    """Update the exit time in plates_log.csv for the given plate"""
    try:
        # Read existing CSV data
        df = pd.read_csv('plates_log.csv')
        
        # Find the last entry for this plate
        mask = df['Plate Number'] == plate
        if mask.any():
            # Update the last entry's Payment Timestamp with exit time
            df.loc[mask.idxmax(), 'Payment Timestamp'] = exit_time
            df.loc[mask.idxmax(), 'Payment Status'] = 1  # Mark as paid
            
            # Save back to CSV
            df.to_csv('plates_log.csv', index=False)
            print(f"Updated exit time for {plate} in CSV")
    except Exception as e:
        print(f"Error updating CSV: {str(e)}")

def log_alert(plate, alert_type, gate_location, description):
    """Log an alert to the database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        cursor.execute('''
            INSERT INTO alerts (plate, alert_type, timestamp, gate_location, description)
            VALUES (?, ?, ?, ?, ?)
        ''', (plate, alert_type, timestamp, gate_location, description))
        conn.commit()
        
        # Emit socket event for real-time alert
        socketio.emit('new_alert', {
            'plate': plate,
            'alert_type': alert_type,
            'timestamp': timestamp,
            'gate_location': gate_location,
            'description': description
        })
    except Exception as e:
        print(f"Error logging alert: {str(e)}")
    finally:
        conn.close()

@app.route('/')
def dashboard():
    return render_template("dashboard.html")

@app.route('/api/logs')
@token_required
@role_required(['read'])
def get_logs(current_user):
    """Get paginated logs with search"""
    print("Fetching logs...")
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    plate_search = request.args.get('plate', '')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Base query
        query = "SELECT * FROM logs"
        count_query = "SELECT COUNT(*) FROM logs"
        params = []
        
        # Add search condition if plate number is provided
        if plate_search:
            query += " WHERE plate LIKE ?"
            count_query += " WHERE plate LIKE ?"
            params.append(f'%{plate_search}%')
        
        # Add pagination
        query += " ORDER BY entry_time DESC LIMIT ? OFFSET ?"
        params.extend([per_page, (page - 1) * per_page])
        
        # Get total count
        cursor.execute(count_query, params[:-2] if plate_search else [])
        total_count = cursor.fetchone()[0]
        
        # Get paginated results
        cursor.execute(query, params)
        logs = [dict(row) for row in cursor.fetchall()]
        
        print(f"Retrieved {len(logs)} logs")
        return jsonify({
            'logs': logs,
            'pagination': {
                'total': total_count,
                'pages': math.ceil(total_count / per_page),
                'current_page': page,
                'per_page': per_page
            }
        })
    except Exception as e:
        print(f"Error fetching logs: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/stats')
def get_stats():
    """Get current statistics"""
    print("Fetching stats...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get latest statistics
        cursor.execute("""
            SELECT * FROM statistics 
            ORDER BY last_updated DESC 
            LIMIT 1
        """)
        stats = cursor.fetchone()
        
        if not stats:
            print("No stats found, calculating new stats...")
            # If no statistics exist, calculate them
            update_statistics()
            cursor.execute("""
                SELECT * FROM statistics 
                ORDER BY last_updated DESC 
                LIMIT 1
            """)
            stats = cursor.fetchone()
        
        print(f"Stats retrieved: {dict(stats)}")
        return jsonify({
            'total_vehicles': stats['total_vehicles'],
            'current_vehicles': stats['current_vehicles'],
            'total_revenue': stats['total_revenue'],
            'last_updated': stats['last_updated']
        })
    except Exception as e:
        print(f"Error fetching stats: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/register_vehicle', methods=['POST'])
def register_vehicle():
    data = request.json
    plate = data.get('plate')
    entry_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if vehicle is already active
        cursor.execute("""
            SELECT id FROM logs 
            WHERE plate = ? AND status = 'active'
        """, (plate,))
        existing = cursor.fetchone()
        
        if existing:
            # Log alert for duplicate entry attempt
            log_alert(
                plate,
                'system_error',
                'entry',
                f'Duplicate entry attempt for vehicle {plate}'
            )
            return jsonify({
                'status': 'error',
                'message': 'Vehicle is already registered and active'
            })
        
        # Register new vehicle
        cursor.execute(
            """INSERT INTO logs 
               (plate, entry_time, status, paid, payment_amount, duration_hours) 
               VALUES (?, ?, 'active', 0, 0, 0)""",
            (plate, entry_time)
        )
        conn.commit()
        
        # Update statistics
        update_statistics()
        
        # Emit socket event
        socketio.emit('new_vehicle', {
            'plate': plate,
            'entry_time': entry_time
        })
        
        return jsonify({
            'status': 'success',
            'entry_time': entry_time
        })
    except Exception as e:
        print(f"Error registering vehicle: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Error registering vehicle'})
    finally:
        conn.close()

@app.route('/api/process_exit', methods=['POST'])
def process_exit():
    data = request.json
    plate = data.get('plate')
    
    if not plate:
        return jsonify({'status': 'error', 'message': 'Plate number is required'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if vehicle exists and has paid
    cursor.execute('''
        SELECT id, entry_time, payment_amount, paid FROM logs 
        WHERE plate = ? AND status = 'active'
    ''', (plate,))
    
    vehicle = cursor.fetchone()
    
    if not vehicle:
        conn.close()
        return jsonify({'status': 'error', 'message': 'No active vehicle found with this plate number'}), 404
    
    try:
        # Check if payment is pending
        if not vehicle['paid']:
            # Log unauthorized exit attempt
            alert_system.log_unauthorized_exit(plate)
            return jsonify({
                'status': 'error',
                'message': 'Payment pending. Cannot process exit.'
            }), 403
        
        # Update exit time and status
        current_time = datetime.now()
        entry_time = datetime.strptime(vehicle['entry_time'], '%Y-%m-%d %H:%M:%S')
        duration = (current_time - entry_time).total_seconds() / 3600
        
        cursor.execute('''
            UPDATE logs 
            SET exit_time = ?, status = 'exit', duration_hours = ?
            WHERE id = ?
        ''', (current_time.strftime('%Y-%m-%d %H:%M:%S'), duration, vehicle['id']))
        
        conn.commit()
        
        # Update CSV with exit time
        update_csv_exit_time(plate, current_time.strftime('%Y-%m-%d %H:%M:%S'))
        
        # Emit socket event for real-time update
        socketio.emit('vehicle_exit', {
            'plate': plate,
            'duration_hours': duration,
            'payment_amount': vehicle['payment_amount']
        })
        
        return jsonify({
            'status': 'success',
            'message': 'Exit processed successfully',
            'duration_hours': duration,
            'payment_amount': vehicle['payment_amount']
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/process_payment', methods=['POST'])
def process_payment():
    data = request.get_json()
    plate = data.get('plate')
    
    if not plate:
        return jsonify({'status': 'error', 'message': 'Plate number is required'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if vehicle exists and hasn't paid
    cursor.execute('''
        SELECT id, entry_time FROM logs 
        WHERE plate = ? AND paid = 0 AND status = 'active'
    ''', (plate,))
    
    vehicle = cursor.fetchone()
    
    if not vehicle:
        conn.close()
        return jsonify({'status': 'error', 'message': 'No active vehicle found with this plate number'}), 404
    
    # Calculate payment amount
    entry_time = datetime.strptime(vehicle['entry_time'], '%Y-%m-%d %H:%M:%S')
    current_time = datetime.now()
    duration = (current_time - entry_time).total_seconds() / 3600  # Convert to hours
    payment_amount = calculate_payment_amount(entry_time, current_time.strftime('%Y-%m-%d %H:%M:%S'))
    
    try:
        # Update payment status
        cursor.execute('''
            UPDATE logs 
            SET paid = 1, payment_amount = ?, payment_time = ?
            WHERE id = ?
        ''', (payment_amount, current_time.strftime('%Y-%m-%d %H:%M:%S'), vehicle['id']))
        
        conn.commit()
        
        # Emit socket event for real-time update
        socketio.emit('payment_processed', {
            'plate': plate,
            'amount': payment_amount
        })
        
        return jsonify({
            'status': 'success',
            'message': 'Payment processed successfully',
            'payment_amount': payment_amount
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/alerts')
def get_alerts():
    """Get recent alerts"""
    print("Fetching alerts...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM alerts 
            ORDER BY timestamp DESC 
            LIMIT 100
        """)
        alerts = [dict(row) for row in cursor.fetchall()]
        print(f"Retrieved {len(alerts)} alerts")
        return jsonify(alerts)
    except Exception as e:
        print(f"Error fetching alerts: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/resolve_alert', methods=['POST'])
def resolve_alert():
    """Mark an alert as resolved"""
    data = request.json
    alert_id = data.get('alert_id')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE alerts 
            SET resolved = 1 
            WHERE id = ?
        ''', (alert_id,))
        conn.commit()
        
        # Emit socket event for alert resolution
        socketio.emit('alert_resolved', {'alert_id': alert_id})
        
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"Error resolving alert: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Error resolving alert'})
    finally:
        conn.close()

@app.route('/api/logs/<int:log_id>', methods=['GET'])
def get_log(log_id):
    """Get a specific log record"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM logs 
        WHERE id = ?
    """, (log_id,))
    
    log = cursor.fetchone()
    conn.close()
    
    if log:
        return jsonify(dict(log))
    return jsonify({'status': 'error', 'message': 'Log not found'}), 404

@app.route('/api/logs/<int:log_id>', methods=['PUT'])
@token_required
@role_required(['write'])
def update_log(current_user, log_id):
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get the original record
        cursor.execute("SELECT * FROM logs WHERE id = ?", (log_id,))
        original = cursor.fetchone()
        
        if not original:
            return jsonify({'status': 'error', 'message': 'Log not found'}), 404
        
        # Update the database record
        cursor.execute("""
            UPDATE logs 
            SET plate = ?,
                entry_time = ?,
                exit_time = ?,
                payment_amount = ?,
                status = ?,
                paid = CASE 
                    WHEN ? > 0 THEN 1 
                    ELSE 0 
                END,
                duration_hours = CASE 
                    WHEN exit_time IS NOT NULL 
                    THEN ROUND((julianday(exit_time) - julianday(entry_time)) * 24, 2)
                    ELSE 0 
                END
            WHERE id = ?
        """, (
            data['plate'],
            data['entry_time'],
            data['exit_time'] or None,
            data['payment_amount'],
            data['status'],
            data['payment_amount'],
            log_id
        ))
        
        # Update the CSV file
        update_csv_record(
            original['plate'],
            data['plate'],
            data['entry_time'],
            data['exit_time'],
            data['payment_amount'] > 0
        )
        
        conn.commit()
        
        socketio.emit('log_updated', {
            'id': log_id,
            'plate': data['plate'],
            'status': data['status']
        })
        
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"Error updating log: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

def update_csv_record(old_plate, new_plate, entry_time, exit_time, is_paid):
    """Update a record in the CSV file"""
    try:
        # Read existing CSV data
        df = pd.read_csv('plates_log.csv')
        
        # Find the record with the old plate
        mask = df['Plate Number'] == old_plate
        if mask.any():
            # Update the record
            df.loc[mask.idxmax(), 'Plate Number'] = new_plate
            df.loc[mask.idxmax(), 'Timestamp'] = entry_time
            df.loc[mask.idxmax(), 'Payment Timestamp'] = exit_time if exit_time else None
            df.loc[mask.idxmax(), 'Payment Status'] = 1 if is_paid else 0
            
            # Save back to CSV
            df.to_csv('plates_log.csv', index=False)
            print(f"Updated record for {old_plate} in CSV")
    except Exception as e:
        print(f"Error updating CSV: {str(e)}")

@app.route('/api/logs/<int:log_id>', methods=['DELETE'])
@token_required
@role_required(['delete'])
def delete_log(current_user, log_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get the record before deleting
        cursor.execute("SELECT * FROM logs WHERE id = ?", (log_id,))
        record = cursor.fetchone()
        
        if not record:
            return jsonify({'status': 'error', 'message': 'Log not found'}), 404
        
        # Delete from database
        cursor.execute("DELETE FROM logs WHERE id = ?", (log_id,))
        
        # Delete from CSV
        delete_csv_record(record['plate'])
        
        conn.commit()
        
        socketio.emit('log_deleted', {'id': log_id})
        
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"Error deleting log: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

def delete_csv_record(plate):
    """Delete a record from the CSV file"""
    try:
        df = pd.read_csv('plates_log.csv')
        df = df[df['Plate Number'] != plate]
        df.to_csv('plates_log.csv', index=False)
        print(f"Deleted record for {plate} from CSV")
    except Exception as e:
        print(f"Error deleting from CSV: {str(e)}")

@app.route('/api/quit', methods=['POST'])
@token_required
def quit_application():
    try:
        # Clean up any resources
        conn = get_db_connection()
        conn.close()
        
        # Schedule the application shutdown
        func = request.environ.get('werkzeug.server.shutdown')
        if func is None:
            raise RuntimeError('Not running with the Werkzeug Server')
        func()
        
        return jsonify({'status': 'success', 'message': 'Application shutting down'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/detect_gate_tampering', methods=['POST'])
@token_required
@role_required(['write'])
def detect_gate_tampering(current_user):
    """Handle gate tampering detection"""
    data = request.json
    gate_location = data.get('gate_location')
    plate = data.get('plate', 'Unknown')
    
    if not gate_location or gate_location not in GATE_TYPES:
        return jsonify({'status': 'error', 'message': 'Invalid gate location'}), 400
    
    # Log the tampering alert
    alert_system.log_incident(plate, gate_location, "Manual Gate Tampering")
    alert_system.activate_buzzer()
    
    return jsonify({
        'status': 'success',
        'message': 'Gate tampering alert logged'
    })

@app.route('/api/check_unauthorized_exit', methods=['POST'])
def check_unauthorized_exit():
    """Endpoint to check for unauthorized exit attempts"""
    data = request.json
    plate = data.get('plate')
    
    if not plate:
        return jsonify({'status': 'error', 'message': 'Plate number is required'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if vehicle exists and has pending payment
        cursor.execute('''
            SELECT id, paid FROM logs 
            WHERE plate = ? AND status = 'active'
        ''', (plate,))
        
        vehicle = cursor.fetchone()
        
        if vehicle and not vehicle['paid']:
            # Log unauthorized exit attempt
            log_alert(
                plate,
                'unauthorized_exit',
                'exit',
                f'Unauthorized exit detected for vehicle {plate} - Payment pending'
            )
            
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized exit detected - Payment pending'
            }), 403
        
        return jsonify({
            'status': 'success',
            'message': 'No unauthorized exit detected'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

@app.route('/incidents')
@token_required
@role_required(['read'])
def incidents(current_user):
    """View incident log page"""
    return render_template("incidents.html", incidents=alert_system.get_incidents())

@app.route('/api/incidents')
@token_required
@role_required(['read'])
def get_incidents(current_user):
    """Get recent incidents"""
    return jsonify({
        'incidents': alert_system.get_incidents()
    })

# Add this to your existing socket.io event handlers
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('gate_tampering_detected')
def handle_gate_tampering(data):
    """Handle gate tampering detection from client"""
    gate_location = data.get('gate_location')
    plate = data.get('plate', 'Unknown')
    
    if gate_location in GATE_TYPES:
        log_alert(
            plate,
            'gate_tampering',
            gate_location,
            f'Gate tampering detected at {GATE_TYPES[gate_location]}'
        )

if __name__ == '__main__':
    try:
        # Initialize database
        print("Initializing database...")
        init_db()
        
        # Start the alert system
        print("Starting alert system...")
        alert_system.start_monitoring()
        
        # Start the application
        print("Starting Flask application...")
        socketio.run(app, debug=True, host='0.0.0.0', port=5000)
    except Exception as e:
        print(f"Error starting application: {str(e)}")
        sys.exit(1)
    finally:
        print("Shutting down application...")
        alert_system.stop_monitoring()
        sys.exit(0)
