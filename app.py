from flask import Flask, render_template, request, jsonify, make_response, session, redirect, url_for
from flask_socketio import SocketIO, emit
from translator import encrypt, decrypt
import datetime
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import uuid
import hashlib

uri = "mongodb://admin:password@localhost:27017/"

app = Flask(__name__)

# Secret key required for session management
# In production this should be a long random string stored securely
app.secret_key = "morse_app_secret_key_itec4810"

socketio = SocketIO(app, cors_allowed_origins="*")

# ── MongoDB connection ──
client = MongoClient(uri, server_api=ServerApi('1'))
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)

db = client['Secret']
collection = db['morese_code']   # Messages collection
users_col  = db['users']         # Users collection (new)

# Track last message ID for polling
all_message = list(collection.find())
last_id = all_message[-1]["_id"] if all_message else None


# ══════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════

def hash_pin(pin):
    """Hashes a PIN using SHA-256 so we never store plain PINs in MongoDB."""
    return hashlib.sha256(pin.encode()).hexdigest()

def get_current_user():
    """Returns the current logged-in user's document from MongoDB, or None."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return users_col.find_one({'_id': user_id})

def login_required(f):
    """Decorator that redirects to login page if user is not logged in."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════
# PAGE ROUTES
# ══════════════════════════════════════════

@app.route('/')
@login_required
def index():
    """Main chat page — only accessible when logged in."""
    return render_template('home.html')


@app.route('/login')
def login_page():
    """Login page — redirects to home if already logged in."""
    if session.get('user_id'):
        return redirect(url_for('index'))
    return render_template('login.html')


# ══════════════════════════════════════════
# AUTH ENDPOINTS
# ══════════════════════════════════════════

@app.route('/register', methods=['POST'])
def register():
    """Creates a new user account and logs them in."""
    data = request.get_json()
    username = data.get('username', '').strip()
    pin      = data.get('pin', '').strip()
    color    = data.get('color', '#00ff41')

    # Validate inputs
    if not username or not pin:
        return jsonify({'error': 'All fields are required.'}), 400

    if len(username) < 2:
        return jsonify({'error': 'Username must be at least 2 characters.'}), 400

    if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        return jsonify({'error': 'PIN must be 4 to 6 digits.'}), 400

    # Check if username already taken (case-insensitive)
    if users_col.find_one({'username_lower': username.lower()}):
        return jsonify({'error': 'Username already taken. Choose another.'}), 409

    # Create user document
    user_id = str(uuid.uuid4())
    users_col.insert_one({
        '_id': user_id,
        'username': username,
        'username_lower': username.lower(),
        'pin_hash': hash_pin(pin),
        'color': color,
        'created_at': datetime.datetime.now()
    })

    # Log the user in immediately after registration
    session['user_id'] = user_id
    session['username'] = username
    session['color'] = color
    print(f"New user registered: {username}")

    return jsonify({'message': 'Account created successfully.'}), 201


@app.route('/login', methods=['POST'])
def login():
    """Logs in an existing user."""
    data = request.get_json()
    username = data.get('username', '').strip()
    pin      = data.get('pin', '').strip()

    if not username or not pin:
        return jsonify({'error': 'All fields are required.'}), 400

    # Find user by username (case-insensitive)
    user = users_col.find_one({'username_lower': username.lower()})

    if not user or user['pin_hash'] != hash_pin(pin):
        return jsonify({'error': 'Incorrect username or PIN.'}), 401

    # Store user info in session
    session['user_id'] = user['_id']
    session['username'] = user['username']
    session['color'] = user['color']
    print(f"User logged in: {user['username']}")

    return jsonify({'message': 'Login successful.'}), 200


@app.route('/logout', methods=['POST'])
def logout():
    """Logs out the current user by clearing their session."""
    username = session.get('username', 'Unknown')
    session.clear()
    print(f"User logged out: {username}")
    return jsonify({'message': 'Logged out.'}), 200


# ══════════════════════════════════════════
# USER INFO ENDPOINT
# ══════════════════════════════════════════

@app.route('/me')
@login_required
def me():
    """Returns the current user's info for the frontend (username, color)."""
    return jsonify({
        'user_id': session['user_id'],
        'username': session['username'],
        'color': session['color']
    })


# ══════════════════════════════════════════
# COLOR UPDATE ENDPOINT
# ══════════════════════════════════════════

@app.route('/update_color', methods=['POST'])
@login_required
def update_color():
    """Updates the user's color in MongoDB, their session, and all their existing messages."""
    data = request.get_json()
    new_color = data.get('color')

    if not new_color:
        return jsonify({'error': 'Color is required.'}), 400

    user_id = session['user_id']

    # Update color in users collection
    users_col.update_one({'_id': user_id}, {'$set': {'color': new_color}})

    # Update color on all existing messages by this user
    collection.update_many({'rescuer': user_id}, {'$set': {'color': new_color}})

    # Update session
    session['color'] = new_color

    print(f"User {session['username']} updated color to {new_color}")
    return jsonify({'message': 'Color updated.', 'color': new_color}), 200


# ══════════════════════════════════════════
# MESSAGE ENDPOINTS
# ══════════════════════════════════════════

@app.route('/new_messages')
@login_required
def get_new_messages():
    """Returns the latest message if it's newer than the last seen one."""
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
    """Returns all messages from MongoDB."""
    try:
        all_messages = list(collection.find())
        for msg in all_messages:
            msg["_id"] = str(msg["_id"])
        if not all_messages:
            print("No messages in the database.")
            return jsonify([])
        return jsonify(all_messages)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/connect')
@login_required
def connect_user():
    """Returns confirmation that the user is connected."""
    return jsonify({"message": "Connected", "username": session.get('username')})


# ══════════════════════════════════════════
# SOCKET.IO EVENTS
# ══════════════════════════════════════════

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')


@socketio.on('connect')
def handle_socketio_connect():
    print(f"Socket connected: {session.get('username', 'unknown')}")
    emit('message', {'message': 'Welcome from MorseApp Flask!'})


@socketio.on('esp32_message')
def handle_esp32_message(data):
    """Handles incoming Morse code messages from the ESP32 glove."""
    print(f"Received from ESP32: {data}")
    message = decrypt(data['morse'])
    device_id = data.get('device_id', 'esp32')
    color = '#ffb700'
    time = datetime.datetime.now()

    collection.insert_one({
        'rescuer': device_id,
        'username': 'ESP32 Glove',
        'message': message,
        'time': time,
        'color': color
    })

    emit('/new_message', {
        'rescuer': device_id,
        'username': 'ESP32 Glove',
        'message': message,
        'time': str(time),
        'color': color
    }, broadcast=True)
    print(f"Stored in MongoDB: {message}")


@socketio.on('/message')
def handle_message(data):
    """Handles incoming Morse code messages from the browser."""
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
    username = session.get('username', 'Unknown')
    color    = session.get('color', '#00ff41')
    time     = datetime.datetime.now()

    doc = {
        'rescuer':  user_id,
        'username': username,
        'message':  message,
        'time':     time,
        'color':    color
    }

    if latitude is not None and longitude is not None:
        doc['latitude']  = latitude
        doc['longitude'] = longitude

    collection.insert_one(doc)

    # Broadcast to ALL clients including sender
    emit('/new_message', {
        'rescuer':   user_id,
        'username':  username,
        'message':   message,
        'time':      str(time),
        'color':     color,
        'latitude':  latitude,
        'longitude': longitude
    }, broadcast=True)

    print(f"Received: {morse} | Translated: {message} | User: {username} | Location: {latitude}, {longitude}")


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
