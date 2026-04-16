from gevent import monkey
monkey.patch_all()
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
from translator import encrypt, decrypt
import datetime
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import uuid
import time
import gpsmod
import hashlib
import random

uri = "mongodb://admin:password@localhost:27017/"

device_status = {
    "g1": {"last_seen": 0},
    "g2": {"last_seen": 0}
}

def handle_missing_ping(device_id):
    users_col.update_one(
        {'username': device_id},
        {'$set': {
            'online': 'false'
        }}
    )
def check_all_devices_timeout(ping_time):
    socketio.sleep(5)

    current_time = time.time()

    for device_id, info in device_status.items():
        # If device didn't respond AFTER this ping
        if info["last_seen"] < ping_time:
            print(f"{device_id} did NOT respond within 5 seconds")
        else:
            
            print(f"{device_id} responded successfully")
            handle_missing_ping(device_id)

def ping_broadcast():
    while True:
        socketio.emit('/new_message', {'message': 'PING'}, broadcast=True)


        ping_time = time.time()

        # Start timeout checker for this round
        socketio.start_background_task(check_all_devices_timeout, ping_time)

        socketio.sleep(30)

app = Flask(__name__)
app.secret_key = "morse_app_secret_key_itec4810"
# socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading", allow_upgrades=False)
socketio = SocketIO(app, cors_allowed_origins="*")

# ── MongoDB ──
client = MongoClient(uri, server_api=ServerApi('1'))
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)

db           = client['Secret']
collection   = db['morese_code']
users_col    = db['users']


# --- Battery Simulation Config ---
bat1_MAX_VOLTAGE = 4.0
bat1_FULL_VOLTAGE = 3.7
bat1_MIN_VOLTAGE = 3.1

bat1_DISCHARGE_RATE = 0.00005  # volts per second (tweak this)


bat2_MAX_VOLTAGE = 4.0
bat2_FULL_VOLTAGE = 3.7
bat2_MIN_VOLTAGE = 3.1

bat2_DISCHARGE_RATE = 0.0005  


battery1 = {
    "voltage": bat1_FULL_VOLTAGE,
    "last_update": time.time(),
    "DISCHARGE_RATE": bat1_DISCHARGE_RATE,
    "MIN_VOLTAGE": bat1_MIN_VOLTAGE,
    "FULL_VOLTAGE": bat1_FULL_VOLTAGE,
    "ACTUAL_VOLTAGE": 0,
}

battery2 = {
    "voltage": bat2_FULL_VOLTAGE,
    "last_update": time.time(),
    "DISCHARGE_RATE": bat2_DISCHARGE_RATE,
    "MIN_VOLTAGE": bat2_MIN_VOLTAGE,
    "FULL_VOLTAGE": bat2_FULL_VOLTAGE,
    "ACTUAL_VOLTAGE": 0,
}

all_message = list(collection.find())
last_id = all_message[-1]["_id"] if all_message else None

# ── NATO Phonetic Alphabet ──
NATO = [
    'ALPHA', 'BRAVO', 'CHARLIE', 'DELTA', 'ECHO', 'FOXTROT',
    'GOLF', 'HOTEL', 'INDIA', 'JULIET', 'KILO', 'LIMA',
    'MIKE', 'NOVEMBER', 'OSCAR', 'PAPA', 'QUEBEC', 'ROMEO',
    'SIERRA', 'TANGO', 'UNIFORM', 'VICTOR', 'WHISKEY',
    'XRAY', 'YANKEE', 'ZULU'
]


# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════

def hash_pin(pin):
    """SHA-256 hash a PIN so we never store it in plain text."""
    return hashlib.sha256(pin.encode()).hexdigest()


def generate_codename():
    """
    Generates a unique two-word NATO codename (e.g. ALPHA BRAVO).
    676 possible combinations (26x26).
    """
    attempts = 0
    while attempts < 676:
        word1 = random.choice(NATO)
        word2 = random.choice(NATO)
        if word1 == word2:
            attempts += 1
            continue
        codename = f"{word1} {word2}"
        if not users_col.find_one({'codename': codename}):
            return codename
        attempts += 1
    return f"ZULU {uuid.uuid4().hex[:4].upper()}"


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('login_page'))
        # Check DB status on every request — catches kick/revoke after refresh
        user = users_col.find_one({'_id': user_id})
        if not user or user.get('status') not in ('approved',):
            session.clear()
            return redirect(url_for('login_page'))
        # If kicked, clear session and force fresh login
        if user.get('kicked'):
            users_col.update_one({'_id': user_id}, {'$set': {'kicked': False}})
            session.clear()
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id') or session.get('role') != 'admin':
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════
# PAGE ROUTES
# ══════════════════════════════════════════

