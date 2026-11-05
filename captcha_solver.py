import io
import logging
from PIL import Image, ImageOps, ImageEnhance
from typing import Optional, Tuple

logger = logging.getLogger("CaptchaSolver")

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    logger.warning("OpenCV not installed, falling back to PIL image processing.")

class FastCaptchaSolver:
    """
    موتور فوق‌سریع پردازش و آماده‌سازی کد امنیتی (CAPTCHA)
    با پشتیبانی دوگانه از OpenCV و PIL جهت سازگاری ۱۰۰٪ با لینوکس و رندر
    """

    @staticmethod
    def preprocess_image(image_bytes: bytes):
        if HAS_CV2:
            try:
                nparr = np.frombuffer(image_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is not None:
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                    contrast = clahe.apply(gray)
                    denoised = cv2.bilateralFilter(contrast, 9, 75, 75)
                    _, thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                    return cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
            except Exception as e:
                logger.error(f"OpenCV processing error: {e}")

        # پردازش با PIL
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
        img = ImageOps.autocontrast(img)
        enhancer = ImageEnhance.Sharpness(img)
        return enhancer.enhance(2.0)

    @classmethod
    def solve_simple_digits(cls, image_bytes: bytes) -> Optional[str]:
        try:
            _ = cls.preprocess_image(image_bytes)
            return None
        except Exception:
            return None

    @classmethod
    def get_clean_png_bytes(cls, image_bytes: bytes) -> bytes:
        try:
            img = Image.open(io.BytesIO(image_bytes))
            img = img.resize((img.width * 2, img.height * 2), Image.Resampling.NEAREST)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return image_bytes
