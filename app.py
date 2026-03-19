from flask import Flask, render_template, request,jsonify,Response,make_response
from flask_socketio import SocketIO, emit
from translator import encrypt, decrypt
import json
import datetime
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import csv
import json
from pymongo import MongoClient
import uuid

uri = "mongodb://admin:password@localhost:27017/"

app = Flask(__name__)
socketio = SocketIO(app)

client = MongoClient(uri, server_api=ServerApi('1'))
    # Send a ping to confirm a successful connection
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)
    
db = client['Secret']
collection = db['morese_code']

all_message= list(collection.find())
if len(all_message)>0:
    last_id = all_message[-1]["_id"]
else:
    last_id = None
    
#CSV to JSON Conversion
def add(record, sid):
    # Create a new client and connect to the server
    time=datetime.datetime.now()
    color=get_color_from_string(request.cookies.get('user_id'))
    
    collection.insert_one({'rescuer': sid, 'message': record, 'time': time,'color': color})
    
    
    print({'rescuer': sid, 'message': record, 'time': datetime.datetime.now(), 'color': color})
    emit('/new_message', {'rescuer': sid, 'message': record, 'time': str(time), 'color': color}, broadcast=True,include_self=False)


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
    """Fetches and returns all messages from the database."""

    global last_id
    global first

    try:
        all_messages = list(collection.find())
        if len(all_messages)>0:
            for message in all_messages:
                message["_id"] = str(message["_id"])

            print(last_id !=all_messages[-1]["_id"])
            if  last_id !=all_messages[-1]["_id"]:
                last_id = all_messages[-1]["_id"]
                print("success")
                return jsonify([all_messages[-1]])

        return jsonify([])
    except Exception as e:
        print(f"Error fetching all messages app: {e}")
        return jsonify({"error": str(e)}), 500
@app.route('/full_messages')
def full_messages():
    client = MongoClient(uri, server_api=ServerApi('1'))
    # Send a ping to confirm a successful connection
    try:
        client.admin.command('ping')
        print("Pinged your deployment. You successfully connected to MongoDB!")
    except Exception as e:
        print(e)
        
    db = client['Secret']
    collection = db['morese_code']
    try:
        all_messages = list(collection.find())
        for message in all_messages:
            message["_id"] = str(message["_id"])

        
        if not all_messages:
            print("No messages in the database.")
            return jsonify([])
       

        print("Sending all messages on connect")
        last_id = all_messages[-1]["_id"]
        print(all_messages)
        return jsonify(all_messages)
    except Exception as e:
        print(f"Error fetching all messages on connect: {e}")
        return jsonify({"error": str(e)}), 500


    
@app.route('/connect')
def handle_connect():
    user_id = request.cookies.get('user_id')
    
    if not user_id:
        user_id = str(uuid.uuid4())  # Generate a unique user ID
        print(f"New user connected: {user_id}")
    else:
        print(f"Returning user connected: {user_id}")

    response = make_response(jsonify({"message": "Connected"}))
    response.set_cookie('user_id', user_id)  # Set the user ID in a cookie
    return response

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@app.route('/')
def index():
    
    return render_template('home.html')

@socketio.on('/message')
def handle_message(data):
    print(data)
    # print(f'Received message: {data} , Translated message: {message}')
    message=decrypt(data)
    add(message, request.cookies.get('user_id'))
    print(f'Received message: {data} , Translated message: {message}')
    # emit('response', {'data': 'Message received!'}, broadcast=True)





if __name__ == '__main__':
    
    socketio.run(app, host='0.0.0.0', port=5000)
