"""The security check of every picture a player uploads for their own heroes, enemies and objects.

A picture is never stored as it arrived. It goes through these checks, in order, and the first one
that fails rejects it with a message the player can understand:

1. Size: at most MAX_UPLOAD_BYTES of file.
2. Type: it must really be a PNG (its first bytes), whatever its name says. The browser turns PNG,
   JPG, GIF and WebP pictures into a PNG before sending, so only one format reaches the server.
3. Structure: every block of the file has a valid checksum, only picture blocks are allowed (no text,
   metadata or unknown blocks, where payloads hide) and nothing follows the end of the picture.
4. Content: no scripts, web pages, PHP, shell or executables hidden anywhere in the bytes.
5. Antivirus: when CLAMAV_HOST is configured, the file is scanned by ClamAV; if the antivirus is
   configured but does not answer, the picture is rejected (it never passes unscanned).
6. Picture: the pixels are decoded in full, with a hard limit on their size (no "compression bomb"),
   between MIN_SIDE and MAX_SIDE pixels per side, and not completely transparent.
7. Clean copy: a brand-new PNG is written from the pixel values alone. That copy is what is stored
   and served: not a single byte of the uploaded file is ever kept.
"""
import os
import re
import socket
import struct
import zlib
from dataclasses import dataclass, field

MAX_UPLOAD_BYTES = 300_000
MIN_SIDE = 8
MAX_SIDE = 256
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Picture blocks only. Text and metadata blocks (tEXt, zTXt, iTXt, eXIf, iCCP...) are refused.
ALLOWED_CHUNKS = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND", b"sRGB", b"gAMA", b"pHYs", b"cHRM"}
SUSPICIOUS = re.compile(
    rb"<\s*script|<\s*/?\s*html|<\s*svg|<\s*iframe|<\?php|javascript:|vbscript:|onerror\s*=|onload\s*=|"
    rb"#!/bin/|#!/usr/|powershell|cmd\.exe|eval\s*\(|base64_decode|\x7fELF|MZ\x90\x00|PK\x03\x04|%PDF-",
    re.IGNORECASE,
)


class SpriteRejected(ValueError):
    """The picture failed a check; the message says which one, in Spanish, for the player."""


class AntivirusUnavailable(RuntimeError):
    """ClamAV is configured but did not answer: the upload must be refused, never let through."""


@dataclass
class CleanSprite:
    png: bytes
    width: int
    height: int
    checks: list = field(default_factory=list)


