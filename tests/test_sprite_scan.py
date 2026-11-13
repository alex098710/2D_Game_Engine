"""The security check of uploaded pictures (app/admin/sprite_scan.py) and its endpoints."""
import base64
import struct
import zlib

import pytest

from app.admin import sprite_scan
from app.admin.sprite_scan import AntivirusUnavailable, SpriteRejected, scan_sprite


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def png(width=16, height=16, color=6, rows=None, extra=b"", after=b"", filter_type=0, idat=None) -> bytes:
    bpp = {2: 3, 6: 4}[color]
    pixel = b"\xff\x00\x00\xff"[:bpp]
    rows = rows if rows is not None else [bytes([filter_type]) + pixel * width for _ in range(height)]
    header = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    data = idat if idat is not None else zlib.compress(b"".join(rows))
    return (sprite_scan.PNG_SIGNATURE + chunk(b"IHDR", header) + extra + chunk(b"IDAT", data)
            + chunk(b"IEND", b"") + after)


def test_a_clean_picture_passes_and_is_rebuilt():
    original = png(extra=chunk(b"pHYs", b"\x00" * 9))
    clean = scan_sprite(original)
    assert (clean.width, clean.height) == (16, 16)
    assert clean.checks == ["size", "type", "structure", "content", "pixels", "rebuilt"]
    assert clean.png != original  # a new file: the pHYs block (and anything else) is gone
    assert b"pHYs" not in clean.png
    assert scan_sprite(clean.png).png == clean.png  # the clean copy is itself valid


def test_rgb_pictures_and_every_row_filter_are_decoded():
    for filter_type in range(5):
        assert scan_sprite(png(color=2, filter_type=filter_type)).width == 16


@pytest.mark.parametrize("data, message", [
    (b"", "vacío"),
    (b"GIF89a" + b"\x00" * 40, "no es una imagen PNG"),
    (b"<svg onload=alert(1)>", "no es una imagen PNG"),
    (b"MZ" + b"\x00" * 100, "no es una imagen PNG"),
])
def test_files_that_are_not_png_are_refused(data, message):
    with pytest.raises(SpriteRejected, match=message):
        scan_sprite(data)


def test_too_big_files_are_refused():
    with pytest.raises(SpriteRejected, match="pesa demasiado"):
        scan_sprite(sprite_scan.PNG_SIGNATURE + b"\x00" * sprite_scan.MAX_UPLOAD_BYTES)


def test_data_hidden_after_the_picture_is_refused():
    with pytest.raises(SpriteRejected, match="después de la imagen"):
        scan_sprite(png(after=b"<?php system($_GET['c']); ?>"))


def test_text_and_metadata_blocks_are_refused():
    for kind in (b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"iCCP", b"evIL"):
        with pytest.raises(SpriteRejected, match="bloques ocultos"):
            scan_sprite(png(extra=chunk(kind, b"Comment\x00<script>alert(1)</script>")))


def test_hidden_code_in_an_allowed_block_is_refused():
    with pytest.raises(SpriteRejected, match="código oculto"):
        scan_sprite(png(extra=chunk(b"pHYs", b"<script>x</script>")))


def test_a_broken_checksum_is_refused():
    data = bytearray(png())
    data[-20] ^= 0xFF  # inside the IDAT block, so its CRC no longer matches
    with pytest.raises(SpriteRejected):
        scan_sprite(bytes(data))


def test_a_compression_bomb_stops_at_the_expected_size():
    bomb = zlib.compress(b"\x00" * 50_000_000, 9)  # tiny file, 50 MB of "pixels"
    with pytest.raises(SpriteRejected, match="no cuadran"):
        scan_sprite(png(idat=bomb))


@pytest.mark.parametrize("width, height", [(4, 16), (16, 4), (300, 16)])
def test_sizes_outside_the_limits_are_refused(width, height):
    with pytest.raises(SpriteRejected, match="entre 8 y 256"):
        scan_sprite(png(width=width, height=height))


def test_fully_transparent_pictures_are_refused():
    rows = [b"\x00" + b"\x00\x00\x00\x00" * 16 for _ in range(16)]
    with pytest.raises(SpriteRejected, match="vacía"):
        scan_sprite(png(rows=rows))


def test_interlaced_or_16_bit_pictures_are_refused():
    header = struct.pack(">IIBBBBB", 16, 16, 16, 6, 0, 0, 0)
    data = sprite_scan.PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00")) + chunk(b"IEND", b"")
    with pytest.raises(SpriteRejected, match="no admitido"):
        scan_sprite(data)


