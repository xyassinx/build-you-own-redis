#!/usr/bin/env python3
"""A tiny end-to-end test suite for the redis clone.

Starts the server as a subprocess and exercises each CodeCrafters stage over a
real TCP connection. No third-party packages required.

    python3 tests/run_tests.py
"""

import os
import socket
import struct
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------
# A minimal RESP client
# --------------------------------------------------------------------------
class Client:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.stream = self.sock.makefile("rb")

    def send(self, *args):
        out = b"*%d\r\n" % len(args)
        for arg in args:
            if isinstance(arg, str):
                arg = arg.encode()
            out += b"$%d\r\n%s\r\n" % (len(arg), arg)
        self.sock.sendall(out)

    def request(self, *args):
        self.send(*args)
        return self.read()

    def read(self):
        line = self.stream.readline()
        if not line:
            raise EOFError("server closed the connection")
        prefix, body = line[:1], line[1:].rstrip(b"\r\n")
        if prefix == b"+":
            return body
        if prefix == b"-":
            return ValueError(body.decode())
        if prefix == b":":
            return int(body)
        if prefix == b"$":
            length = int(body)
            if length == -1:
                return None
            data = self.stream.read(length)
            self.stream.read(2)
            return data
        if prefix == b"*":
            count = int(body)
            if count == -1:
                return None
            return [self.read() for _ in range(count)]
        raise ValueError("bad reply: %r" % line)

    def close(self):
        self.stream.close()
        self.sock.close()


# --------------------------------------------------------------------------
# Server lifecycle
# --------------------------------------------------------------------------
def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def start_server(port, workdir):
    process = subprocess.Popen(
        [sys.executable, "-m", "app", "--port", str(port),
         "--dir", workdir, "--dbfilename", "dump.rdb"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            probe = socket.create_connection(("127.0.0.1", port), timeout=0.2)
            probe.close()
            return process
        except OSError:
            time.sleep(0.05)
    process.kill()
    raise RuntimeError("server did not start")


# --------------------------------------------------------------------------
# RDB fixture writer (so we can test loading keys from a dump file)
# --------------------------------------------------------------------------
def encode_length(n):
    if n < 64:
        return bytes([n])
    if n < 16384:
        return bytes([0x40 | (n >> 8), n & 0xFF])
    return bytes([0x80, (n >> 24) & 0xFF, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF])


def encode_string(value):
    return encode_length(len(value)) + value


def build_rdb(entries):
    out = b"REDIS0011"
    out += b"\xFA" + encode_string(b"redis-ver") + encode_string(b"7.4.0")
    out += b"\xFE\x00"
    out += b"\xFB" + encode_length(len(entries)) + encode_length(0)
    for key, value, expiry_ms in entries:
        if expiry_ms is not None:
            out += b"\xFC" + struct.pack("<Q", expiry_ms)
        out += b"\x00" + encode_string(key) + encode_string(value)
    out += b"\xFF" + b"\x00" * 8
    return out


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    status = "PASS" if condition else "FAIL"
    line = "  [%s] %s" % (status, name)
    if detail and not condition:
        line += "  -> " + detail
    print(line)


def run():
    port = free_port()
    with tempfile.TemporaryDirectory() as workdir:
        # Stage 9/10: write a dump file the server should load at startup.
        dump = build_rdb([
            (b"foo", b"bar", None),
            (b"expiring", b"soon", int(time.time() * 1000) + 60_000),
            (b"gone", b"bye", int(time.time() * 1000) - 60_000),
        ])
        with open(os.path.join(workdir, "dump.rdb"), "wb") as handle:
            handle.write(dump)

        process = start_server(port, workdir)
        try:
            # Stage 2: respond to PING
            client = Client(port)
            check("PING returns PONG", client.request("PING") == b"PONG")

            # Stage 3: multiple PINGs on one connection
            ok = all(client.request("PING") == b"PONG" for _ in range(5))
            check("multiple PINGs on one connection", ok)

            # Stage 4 (bonus): ECHO
            check("ECHO returns its argument",
                  client.request("ECHO", "hello") == b"hello")

            # Stage 4: concurrent clients
            other = Client(port)
            client.send("PING")
            other.send("PING")
            check("concurrent clients",
                  client.read() == b"PONG" and other.read() == b"PONG")
            other.close()

            # Stage 5: SET / GET
            check("SET returns OK", client.request("SET", "name", "redis") == b"OK")
            check("GET returns the stored value",
                  client.request("GET", "name") == b"redis")
            check("GET missing key returns null",
                  client.request("GET", "nope") is None)

            # Stage 6: expiry
            client.request("SET", "temp", "value", "PX", "100")
            check("GET before expiry", client.request("GET", "temp") == b"value")
            time.sleep(0.25)
            check("GET after expiry returns null",
                  client.request("GET", "temp") is None)

            # Stage 7/8: keys loaded from the RDB file
            keys = client.request("KEYS", "*")
            keys = set(keys or [])
            check("RDB key present in KEYS", b"foo" in keys, "got %r" % (keys,))
            check("RDB value readable with GET", client.request("GET", "foo") == b"bar")
            check("expired RDB key is not returned",
                  b"gone" not in keys, "got %r" % (keys,))

            # Bonus: CONFIG GET and DBSIZE
            reply = client.request("CONFIG", "GET", "dir")
            check("CONFIG GET dir", reply == [b"dir", workdir.encode()], "got %r" % (reply,))
            check("DBSIZE is an integer", isinstance(client.request("DBSIZE"), int))

            client.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n%d/%d checks passed" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