@app.route('/')
@login_required
def index():
    # Admins should never see home.html — redirect to admin page
    if session.get('role') == 'admin':
        return redirect(url_for('admin_page'))
    return render_template('home.html')


@app.route('/login')
def login_page():
    if session.get('user_id'):
        if session.get('role') == 'admin':
            return redirect(url_for('admin_page'))
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/admin')
@admin_required
def admin_page():
    return render_template('admin.html')


# ══════════════════════════════════════════
# AUTH ENDPOINTS
# ══════════════════════════════════════════

@app.route('/register', methods=['POST'])
def register():
    """Adds user to the waiting list — does NOT log them in."""
    data     = request.get_json()
    username = data.get('username', '').strip()
    pin      = data.get('pin', '').strip()
    color    = data.get('color', '#00ff41')

    if not username or not pin:
        return jsonify({'error': 'All fields are required.'}), 400
    if len(username) < 2:
        return jsonify({'error': 'Username must be at least 2 characters.'}), 400
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        return jsonify({'error': 'PIN must be 4 to 6 digits.'}), 400
    if users_col.find_one({'username_lower': username.lower()}):
        return jsonify({'error': 'Username already taken.'}), 409

    # Use lowercase username as the ID for easy tracking in messages collection
    user_id = username.lower()
    users_col.insert_one({
        '_id':            user_id,
        'username':       username,
        'username_lower': username.lower(),
        'pin_hash':       hash_pin(pin),
        'color':          color,
        'codename':       None,
        'role':           'user',
        'status':         'pending',
        'layout_color':   None,
        'bg_color':       None,
        'theme_name':     None,
        'created_at':     datetime.datetime.now()
    })

    print(f"New registration pending: {username}")

    # Notify admin page in real time that a new user is waiting
    socketio.emit('new_pending_user', {'username': username})

    return jsonify({'message': 'Registration submitted. Awaiting admin approval.', 'username': username}), 201


@app.route('/login', methods=['POST'])
def login():
    """Logs in a user or admin."""
    data     = request.get_json()
    username = data.get('username', '').strip()
    pin      = data.get('pin', '').strip()

    if not username or not pin:
        return jsonify({'error': 'All fields are required.'}), 400

    user = users_col.find_one({'username_lower': username.lower()})

    if not user or user['pin_hash'] != hash_pin(pin):
        return jsonify({'error': 'Incorrect username or PIN.'}), 401

    if user.get('status') == 'pending':
        return jsonify({'status': 'pending', 'username': username, 'message': 'Your account is awaiting admin approval.'}), 403

    if user.get('status') == 'rejected':
        return jsonify({'error': 'Your account has been rejected. Contact your administrator.'}), 403

    # Clear kicked flag on fresh login
    users_col.update_one({'_id': user['_id']}, {'$set': {'kicked': False}})

    session['user_id']  = user['_id']
    session['username'] = user['username']
    session['codename'] = user.get('codename', user['username'])
    session['color']    = user['color']
    session['role']     = user.get('role', 'user')
    print(f"User logged in: {user['username']} ({session['role']})")

    if user.get('role') == 'admin':
        return jsonify({'message': 'Login successful.', 'redirect': '/admin'}), 200

    return jsonify({'message': 'Login successful.', 'redirect': '/'}), 200


@app.route('/logout', methods=['POST'])
def logout():
    username = session.get('username', 'Unknown')
    user_id  = session.get('user_id')
    if user_id:
        users_col.update_one({'_id': user_id}, {'$set': {'online': False}})
        socketio.emit('operator_status_change', {'user_id': user_id, 'online': False})
    session.clear()
    print(f"User logged out: {username}")
    return jsonify({'message': 'Logged out.'}), 200


