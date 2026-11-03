"""Regenerate codepack/gui/codepack.ico (multi-size). Run: python packaging/make_icon.py"""

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = Path(__file__).resolve().parents[1] / "codepack" / "gui" / "codepack.ico"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    m = size * 0.06
    path = QPainterPath()
    path.addRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), size * 0.18, size * 0.18)
    p.fillPath(path, QColor("#2f6fdf"))
    font = QFont("Consolas")
    font.setBold(True)
    font.setPixelSize(int(size * 0.42))
    p.setFont(font)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "{ }" if size >= 24 else "{}")
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def main() -> None:
    _app = QGuiApplication([])  # fonts need an application instance
    frames = [(s, png_bytes(draw(s))) for s in SIZES]
    # ICO container: header, one directory entry per size, then PNG-encoded frames.
    offset = 6 + 16 * len(frames)
    entries, blobs = b"", b""
    for size, png in frames:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    OUT.write_bytes(struct.pack("<HHH", 0, 1, len(frames)) + entries + blobs)
    print(f"wrote {OUT} ({len(frames)} sizes)")


if __name__ == "__main__":
    main()
