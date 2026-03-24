from flask import Flask, render_template, request, jsonify, Response, make_response
from flask_socketio import SocketIO, emit
from translator import encrypt, decrypt
import json
import datetime
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import uuid

uri = "mongodb://admin:password@localhost:27017/"

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

client = MongoClient(uri, server_api=ServerApi('1'))
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)

db = client['Secret']
collection = db['morese_code']

all_message = list(collection.find())
if len(all_message) > 0:
    last_id = all_message[-1]["_id"]
else:
    last_id = None


def add(record, sid, latitude=None, longitude=None):
    """Insert a decoded message into MongoDB and broadcast to all clients."""
    time = datetime.datetime.now()
    color = get_color_from_string(sid)

    doc = {
        'rescuer': sid,
        'message': record,
        'time': time,
        'color': color
    }

    # Attach location if provided
    if latitude is not None and longitude is not None:
        doc['latitude'] = latitude
        doc['longitude'] = longitude

    collection.insert_one(doc)
    print(doc)

    # Broadcast to all clients including sender so message appears in their feed
    emit('/new_message', {
        'rescuer': sid,
        'message': record,
        'time': str(time),
        'color': color,
        'latitude': latitude,
        'longitude': longitude
    }, broadcast=True)


def string_to_hash(s):
    """Hashes a string to a numerical value."""
    hash_val = 0
    for char in s:
        hash_val = ord(char) + ((hash_val << 5) - hash_val)
    return hash_val


def hash_to_color(hash_val):
    """Converts a hash value to an RGB color string."""
    r = (hash_val & 0xFF0000) >> 16
    g = (hash_val & 0x00FF00) >> 8
    b = hash_val & 0x0000FF
    return f"rgb({r}, {g}, {b})"


def get_color_from_string(s):
    """Generates a color string from an input string."""
    hash_val = string_to_hash(s)
    return hash_to_color(hash_val)


@app.route('/new_messages')
def get_all_messages():
    """Fetches and returns the latest message from the database."""
    global last_id

    try:
        all_messages = list(collection.find())
        if len(all_messages) > 0:
            for message in all_messages:
                message["_id"] = str(message["_id"])

            if last_id != all_messages[-1]["_id"]:
                last_id = all_messages[-1]["_id"]
                return jsonify([all_messages[-1]])

        return jsonify([])
    except Exception as e:
        print(f"Error fetching messages: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/full_messages')
def full_messages():
    """Fetches and returns all messages from the database."""
    try:
        all_messages = list(collection.find())
        for message in all_messages:
            message["_id"] = str(message["_id"])

        if not all_messages:
            print("No messages in the database.")
            return jsonify([])

        print("Sending all messages on connect")
        return jsonify(all_messages)
    except Exception as e:
        print(f"Error fetching all messages: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/connect')
def connect_user():
    """Handles user connection and sets a cookie with a unique user ID."""
    user_id = request.cookies.get('user_id')

    if not user_id:
        user_id = str(uuid.uuid4())
        print(f"New user connected: {user_id}")
    else:
        print(f"Returning user connected: {user_id}")

    response = make_response(jsonify({"message": "Connected"}))
    response.set_cookie('user_id', user_id)
    return response


@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')


@socketio.on('connect')
def handle_socketio_connect():
    user_id = request.cookies.get('user_id')
    if not user_id:
        print(f"New device connected")
    else:
        print(f"Returning device connected: {user_id}")
    emit('message', {'message': 'Welcome from MorseApp Flask!'})


@socketio.on('esp32_message')
def handle_esp32_message(data):
    """Handles incoming Morse code messages from the ESP32 glove."""
    print(f"Received from ESP32: {data}")
    message = decrypt(data['morse'])
    color = get_color_from_string(data.get('device_id', 'esp32'))
    time = datetime.datetime.now()
    collection.insert_one({
        'rescuer': data.get('device_id', 'esp32'),
        'message': message,
        'time': time,
        'color': color
    })
    emit('/new_message', {
        'rescuer': data.get('device_id', 'esp32'),
        'message': message,
        'time': str(time),
        'color': color
    }, broadcast=True)
    print(f"Stored in MongoDB: {message}")


@app.route('/')
def index():
    return render_template('home.html')


@socketio.on('/message')
def handle_message(data):
    """Handles incoming Morse code messages from the browser."""
    # data can be a string (morse only) or a dict (morse + location)
    if isinstance(data, dict):
        morse = data.get('morse', '')
        latitude = data.get('latitude')
        longitude = data.get('longitude')
    else:
        morse = data
        latitude = None
        longitude = None

    message = decrypt(morse)
    sid = request.cookies.get('user_id', str(uuid.uuid4()))
    add(message, sid, latitude, longitude)
    print(f"Received: {morse} | Translated: {message} | Location: {latitude}, {longitude}")


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
