from flask import Flask, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)  # Permet les requêtes cross-origin (utile si frontend séparé)

@app.route('/')
def home():
    return jsonify({"message": "Hello, Render!"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