@app.route('/check_status')
def check_status():
    """Polling endpoint — checks if a pending user has been approved."""
    username = request.args.get('username', '').strip()
    if not username:
        return jsonify({'status': 'unknown'}), 400
    user = users_col.find_one({'username_lower': username.lower()})
    if not user:
        return jsonify({'status': 'unknown'}), 404
    return jsonify({'status': user.get('status', 'pending')}), 200


# ══════════════════════════════════════════
# USER INFO
# ══════════════════════════════════════════

@app.route('/me')
@login_required
def me():
    user = users_col.find_one({'_id': session['user_id']})
    return jsonify({
        'user_id':      session['user_id'],
        'username':     session['username'],
        'codename':     session.get('codename', session['username']),
        'color':        session['color'],
        'role':         session.get('role', 'user'),
        'layout_color': user.get('layout_color') if user else None,
        'bg_color':     user.get('bg_color') if user else None,
        'theme_name':   user.get('theme_name') if user else None,
    })


# ══════════════════════════════════════════
# COLOR & LAYOUT
# ══════════════════════════════════════════

@app.route('/update_color', methods=['POST'])
@login_required
def update_color():
    data      = request.get_json()
    new_color = data.get('color')
    if not new_color:
        return jsonify({'error': 'Color is required.'}), 400

    user_id = session['user_id']
    users_col.update_one({'_id': user_id}, {'$set': {'color': new_color}})
    collection.update_many({'rescuer': user_id}, {'$set': {'color': new_color}})
    session['color'] = new_color
    return jsonify({'message': 'Color updated.', 'color': new_color}), 200


@app.route('/update_layout', methods=['POST'])
@login_required
def update_layout():
    data         = request.get_json()
    layout_color = data.get('layout_color')
    bg_color     = data.get('bg_color')

    theme_name = data.get('theme_name')
    update = {}
    if layout_color: update['layout_color'] = layout_color
    if bg_color:     update['bg_color']     = bg_color
    if theme_name:   update['theme_name']   = theme_name
    if update:
        users_col.update_one({'_id': session['user_id']}, {'$set': update})
    return jsonify({'message': 'Layout updated.'}), 200


# ══════════════════════════════════════════
# ADMIN ENDPOINTS
# ══════════════════════════════════════════

@app.route('/admin/pending')
@admin_required
def admin_pending():
    pending = list(users_col.find({'status': 'pending', 'role': 'user'}))
    for u in pending:
        u['_id'] = str(u['_id'])
        u.pop('pin_hash', None)
    return jsonify(pending), 200


@app.route('/admin/approved')
@admin_required
def admin_approved():
    approved = list(users_col.find({'status': 'approved', 'role': 'user'}))
    for u in approved:
        u['_id'] = str(u['_id'])
        u.pop('pin_hash', None)
    return jsonify(approved), 200


@app.route('/admin/approve', methods=['POST'])
@admin_required
def admin_approve():
    data    = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id required.'}), 400

    user = users_col.find_one({'_id': user_id})
    if not user:
        return jsonify({'error': 'User not found.'}), 404

    codename = generate_codename()
    users_col.update_one({'_id': user_id}, {'$set': {
        'status':      'approved',
        'codename':    codename,
        'approved_at': datetime.datetime.now()
    }})
    print(f"Approved: {user['username']} → {codename}")
    return jsonify({'message': f"Approved. Codename: {codename}", 'codename': codename}), 200


@app.route('/admin/reject', methods=['POST'])
@admin_required
def admin_reject():
    data    = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id required.'}), 400
    user = users_col.find_one({'_id': user_id})
    users_col.update_one({'_id': user_id}, {'$set': {'status': 'rejected'}})
    print(f"Rejected user: {user.get('username', user_id) if user else user_id}")
    return jsonify({'message': 'User rejected.'}), 200


