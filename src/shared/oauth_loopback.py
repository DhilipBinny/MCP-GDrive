"""Loopback listener for the installed-app OAuth redirect.

``google-auth-oauthlib`` 1.5.0 ``run_local_server`` listens on 127.0.0.1.
When the redirect host is ``localhost`` it also binds ``::1`` without calling
``listen``. A connect to that IPv6 socket returns ``ECONNREFUSED``, and the
socket does not appear in ``/proc/net/tcp6``. This listener accepts on both
loopback addresses when the kernel allows the IPv6 bind, and it keeps
accepting until the OAuth redirect arrives so a probe or favicon request
cannot consume the authorization response.
"""

from __future__ import annotations

import contextlib
import errno
import select
import socket
import sys
import threading
import urllib.parse
from dataclasses import dataclass

_MAX_REQUEST_BYTES = 65536
_SUCCESS_BODY = b"The authentication flow has completed. You may close this window.\n"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


@dataclass(frozen=True)
class ProbeResult:
    """Result of a same-process TCP connect to one loopback address."""

    address: str
    errno: int


class LoopbackCallbackServer:
    """HTTP server bound to loopback for one OAuth redirect."""

    def __init__(self) -> None:
        self.port = 0
        self.redirect_host = ""
        self.redirect_uri = ""
        self.probe_results: list[ProbeResult] = []
        self.ipv6_bind_error = ""
        self.callback_peer = ""
        self._sockets: list[socket.socket] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._serving = threading.Event()
        self._got_callback = threading.Event()
        self._got_browser = threading.Event()
        self._lock = threading.Lock()
        self._callback_uri: str | None = None
        self._browser_peer = ""
        self._closed = False
        self._started = False

    def __enter__(self) -> LoopbackCallbackServer:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def ipv4_ok(self) -> bool:
        return any(item.address == "127.0.0.1" and item.errno == 0 for item in self.probe_results)

    @property
    def ipv6_listening(self) -> bool:
        return any(item.address == "::1" and item.errno == 0 for item in self.probe_results)

    def start(self) -> None:
        if self._started:
            raise RuntimeError("Callback listener is already started.")
        ipv4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            ipv4.bind(("127.0.0.1", 0))
            self.port = int(ipv4.getsockname()[1])
            ipv4.listen(5)
            self._sockets.append(ipv4)
        except Exception:
            ipv4.close()
            raise

        if hasattr(socket, "AF_INET6"):
            ipv6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            try:
                ipv6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                ipv6.bind(("::1", self.port))
                ipv6.listen(5)
                self._sockets.append(ipv6)
            except OSError as exc:
                ipv6.close()
                self.ipv6_bind_error = f"{exc.errno} {exc.strerror}"

        # Updated after the same-process probes. Requests during the probe use
        # the IPv4 host; the flow reads redirect_uri only after start() returns.
        self.redirect_host = "127.0.0.1"
        self.redirect_uri = f"http://127.0.0.1:{self.port}/"
        self._started = True
        self._thread = threading.Thread(target=self._serve, name="oauth-loopback", daemon=True)
        self._thread.start()
        if not self._serving.wait(2):
            self.close()
            raise RuntimeError("OAuth callback listener did not start.")
        if hasattr(socket, "AF_INET6"):
            ipv6_probe = self._probe("::1", socket.AF_INET6)
        else:
            ipv6_probe = ProbeResult("::1", errno.EAFNOSUPPORT)
        self.probe_results = [self._probe("127.0.0.1", socket.AF_INET), ipv6_probe]
        self.redirect_host = "localhost" if ipv6_probe.errno == 0 else "127.0.0.1"
        self.redirect_uri = f"http://{self.redirect_host}:{self.port}/"

    def describe(self) -> list[str]:
        """Factual lines about the sockets this process bound and probed."""
        if not self._started:
            raise RuntimeError("Callback listener has not started.")
        lines: list[str] = []
        for probe in self.probe_results:
            if probe.errno == 0:
                lines.append(f"Loopback {probe.address}:{self.port} accepted a connection from this process.")
            else:
                name = errno.errorcode.get(probe.errno, "unknown")
                lines.append(
                    f"Loopback {probe.address}:{self.port} connection from this process failed: "
                    f"errno {probe.errno} ({name})."
                )
        if self.ipv6_bind_error:
            lines.append(f"IPv6 loopback bind did not listen: {self.ipv6_bind_error}.")
        lines.append(f"OAuth redirect host is {self.redirect_host}.")
        lines.append("A same-process connection does not show whether a browser can connect.")
        return lines

    def wait_for_oauth_redirect(self, timeout: float | None = None) -> str:
        if not self._got_callback.wait(timeout):
            raise TimeoutError("timed out waiting for the OAuth callback")
        with self._lock:
            if self._callback_uri is None:
                raise TimeoutError("timed out waiting for the OAuth callback")
            return self._callback_uri

    def wait_for_browser(self, timeout: float) -> str | None:
        """Wait for a request other than the same-process ``/ready`` probe."""
        if not self._got_browser.wait(timeout):
            return None
        return self._browser_peer

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        for sock in self._sockets:
            with contextlib.suppress(OSError):
                sock.close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _probe(self, address: str, family: int) -> ProbeResult:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            if family == socket.AF_INET6:
                err = sock.connect_ex((address, self.port, 0, 0))
            else:
                err = sock.connect_ex((address, self.port))
            if err != 0:
                return ProbeResult(address, err)
            host = f"[{address}]" if family == socket.AF_INET6 else address
            request = f"GET /ready HTTP/1.1\r\nHost: {host}:{self.port}\r\nConnection: close\r\n\r\n"
            sock.sendall(request.encode("ascii"))
            status = _read_status_line(sock)
            if not status.startswith("HTTP/1.1 200"):
                return ProbeResult(address, getattr(errno, "EPROTO", errno.EIO))
            return ProbeResult(address, 0)
        except OSError as exc:
            return ProbeResult(address, exc.errno or errno.EIO)
        finally:
            sock.close()

    def _serve(self) -> None:
        self._serving.set()
        while not self._stop.is_set():
            try:
                readable, _, _ = select.select(self._sockets, [], [], 0.2)
            except (OSError, ValueError):
                break
            for listening in readable:
                try:
                    conn, addr = listening.accept()
                except OSError:
                    continue
                try:
                    self._handle(conn, addr)
                except OSError:
                    pass
                except Exception:
                    print("Loopback callback connection could not be read.", file=sys.stderr)
                finally:
                    with contextlib.suppress(OSError):
                        conn.close()

    def _handle(self, conn: socket.socket, addr: tuple[object, ...]) -> None:
        conn.settimeout(2)
        peer = str(addr[0])
        if peer.startswith("::ffff:"):
            peer = peer.removeprefix("::ffff:")
        if peer not in _LOOPBACK_HOSTS:
            _respond(conn, 403, b"forbidden\n")
            return
        data = _read_headers(conn)
        if data is None:
            _respond(conn, 414, b"request too large\n")
            return
        target = _request_target(data)
        if target is None or not target.startswith("/"):
            _respond(conn, 400, b"bad request\n")
            return
        parsed = urllib.parse.urlsplit(target)
        path = parsed.path or "/"
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if path != "/ready":
            with self._lock:
                if not self._browser_peer:
                    self._browser_peer = peer
            self._got_browser.set()
        if "code" in query or "error" in query:
            uri = f"http://{self.redirect_host}:{self.port}{target}"
            with self._lock:
                if self._callback_uri is None:
                    self._callback_uri = uri
                    self.callback_peer = peer
                    notify = True
                else:
                    notify = False
            _respond(conn, 200, _SUCCESS_BODY)
            if notify:
                self._got_callback.set()
            return
        if path in {"/ready", "/diag"}:
            _respond(conn, 200, b"ok\n")
            return
        _respond(conn, 404, b"not found\n")


