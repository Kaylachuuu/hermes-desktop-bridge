import importlib.util
import json
from pathlib import Path
import types
from test_backend import BridgeIntegration, plugin
from test_routing import routing
from tui_gateway.transport import bind_transport, reset_transport

spec = importlib.util.spec_from_file_location('diagnostic_test', Path(__file__).with_name('diagnostic.py'))
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


class DirectDiagnostic(BridgeIntegration):
    def run_command(self, peer, default=True):
        commands = {}
        ctx = types.SimpleNamespace(register_tool=lambda **kw: None,
                                    register_middleware=lambda *args: None,
                                    get_config=lambda key, fallback: default,
                                    register_command=lambda name, handler, **kw: commands.update({name: handler}))
        control, route = routing.install(ctx, plugin)
        diagnostic.install(ctx, plugin, route, control)
        token = bind_transport(peer)
        try:
            return commands['desktop-bridge-test']('')
        finally:
            reset_transport(token)

    def tearDown(self):
        from tools.terminal_tool_lifecycle import cleanup_all_environments
        cleanup_all_environments()
        super().tearDown()

    def test_model_free_large_write_through_ordinary_tools(self):
        result = json.loads(self.run_command(self.peer))
        self.assertTrue(result['passed'], result)
        self.assertEqual(Path(result['path']).read_text(), 'Athena larger file bridge test — α\n' * 300)
        self.assertEqual(result['write']['bytes_written'], Path(result['path']).stat().st_size)

    def test_other_transport_cannot_start_diagnostic(self):
        before = len(self.frames)
        self.assertIn('Refused', self.run_command(object()))
        self.assertEqual(len(self.frames), before)

    def test_disabled_default_never_uses_server_tools(self):
        before = len(self.frames)
        self.assertIn('no server fallback', self.run_command(self.peer, default=False))
        self.assertEqual(len(self.frames), before)