@app.route('/admin/kick', methods=['POST'])
@admin_required
def admin_kick():
    data    = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id required.'}), 400
    user = users_col.find_one({'_id': user_id})
    if not user:
        return jsonify({'error': 'User not found.'}), 404
    socket_id = user.get('socket_id')
    # Mark offline and set a kicked flag so login_required forces re-login
    users_col.update_one({'_id': user_id}, {'$set': {
        'online':    False,
        'socket_id': None,
        'kicked':    True
    }})

    # Target the specific user's socket if available
    if socket_id:
        socketio.emit('kicked', {'message': 'You have been disconnected by OVERLORD.'}, to=socket_id)
    else:
        socketio.emit('kicked', {'message': 'You have been disconnected by OVERLORD.'})

    socketio.emit('operator_status_change', {'user_id': user_id, 'online': False, 'username': user.get('username', '')})
    print(f"Admin kicked: {user.get('username', user_id)}")
    return jsonify({'message': 'User kicked.'}), 200


@app.route('/admin/revoke', methods=['POST'])
@admin_required
def admin_revoke():
    data    = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id required.'}), 400
    user = users_col.find_one({'_id': user_id})
    if not user:
        return jsonify({'error': 'User not found.'}), 404
    socket_id = user.get('socket_id')
    users_col.update_one({'_id': user_id}, {'$set': {
        'status':    'rejected',
        'online':    False,
        'socket_id': None,
        'codename':  None
    }})

    # Target the specific user's socket if available
    if socket_id:
        socketio.emit('kicked', {'message': 'Your access has been revoked by OVERLORD.'}, to=socket_id)
    else:
        socketio.emit('kicked', {'message': 'Your access has been revoked by OVERLORD.'})

    socketio.emit('operator_status_change', {'user_id': user_id, 'online': False, 'username': user.get('username', '')})
    print(f"Admin revoked access: {user.get('username', user_id)}")
    return jsonify({'message': 'Access revoked.'}), 200


@app.route('/admin/stats')
@admin_required
def admin_stats():
    return jsonify({
        'pending':  users_col.count_documents({'status': 'pending', 'role': 'user'}),
        'approved': users_col.count_documents({'status': 'approved', 'role': 'user'}),
        'rejected': users_col.count_documents({'status': 'rejected', 'role': 'user'}),
        'messages': collection.count_documents({})
    }), 200


# ══════════════════════════════════════════
# MESSAGE ENDPOINTS
# ══════════════════════════════════════════

@app.route('/new_messages')
@login_required
def get_new_messages():
    global last_id
    try:
        all_messages = list(collection.find())
        if all_messages:
            for msg in all_messages:
                msg["_id"] = str(msg["_id"])
            if last_id != all_messages[-1]["_id"]:
                last_id = all_messages[-1]["_id"]
                return jsonify([all_messages[-1]])
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/full_messages')
@login_required
def full_messages():
    try:
        all_messages = list(collection.find())
        for msg in all_messages:
            msg["_id"] = str(msg["_id"])
        if not all_messages:
            return jsonify([])
        return jsonify(all_messages)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# @socketio.on('lora_data')
# def handle_lora_data(data):
#     print("Received from ESP32:", data)
 
@socketio.on('lora_data')
def handle_lora_data(data):
    print("SUCCESS! Received from Heltec:", data)
    # If you want to broadcast this to the web dashboard:
    # the data is off the format g1:name,lat,lon,battery
    #get the battery val and add it to battery1 if the data starts with "g1:" and to battery2 if the data starts with "g2:"
    if data["message"].startswith("g1:"):
        try:
            battery_val = float(data["message"].split(",")[2])
            battery1["ACTUAL_VOLTAGE"] = int(battery_val)/1000
            print(f"Updated battery1 voltage to {battery_val}V")
        except Exception as e:
            print(f"Error parsing battery value for battery1: {e}")
    elif data["message"].startswith("g2:"):
        try:
            battery_val = float(data["message"].split(",")[2])
            battery2["ACTUAL_VOLTAGE"] = int(battery_val)/1000
            print(f"Updated battery2 voltage to {battery2['ACTUAL_VOLTAGE']}V")
        except Exception as e:
            print(f"Error parsing battery value for battery2: {e}")


        
    # if data starts with "g1:",  then add the battery val
    emit('/new_message', {
        'username': 'Heltec LoRa',
        'message': data.get('message', 'No message'),
        'time': str(datetime.datetime.now()),
        'color': '#00ff41'
    }, broadcast=True)

@app.route('/connect')
@login_required
def connect_user():
    return jsonify({"message": "Connected"})


# ══════════════════════════════════════════
# SOCKET.IO
# ══════════════════════════════════════════

