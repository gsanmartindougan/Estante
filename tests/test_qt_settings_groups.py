"""GTK card grouping retains every editable setting exactly once."""
import unittest
from qt_app.settings_schema import groups, specs

class SettingsGroupsTests(unittest.TestCase):
    def test_every_setting_has_one_card_in_its_page(self):
        for mode in ['global','scan','list','grid','carousel','ps5']:
            with self.subTest(mode=mode):
                cards=groups({},mode)
                keys=[tuple(row['path']) for card in cards for row in card['rows']]
                expected=[tuple(row['path']) for row in specs({}) if row['groupId']==('general' if mode=='global' else mode)]
                self.assertCountEqual(keys,expected)
                self.assertEqual(len(keys),len(set(keys)))
                self.assertTrue(all(card['column'] in (0,1) for card in cards))

    def test_grouping_preserves_selected_radio_and_unrecognized_settings(self):
        state={'language':'es','controller_type':'nintendo','plugin_setting':{'preserved':True}}
        before=repr(state)
        rows=[row for card in groups(state) for row in card['rows']]
        self.assertEqual(next(row for row in rows if row['path']==['language'])['value'],'es')
        self.assertEqual(next(row for row in rows if row['path']==['controller_type'])['values'],['sony','xbox','nintendo'])
        self.assertEqual(repr(state),before)

    def test_screensaver_background_uses_visual_options_and_preserves_custom_paths(self):
        from qt_app.settings_schema import merge_values
        cards=groups({})
        timing=next(card for card in cards if ['screensaver_enabled'] in [row['path'] for row in card['rows']])
        backgrounds=next(card for card in cards if ['screensaver_background'] in [row['path'] for row in card['rows']])
        self.assertTrue(timing['compact'] and backgrounds['compact'])
        self.assertIs(timing,backgrounds)
        self.assertFalse(any(row['path'][0].startswith(('steamgriddb','igdb')) for card in cards for row in card['rows']))
        choice=next(row for row in backgrounds['rows'] if row['path']==['screensaver_background'])
        self.assertEqual(choice['type'],'background')
        self.assertEqual(len(choice['values']),6)
        self.assertIn('bundled:1.png',choice['values'])
        for value in ('bundled:2.png','/home/example/custom image.png'):
            result=merge_values({'unrelated':'retained'},[{'path':['screensaver_background'],'value':value}])
            self.assertEqual(result,{'unrelated':'retained','screensaver_background':value})

    def test_steam_startup_is_optional_in_startup_card(self):
        from qt_app.settings_schema import merge_values
        card = next(card for card in groups({}) if any(row['path'] == ['start_fullscreen'] for row in card['rows']))
        row = next(row for row in card['rows'] if row['path'] == ['start_steam_on_start'])
        self.assertEqual(row['type'], 'bool')
        self.assertFalse(row['value'])
        for enabled in (True, False):
            saved = merge_values({'unrelated': 42}, [{'path': row['path'], 'value': enabled}])
            self.assertEqual(saved['start_steam_on_start'], enabled)
            self.assertEqual(saved['unrelated'], 42)
            persisted = next(row for row in specs(saved) if row['path'] == ['start_steam_on_start'])
            self.assertEqual(persisted['value'], enabled)

    def test_grid_page_size_defaults_to_ten_and_is_saved_in_grid_settings(self):
        from qt_app.settings_schema import merge_values
        card=next(card for card in groups({},'grid') if any(row['path']==['grid_page_size'] for row in card['rows']))
        row=next(row for row in card['rows'] if row['path']==['grid_page_size'])
        self.assertEqual(row['value'],10)
        self.assertEqual(row['type'],'number')
        saved=merge_values({'unrelated':42},[{'path':['grid_page_size'],'value':7}])
        self.assertEqual(saved,{'unrelated':42,'grid_page_size':7})
        for invalid in (0,101,float('inf')):
            with self.assertRaises(ValueError):merge_values({},[{'path':['grid_page_size'],'value':invalid}])
