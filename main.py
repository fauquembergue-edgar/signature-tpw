
import webbrowser
import threading
from app import app

def open_browser():
    webbrowser.open_new("http://localhost:5000")

if __name__ == '__main__':
    threading.Timer(1.5, open_browser).start()
    app.run()
