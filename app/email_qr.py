from __future__ import annotations

import base64
import io

import qrcode
from qrcode.image.pil import PilImage


def make_qr_png(url: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img: PilImage = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_data_uri(url: str) -> str:
    return "data:image/png;base64," + base64.b64encode(make_qr_png(url)).decode()
