from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from pymongo import MongoClient

app = Flask(__name__)
socketio = SocketIO(app)

client = MongoClient('localhost', 27017)
db = client.morsecode_db
messages = db.messages

morse_code_dict = {
    'dot': '.',
    'dash': '-',
    'space': ' '
}

current_message = []

@app.route('/')
def index():
    return render_template('home.html')

@socketio.on('message')
def handle_message(data):
    global current_message
    if data == 'start':
        current_message = []
    elif data in morse_code_dict:
        current_message.append(morse_code_dict[data])
    elif data == 'end':
        translated_message = ''.join(current_message)
        messages.insert_one({'message': translated_message})
        emit('response', {'data': translated_message})
    else:
        emit('response', {'data': 'Invalid input'})
    
if __name__ == '__main__':
    socketio.run(app)
