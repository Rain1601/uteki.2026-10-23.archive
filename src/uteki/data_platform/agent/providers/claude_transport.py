"""Bound and record native HTTP requests without changing their protocol or loop.

The only public entry is offline: loopback upstream and synthetic credentials.
No provider credential discovery, retry, redirect or live fallback is provided.
"""
from __future__ import annotations

import asyncio
import base64
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time
import secrets
from urllib.parse import urlsplit

from ...contracts.common import canonical, digest


def unambiguous_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


class OfflineClaudeTransport:
    def __init__(self, journal, upstream, *, before_request, observed_request, validate_request=None):
        parsed = urlsplit(upstream)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
                or parsed.username is not None or parsed.query or parsed.fragment or parsed.path not in {'','/'}):
            raise ValueError('Offline native transport requires an exact loopback fixture root')
        self.journal, self.upstream = journal, parsed
        self.token = secrets.token_urlsafe(32)
        self.before_request, self.observed_request = before_request, observed_request
        self.validate_request = validate_request
        self.events = []
        self.connections, self.lock = set(), threading.Lock()
        self.loop = asyncio.get_running_loop()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_CONNECT(self):
                self.send_error(403, 'External transport is outside the offline boundary')

            def do_GET(self):
                self.send_error(404)

            def do_POST(self):
                owner.handle(self)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.base_url = 'http://127.0.0.1:'+str(self.server.server_port)

    async def __aenter__(self):
        self.thread.start()
        return self

    def callback(self, callback, *arguments):
        async def invoke():
            return callback(*arguments)
        future = asyncio.run_coroutine_threadsafe(invoke(), self.loop)
        try:
            return future.result(timeout=max(.01, self.journal.deadline-time.monotonic()))
        except BaseException:
            future.cancel()
            raise

    def handle(self, handler):
        key, connection, raw_response = None, None, b''
        try:
            self.journal.guard_transport()
            if handler.headers.get('Authorization') != 'Bearer '+self.token:
                raise ValueError('Native request lacks the private runtime transport token')
            parsed = urlsplit(handler.path)
            if parsed.scheme or parsed.netloc or parsed.path != '/v1/messages' or parsed.fragment:
                raise ValueError('Only the explicit native Messages endpoint is permitted')
            retry = handler.headers.get('x-stainless-retry-count', '0')
            if retry != '0':
                raise ValueError('Native automatic retries are not authorized by the offline contract')
            length = int(handler.headers.get('Content-Length', '-1'))
            if length < 1 or length > self.journal.limits.max_request_bytes:
                raise ValueError('Native request body exceeds its explicit bound')
            handler.connection.settimeout(max(.01, self.journal.deadline-time.monotonic()))
            raw_request = handler.rfile.read(length)
            if len(raw_request) != length:
                raise ValueError('Incomplete native request body')
            request = json.loads(raw_request, object_pairs_hook=unambiguous_object)
            if (request.get('model') != self.journal.profile['model_id']
                    or request.get('max_tokens') != self.journal.profile['max_output_tokens']):
                raise ValueError('Native model/output settings differ from the frozen profile')
            self.callback(self.before_request)
            if self.validate_request is not None:
                self.callback(self.validate_request, request)
            metadata = dict(boundary='native_http', method='POST', path=handler.path,
                            body_sha256=digest(raw_request), body_base64=base64.b64encode(raw_request).decode())
            key = self.journal.prepare_model(metadata, request_bytes=len(raw_request))
            connection = http.client.HTTPConnection(self.upstream.hostname, self.upstream.port,
                timeout=max(.01, self.journal.deadline-time.monotonic()))
            with self.lock:
                self.connections.add(connection)
            self.journal.guard_transport()
            headers = {'Content-Type':'application/json', 'Authorization':'Bearer uteki-offline-fixture',
                       'anthropic-version':handler.headers.get('anthropic-version','2023-06-01')}
            if handler.headers.get('anthropic-beta'):
                headers['anthropic-beta'] = handler.headers['anthropic-beta']
            connection.request('POST', handler.path, body=raw_request, headers=headers)
            response = connection.getresponse()
            raw_response = response.read(self.journal.limits.max_response_bytes+1)
            if len(raw_response) > self.journal.limits.max_response_bytes:
                raise ValueError('Native response body exceeds its explicit bound')
            content_type = response.getheader('Content-Type', 'application/octet-stream')
            if response.status == 200 and 'text/event-stream' in content_type:
                # A successful transport EOF is not a complete model stream.
                # This checks the final marker only; the official SDK parses
                # the unmodified protocol bytes and owns content semantics.
                stops = [json.loads(line[5:]) for line in raw_response.splitlines()
                         if line.startswith(b'data:') and line[5:].strip() != b'[DONE]']
                if not any(event.get('type') == 'message_stop' for event in stops):
                    raise ValueError('Native model stream ended without message_stop')
            saved = dict(complete=True, status=response.status, content_type=content_type,
                         body_sha256=digest(raw_response), body_base64=base64.b64encode(raw_response).decode())
            self.journal.record_model(key, saved, complete=True)
            self.journal.guard_transport()
            if response.status == 200:
                self.callback(self.observed_request, request)
            handler.send_response(response.status)
            handler.send_header('Content-Type', content_type)
            handler.send_header('Content-Length', str(len(raw_response)))
            handler.end_headers()
            handler.wfile.write(raw_response)
            self.events.append(dict(request_key=key, status='forwarded', body_sha256=metadata['body_sha256']))
        except Exception as error:
            self.events.append(dict(request_key=key, status='blocked_or_interrupted', error_type=type(error).__name__))
            if key is not None:
                saved = self.journal.budget.inspect_request(key)
                if saved['stage'] == 'dispatched':
                    self.journal.record_model(key, dict(complete=False, error_type=type(error).__name__,
                        partial_body_base64=base64.b64encode(raw_response[:self.journal.limits.max_response_bytes]).decode()), complete=False)
            try:
                body = canonical(dict(type='error',error=dict(type='invalid_request_error',
                    message='Data runtime transport stopped: '+type(error).__name__)))
                handler.send_response(400)
                handler.send_header('Content-Type','application/json')
                handler.send_header('Content-Length',str(len(body)))
                handler.end_headers();handler.wfile.write(body)
            except (OSError,ValueError):
                pass
        finally:
            if connection is not None:
                connection.close()
                with self.lock:
                    self.connections.discard(connection)

    def close(self):
        with self.lock:
            for connection in self.connections:
                if connection.sock is not None:
                    try:
                        connection.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    async def __aexit__(self, *errors):
        await asyncio.to_thread(self.close)
