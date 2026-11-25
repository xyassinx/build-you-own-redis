"""Entry point: parse arguments, load the RDB file and serve TCP clients."""

import argparse
import os
import socket
import sys
import threading

from . import resp
from .commands import CommandHandler
from .rdb import RDB
from .store import Store


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="redis-clone")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--dir", default=".")
    parser.add_argument("--dbfilename", default="dump.rdb")
    return parser.parse_args(argv)


def build_store(args):
    store = Store()
    rdb = RDB.load(os.path.join(args.dir, args.dbfilename))
    for key, value in rdb.entries.items():
        store.set(key, value, expires_at=rdb.expires.get(key))
    return store


class Server:
    """A simple thread-per-client TCP server."""

    def __init__(self, port, handler):
        self.port = port
        self.handler = handler

    def serve_forever(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", self.port))
        listener.listen(128)
        print("redis-clone listening on port %d" % self.port, file=sys.stderr)
        try:
            while True:
                connection, _ = listener.accept()
                thread = threading.Thread(
                    target=self._serve_client, args=(connection,), daemon=True
                )
                thread.start()
        except KeyboardInterrupt:
            pass
        finally:
            listener.close()

    def _serve_client(self, connection):
        with connection:
            stream = connection.makefile("rb")
            try:
                while True:
                    args = resp.read_command(stream)
                    if args is None:
                        break
                    if not args:
                        continue
                    reply = self.handler.handle(args)
                    if reply:
                        connection.sendall(reply)
            except (ConnectionError, OSError, resp.RespError):
                pass
            finally:
                stream.close()


def main(argv=None):
    args = parse_args(argv)
    store = build_store(args)
    config = {"dir": args.dir, "dbfilename": args.dbfilename}
    handler = CommandHandler(store, config)
    Server(args.port, handler).serve_forever()
