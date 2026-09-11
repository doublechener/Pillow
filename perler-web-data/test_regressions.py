import io
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import time

import numpy as np
from PIL import Image
from streamlit.testing.v1 import AppTest

from image_safety import load_image, nearest_colors, validate_pattern
from ocr_runtime import SerializedOCR
import supabase_client


class RegressionTests(unittest.TestCase):
    def test_matching_equivalence(self):
        rng = np.random.default_rng(5)
        pixels = rng.integers(0, 256, (120, 120, 3), dtype=np.int32)
        palette = rng.integers(0, 256, (221, 3), dtype=np.int32)
        diff = pixels.reshape(-1, 3)[:, None, :] - palette[None, :, :]
        expected = ((diff * diff).astype(np.float32) @ np.array([.3, .59, .11], dtype=np.float32)).argmin(axis=1)
        np.testing.assert_array_equal(nearest_colors(pixels, palette), expected)

    def test_invalid_images_and_pattern_limits(self):
        with self.assertRaises(ValueError):
            load_image(b'not an image')
        with self.assertRaises(ValueError):
            load_image(b'x' * (20 * 1024 * 1024 + 1))
        for dimensions in [(120, 3000, 22), (120, 120, 60), (120, 0, 22)]:
            with self.assertRaises(ValueError):
                validate_pattern(*dimensions, {'H1': (255, 255, 255)})
        with self.assertRaises(ValueError):
            validate_pattern(29, 29, 22, {})

    def test_image_orientation_alpha_and_resize(self):
        image = Image.new('RGBA', (4000, 1000), (0, 0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        result = load_image(buffer.getvalue())
        self.assertEqual(result.size, (3200, 800))
        self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))
        exif = Image.Exif()
        exif[274] = 6
        buffer = io.BytesIO()
        Image.new('RGB', (80, 40)).save(buffer, format='JPEG', exif=exif)
        self.assertEqual(load_image(buffer.getvalue()).size, (40, 80))

    def test_clients_are_session_local(self):
        state = {}
        fake_st = SimpleNamespace(session_state=state, secrets={'supabase': {'url': 'url', 'anon_key': 'key'}})
        with patch.object(supabase_client, 'st', fake_st), patch.object(supabase_client, 'create_client', side_effect=lambda *a, **k: object()):
            first = supabase_client._base_client()
            self.assertIs(first, supabase_client._base_client())
            fake_st.session_state = {}
            self.assertIsNot(first, supabase_client._base_client())

    def test_ocr_serializes_and_releases_after_error(self):
        active = []
        def infer(value):
            active.append(value)
            self.assertEqual(len(active), 1)
            time.sleep(.02)
            active.pop()
            return value
        engine = SerializedOCR(infer)
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(list(pool.map(engine, range(3))), [0, 1, 2])
        engine.engine = lambda value: 1 / 0
        with self.assertRaises(ZeroDivisionError):
            engine(1)
        self.assertTrue(engine.lock.acquire(blocking=False))
        engine.lock.release()

    def test_authenticated_page_reruns(self):
        # No live account or database writes in local regression tests.
        with patch('auth.require_login', return_value={'email': 'test@example.com', 'user_id': 'test'}), patch('db.ensure_inventory_seeded') as seed:
            app = AppTest.from_file(str(Path(__file__).with_name('app.py'))).run()
            self.assertFalse(app.exception)
            app.radio(key='nav_page').set_value('🔍 识别已有拼豆图').run()
            self.assertFalse(app.exception)
            app.radio(key='rec_mode').set_value('🎨 整图逐格识别色块').run()
            self.assertFalse(app.exception)
            self.assertEqual(seed.call_count, 1)

    def test_legacy_viewer_module_with_floating_window(self):
        # Emulate a warm deployment retaining the original viewer API.
        from unittest.mock import Mock
        viewer = Mock()
        legacy = SimpleNamespace(render_quick_check=viewer)
        upload = io.BytesIO()
        Image.new('RGB', (80, 40), 'white').save(upload, format='PNG')
        upload.name = 'fixture.png'
        with patch.dict(sys.modules, {'image_viewer': legacy}), patch('auth.require_login', return_value={'email': 'test@example.com', 'user_id': 'test'}), patch('db.ensure_inventory_seeded'), patch('streamlit.file_uploader', return_value=upload):
            app = AppTest.from_file(str(Path(__file__).with_name('app.py')))
            app.session_state['nav_page'] = '🔍 识别已有拼豆图'
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(viewer.call_count, 1)
            app.button(key='quick_check_close').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(viewer.call_count, 1)
            app.button(key='quick_check_open').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(viewer.call_count, 2)


if __name__ == '__main__':
    unittest.main()