@socketio.on('disconnect')
def handle_disconnect():
    username = session.get('username', 'unknown')
    user_id  = session.get('user_id')
    print(f'Client disconnected: {username}')

    # Mark user as offline in MongoDB and notify admin page
    if user_id and session.get('role') != 'admin':
        users_col.update_one({'_id': user_id}, {'$set': {'online': False, 'socket_id': None}})
        socketio.emit('operator_status_change', {'user_id': user_id, 'online': False, 'username': username})


@socketio.on('connect')
def handle_socketio_connect(auth=None):
    from flask import request as flask_request
    username  = session.get('username', 'unknown')
    user_id   = session.get('user_id')
    socket_id = flask_request.sid
    global ping_thread
    if not globals().get('ping_thread'):
        ping_thread = socketio.start_background_task(ping_broadcast)
    print(f"Socket connected: {username} ({socket_id})")
    emit('message', {'message': 'Welcome from MorseApp Flask!'})

    # Mark user as online and store their socket ID for targeted kicks
    if user_id and session.get('role') != 'admin':
        users_col.update_one({'_id': user_id}, {'$set': {'online': True, 'socket_id': socket_id}})
        emit('operator_status_change', {'user_id': user_id, 'online': True, 'username': username}, broadcast=True)


# @socketio.on('esp32_ping')
# def handle_esp32_ping(data):
#     # ESP32 sends a ping — broadcast to all connected clients
#     print("Ping received from ESP32, broadcasting to all devices")
#     emit('ping_devices', {'type': 'PING'}, broadcast=True)


@socketio.on('esp32_message')
def handle_esp32_message(data):
    print(f"Received from ESP32: {data}")
    message   = decrypt(data['morse'])
    device_id = data.get('device_id', 'esp32')
    color     = '#ffb700'
    time      = datetime.datetime.now()

    latitude  = data.get('latitude')
    longitude = data.get('longitude')

    collection.insert_one({
        'rescuer':  device_id,
        'codename': 'ESP32 GLOVE',
        'message':  message,
        'time':     time,
        'color':    color
    })

    # Update ESP32 device location in users collection if GPS provided
    if latitude is not None and longitude is not None:
        users_col.update_one({'_id': device_id}, {'$set': {
            'latitude':  latitude,
            'longitude': longitude
        }}, upsert=True)

    emit('/new_message', {
        'rescuer':  device_id,
        'codename': 'ESP32 GLOVE',
        'message':  message,
        'time':     str(time),
        'color':    color
    }, broadcast=True)
    print(f"Stored: {message}")




# --- Internal State ---


def update_battery(battery):
    now = time.time()
    elapsed = now - battery["last_update"]

    # Simulate discharge
    drop = elapsed * battery["DISCHARGE_RATE"]
    battery["voltage"] = max(battery["MIN_VOLTAGE"], battery["voltage"] - drop)
    
    battery["last_update"] = now


def voltage_to_percentage(battery, voltage):
    if voltage >= battery["FULL_VOLTAGE"]:
        return 100
    if voltage <= battery["MIN_VOLTAGE"]:
        return 0

    # Linear interpolation between 3.7V (100%) and 3.1V (0%)
    percent = ((voltage - battery["MIN_VOLTAGE"]) / (battery["FULL_VOLTAGE"] - battery["MIN_VOLTAGE"])) * 100
    return round(percent, 2)



@app.route('/battery1', methods=['GET'])
def get_battery1():
    update_battery(battery1)

    voltage = battery1["ACTUAL_VOLTAGE"] if battery1["ACTUAL_VOLTAGE"] > 0 else battery1["voltage"]
    percentage = voltage_to_percentage(battery1,voltage)

    return jsonify({
        "voltage": round(voltage, 3),
        "percentage": percentage
    })



#provide list of node and edges
@app.route('/graph', methods=['GET'])
def get_graph():
    edge=request.args.get('edge')
    # formate of node data 
    #     nodes=[
