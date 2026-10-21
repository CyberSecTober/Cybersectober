"""Local-only HTTP server for PromptTrace Lab.

This is a deterministic training simulator, not a production AI agent.
It never connects to external services or executes real-world tools.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from prompttrace.engine import run_experiment
from prompttrace.scenarios import list_scenarios

HOST = "127.0.0.1"
PORT = 8000
WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_BODY_BYTES = 8192
MAX_TEXT_CHARS = 4000

STATIC_FILES = {
    "/": "index.html",
    "/web/index.html": "index.html",
    "/web/app.js": "app.js",
    "/web/styles.css": "styles.css",
}


class PromptTraceHandler(BaseHTTPRequestHandler):
    """Serve the UI and a small, validated JSON API."""

    server_version = "PromptTraceLab/1.0"

    def send_bytes(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, payload):
        content = json.dumps(payload).encode("utf-8")
        self.send_bytes(status, content, "application/json; charset=utf-8")

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/scenarios":
            self.send_json(200, {"scenarios": list_scenarios()})
            return

        filename = STATIC_FILES.get(path)
        if filename is None:
            self.send_json(404, {"error": "Route not found."})
            return

        file_path = WEB_DIR / filename
        try:
            content = file_path.read_bytes()
        except OSError:
            self.send_json(500, {"error": "The requested UI file is unavailable."})
            return

        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(file_path.suffix, "application/octet-stream")

        self.send_bytes(200, content, content_type)

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            self.send_json(404, {"error": "Route not found."})
            return

        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type.lower():
            self.send_json(
                415, {"error": "Content-Type must be application/json."}
            )
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid Content-Length header."})
            return

        if length <= 0 or length > MAX_BODY_BYTES:
            self.send_json(
                413,
                {"error": "Request body must be between 1 and 8192 bytes."},
            )
            return

        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(
                400, {"error": "Request body must contain valid JSON."}
            )
            return

        if not isinstance(payload, dict):
            self.send_json(400, {"error": "JSON body must be an object."})
            return

        mode = payload.get("mode")
        if not isinstance(mode, str):
            self.send_json(400, {"error": "Provide a string field 'mode'."})
            return

        user_prompt = payload.get("user_prompt")
        retrieved_document = payload.get("retrieved_document")
        scenario_id = payload.get("scenario_id")

        # Custom mode is selected when a user_prompt field is supplied.
        if "user_prompt" in payload:
            if not isinstance(user_prompt, str) or not user_prompt.strip():
                self.send_json(
                    400, {"error": "'user_prompt' must be a non-empty string."}
                )
                return

            if len(user_prompt) > MAX_TEXT_CHARS:
                self.send_json(
                    413, {"error": "User prompt exceeds 4000 characters."}
                )
                return

            if retrieved_document is not None:
                if not isinstance(retrieved_document, str):
                    self.send_json(
                        400,
                        {
                            "error": (
                                "'retrieved_document' must be a string or null."
                            )
                        },
                    )
                    return
                if len(retrieved_document) > MAX_TEXT_CHARS:
                    self.send_json(
                        413,
                        {
                            "error": (
                                "Retrieved document exceeds 4000 characters."
                            )
                        },
                    )
                    return

            try:
                result = run_experiment(
                    scenario_id if isinstance(scenario_id, str) else "custom",
                    mode,
                    user_prompt=user_prompt,
                    retrieved_document=retrieved_document,
                )
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
                return
        else:
            if not isinstance(scenario_id, str):
                self.send_json(
                    400,
                    {
                        "error": (
                            "Provide 'scenario_id' for a preset scenario, "
                            "or 'user_prompt' for custom input."
                        )
                    },
                )
                return

            try:
                result = run_experiment(scenario_id, mode)
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
                return

        self.send_json(200, result)

    def log_message(self, format_string, *args):
        """Keep local terminal logs concise."""
        print(f"[PromptTrace] {args[0]}")


def main():
    server = ThreadingHTTPServer((HOST, PORT), PromptTraceHandler)
    print(f"PromptTrace Lab running at http://{HOST}:{PORT}")
    print("Local-only training simulator. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping PromptTrace Lab...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
