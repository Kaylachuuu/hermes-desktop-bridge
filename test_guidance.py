import types
import unittest
from test_routing import routing
from test_backend import plugin


class DesktopGuidance(unittest.TestCase):
    def test_execution_refusal_keeps_desktop_reason(self):
        with self.assertRaisesRegex(ValueError, 'execution refusal: unavailable'):
            plugin._decode({'value': '{"error":"unavailable"}'})

    def capture(self, default):
        prompts = []
        ctx = types.SimpleNamespace(register_tool=lambda **kwargs: None,
                                    register_middleware=lambda *args: None,
                                    get_config=lambda key, fallback: default,
                                    register_system_prompt_section=lambda name, callback, **kwargs: prompts.append(callback))
        routing.install(ctx, types.SimpleNamespace())
        return prompts[0]

    def test_desktop_default_explains_ordinary_tools(self):
        prompt = self.capture(True)({'platform': 'desktop'})
        self.assertIn('enabled by default', prompt)
        self.assertIn('normal terminal, read_file', prompt)
        self.assertIn('DIFFERENT', prompt)
        self.assertIn('{"action":"list"}', prompt)

    def test_opt_in_requires_enable(self):
        prompt = self.capture(False)({'platform': 'desktop'})
        self.assertIn('First call desktop_terminal_session', prompt)

    def test_non_desktop_sessions_do_not_receive_local_routing_claim(self):
        callback = self.capture(True)
        for platform in ('cli', 'telegram', ''):
            self.assertEqual(callback({'platform': platform}), '')
