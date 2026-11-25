# Build Your Own Redis (Python)

A small Redis-compatible server written from scratch in Python, using only the
standard library. It follows the [CodeCrafters "Build Your Own Redis"](https://codecrafters.io/challenges/redis)
challenge, so the goal is a clear, working implementation of the real protocol
rather than a production-grade database.

## What it does

- Listens on a TCP port (default `6379`) and speaks the real **RESP** protocol.
- Handles **multiple clients at once** with one thread per connection.
- Implements `PING`, `ECHO`, `SET`, `GET`, `KEYS`, `CONFIG GET` and `DBSIZE`.
- Supports key **expiry** with `SET key value PX <milliseconds>` (lazy expiration).
- **Loads keys from an RDB dump file** at startup (`--dir` / `--dbfilename`).

## Project layout

```
redis/
├── app/
│   ├── __main__.py    # entry point (python3 -m app)
│   ├── main.py        # argument parsing, TCP server, per-client thread
│   ├── resp.py        # RESP protocol decoder and encoder
│   ├── commands.py    # command dispatch (PING, SET, GET, ...)
│   ├── store.py       # in-memory store with expiry timestamps
│   └── rdb.py         # RDB file parser (strings, ints, LZF, lists, ...)
├── tests/
│   └── run_tests.py   # end-to-end tests over a real socket
├── your_program.sh    # convenience launcher
└── README.md
```

## Running

```sh
./your_program.sh --port 6379 --dir . --dbfilename dump.rdb
# or
python3 -m app --port 6379 --dir . --dbfilename dump.rdb
```

Then talk to it with any Redis client:

```sh
redis-cli -p 6379
127.0.0.1:6379> PING
PONG
127.0.0.1:6379> SET greeting hello PX 5000
OK
127.0.0.1:6379> GET greeting
"hello"
```

## Testing

```sh
python3 tests/run_tests.py
```

The test runner starts the server as a subprocess and checks each stage over a
real TCP connection: PING, multiple and concurrent clients, ECHO, SET/GET,
expiry, and keys loaded from a generated RDB file.

## How it works

- **`resp.py`** reads a command as a RESP array of bulk strings and encodes
  replies (simple strings, bulk strings, errors, integers, arrays).
- **`main.py`** binds the socket, accepts connections, and starts a thread for
  each one. Every thread loops reading commands and writing replies.
- **`store.py`** keeps a `dict` of key -> value plus a second `dict` of key ->
  expiration time. Expired keys are removed lazily on access.
- **`rdb.py`** parses the dump file: the `REDIS` header, metadata opcodes,
  expiry timestamps (`0xFC` / `0xFD`) and the common value types, including
  length-prefixed, integer and LZF-compressed strings.
- **`commands.py`** maps each command name to a handler function.

## CodeCrafters stages covered

1. Bind to a port and accept connections
2. Respond to `PING`
3. Respond to multiple `PING`s on one connection
4. Handle concurrent clients
5. Implement `ECHO`
6. Implement `SET` and `GET`
7. Set a key with an expiry (`PX`)
8. RDB file configuration (`--dir`, `--dbfilename`)
9. Read a key from the RDB file
10. Read a key that has an expiry from the RDB file

Bonus commands: `CONFIG GET`, `DBSIZE`.
