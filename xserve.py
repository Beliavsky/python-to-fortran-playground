"""Serve the built static playground locally; no submitted code runs here."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


if __name__ == '__main__':
    if not (ROOT / 'site/vendor/manifest.json').exists():
        raise SystemExit('Run python xvendor.py first.')
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT / 'site'))
    server = ThreadingHTTPServer(('127.0.0.1', 8765), handler)
    print('Open http://127.0.0.1:8765/ (Ctrl+C to stop)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
