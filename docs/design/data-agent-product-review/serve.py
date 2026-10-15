"""Read-only, loopback-only preview of the prototype and its shared assets."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

DESIGN_ROOT = Path(__file__).resolve().parent.parent
ENTRY = "/data-agent-product-review/index.html"
ALLOWED = {
    ENTRY,
    "/data-agent-product-review/style.css",
    "/data-agent-product-review/app.mjs",
    "/data-agent-product-review/model.mjs",
    "/dashboard-demos/editorial/tokens.mjs",
    "/dashboard-demos/editorial/citation-components.mjs",
    "/dashboard-demos/editorial/source-excerpt.mjs",
    "/company-workspace-swiss-c/assets/uteki-drop-silk.png",
}


class PreviewHandler(SimpleHTTPRequestHandler):
    def allowed_request(self):
        pathname = unquote(urlsplit(self.path).path)
        if pathname in ("/", "/data-agent-product-review/"):
            self.send_response(302)
            self.send_header("Location", ENTRY)
            self.end_headers()
            return False
        if pathname not in ALLOWED:
            self.send_error(404, "Not a prototype resource")
            return False
        self.path = pathname
        return True

    def do_GET(self):
        if self.allowed_request():
            super().do_GET()

    def do_HEAD(self):
        if self.allowed_request():
            super().do_HEAD()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'")
        super().end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8874)
    args = parser.parse_args()
    handler = partial(PreviewHandler, directory=str(DESIGN_ROOT))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Preview: http://127.0.0.1:{args.port}{ENTRY}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