def _chunks(data: bytes):
    """(type, body) of every block after the signature, checking lengths and checksums."""
    pos = len(PNG_SIGNATURE)
    while pos < len(data):
        if pos + 12 > len(data):
            raise SpriteRejected("El archivo está cortado o dañado")
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if length > MAX_UPLOAD_BYTES or end > len(data):
            raise SpriteRejected("El archivo está cortado o dañado")
        body = data[pos + 8:pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length:end])[0]
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise SpriteRejected("El archivo está dañado (un bloque no cuadra)")
        yield kind, body
        pos = end
        if kind == b"IEND":
            if pos != len(data):
                raise SpriteRejected("El archivo esconde datos después de la imagen")
            return
    raise SpriteRejected("El archivo no termina como una imagen")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> bytearray:
    """Undo the PNG row filters; returns the pixel bytes (bpp bytes per pixel)."""
    stride = width * bpp
    out = bytearray(stride * height)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        kind = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if kind == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif kind == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif kind == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                up_left = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], up_left)) & 0xFF
        elif kind != 0:
            raise SpriteRejected("La imagen tiene datos que no son válidos")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def _write_png(rgba: bytes, width: int, height: int) -> bytes:
    """A new RGBA PNG with only the three blocks a picture needs."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _antivirus(data: bytes) -> str | None:
    """'limpio' after a ClamAV scan, or None when no antivirus is configured. Raises if it finds something."""
    host = os.environ.get("CLAMAV_HOST", "").strip()
    if not host:
        return None
    port = int(os.environ.get("CLAMAV_PORT", "3310"))
    try:
        with socket.create_connection((host, port), timeout=8) as conn:
            conn.sendall(b"zINSTREAM\0")
            for start in range(0, len(data), 8192):
                piece = data[start:start + 8192]
                conn.sendall(struct.pack(">I", len(piece)) + piece)
            conn.sendall(struct.pack(">I", 0))
            reply = b""
            while not reply.endswith(b"\0"):
                part = conn.recv(4096)
                if not part:
                    break
                reply += part
    except OSError as error:
        raise AntivirusUnavailable("El antivirus no respondió; inténtalo más tarde") from error
    text = reply.rstrip(b"\0").decode("utf-8", "replace")
    if text.endswith("FOUND"):
        raise SpriteRejected("El antivirus encontró una amenaza en el archivo")
    if not text.endswith("OK"):
        raise AntivirusUnavailable("El antivirus no pudo revisar el archivo; inténtalo más tarde")
    return "limpio"


def scan_sprite(data: bytes) -> CleanSprite:
    """Run every check on an uploaded picture and return its clean copy (see the module's docstring)."""
    checks = []
    if not data:
        raise SpriteRejected("El archivo está vacío")
    if len(data) > MAX_UPLOAD_BYTES:
        raise SpriteRejected(f"La imagen pesa demasiado (máximo {MAX_UPLOAD_BYTES // 1000} KB)")
    checks.append("size")
    if not data.startswith(PNG_SIGNATURE):
        raise SpriteRejected("El archivo no es una imagen PNG válida")
    checks.append("type")

    header = None
    palette = None
    idat = bytearray()
    for kind, body in _chunks(data):
        if kind not in ALLOWED_CHUNKS:
            raise SpriteRejected("La imagen trae bloques ocultos o metadatos que no se permiten")
        if kind == b"IHDR":
            if header is not None or len(body) != 13:
                raise SpriteRejected("La cabecera de la imagen no es válida")
            header = struct.unpack(">IIBBBBB", body)
        elif header is None:
            raise SpriteRejected("La imagen no empieza con su cabecera")
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            idat += body
    if header is None or not idat:
        raise SpriteRejected("El archivo no contiene una imagen")
    checks.append("structure")

    if SUSPICIOUS.search(data):
        raise SpriteRejected("El archivo contiene código oculto y se ha bloqueado")
    checks.append("content")

    if _antivirus(data) is not None:
        checks.append("antivirus")

    width, height, depth, color, compression, filtering, interlace = header
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        raise SpriteRejected(f"La imagen debe medir entre {MIN_SIDE} y {MAX_SIDE} píxeles por lado")
    if depth != 8 or color not in (2, 3, 6) or compression != 0 or filtering != 0 or interlace != 0:
        raise SpriteRejected("Formato de imagen no admitido; súbela como PNG, JPG, GIF o WebP")
    bpp = {2: 3, 3: 1, 6: 4}[color]
    expected = height * (1 + width * bpp)
    inflater = zlib.decompressobj()
    try:
        # Never more than the picture needs: a "compression bomb" stops here.
        raw = inflater.decompress(bytes(idat), expected + 1)
    except zlib.error as error:
        raise SpriteRejected("Los píxeles de la imagen están dañados") from error
    if len(raw) != expected or inflater.unconsumed_tail:
        raise SpriteRejected("Los píxeles de la imagen no cuadran con su tamaño")
    pixels = _unfilter(raw, width, height, bpp)

    if color == 6:
        rgba = bytes(pixels)
    elif color == 2:
        rgba = b"".join(bytes(pixels[i:i + 3]) + b"\xff" for i in range(0, len(pixels), 3))
    else:
        if palette is None or len(palette) % 3:
            raise SpriteRejected("La paleta de la imagen no es válida")
        colors = [palette[i:i + 3] + b"\xff" for i in range(0, len(palette), 3)]
        try:
            rgba = b"".join(colors[index] for index in pixels)
        except IndexError as error:
            raise SpriteRejected("La imagen usa colores fuera de su paleta") from error
    if not any(rgba[i] for i in range(3, len(rgba), 4)):
        raise SpriteRejected("La imagen está vacía (es toda transparente)")
    checks.append("pixels")

    clean = _write_png(rgba, width, height)
    checks.append("rebuilt")
    return CleanSprite(png=clean, width=width, height=height, checks=checks)
