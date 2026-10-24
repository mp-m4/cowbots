import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Import your two bot files
import bot_mvpMarketLogs
import bot_mvpDeathLogs

# --- SINGLE KEEP-ALIVE WEB SERVER FOR RENDER & UPTIMEROBOT ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"MuhRO Combined Bots are active and running!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    print(f"🌐 Keep-alive server running on port {port}")
    server.serve_forever()

def run_market_bot():
    try:
        bot_mvpMarketLogs.run()
    except Exception as e:
        print(f"❌ Error in Market Logs Bot: {e}")

def run_death_bot():
    try:
        # Assuming bot_mvpDeathLogs has a similar run() function
        bot_mvpDeathLogs.run()
    except Exception as e:
        print(f"❌ Error in Death Logs Bot: {e}")

if __name__ == "__main__":
    print("==================================================")
    print(" Starting Unified Multi-Bot Application on Render")
    print("==================================================")

    # 1. Start the HTTP keep-alive web server on its own daemon thread
    threading.Thread(target=run_web_server, daemon=True).start()

    # 2. Create threads for each bot process
    market_thread = threading.Thread(target=run_market_bot)
    death_thread = threading.Thread(target=run_death_bot)

    # 3. Start both bots concurrently
    market_thread.start()
    death_thread.start()

    # 4. Block main thread to keep everything running
    market_thread.join()
    death_thread.join()