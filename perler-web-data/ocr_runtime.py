"""One inference at a time for the shared, mutable RapidOCR engine."""
from threading import Lock


class SerializedOCR:
    def __init__(self, engine):
        self.engine = engine
        self.lock = Lock()

    def __call__(self, image):
        if not self.lock.acquire(timeout=2):
            raise RuntimeError("OCR 正忙，请稍后重新点击识别。")
        try:
            return self.engine(image)
        finally:
            self.lock.release()
