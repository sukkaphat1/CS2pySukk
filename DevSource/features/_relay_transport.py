"""Small transport adapter shared by the skin-share client."""

import json
import socket

try:
    import websocket as _websocket
except ImportError:
    _websocket = None


class RelayConnection:
    """Expose the same send/recv/close surface for TCP and WebSockets."""

    def __init__(self, connection, is_websocket):
        self.connection = connection
        self.is_websocket = is_websocket

    def send(self, message):
        encoded = json.dumps(message, separators=(",", ":"), sort_keys=True)
        if self.is_websocket:
            self.connection.send(encoded)
        else:
            self.connection.sendall((encoded + "\n").encode("utf-8"))

    def recv(self):
        if self.is_websocket:
            try:
                return self.connection.recv()
            except Exception as exc:
                if _websocket and isinstance(exc, _websocket.WebSocketTimeoutException):
                    return None
                raise
        try:
            return self.connection.recv(4096)
        except socket.timeout:
            return None

    def close(self):
        try:
            if not self.is_websocket:
                self.connection.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.connection.close()
        except Exception:
            pass
