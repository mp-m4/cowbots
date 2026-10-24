"""Unified launcher for the MuhRO market and MVP trackers."""
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
RESTART_DELAY_SECONDS = max(1, int(os.getenv("BOT_RESTART_DELAY_SECONDS", "10")))
PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
)
log = logging.getLogger("muhro-launcher")

# Import after configuring logging so all modules share the launcher log setup.
import bot_mvpMarketLogs
import bot_mvpDeathLogs

stop_event = threading.Event()
fatal_event = threading.Event()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/health", "/healthz"):
            self.send_error(404)
            return
        status = 500 if fatal_event.is_set() else 200
        body = (
            '{"status":"%s","service":"muhro-combined-bots"}'
            % ("degraded" if fatal_event.is_set() else "ok")
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200 if not fatal_event.is_set() else 500)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def log_message(self, fmt, *args):
        log.debug("HTTP: " + fmt, *args)


def run_web_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.daemon_threads = True
    server.timeout = 1
    log.info("Health server listening on port %s", PORT)
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()
        log.info("Health server stopped")


def supervise_market_bot():
    """Restart the market loop if an unexpected exception escapes it."""
    while not stop_event.is_set():
        try:
            log.info("Starting market tracker")
            bot_mvpMarketLogs.run()
            if not stop_event.is_set():
                log.error("Market tracker returned unexpectedly; restarting in %ss", RESTART_DELAY_SECONDS)
        except Exception:
            log.exception("Market tracker crashed; restarting in %ss", RESTART_DELAY_SECONDS)
        stop_event.wait(RESTART_DELAY_SECONDS)


def run_death_bot():
    """Run once; a fatal exit asks the hosting platform to restart the process."""
    try:
        log.info("Starting MVP death tracker")
        bot_mvpDeathLogs.run()
        if not stop_event.is_set():
            log.critical("MVP death tracker returned unexpectedly")
            fatal_event.set()
    except Exception:
        log.exception("MVP death tracker crashed; marking service unhealthy")
        fatal_event.set()
    finally:
        if fatal_event.is_set():
            stop_event.set()


def main():
    log.info("Starting unified MuhRO multi-bot system")
    server_thread = threading.Thread(target=run_web_server, name="health-server", daemon=True)
    market_thread = threading.Thread(target=supervise_market_bot, name="market-supervisor", daemon=True)
    death_thread = threading.Thread(target=run_death_bot, name="death-tracker", daemon=True)

    server_thread.start()
    market_thread.start()
    death_thread.start()

    try:
        while not stop_event.wait(1):
            if not server_thread.is_alive():
                log.critical("Health server thread exited; stopping service")
                fatal_event.set()
                stop_event.set()
    except KeyboardInterrupt:
        log.info("Shutdown requested")
        stop_event.set()

    # Threads are daemons because the death tracker owns a discord.py event loop.
    # Give them a short chance to observe shutdown before this process exits.
    market_thread.join(timeout=3)
    server_thread.join(timeout=3)
    return 1 if fatal_event.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(main())
