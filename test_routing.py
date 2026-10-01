import importlib.util
import json
import pathlib
import types

from test_backend import BridgeIntegration, plugin
from tools.terminal_scope import set_terminal_scope, reset_terminal_scope, get_terminal_scope

spec = importlib.util.spec_from_file_location('routing_test_module', pathlib.Path(__file__).with_name('routing.py'))
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


class OrdinaryToolRouting(BridgeIntegration):
    def setUp(self):
        super().setUp()
        self.middleware = None
        ctx = types.SimpleNamespace(register_tool=lambda **kwargs: None,
                                    register_middleware=lambda kind, callback: setattr(self, 'middleware', callback))
        self.enable, self.route = routing.install(ctx, plugin)
        self.policy = {'TERMINAL_ENV': 'local', 'TERMINAL_CWD': self.temp.name}
        self.scope_token = set_terminal_scope(self.policy)
        self.task = 'ordinary-routing-test'

    def tearDown(self):
        from tools.terminal_tool_lifecycle import cleanup_all_environments
        cleanup_all_environments()
        reset_terminal_scope(self.scope_token)
        super().tearDown()

    def call(self, name, args):
        from model_tools import handle_function_call
        return self.route(name, args,
            lambda final: handle_function_call(name, final, task_id=self.task, skip_tool_execution_middleware=True),
            task_id=self.task)

    def test_ordinary_files_first_then_terminal(self):
        self.assertTrue(json.loads(self.enable({'action': 'enable'}))['enabled'])
        target = str(pathlib.Path(self.temp.name) / 'ordinary.txt')
        content = 'Ordinary tools α\n'
        written = json.loads(self.call('write_file', {'path': target, 'content': content}))
        self.assertFalse(written.get('error'), written)
        self.assertEqual(pathlib.Path(target).read_text(), content)
        read = json.loads(self.call('read_file', {'path': target}))
        self.assertFalse(read.get('error'), read)
        self.assertIn('α', str(read))
        result = json.loads(self.call('terminal', {'command': 'printf ordinary-terminal', 'timeout': 5}))
        self.assertEqual(result.get('exit_code', result.get('returncode')), 0, result)
        self.assertIn('ordinary-terminal', result['output'])
        self.assertIs(get_terminal_scope(), self.policy)

    def test_opted_in_disconnect_refuses_without_downstream(self):
        self.enable({'action': 'enable'})
        self.peers = []
        calls = []
        result = json.loads(self.route('terminal', {}, lambda args: calls.append(args), task_id=self.task))
        self.assertIn('error', result)
        self.assertFalse(calls)
        self.assertIs(get_terminal_scope(), self.policy)

    def test_unselected_tools_keep_policy(self):
        observed = []
        self.route('terminal', {}, lambda args: observed.append(get_terminal_scope()))
        self.enable({'action': 'enable'})
        self.route('web_search', {}, lambda args: observed.append(get_terminal_scope()))
        self.assertEqual(observed, [self.policy, self.policy])

    def test_disable_blocks_and_reenable_restores_routing(self):
        self.enable({'action': 'enable'})
        self.assertTrue(json.loads(self.enable({'action': 'status'}))['enabled'])
        self.assertTrue(json.loads(self.enable({'action': 'disable'}))['blocked'])
        calls = []
        refused = json.loads(self.route('read_file', {}, lambda args: calls.append(args)))
        self.assertIn('error', refused)
        self.assertFalse(calls)
        self.assertTrue(json.loads(self.enable({'action': 'enable'}))['enabled'])

    def test_changed_owner_refuses_and_policy_is_restored(self):
        self.enable({'action': 'enable'})
        self.server._sessions = {'replacement': {'session_key': self.key}}
        calls = []
        refused = json.loads(self.route('terminal', {}, lambda args: calls.append(args)))
        self.assertIn('error', refused)
        self.assertFalse(calls)
        self.assertIs(get_terminal_scope(), self.policy)

    def auto_route(self):
        ctx = types.SimpleNamespace(register_tool=lambda **kwargs: None,
                                    register_middleware=lambda *args: None,
                                    get_config=lambda key, default: True)
        return routing.install(ctx, plugin)

    def test_desktop_default_and_explicit_opt_out(self):
        control, route = self.auto_route()
        self.assertTrue(json.loads(control({'action': 'status'}))['enabled'])
        seen = []
        route('terminal', {}, lambda args: seen.append(get_terminal_scope()['TERMINAL_ENV']), task_id=self.task)
        self.assertEqual(seen, ['hermes-desktop-terminal'])
        control({'action': 'disable'})
        seen.clear()
        result = json.loads(route('terminal', {}, lambda args: seen.append(args)))
        self.assertIn('error', result)
        self.assertFalse(seen)
        self.assertIs(get_terminal_scope(), self.policy)

    def test_desktop_default_disconnect_never_falls_back(self):
        _, route = self.auto_route()
        self.peers = []
        seen = []
        result = json.loads(route('read_file', {}, lambda args: seen.append(args)))
        self.assertIn('error', result)
        self.assertFalse(seen)

    def test_desktop_default_does_not_route_messaging(self):
        from gateway.session_context import set_session_vars, clear_session_vars
        _, route = self.auto_route()
        tokens = set_session_vars(source='telegram', session_key='messaging-test')
        try:
            seen = []
            route('terminal', {}, lambda args: seen.append(get_terminal_scope()))
            self.assertEqual(seen, [self.policy])
        finally:
            clear_session_vars(tokens)
