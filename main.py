import os
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# Import both bot files
import bot_mvpMarketLogs
import bot_mvpDeathLogs

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok", "service": "muhro-combined-bots"}')

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    print(f"🌐 Keep-alive server running on port {port}")
    server.serve_forever()

def run_market_bot():
    try:
        bot_mvpMarketLogs.run()
    except Exception as e:
        print(f"❌ Error in Market Bot: {e}")

def run_death_bot():
    try:
        bot_mvpDeathLogs.run()
    except Exception as e:
        print(f"❌ Error in Death Bot: {e}")

if __name__ == "__main__":
    print("==================================================")
    print(" Starting Unified MuhRO Multi-Bot System")
    print("==================================================")

    # Start web keep-alive server
    threading.Thread(target=run_web_server, daemon=True).start()

    # Start both bots concurrently on separate threads
    market_thread = threading.Thread(target=run_market_bot, daemon=True)
    death_thread = threading.Thread(target=run_death_bot, daemon=True)

    market_thread.start()
    death_thread.start()

    # Keep main thread alive
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
