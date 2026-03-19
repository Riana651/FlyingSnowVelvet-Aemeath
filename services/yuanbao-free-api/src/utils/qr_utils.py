import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import qrcode

logger = logging.getLogger(__name__)


def _load_image(image_path: str) -> Optional[np.ndarray]:
    image_file = Path(str(image_path or "")).expanduser()
    if not image_file.exists():
        logger.warning("QR image does not exist: %s", image_file)
        return None
    try:
        data = np.fromfile(str(image_file), dtype=np.uint8)
        if data.size == 0:
            logger.warning("QR image is empty: %s", image_file)
            return None
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.warning("Failed to read QR image: %s (%s)", image_file, exc)
        return None
    if img is None:
        logger.warning("Failed to read QR image: %s", image_file)
        return None
    return img


def _save_image(image_path: str, img: np.ndarray) -> bool:
    image_file = Path(str(image_path or "")).expanduser()
    image_file.parent.mkdir(parents=True, exist_ok=True)
    suffix = image_file.suffix.lower() or ".png"
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    try:
        ok, encoded = cv2.imencode(ext, img)
        if not ok:
            logger.warning("Failed to encode QR image for save: %s", image_file)
            return False
        encoded.tofile(str(image_file))
        return True
    except Exception as exc:
        logger.warning("Failed to save QR image: %s (%s)", image_file, exc)
        return False


def _crop_points_region(img: np.ndarray, points: np.ndarray, padding: int = 16) -> Optional[np.ndarray]:
    if img is None or points is None:
        return None
    pts = np.array(points, dtype=np.float32).reshape(-1, 2)
    if pts.size < 8:
        return None
    min_x = max(0, int(np.floor(np.min(pts[:, 0]))) - padding)
    min_y = max(0, int(np.floor(np.min(pts[:, 1]))) - padding)
    max_x = min(img.shape[1], int(np.ceil(np.max(pts[:, 0]))) + padding)
    max_y = min(img.shape[0], int(np.ceil(np.max(pts[:, 1]))) + padding)
    if max_x <= min_x or max_y <= min_y:
        return None
    cropped = img[min_y:max_y, min_x:max_x]
    if cropped.size == 0:
        return None
    return cropped


def extract_qr_region_from_image(image_path: str, output_path: str | None = None) -> bool:
    """Detect and crop the real QR region from a screenshot."""
    img = _load_image(image_path)
    if img is None:
        return False

    detector = cv2.QRCodeDetector()
    cropped: Optional[np.ndarray] = None

    try:
        ok, decoded_info, points, _ = detector.detectAndDecodeMulti(img)
    except Exception as exc:
        logger.warning("QR multi-detect failed: %s", exc)
        ok, decoded_info, points = False, (), None

    if ok and points is not None and len(points):
        best_idx = 0
        best_area = -1.0
        for idx, quad in enumerate(points):
            quad_np = np.array(quad, dtype=np.float32).reshape(-1, 2)
            area = float(cv2.contourArea(quad_np.astype(np.int32)))
            if area > best_area:
                best_area = area
                best_idx = idx
        cropped = _crop_points_region(img, points[best_idx])
        if cropped is not None and output_path:
            return _save_image(output_path, cropped)

    try:
        data, points, _ = detector.detectAndDecode(img)
    except Exception as exc:
        logger.warning("QR single-detect failed: %s", exc)
        data, points = "", None
    if points is not None:
        cropped = _crop_points_region(img, points)
        if cropped is not None and output_path:
            return _save_image(output_path, cropped)

    return False


def print_qr_to_terminal(image_path: str):
    """Print QR code content to terminal if decodable."""
    try:
        qr_content = decode_qr_from_image(image_path)
    except Exception as exc:
        logger.warning("Print terminal QR failed: %s", exc)
        qr_content = None

    print("\n" + "=" * 50)
    print("  Please scan the QR code below")
    print("=" * 50)
    print()

    if qr_content:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=2,
            border=2,
        )
        qr.add_data(qr_content)
        qr.make(fit=True)
        qr.print_ascii(invert=True)

        print()
        print("=" * 50)
        print(f"  QR content: {qr_content}")
        print("=" * 50 + "\n")
    else:
        logger.warning("QR decode failed, skip terminal print")


def decode_qr_from_image(image_path: str) -> Optional[str]:
    """Decode QR content from an image file."""
    img = _load_image(image_path)
    if img is None:
        return None

    detector = cv2.QRCodeDetector()
    try:
        ok, decoded_info, points, _ = detector.detectAndDecodeMulti(img)
        if ok and decoded_info:
            for item in decoded_info:
                if item:
                    return str(item)
    except Exception:
        pass

    try:
        data, _, _ = detector.detectAndDecode(img)
    except Exception as exc:
        logger.warning("QR decode failed: %s", exc)
        return None
    return data if data else None