def diagnose_loopback(wait_seconds: float = 60) -> int:
    """Bind a fresh callback socket and report same-process connect results.

    Does not read a client secret, contact Google, or connect to any other port.
    """
    with LoopbackCallbackServer() as server:
        for line in server.describe():
            print(line, file=sys.stderr)
        print("This check does not contact Google and does not read a client secret.", file=sys.stderr)
        print(
            "It listens on a new port. Do not send a request to any other auth process's port.",
            file=sys.stderr,
        )
        print(
            "Do not open an existing OAuth redirect URL here. Its query contains the authorization code.",
            file=sys.stderr,
        )
        if not server.ipv4_ok:
            print("This process could not connect to its IPv4 loopback listener.", file=sys.stderr)
            return 1
        print(f"Diagnostic URL (IPv4): http://127.0.0.1:{server.port}/diag", file=sys.stderr)
        if server.redirect_host == "localhost":
            print(f"Diagnostic URL (localhost): http://localhost:{server.port}/diag", file=sys.stderr)
        if wait_seconds <= 0:
            return 0
        print(
            f"Waiting up to {wait_seconds:.0f}s for a request to this diagnostic port.",
            file=sys.stderr,
        )
        peer = server.wait_for_browser(wait_seconds)
        if peer is None:
            print("No request arrived from outside the same-process probe.", file=sys.stderr)
            return 0
        print(f"A request reached this process from {peer}.", file=sys.stderr)
        return 0


def _read_status_line(sock: socket.socket) -> str:
    data = b""
    while b"\r\n" not in data and len(data) < 128:
        chunk = sock.recv(64)
        if not chunk:
            break
        data += chunk
    return data.split(b"\r\n", 1)[0].decode("ascii", "replace")


def _read_headers(conn: socket.socket) -> bytes | None:
    data = b""
    while b"\r\n\r\n" not in data:
        try:
            chunk = conn.recv(4096)
        except TimeoutError:
            return data or None
        if not chunk:
            break
        data += chunk
        if len(data) > _MAX_REQUEST_BYTES and b"\r\n\r\n" not in data:
            return None
    return data


def _request_target(data: bytes) -> str | None:
    line = data.split(b"\r\n", 1)[0].decode("iso-8859-1", "replace")
    parts = line.split(" ")
    if len(parts) < 2 or parts[0].upper() not in {"GET", "HEAD"}:
        return None
    return parts[1]


def _respond(conn: socket.socket, status: int, body: bytes) -> None:
    reason = {
        200: "OK",
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        414: "URI Too Long",
    }.get(status, "OK")
    head = (
        f"HTTP/1.1 {status} {reason}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "\r\n"
    ).encode("ascii")
    try:
        conn.sendall(head + body)
    except OSError:
        return
