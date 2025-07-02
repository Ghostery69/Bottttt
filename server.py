from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Pour autoriser le frontend web à accéder à ce serveur

messages = []

@app.route('/messages', methods=['GET', 'POST'])
def chat():
    if request.method == 'POST':
        data = request.json
        username = data.get('username')
        message = data.get('message')
        if username and message:
            messages.append({'username': username, 'message': message})
            return jsonify({'status': 'ok'}), 200
        else:
            return jsonify({'status': 'error', 'msg': 'Missing data'}), 400
    else:
        return jsonify(messages)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
