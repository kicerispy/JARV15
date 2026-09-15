"""
JARVIS Web Interface - browser-based chat interface.
Run: python web_interface.py
Opens at http://localhost:5000
"""
from flask import Flask, render_template_string, request, jsonify
import sys
import os
from pathlib import Path

# Use the virtual environment's Python packages
VENV_PATH = Path(__file__).parent / "jarvis_cuda" / "Lib" / "site-packages"
if VENV_PATH.exists():
    sys.path.insert(0, str(VENV_PATH))

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>JARVIS</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #1a1a2e; color: #e0e0e0; }
        .container { background: #16213e; border-radius: 10px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        h1 { color: #00d4ff; text-align: center; }
        #messages { height: 400px; overflow-y: scroll; border: 1px solid #0f3460; border-radius: 5px; padding: 10px; margin-bottom: 10px; background: #0f3460; }
        .message { margin: 5px 0; padding: 8px; border-radius: 5px; }
        .user { background: #00d4ff; color: #000; text-align: right; }
        .jarvis { background: #0f3460; text-align: left; }
        input { width: 100%; padding: 10px; border: none; border-radius: 5px; font-size: 16px; }
        button { width: 100%; padding: 10px; background: #00d4ff; color: #000; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; }
        button:hover { background: #00b8d4; }
    </style>
</head>
<body>
    <div class="container">
        <h1>JARVIS</h1>
        <div id="messages"></div>
        <input type="text" id="userInput" placeholder="Type your command..." autofocus>
        <button onclick="sendMessage()">Send</button>
    </div>
    <script>
        function addMessage(text, isUser) {
            var div = document.createElement('div');
            div.className = 'message ' + (isUser ? 'user' : 'jarvis');
            div.textContent = text;
            document.getElementById('messages').appendChild(div);
            document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
        }
        
        async function sendMessage() {
            var input = document.getElementById('userInput');
            var text = input.value;
            if (!text) return;
            
            addMessage(text, true);
            input.value = '';
            
            try {
                var response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: text})
                });
                var data = await response.json();
                addMessage(data.response, false);
            } catch (e) {
                addMessage('Error: ' + e, false);
            }
        }
        
        document.getElementById('userInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') sendMessage();
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/chat', methods=['POST'])
def chat():
    sys.path.insert(0, str(Path(__file__).parent))
    
    from main import process_command
    from state import JarvisState
    from conversation import ConversationHistory
    from code_gen import is_code_request, handle_code_generation
    
    data = request.get_json()
    message = data.get('message', '')
    
    state = JarvisState()
    conversation = ConversationHistory()
    
    if is_code_request(message):
        result = handle_code_generation(message)
    else:
        result = process_command(message, state, conversation, "", lambda x: False)
    
    return jsonify({'response': result})

if __name__ == '__main__':
    print("Starting JARVIS Web Interface...")
    print("Open http://localhost:5000 in your browser")
    app.run(host='127.0.0.1', port=5000, debug=False)