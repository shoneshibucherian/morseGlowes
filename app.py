from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
from translator import encrypt, decrypt
import datetime
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import uuid
import hashlib
import random

uri = "mongodb://admin:password@localhost:27017/"

app = Flask(__name__)
app.secret_key = "morse_app_secret_key_itec4810"
socketio = SocketIO(app, cors_allowed_origins="*")

# ── MongoDB ──
client = MongoClient(uri, server_api=ServerApi('1'))
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)

db         = client['Secret']
collection = db['morese_code']
users_col  = db['users']

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
    print(f"Socket connected: {username} ({socket_id})")
    emit('message', {'message': 'Welcome from MorseApp Flask!'})

    # Mark user as online and store their socket ID for targeted kicks
    if user_id and session.get('role') != 'admin':
        users_col.update_one({'_id': user_id}, {'$set': {'online': True, 'socket_id': socket_id}})
        emit('operator_status_change', {'user_id': user_id, 'online': True, 'username': username}, broadcast=True)


@socketio.on('esp32_message')
def handle_esp32_message(data):
    print(f"Received from ESP32: {data}")
    message   = decrypt(data['morse'])
    device_id = data.get('device_id', 'esp32')
    color     = '#ffb700'
    time      = datetime.datetime.now()

    collection.insert_one({
        'rescuer':  device_id,
        'codename': 'ESP32 GLOVE',
        'message':  message,
        'time':     time,
        'color':    color
    })

    emit('/new_message', {
        'rescuer':  device_id,
        'codename': 'ESP32 GLOVE',
        'message':  message,
        'time':     str(time),
        'color':    color
    }, broadcast=True)
    print(f"Stored: {message}")


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

    if latitude is not None and longitude is not None:
        doc['latitude']  = latitude
        doc['longitude'] = longitude

    collection.insert_one(doc)

    emit('/new_message', {
        'rescuer':   user_id,
        'codename':  codename,
        'message':   message,
        'time':      str(time),
        'color':     color,
        'latitude':  latitude,
        'longitude': longitude
    }, broadcast=True)

    print(f"Received: {morse} | Translated: {message} | Codename: {codename}")


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
