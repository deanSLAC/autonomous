"""TCP client for SPEC server-mode (www.certif.com/spec_help/server.html).

SPEC runs in server mode when launched with `spec -S <port>` and listens
for a structured binary protocol on that port (we default to 2033). This
module speaks that protocol directly: a 132-byte header (magic
0xFEEDFACE, version 4) followed by an optional null-terminated data
payload.

Advantages over screen-stuffing:
  * Server returns the command's stdout/result in a REPLY packet — no
    hardcopy + prompt-scraping needed.
  * ABORT is a first-class message, not a simulated Ctrl-C.
  * Error reporting is structured (err field + SV_ERROR type).
  * No dependency on GNU screen running at all.

Public surface mirrors `screen_client` so the transport switch in
`screen_client.dispatch()` can pick between them at call time.
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from config import SPEC_HOST, SPEC_MOCK, SPEC_NAME, SPEC_PORT
from spec.screen_client import DispatchResult, _MockScreen

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol constants (from SPECD/include/spec_server.h, doc'd at
# www.certif.com/spec_help/server.html)
# ---------------------------------------------------------------------------

SV_SPEC_MAGIC = 0xFEEDFACE  # 4277009102
SV_VERSION = 4
SV_NAME_LEN = 80

# struct svr_head: 13 32-bit fields + 80-byte name = 132 bytes, packed,
# little-endian (server auto-detects endianness from the first magic word
# we send and byte-swaps as needed — native little-endian is the common
# case on x86/ARM so we hardcode it).
_HDR_FMT = "<IiIIIIiiIIIii80s"
_HDR_SIZE = struct.calcsize(_HDR_FMT)
assert _HDR_SIZE == 132, f"header size mismatch: {_HDR_SIZE}"

# Command codes (svr_head.cmd)
SV_CLOSE = 1
SV_ABORT = 2
SV_CMD = 3
SV_CMD_WITH_RETURN = 4
SV_EVENT = 8
SV_REPLY = 13
SV_HELLO = 14
SV_HELLO_REPLY = 15

# Data types (svr_head.type)
SV_DOUBLE = 1
SV_STRING = 2
SV_ERROR = 3


# ---------------------------------------------------------------------------
# Connection state
# ---------------------------------------------------------------------------

@dataclass
class _Conn:
    sock: socket.socket
    serial: int = 0
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    server_name: str = ""


_conn: Optional[_Conn] = None
_conn_lock = threading.Lock()  # guards _conn init/replacement


# ---------------------------------------------------------------------------
# Packet I/O
# ---------------------------------------------------------------------------

def _pack_header(cmd: int, datatype: int, datalen: int, serial: int, name: str) -> bytes:
    """Build a 132-byte svr_head packed little-endian."""
    t = time.time()
    sec = int(t)
    usec = int((t - sec) * 1_000_000)
    name_bytes = name.encode("latin-1")[: SV_NAME_LEN - 1].ljust(SV_NAME_LEN, b"\x00")
    return struct.pack(
        _HDR_FMT,
        SV_SPEC_MAGIC, SV_VERSION, _HDR_SIZE,
        serial, sec, usec,
        cmd, datatype,
        0, 0,            # rows, cols
        datalen,
        0, 0,            # err, flags (set by server on reply)
        name_bytes,
    )


def _unpack_header(buf: bytes) -> dict:
    (magic, vers, size, sn, sec, usec, cmd, datatype,
     rows, cols, datalen, err, flags, name) = struct.unpack(_HDR_FMT, buf)
    if magic != SV_SPEC_MAGIC:
        raise ConnectionError(
            f"bad magic from SPEC: 0x{magic:08x} (expected 0x{SV_SPEC_MAGIC:08x}); "
            "likely a byte-order mismatch or corrupt stream"
        )
    name_str = name.split(b"\x00", 1)[0].decode("latin-1", errors="replace")
    return {
        "version": vers, "size": size, "sn": sn, "cmd": cmd,
        "type": datatype, "rows": rows, "cols": cols, "len": datalen,
        "err": err, "flags": flags, "name": name_str,
    }


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes, or raise ConnectionError on EOF."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("SPEC connection closed by peer")
        buf.extend(chunk)
    return bytes(buf)


def _read_packet(sock: socket.socket) -> tuple[dict, bytes]:
    hdr = _unpack_header(_recv_exact(sock, _HDR_SIZE))
    data = _recv_exact(sock, hdr["len"]) if hdr["len"] else b""
    return hdr, data


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

def _connect() -> _Conn:
    sock = socket.create_connection((SPEC_HOST, SPEC_PORT), timeout=10.0)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn = _Conn(sock=sock)

    # HELLO handshake. SPEC puts the server's process name in the
    # HELLO_REPLY data section; we use that to sanity-check we hit the
    # right instance when the user has configured SPEC_NAME.
    conn.serial += 1
    sock.sendall(_pack_header(SV_HELLO, SV_STRING, 0, conn.serial, "beamtimehero"))
    hdr, data = _read_packet(sock)
    if hdr["cmd"] != SV_HELLO_REPLY:
        sock.close()
        raise ConnectionError(
            f"expected SV_HELLO_REPLY (15), got cmd={hdr['cmd']} from {SPEC_HOST}:{SPEC_PORT}"
        )
    conn.server_name = data.split(b"\x00", 1)[0].decode("latin-1", errors="replace")
    if SPEC_NAME and conn.server_name and conn.server_name != SPEC_NAME:
        logger.warning(
            "SPEC server name mismatch: got %r at %s:%s, expected %r (SPEC_NAME)",
            conn.server_name, SPEC_HOST, SPEC_PORT, SPEC_NAME,
        )
    logger.info(
        "Connected to SPEC %s:%s (process=%r)",
        SPEC_HOST, SPEC_PORT, conn.server_name,
    )
    return conn


def _get_conn() -> _Conn:
    """Return the live connection, opening/reconnecting if needed."""
    global _conn
    with _conn_lock:
        if _conn is None or _conn.sock.fileno() < 0:
            _conn = _connect()
        return _conn


def _drop_conn(reason: str) -> None:
    global _conn
    with _conn_lock:
        if _conn is None:
            return
        try:
            _conn.sock.close()
        except OSError:
            pass
        _conn = None
        logger.info("SPEC TCP connection dropped: %s", reason)


# ---------------------------------------------------------------------------
# Public surface — mirrors screen_client.{dispatch,abort_current}
# ---------------------------------------------------------------------------

def dispatch(spec_string: str, *, timeout_s: float = 1800.0) -> DispatchResult:
    """Send a SPEC command and return its output.

    In SPEC_MOCK mode, routes to the same in-memory simulator used by the
    screen transport so the two paths behave identically under test.
    """
    started = time.time()

    if SPEC_MOCK:
        output = _MockScreen.inject(spec_string)
        return DispatchResult(
            ok=True, output=output, prompt_seen=True,
            elapsed_s=time.time() - started,
        )

    try:
        conn = _get_conn()
    except Exception as e:
        return DispatchResult(
            ok=False, output="", prompt_seen=False,
            elapsed_s=time.time() - started,
            error=f"spec connect failed ({SPEC_HOST}:{SPEC_PORT}): {e}",
        )

    data_bytes = spec_string.encode("latin-1") + b"\x00"
    with conn.send_lock:
        conn.serial += 1
        serial = conn.serial
        pkt = _pack_header(
            SV_CMD_WITH_RETURN, SV_STRING, len(data_bytes), serial, "",
        )
        try:
            conn.sock.sendall(pkt + data_bytes)
        except OSError as e:
            _drop_conn(f"send failed: {e}")
            return DispatchResult(
                ok=False, output="", prompt_seen=False,
                elapsed_s=time.time() - started,
                error=f"spec send failed: {e}",
            )

    # Wait for the REPLY whose serial matches. Discard intervening
    # EVENTs (we haven't subscribed to any, but a stray one during
    # reconnect is possible).
    conn.sock.settimeout(max(timeout_s, 1.0))
    try:
        while True:
            hdr, data = _read_packet(conn.sock)
            if hdr["cmd"] == SV_REPLY and hdr["sn"] == serial:
                output = data.split(b"\x00", 1)[0].decode("latin-1", errors="replace")
                err = hdr["err"]
                is_err = err != 0 or hdr["type"] == SV_ERROR
                return DispatchResult(
                    ok=not is_err,
                    output=output,
                    prompt_seen=True,
                    elapsed_s=time.time() - started,
                    error=(
                        f"spec error (err={err}): {output or 'no message'}"
                        if is_err else None
                    ),
                )
            if hdr["cmd"] == SV_EVENT:
                logger.debug("ignoring SV_EVENT for %r", hdr["name"])
                continue
            logger.warning(
                "unexpected SPEC packet cmd=%s sn=%s name=%r (waiting for sn=%s)",
                hdr["cmd"], hdr["sn"], hdr["name"], serial,
            )
    except socket.timeout:
        return DispatchResult(
            ok=False, output="", prompt_seen=False,
            elapsed_s=time.time() - started,
            error=f"spec timeout after {timeout_s}s",
        )
    except ConnectionError as e:
        _drop_conn(str(e))
        return DispatchResult(
            ok=False, output="", prompt_seen=False,
            elapsed_s=time.time() - started,
            error=f"spec connection lost: {e}",
        )


def abort_current() -> bool:
    """Send SV_ABORT to SPEC (equivalent to ^C at the server keyboard)."""
    if SPEC_MOCK:
        logger.info("[mock] tcp abort")
        return True
    try:
        conn = _get_conn()
    except Exception as e:
        logger.error("tcp abort: cannot reach SPEC: %s", e)
        return False
    with conn.send_lock:
        conn.serial += 1
        pkt = _pack_header(SV_ABORT, SV_STRING, 0, conn.serial, "")
        try:
            conn.sock.sendall(pkt)
            return True
        except OSError as e:
            _drop_conn(f"abort send failed: {e}")
            return False


def close() -> None:
    """Send SV_CLOSE and tear down the socket. Idempotent; safe at shutdown."""
    global _conn
    with _conn_lock:
        if _conn is None:
            return
        try:
            _conn.sock.sendall(_pack_header(SV_CLOSE, SV_STRING, 0, 0, ""))
        except OSError:
            pass
    _drop_conn("explicit close")
