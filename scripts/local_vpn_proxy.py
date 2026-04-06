#!/usr/bin/env python3

import errno
import select
import socket
import socketserver
import threading
from urllib.parse import urlsplit


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class BoundProxyHandler(socketserver.StreamRequestHandler):
    timeout = 30

    def handle(self):
        try:
            self.connection.settimeout(self.timeout)
            request_line = self.rfile.readline(65536)
            if not request_line:
                return

            method, target, version = self.parse_request_line(request_line)
            headers = self.read_headers()

            if method.upper() == "CONNECT":
                self.handle_connect(target, version, headers)
            else:
                self.handle_http(method, target, version, headers, request_line)
        except Exception:
            self.safe_close()

    def parse_request_line(self, request_line):
        parts = request_line.decode("iso-8859-1", errors="replace").strip().split()
        if len(parts) != 3:
            raise ValueError("Invalid proxy request line")
        return parts[0], parts[1], parts[2]

    def read_headers(self):
        headers = []
        while True:
            line = self.rfile.readline(65536)
            if not line or line in {b"\r\n", b"\n"}:
                break
            headers.append(line)
        return headers

    def create_bound_socket(self, host, port):
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        remote = socket.socket(family, socket.SOCK_STREAM)
        remote.settimeout(self.timeout)
        remote.bind((self.server.source_ip, 0))
        remote.connect((host, port))
        return remote

    def handle_connect(self, target, version, headers):
        host, port = self.split_host_port(target, default_port=443)
        remote = self.create_bound_socket(host, port)
        try:
            self.wfile.write(f"{version} 200 Connection Established\r\n\r\n".encode("iso-8859-1"))
            self.wfile.flush()
            self.tunnel(self.connection, remote)
        finally:
            remote.close()

    def handle_http(self, method, target, version, headers, request_line):
        parsed = urlsplit(target)
        if parsed.scheme and parsed.hostname:
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
        else:
            host = self.find_host_header(headers)
            if not host:
                raise ValueError("Missing Host header in proxy request")
            host, port = self.split_host_port(host, default_port=80)
            path = target

        remote = self.create_bound_socket(host, port)
        try:
            rewritten_headers = self.rewrite_headers(headers)
            outbound = [f"{method} {path} {version}\r\n".encode("iso-8859-1")]
            outbound.extend(rewritten_headers)
            outbound.append(b"\r\n")
            remote.sendall(b"".join(outbound))

            content_length = self.find_content_length(rewritten_headers)
            if content_length > 0:
                body = self.rfile.read(content_length)
                if body:
                    remote.sendall(body)

            self.tunnel(remote, self.connection)
        finally:
            remote.close()

    def rewrite_headers(self, headers):
        rewritten = []
        saw_connection = False
        for raw in headers:
            lower = raw.lower()
            if lower.startswith(b"proxy-connection:"):
                continue
            if lower.startswith(b"connection:"):
                saw_connection = True
                rewritten.append(b"Connection: close\r\n")
                continue
            rewritten.append(raw)
        if not saw_connection:
            rewritten.append(b"Connection: close\r\n")
        return rewritten

    def find_content_length(self, headers):
        for raw in headers:
            lower = raw.lower()
            if lower.startswith(b"content-length:"):
                try:
                    return int(raw.decode("iso-8859-1").split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    return 0
        return 0

    def find_host_header(self, headers):
        for raw in headers:
            lower = raw.lower()
            if lower.startswith(b"host:"):
                return raw.decode("iso-8859-1").split(":", 1)[1].strip()
        return None

    def split_host_port(self, value, default_port):
        if value.startswith("["):
            host, _, rest = value[1:].partition("]")
            if rest.startswith(":"):
                return host, int(rest[1:])
            return host, default_port

        if value.count(":") == 1:
            host, port_text = value.rsplit(":", 1)
            try:
                return host, int(port_text)
            except ValueError:
                return value, default_port

        return value, default_port

    def tunnel(self, source, destination):
        sockets = [source, destination]
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, self.timeout)
            if exceptional:
                break
            if not readable:
                break
            for current in readable:
                other = destination if current is source else source
                try:
                    data = current.recv(65536)
                    if not data:
                        return
                    other.sendall(data)
                except OSError as exc:
                    if exc.errno not in {errno.EPIPE, errno.ECONNRESET}:
                        raise
                    return

    def safe_close(self):
        try:
            self.connection.close()
        except OSError:
            pass


class LocalBoundProxy:
    def __init__(self, source_ip, listen_host="127.0.0.1", listen_port=0):
        self.source_ip = source_ip
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.server = None
        self.thread = None

    def start(self):
        self.server = ThreadingTCPServer((self.listen_host, self.listen_port), BoundProxyHandler)
        self.server.source_ip = self.source_ip
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server.server_address[1]

    def stop(self):
        if not self.server:
            return
        self.server.shutdown()
        self.server.server_close()
        self.server = None