#             { "id": "node0", "title": "Washington, D.C.", "color": "blue" },
#             { "id": "node1", "title": "San Juan, Puerto Rico", "color": "blue" },
#             { "id": "node2", "title": "Miami, FL", "color": "blue" },
#             { "id": "node3", "title": "Boca Raton, FL", "color": "blue" },]
    nodes=[{"id":"Grafana", "title":"Grafana", "color":"green"}
           ,{"id":"MongoDB", "title":"MongoDB", "color":"green"}
           ,{"id":"MorseApp", "title":"MorseApp", "color":"green"}]
    #formate of edge data
    #             { "id": "e8", "source": "node3", "target": "node13", "mainStat": 2 },
#             { "id": "e9", "source": "node2", "target": "node3", "mainStat": 3 },
#             { "id": "e10", "source": "node2", "target": "node12", "mainStat": 2 }]
    edges=[{ "id": "e1", "source": "Grafana", "target": "MorseApp" },
           { "id": "e2", "source": "MongoDB", "target": "MorseApp" },]
    users = list(users_col.find()) 
    for user in users:
            if user["username"]=="admin":
                node_row={"id": user['username'], "title": user['username'], "color": "green"}
            elif user['online']==True:
                node_row={"id": user['username'], "title": user['username'], "color": "green"}
            else:
                node_row={"id": user['username'], "title": user['username'], "color": "red"}
            nodes.append(node_row)
    
    if int(edge)==1:     
        for user in users:
            row={"id": f"e_{user['username']}", "source": "MorseApp", "target": user['username']}
            edges.append(row)
        return jsonify(edges)
    else:
        return jsonify(nodes)


@app.route('/battery2', methods=['GET'])
def get_battery2():
    update_battery(battery2)

    # voltage = battery2["voltage"]
    voltage = battery2["ACTUAL_VOLTAGE"] if battery2["ACTUAL_VOLTAGE"] > 0 else battery2["voltage"]
    percentage = voltage_to_percentage(battery2, voltage)

    return jsonify({
        "voltage": round(voltage, 3),
        "percentage": percentage
    })

@socketio.on('/message')
def handle_message(data):
    if isinstance(data, dict):
        morse     = data.get('morse', '')
        latitude  = data.get('latitude')
        longitude = data.get('longitude')
    else:
        morse     = data
        latitude  = None
        longitude = None

    message  = decrypt(morse)
    user_id  = session.get('user_id', str(uuid.uuid4()))
    codename = session.get('codename', 'UNKNOWN')
    color    = session.get('color', '#00ff41')
    time     = datetime.datetime.now()

    doc = {
        'rescuer':  user_id,
        'codename': codename,
        'message':  message,
        'time':     time,
        'color':    color
    }

    collection.insert_one(doc)

    # Update user's latitude/longitude in users collection if provided
    if latitude is not None and longitude is not None:
        users_col.update_one({'_id': user_id}, {'$set': {
            'latitude':  latitude,
            'longitude': longitude
        }})

    emit('/new_message', {
        'rescuer':  user_id,
        'codename': codename,
        'message':  message,
        'time':     str(time),
        'color':    color
    }, broadcast=True)

    print(f"Received: {morse} | Translated: {message} | Codename: {codename}")


#reads the collections namesd users and sents the data in the following format 


# "target","geojson","aggrType","srcPath","stat1"
# TTK,"{""coordinates"":[-84.00518567235461,33.980605849171305],""type"":""Point""}",node,,1
# U29,"{""coordinates"":[-84.00518567235461,33.980605849171305],""type"":""Point""}",node,U24,1
# U21,"{""coordinates"":[-84.00518567235461,33.980605849171305],""type"":""Point""}",node,U22,1
@app.route('/get_users', methods=['GET'])
def handle_get_users():
    #read all rows in the users collection and send them to the client
    users = list(users_col.find())
    

    lat, lon = 33.980605849171305, -84.00518567235461

    data=[]
    for user in users:
        user['_id'] = str(user['_id'])
        user.pop('pin_hash', None) 
        sim = gpsmod.GPSSimulator()
        noisy_lat, noisy_lon = sim.add_noise(lat, lon)
        
         # Remove sensitive info
        data.append({
            "target": user['username'],
            "geojson": {
                "type": "Point",
                "coordinates": [noisy_lon, noisy_lat]  # Placeholder coordinates
            },
            "aggrType": "node",
            "srcPath": "",
            "stat1": 1
        })
    return jsonify(data), 200


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
