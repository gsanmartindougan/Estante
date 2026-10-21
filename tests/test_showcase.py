import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from tools.showcase import Recorder, encoder_command


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
