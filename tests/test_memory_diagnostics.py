import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from gtk_app.estante import Shelf


class MemoryDiagnosticsTests(TestCase):
    def test_explicit_diagnostics_compare_before_and_after_trim(self):
        for enabled in ('0', '1'):
            host = SimpleNamespace(memory_diagnostics=True, memory_report_count=0, focus_revision=1,
                get_renderer=lambda: SimpleNamespace(__gtype__=SimpleNamespace(name='TestRenderer')))
            with patch('gtk_app.estante.GLib.timeout_add') as timer, \
                 patch.dict('os.environ', {'ESTANTE_MEMORY_DIAGNOSTICS': enabled}), \
                 patch('gtk_app.estante.memory_usage', side_effect=[{'Rss': 244}, {'Rss': 220}]), \
                 patch('gtk_app.estante.reclaim_unused_memory', return_value={'collected': 2, 'native_trim': True}) as trim, \
                 patch('gtk_app.estante.os.open', side_effect=OSError('test does not write logs')), patch('builtins.print') as output:
                Shelf.schedule_memory_report(host)
                self.assertFalse(timer.call_args.args[1]())
                values = json.loads(output.call_args.args[0].removeprefix('Estante memoria: '))
                self.assertEqual(values['Rss'], 244)
                self.assertEqual(values['renderer'], 'TestRenderer')
                self.assertEqual(trim.call_count, int(enabled == '1'))
                if enabled == '1':
                    self.assertEqual(values['after_trim']['Rss'], 220)

    def test_stale_selection_does_not_collect_or_log(self):
        host = SimpleNamespace(memory_diagnostics=True, memory_report_count=0, focus_revision=1)
        with patch('gtk_app.estante.GLib.timeout_add') as timer, patch('gtk_app.estante.memory_usage') as measure:
            Shelf.schedule_memory_report(host)
            host.focus_revision = 2
            self.assertFalse(timer.call_args.args[1]())
            measure.assert_not_called()
