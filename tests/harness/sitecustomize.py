"""Netzwerk-Sperre für den CLI-Subprozess der Akzeptanztests.

Wird automatisch geladen, weil PYTHONPATH auf dieses Verzeichnis zeigt. Erlaubt nur
Loopback-Verbindungen (127.0.0.1, ::1, localhost). Jeder andere Verbindungs- oder
DNS-Versuch wird blockiert (ConnectionRefusedError) und in $ACCEPTANCE_NET_LOG
protokolliert, damit der Test fehlschlägt. So kann eine Implementierung, die die
Test-Konfiguration ignoriert und auf die echten HHN-Defaults zurückfällt,
niemals echte Server kontaktieren.
"""

import os
import socket

_LOG = os.environ.get("ACCEPTANCE_NET_LOG")
_ALLOWED_NAMES = {"localhost", "127.0.0.1", "::1", "localhost.localdomain", "ip6-localhost"}


def _record(what):
    if _LOG:
        try:
            with open(_LOG, "a", encoding="utf-8") as fh:
                fh.write(f"{what}\n")
        except OSError:
            pass


def _is_loopback(host):
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip("[]").lower()
    return host in _ALLOWED_NAMES or host.startswith("127.")


_orig_getaddrinfo = socket.getaddrinfo


def _guarded_getaddrinfo(host, *args, **kwargs):
    if not _is_loopback(host):
        _record(f"getaddrinfo {host}")
        raise socket.gaierror(socket.EAI_NONAME, f"acceptance sandbox: DNS for {host!r} blocked")
    return _orig_getaddrinfo(host, *args, **kwargs)


_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex


def _check_addr(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
        if not _is_loopback(address[0]):
            _record(f"connect {address[0]}:{address[1]}")
            raise ConnectionRefusedError(f"acceptance sandbox: connection to {address[0]} blocked")


def _guarded_connect(self, address):
    _check_addr(self, address)
    return _orig_connect(self, address)


def _guarded_connect_ex(self, address):
    _check_addr(self, address)
    return _orig_connect_ex(self, address)


if os.environ.get("ACCEPTANCE_SANDBOX") == "1":
    socket.getaddrinfo = _guarded_getaddrinfo
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
