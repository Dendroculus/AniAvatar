from flask import Flask
from threading import Thread
import logging

"""
This module sets up a minimal Flask web server to keep the bot alive on hosting platforms
that require periodic HTTP requests to prevent idling (e.g., Replit).
"""

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

@app.route('/')
def home():
    # This page is hit by the uptime monitor
    return "Minori Bot is UP!"

def run_flask_server():
    # Run the Flask server in a separate thread on port 8080 (Replit default)
    # use_reloader=False is crucial here to prevent the bot from running twice
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

def keep_alive():
    """Starts the Flask web server in a background thread."""
    t = Thread(target=run_flask_server)
    t.daemon = True 
    t.start()