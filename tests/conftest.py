import io
import tarfile

import pytest


def lzw_compress(data: bytes) -> bytes:
    out = bytearray(b"\x1f\x9d\x90")
    table = {bytes([i]): i for i in range(256)}
    next_code = 257
    width = 9
    buf = 0
    nbits = 0

    def emit(code: int) -> None:
        nonlocal buf, nbits
        buf |= code << nbits
        nbits += width
        while nbits >= 8:
            out.append(buf & 0xFF)
            buf >>= 8
            nbits -= 8

    w = b""
    for byte in data:
        wc = w + bytes([byte])
        if wc in table:
            w = wc
            continue
        emit(table[w])
        if next_code < (1 << 16):
            table[wc] = next_code
            if next_code > (1 << width) - 1 and width < 16:
                width += 1
            next_code += 1
        else:
            emit(256)
            table = {bytes([i]): i for i in range(256)}
            next_code = 257
            width = 9
        w = bytes([byte])
    if w:
        emit(table[w])
    if nbits > 0:
        out.append(buf & 0xFF)
    return bytes(out)


@pytest.fixture
def make_archive(tmp_path):
    def _make(path, files):
        tf = io.BytesIO()
        with tarfile.open(fileobj=tf, mode="w") as tar:
            for name, text in sorted(files.items()):
                payload = text.encode("utf-8")
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
        path.write_bytes(lzw_compress(tf.getvalue()))
        return path

    return _make
