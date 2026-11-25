"""Command dispatch. Maps a decoded command to a RESP reply."""

import fnmatch

from . import resp


class CommandHandler:
    def __init__(self, store, config):
        self.store = store
        self.config = config  # e.g. {"dir": ".", "dbfilename": "dump.rdb"}
        self._commands = {
            b"PING": self._ping,
            b"ECHO": self._echo,
            b"SET": self._set,
            b"GET": self._get,
            b"KEYS": self._keys,
            b"CONFIG": self._config,
            b"COMMAND": self._command,
            b"DBSIZE": self._dbsize,
        }

    def handle(self, args):
        name = args[0].upper()
        command = self._commands.get(name)
        if command is None:
            return resp.error("unknown command '%s'" % args[0].decode("latin-1", "replace"))
        return command(args)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def _ping(self, args):
        if len(args) > 1:
            return resp.bulk(args[1])
        return resp.simple(b"PONG")

    def _echo(self, args):
        if len(args) != 2:
            return resp.error("wrong number of arguments for 'echo' command")
        return resp.bulk(args[1])

    def _set(self, args):
        if len(args) < 3:
            return resp.error("wrong number of arguments for 'set' command")
        key, value = args[1], args[2]
        px = None
        if len(args) >= 5 and args[3].upper() == b"PX":
            try:
                px = int(args[4])
            except ValueError:
                return resp.error("value is not an integer or out of range")
        self.store.set(key, value, px=px)
        return resp.simple(b"OK")

    def _get(self, args):
        if len(args) != 2:
            return resp.error("wrong number of arguments for 'get' command")
        value = self.store.get(args[1])
        if value is None:
            return resp.bulk(None)
        if not isinstance(value, (bytes, bytearray)):
            return resp.error("WRONGTYPE Operation against a key holding the wrong kind of value")
        return resp.bulk(value)

    def _keys(self, args):
        pattern = args[1] if len(args) > 1 else b"*"
        pattern = pattern.decode("latin-1")
        matched = [
            key for key in self.store.keys()
            if fnmatch.fnmatchcase(key.decode("latin-1"), pattern)
        ]
        return resp.array([resp.bulk(key) for key in matched])

    def _config(self, args):
        if len(args) < 3:
            return resp.error("wrong number of arguments for 'config' command")
        if args[1].upper() != b"GET":
            return resp.error("unsupported CONFIG subcommand '%s'" % args[1].decode("latin-1", "replace"))
        name = args[2].decode("latin-1").lower()
        value = self.config.get(name, "")
        return resp.array([resp.bulk(name), resp.bulk(str(value))])

    def _command(self, args):
        # Minimal stub so clients like redis-cli are happy.
        return resp.array([])

    def _dbsize(self, args):
        return resp.integer(self.store.size())
