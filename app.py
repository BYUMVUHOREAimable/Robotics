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

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Change this to a secure secret key
socketio = SocketIO(app)

# Constants
HOURLY_RATE = 500  # RWF per hour

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
    auth = request.json
    if not auth or not auth.get('username') or not auth.get('password'):
        return jsonify({'message': 'Could not verify!'}), 401

    user = USERS.get(auth.get('username'))
    if not user or user['password'] != auth.get('password'):
        return jsonify({'message': 'Invalid credentials!'}), 401

    token = jwt.encode({
        'username': auth.get('username'),
        'exp': datetime.utcnow() + timedelta(hours=24)
    }, app.config['SECRET_KEY'])

    return jsonify({
        'token': token,
        'role': user['role']
    })

# Database setup
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    # Drop existing tables if they exist
    cursor.execute('DROP TABLE IF EXISTS logs')
    cursor.execute('DROP TABLE IF EXISTS statistics')
    cursor.execute('DROP TABLE IF EXISTS alerts')
    
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
    if not os.path.exists('plates_log.csv'):
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Read CSV file
        df = pd.read_csv('plates_log.csv')
        
        # Convert timestamp columns to datetime
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df['Payment Timestamp'] = pd.to_datetime(df['Payment Timestamp'], errors='coerce')  # Handle NaN values
        
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
        
        conn.commit()
        
        # Update statistics after import
        update_statistics()
        
    except Exception as e:
        print(f"Error importing CSV data: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

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
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    plate_search = request.args.get('plate', '')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
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
    
    conn.close()
    
    return jsonify({
        'logs': logs,
        'pagination': {
            'total': total_count,
            'pages': math.ceil(total_count / per_page),
            'current_page': page,
            'per_page': per_page
        }
    })

@app.route('/api/stats')
def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get latest statistics
    cursor.execute("""
        SELECT * FROM statistics 
        ORDER BY last_updated DESC 
        LIMIT 1
    """)
    stats = cursor.fetchone()
    
    if not stats:
        # If no statistics exist, calculate them
        update_statistics()
        cursor.execute("""
            SELECT * FROM statistics 
            ORDER BY last_updated DESC 
            LIMIT 1
        """)
        stats = cursor.fetchone()
    
    conn.close()
    
    return jsonify({
        'total_vehicles': stats['total_vehicles'],
        'current_vehicles': stats['current_vehicles'],
        'total_revenue': stats['total_revenue'],
        'last_updated': stats['last_updated']
    })

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
    exit_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get entry time for the vehicle
        cursor.execute("""
            SELECT entry_time, paid, payment_time 
            FROM logs 
            WHERE plate = ? AND status = 'active'
        """, (plate,))
        result = cursor.fetchone()
        
        if result:
            entry_time = result['entry_time']
            is_paid = result['paid']
            payment_time = result['payment_time']
            
            # Check for unauthorized exit
            if not is_paid:
                log_alert(
                    plate,
                    'unauthorized_exit',
                    'exit',
                    f'Vehicle attempted to exit without payment. Entry time: {entry_time}'
                )
            
            # Calculate payment amount and duration
            payment_amount = calculate_payment_amount(entry_time, exit_time)
            entry_dt = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
            exit_dt = datetime.strptime(exit_time, '%Y-%m-%d %H:%M:%S')
            duration = max(0, (exit_dt - entry_dt).total_seconds() / 3600)
            
            # Update the log with exit time and payment information
            cursor.execute(
                """UPDATE logs 
                   SET exit_time = ?, 
                       status = 'exit',
                       payment_amount = ?,
                       duration_hours = ?,
                       payment_time = CASE 
                           WHEN paid = 0 THEN ?
                           ELSE payment_time 
                       END,
                       paid = CASE 
                           WHEN paid = 0 THEN 1 
                           ELSE paid 
                       END,
                       gate_location = 'exit'
                   WHERE plate = ? AND status = 'active'""",
                (exit_time, payment_amount, duration, exit_time, plate)
            )
            conn.commit()
            
            # Update CSV with exit time
            update_csv_exit_time(plate, exit_time)
            
            # Update statistics
            update_statistics()
            
            # Emit socket event with all relevant information
            socketio.emit('vehicle_exit', {
                'plate': plate,
                'entry_time': entry_time,
                'exit_time': exit_time,
                'payment_time': payment_time,
                'payment_amount': payment_amount,
                'duration_hours': duration,
                'was_paid': is_paid
            })
            
            return jsonify({
                'status': 'success',
                'entry_time': entry_time,
                'exit_time': exit_time,
                'payment_time': payment_time,
                'payment_amount': payment_amount,
                'duration_hours': duration,
                'was_paid': is_paid
            })
        
        return jsonify({'status': 'error', 'message': 'Vehicle not found or already exited'})
    except Exception as e:
        print(f"Error processing exit: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Error processing exit'})
    finally:
        conn.close()

@app.route('/api/process_payment', methods=['POST'])
def process_payment():
    data = request.json
    plate = data.get('plate')
    payment_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get vehicle details
        cursor.execute("""
            SELECT entry_time, exit_time, payment_amount, status
            FROM logs 
            WHERE plate = ? AND status = 'active'
        """, (plate,))
        result = cursor.fetchone()
        
        if result:
            # Calculate payment amount if not already set
            if not result['payment_amount']:
                payment_amount = calculate_payment_amount(
                    result['entry_time'],
                    result['exit_time'] if result['exit_time'] else payment_time
                )
            else:
                payment_amount = result['payment_amount']
            
            # Ensure payment amount is positive
            payment_amount = max(HOURLY_RATE, payment_amount)
            
            # Update the log with payment information
            cursor.execute(
                """UPDATE logs 
                   SET paid = 1, 
                       payment_time = ?,
                       payment_amount = ?,
                       status = 'active'  -- Keep status as active after payment
                   WHERE plate = ? AND status = 'active'""",
                (payment_time, payment_amount, plate)
            )
            conn.commit()
            
            # Get updated record
            cursor.execute("""
                SELECT * FROM logs 
                WHERE plate = ? 
                ORDER BY id DESC 
                LIMIT 1
            """, (plate,))
            updated_record = cursor.fetchone()
            
            # Update statistics
            update_statistics()
            
            # Emit socket event with complete information
            socketio.emit('payment_processed', {
                'plate': plate,
                'amount': payment_amount,
                'payment_time': payment_time,
                'status': 'active',  # Always active after payment
                'paid': True
            })
            
            return jsonify({
                'status': 'success',
                'payment_amount': payment_amount,
                'payment_time': payment_time,
                'record_status': 'active'  # Always active after payment
            })
        
        return jsonify({'status': 'error', 'message': 'Vehicle not found or already paid'})
    except Exception as e:
        print(f"Error processing payment: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Error processing payment'})
    finally:
        conn.close()

@app.route('/api/alerts')
def get_alerts():
    """Get recent alerts"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM alerts 
        ORDER BY timestamp DESC 
        LIMIT 100
    """)
    alerts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify(alerts)

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

if __name__ == '__main__':
    init_db()
    import_csv_data()  # Import existing data from CSV
    update_statistics()  # Initialize statistics
    socketio.run(app, debug=True)
