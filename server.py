from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Stockage en mémoire (exemple simple, pas pour prod)
messages = []

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/messages", methods=["GET", "POST"])
def messages_route():
    if request.method == "POST":
        data = request.get_json()
        username = data.get("username")
        message = data.get("message")
        if username and message:
            messages.append({"username": username, "message": message})
            # Limiter la liste à 100 messages max (optionnel)
            if len(messages) > 100:
                messages.pop(0)
            return jsonify({"status": "ok"}), 201
        return jsonify({"error": "Bad request"}), 400

    # GET
    return jsonify(messages)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
