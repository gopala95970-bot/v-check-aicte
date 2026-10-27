"""Run the API: `python -m vcheck_api` from the backend/ folder."""
from __future__ import annotations

import logging
import socketserver
import sys
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from .app import create_app
from .config import Settings


class ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):      # one concise line per request, no query strings (may contain search terms)
        sys.stderr.write("%s %s\n" % (self.address_string(), (fmt % args).split("?")[0]))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()
    app = create_app(settings)
    srv = make_server(settings.host, settings.port, app, server_class=ThreadingWSGIServer, handler_class=QuietHandler)
    print(f"V-Check AICTE API (independent demonstration prototype) on http://{settings.host}:{settings.port}{'/api/v1'}")
    print("Demo accounts are listed in the README. Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        app.ctx.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
