"""LAN-мост на Mac: один раз запустить, Windows сам шлёт прокси при каждом run.bat."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from proxy_relay import UpstreamStore, start_dynamic_relay

DEFAULT_PORT = 8765
DEFAULT_CONTROL_PORT = 8767


def _start_control(store: UpstreamStore, port: int, bind: str) -> ThreadingHTTPServer:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def do_PUT(self) -> None:
            if self.path.rstrip("/") != "/upstream":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8", errors="replace").strip()
            try:
                label = store.set_from_line(body)
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            print(f"  upstream: {label}", flush=True)
            self.send_response(204)
            self.end_headers()

    srv = ThreadingHTTPServer((bind, port), _Handler)
    threading.Thread(target=srv.serve_forever, name="bridge-ctl", daemon=True).start()
    return srv


def _configure_stdio() -> None:
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def main() -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="Mac LAN-мост для YT-COOKIES (Windows).")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--bind", default="0.0.0.0")
    args = parser.parse_args()

    relay, store = start_dynamic_relay(bind_host=args.bind, fixed_port=args.port)
    ctl = _start_control(store, args.control_port, args.bind)

    print(f"Мост: {args.bind}:{relay.local_port}  |  control: {args.control_port}")
    print("Windows: URL v .lan_bridge -> run.bat (proksi peredastsa sam)")
    print("Ctrl+C - stop")
    print()

    def _stop(*_a) -> None:
        relay.close()
        ctl.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, _stop)

    try:
        signal.pause()
    except AttributeError:
        import time

        while True:
            time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
