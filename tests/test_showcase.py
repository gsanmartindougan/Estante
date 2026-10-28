import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from tools.showcase import Recorder, encoder_command, recording_settings, rgba_pixels


class ShowcaseTests(TestCase):
    def test_encoder_records_only_explicit_pixel_stream_and_never_overwrites(self):
        command = encoder_command(Path('/tmp/demo.mp4'), 1920, 1080, 30)
        self.assertIn('-n', command)
        self.assertEqual(command[command.index('-i')+1], 'pipe:0')
        self.assertIn('-an', command)
        self.assertNotIn('x11grab', command)

    @skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_real_video_encoding_finishes_with_expected_frames(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'test.mp4'
            recorder = Recorder(path, 64, 64, 24, .25)
            recorder.submit(0, bytes([255, 0, 0, 255]) * 64 * 64)
            recorder.submit(.12, bytes([0, 255, 0, 255]) * 64 * 64)
            recorder.finish()
            self.assertTrue(path.is_file())
            result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                'stream=width,height,nb_frames', '-of', 'json', str(path)], capture_output=True, text=True, check=True)
            stream = json.loads(result.stdout)['streams'][0]
            self.assertEqual((stream['width'], stream['height'], int(stream['nb_frames'])), (64, 64, 6))
            self.assertFalse(recorder.thread.is_alive())

    def test_recording_profile_preserves_input_and_disables_external_actions(self):
        source={'steamgriddb_key':'secret','igdb_client_id':'id','igdb_client_secret':'secret',
                'start_steam_on_start':True,'start_faugus_on_start':True,'start_heroic_on_start':True,
                'close_steam_on_exit':True,'close_faugus_on_exit':True,'close_heroic_on_exit':True,
                'controller_type':'nintendo','cover_formats':{'grid':'portrait'}}
        before=json.dumps(source,sort_keys=True)
        result=recording_settings(source)
        self.assertEqual(json.dumps(source,sort_keys=True),before)
        self.assertFalse(any(key in result for key in ('steamgriddb_key','igdb_client_id','igdb_client_secret')))
        for client in ('steam','faugus','heroic'):
            self.assertFalse(result['start_'+client+'_on_start'])
            self.assertFalse(result['close_'+client+'_on_exit'])
        self.assertEqual(result['controller_type'],'nintendo')
        self.assertEqual(result['cover_formats'],source['cover_formats'])
        self.assertEqual(result['onscreen_keyboard'],'disabled')

    def test_qt_pixel_capture_conversion_and_resize(self):
        try:
            from PySide6.QtGui import QImage,QColor
        except ImportError:
            self.skipTest('PySide6 required')
        image=QImage(3,2,QImage.Format_RGB888)
        image.fill(QColor(20,40,60))
        self.assertEqual(rgba_pixels(image,3,2),bytes([20,40,60,255])*6)
        self.assertEqual(len(rgba_pixels(image,8,6)),8*6*4)
        with self.assertRaises(RuntimeError):rgba_pixels(QImage(),8,6)