def test_the_antivirus_is_used_when_configured_and_never_skipped_if_it_fails(monkeypatch):
    monkeypatch.setenv("CLAMAV_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMAV_PORT", "1")  # nothing listens there
    with pytest.raises(AntivirusUnavailable):
        scan_sprite(png())


def test_the_antivirus_verdict_is_respected(monkeypatch):
    monkeypatch.setattr(sprite_scan, "_antivirus", lambda data: (_ for _ in ()).throw(SpriteRejected("El antivirus encontró una amenaza en el archivo")))
    with pytest.raises(SpriteRejected, match="antivirus"):
        scan_sprite(png())
    monkeypatch.setattr(sprite_scan, "_antivirus", lambda data: "limpio")
    assert "antivirus" in scan_sprite(png()).checks


# --- the endpoints ---------------------------------------------------------------------------------

class FakeSprites:
    """Just the sprite part of AdminRepository, in memory."""

    def __init__(self):
        self.rows = []

    def sprite_count(self, user_id):
        return sum(1 for row in self.rows if row["owner_id"] == user_id)

    def add_sprite(self, user_id, name, png_bytes, width, height, sha256):
        from datetime import datetime, timezone
        row = {"id": len(self.rows) + 1, "owner_id": user_id, "name": name, "png": png_bytes,
               "width": width, "height": height, "created_at": datetime.now(timezone.utc)}
        self.rows.append(row)
        return row

    def sprites(self, user_id):
        return [row for row in self.rows if row["owner_id"] == user_id]

    def owns_sprite(self, user_id, sprite_id):
        return any(row["id"] == sprite_id and row["owner_id"] == user_id for row in self.rows)

    def delete_sprite(self, user_id, sprite_id):
        before = len(self.rows)
        self.rows = [row for row in self.rows if not (row["id"] == sprite_id and row["owner_id"] == user_id)]
        return len(self.rows) < before


@pytest.fixture
def sprite_client():
    from fastapi.testclient import TestClient

    from app.admin.router import get_admin_repository
    from app.auth.dependencies import current_user
    from app.auth.user import User
    from app.main import app

    repo = FakeSprites()
    owner = {"id": 1}
    app.dependency_overrides[get_admin_repository] = lambda: repo
    app.dependency_overrides[current_user] = lambda: User(owner["id"], "ana", "ana@example.com", b"s", b"h")
    app.state.rate_limiter.reset()
    yield TestClient(app), repo, owner
    app.dependency_overrides.clear()


def upload(client, data: bytes, name="Mi heroe"):
    return client.post("/me/sprites", json={"name": name, "data": base64.b64encode(data).decode()})


def test_upload_keeps_only_the_clean_copy_for_its_owner(sprite_client):
    client, repo, owner = sprite_client
    original = png(extra=chunk(b"pHYs", b"\x00" * 9))
    answer = upload(client, original)
    assert answer.status_code == 201
    body = answer.json()
    assert body["data_url"].startswith("data:image/png;base64,")
    assert "rebuilt" in body["checks"]
    assert repo.rows[0]["png"] != original
    owner["id"] = 2  # another account sees nothing and cannot delete it
    assert client.get("/me/sprites").json() == []
    assert client.delete(f"/me/sprites/{body['id']}").status_code == 404


def test_upload_refuses_malicious_files_with_a_clear_message(sprite_client):
    client, repo, _ = sprite_client
    answer = upload(client, png(after=b"<script>alert(1)</script>"))
    assert answer.status_code == 422
    assert "después de la imagen" in answer.json()["detail"]
    bad = client.post("/me/sprites", json={"name": "x", "data": "@@@"})
    assert bad.status_code == 422
    assert repo.rows == []


def test_a_creation_can_only_use_its_owners_pictures(sprite_client):
    client, repo, owner = sprite_client
    sprite_id = upload(client, png()).json()["id"]
    owner["id"] = 2
    creation = {"category": "enemy", "base_kind": "enemy", "name": "Ogro", "tint": "#ffffff",
                "health": 3, "damage": 1, "speed": 70, "sprite_id": sprite_id}
    answer = client.post("/me/creations", json=creation)
    assert answer.status_code == 422
    assert "no es tuya" in answer.json()["detail"]
