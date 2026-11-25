"""RESP (REdis Serialization Protocol) decoding and encoding helpers.

Client commands arrive as RESP arrays of bulk strings:

    *2\r\n$4\r\nECHO\r\n$5\r\nhello\r\n

Replies are simple strings (+OK), bulk strings ($...), errors (-...),
integers (:...) or arrays (*...).
"""

CRLF = b"\r\n"


class RespError(Exception):
    """Raised when a client sends something that is not valid RESP."""


def read_command(stream):
    """Read one command from a binary stream.

    Returns a list of byte strings (the command and its arguments), or
    ``None`` when the client closes the connection. Inline commands such as
    ``PING`` (sent by some tools) are also supported.
    """
    line = _read_line(stream)
    if line is None:
        return None
    if not line:
        # Empty line, skip it and read the next command.
        return read_command(stream)

    if line[:1] == b"*":
        try:
            count = int(line[1:])
        except ValueError:
            raise RespError("invalid array header: %r" % line)
        if count <= 0:
            return []
        return [_read_bulk(stream) for _ in range(count)]

    # Fallback: a plain text line like "PING".
    return line.split()


def _read_line(stream):
    line = stream.readline()
    if not line:
        return None
    if not line.endswith(CRLF):
        raise RespError("expected CRLF terminated line, got %r" % line)
    return line[:-2]


def _read_bulk(stream):
    line = _read_line(stream)
    if line is None:
        raise RespError("unexpected end of stream inside command")
    if line[:1] != b"$":
        raise RespError("expected bulk string, got %r" % line)
    length = int(line[1:])
    if length < 0:
        return None
    data = stream.read(length)
    if len(data) != length:
        raise RespError("truncated bulk string")
    stream.read(2)  # trailing CRLF
    return data


# --------------------------------------------------------------------------
# Encoding helpers. Each returns bytes ready to be written to the socket.
# --------------------------------------------------------------------------

def simple(text):
    if isinstance(text, str):
        text = text.encode()
    return b"+" + text + CRLF


def error(text):
    if isinstance(text, str):
        text = text.encode()
    return b"-" + text + CRLF


def integer(number):
    return b":" + str(int(number)).encode() + CRLF


def bulk(data):
    if data is None:
        return b"$-1\r\n"
    if isinstance(data, str):
        data = data.encode()
    return b"$" + str(len(data)).encode() + CRLF + data + CRLF


def array(items):
    out = b"*" + str(len(items)).encode() + CRLF
    return out + b"".join(items)
