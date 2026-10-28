from unittest import TestCase
from unittest.mock import Mock, call, patch
from native_memory import configure_native_allocator


class NativeAllocatorTests(TestCase):
    def test_large_buffer_thresholds_are_fixed_at_startup(self):
        library = Mock()
        library.mallopt.return_value = 1
        with patch.dict('os.environ', {}, clear=True), patch('native_memory.ctypes.CDLL', return_value=library):
            self.assertTrue(configure_native_allocator())
        self.assertEqual(library.mallopt.call_args_list, [call(-3, 131072), call(-1, 131072)])

    def test_caller_settings_and_comparison_opt_out_are_preserved(self):
        for environment in ({'ESTANTE_NATIVE_ALLOCATOR': '0'}, {'MALLOC_MMAP_THRESHOLD_': '999'},
                            {'MALLOC_TRIM_THRESHOLD_': '999'}, {'GLIBC_TUNABLES': 'glibc.malloc.mmap_threshold=999'}):
            with self.subTest(environment=environment), patch.dict('os.environ', environment, clear=True), \
                 patch('native_memory.ctypes.CDLL') as load:
                self.assertFalse(configure_native_allocator())
                load.assert_not_called()

    def test_missing_or_rejected_native_api_does_not_prevent_startup(self):
        for library in (object(), Mock(mallopt=Mock(return_value=0))):
            with patch.dict('os.environ', {}, clear=True), patch('native_memory.ctypes.CDLL', return_value=library):
                self.assertFalse(configure_native_allocator())
        with patch.dict('os.environ', {}, clear=True), patch('native_memory.ctypes.CDLL', side_effect=OSError()):
            self.assertFalse(configure_native_allocator())
