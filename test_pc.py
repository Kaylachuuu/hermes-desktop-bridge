import base64
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pc_bridge_under_test', Path(__file__).with_name('pc.py'))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)


class PcTests(unittest.TestCase):
    def test_denial_preserved(self):
        result = json.loads(pc.render_result({'isError': True, 'content': [{'type': 'text', 'text': 'Denied'}]}))
        self.assertTrue(result['isError'])
        self.assertEqual(result['output'], 'Denied')

    def test_missing_response_not_success(self):
        for value in (None, {}, {'content': 'wrong'}):
            with self.assertRaises(ValueError):
                pc.render_result(value)

    def test_screenshot_cached_and_base64_not_sent_as_text(self):
        cache = types.ModuleType('gateway.platforms.base')
        captured = []
        cache.cache_image_from_bytes = lambda raw, ext: captured.append((raw, ext)) or '/cache/pc.png'
        with patch.dict(sys.modules, {'gateway.platforms.base': cache}), patch.object(pc, '_use_aux_vision', return_value=False):
            envelope = pc.render_result({'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(b'pngbytes').decode()}]})
        self.assertTrue(envelope['_multimodal'])
        self.assertEqual(envelope['content'][1]['image_url']['url'], 'data:image/png;base64,cG5nYnl0ZXM=')
        result = json.loads(envelope['text_summary'])
        self.assertEqual(captured, [(b'pngbytes', '.png')])
        self.assertEqual(result['output'], 'MEDIA:/cache/pc.png')

    def test_invalid_image_fails_closed(self):
        with self.assertRaises(ValueError):
            pc.render_result({'content': [{'type': 'image', 'mimeType': 'image/png', 'data': '!!!'}]})


class PcDispatchTests(unittest.TestCase):
    def setUp(self):
        self.registered = None
        self.tools = {}
        def register(name, toolset, schema, handler, **kwargs):
            self.tools[name] = (schema, handler)
            if name == 'desktop_pc':
                self.registered = handler
        self.bridge = types.SimpleNamespace(_session_key=lambda: 'owner-key', _owner=lambda key: 'owner-sid')
        pc.install(types.SimpleNamespace(register_tool=register), self.bridge)

    def test_missing_owner_never_dispatches(self):
        from tui_gateway import server_requests
        def refuse(key):
            raise RuntimeError('No unique Desktop owner')
        self.bridge._owner = refuse
        with patch.object(server_requests, 'send') as send:
            result = json.loads(self.registered({'action': 'click', 'arguments': {}}))
        self.assertTrue(result['isError'])
        self.assertFalse(result['retry'])
        send.assert_not_called()

    def test_managed_scope_cannot_be_overridden(self):
        from tui_gateway import server_requests
        with patch.object(server_requests, 'send') as send:
            result = json.loads(self.registered({'action': 'click', 'arguments': {'session': 'someone-else'}}))
        self.assertTrue(result['isError'])
        send.assert_not_called()

    def test_reply_routes_to_exact_owner_and_preserves_denial(self):
        from tui_gateway import server_requests
        reply = {'value': json.dumps({'isError': True, 'content': [{'type': 'text', 'text': 'Denied'}]})}
        with patch.object(server_requests, 'send', return_value=reply) as send:
            result = json.loads(self.registered({'action': 'click', 'arguments': {'pid': 42}}))
        send.assert_called_once_with('desktop.pc', 'owner-sid', {'action': 'click', 'arguments': {'pid': 42}}, timeout=180)
        self.assertTrue(result['isError'])

    def test_lost_response_not_retried(self):
        from tui_gateway import server_requests
        with patch.object(server_requests, 'send', return_value=None) as send:
            result = json.loads(self.registered({'action': 'click', 'arguments': {}}))
        self.assertFalse(result['retry'])
        send.assert_called_once()

    def test_browser_navigation_preserves_exact_target(self):
        from tui_gateway import server_requests
        args = {'target_id': 'owned-browser', 'tab_id': 'owned-tab', 'url': 'https://example.com'}
        reply = {'value': json.dumps({'content': [{'type': 'text', 'text': 'Navigated'}]})}
        with patch.object(server_requests, 'send', return_value=reply) as send:
            result = json.loads(self.registered({'action': 'browser_navigate', 'arguments': args}))
        send.assert_called_once_with('desktop.pc', 'owner-sid', {'action': 'browser_navigate', 'arguments': args}, timeout=180)
        self.assertFalse(result['isError'])

    def test_typed_browser_tool_wraps_flat_arguments(self):
        from tui_gateway import server_requests
        schema, handler = self.tools['desktop_browser_prepare']
        self.assertEqual(set(schema['parameters']['required']), {'allow_launch', 'profile'})
        args = {'allow_launch': True, 'profile': {'mode': 'isolated_new'}}
        reply = {'value': json.dumps({'content': [{'type': 'text', 'text': 'Prepared'}]})}
        with patch.object(server_requests, 'send', return_value=reply) as send:
            handler(args)
        send.assert_called_once_with('desktop.pc', 'owner-sid', {'action': 'browser_prepare', 'arguments': args}, timeout=180)

    def test_browser_tools_do_not_expose_session_override(self):
        for name, (schema, _) in self.tools.items():
            if name.startswith('desktop_browser_'):
                self.assertNotIn('session', schema['parameters']['properties'])

    def test_window_listing_needs_no_action_wrapper(self):
        from tui_gateway import server_requests
        schema, handler = self.tools['desktop_list_windows']
        self.assertNotIn('action', schema['parameters']['properties'])
        reply = {'value': json.dumps({'content': [{'type': 'text', 'text': 'Exact windows'}]})}
        with patch.object(server_requests, 'send', return_value=reply) as send:
            result = json.loads(handler({}))
        send.assert_called_once_with('desktop.pc', 'owner-sid', {'action': 'list_windows', 'arguments': {}}, timeout=180)
        self.assertEqual(result['output'], 'Exact windows')

    def test_browser_modes_are_explicit_and_account_arguments_preserved(self):
        from tui_gateway import server_requests
        schema, handler = self.tools['desktop_browser_prepare']
        parameters = schema['parameters']
        self.assertEqual(parameters['properties']['profile']['properties']['mode']['enum'], ['isolated_new', 'athena_profile', 'existing_profile'])
        self.assertEqual(len(parameters['oneOf']), 2)
        args = {'browser': 'edge', 'allow_launch': False, 'profile': {'mode': 'existing_profile'}, 'pid': 42, 'window_id': 84}
        reply = {'value': json.dumps({'content': [{'type': 'text', 'text': 'Prepared'}]})}
        with patch.object(server_requests, 'send', return_value=reply) as send:
            handler(args)
        send.assert_called_once_with('desktop.pc', 'owner-sid', {'action': 'browser_prepare', 'arguments': args}, timeout=180)

    def test_browser_product_selection_preserved_without_managed_scope(self):
        from tui_gateway import server_requests
        schema, handler = self.tools['desktop_browser_prepare']
        self.assertEqual(schema['parameters']['properties']['browser']['enum'], ['chrome', 'edge', 'firefox'])
        args = {'browser': 'firefox', 'allow_launch': True, 'profile': {'mode': 'isolated_new'}}
        reply = {'value': json.dumps({'content': [{'type': 'text', 'text': 'Prepared'}]})}
        with patch.object(server_requests, 'send', return_value=reply) as send:
            handler(args)
        send.assert_called_once_with('desktop.pc', 'owner-sid', {'action': 'browser_prepare', 'arguments': args}, timeout=180)
        self.assertNotIn('session', self.tools['desktop_browser_pointer'][0]['parameters'].get('required', []))


if __name__ == '__main__':
    unittest.main()
