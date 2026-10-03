"""Signed reconnects exercise the real provider and stock shell file operations."""
import base64
import hashlib
import importlib.util
import json
import pathlib
import types
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_backend import BridgeIntegration, plugin
from tui_gateway import server_requests
from tui_gateway.ws import WSTransport
from tools.file_operations import ShellFileOperations
from tools.terminal_tool_backends import _create_environment

spec = importlib.util.spec_from_file_location('reconnect_test', pathlib.Path(__file__).with_name('reconnect.py'))
reconnect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconnect)


class State:
    def __init__(self):
        self.data = {}
    def get(self, key, default=None):
        return self.data.get(key, default)
    def set(self, key, value):
        self.data[key] = value


class SignedReconnect(BridgeIntegration):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.gateway = 'a' * 64
        self.approve = True
        self.prompts = 0
        self.tamper = False
        self.change_during_proof = False
        super().setUp()
        from hermes_constants import set_hermes_home_override
        from hermes_cli.plugins_state import PluginState
        self.home_token = set_hermes_home_override(pathlib.Path(self.temp.name) / 'profile-a')
        self.server._sessions[self.sid]['profile_home'] = str(pathlib.Path(self.temp.name) / 'profile-a')
        self.state = PluginState('hermes-desktop-bridge')
        self.load()
        self.env.cleanup()
        self.env = _create_environment('hermes-desktop-bridge', None, '/workspace', 10)

    def load(self):
        from agent import terminal_env_registry
        from hermes_constants import get_hermes_home
        scope = str(get_hermes_home())
        if not hasattr(self, 'registry_scope'):
            self.registry_scope = scope
            self.previous_provider = terminal_env_registry.snapshot_registration('hermes-desktop-bridge', scope=scope)
        def register(provider):
            self.current_provider = provider
            terminal_env_registry.register_provider(provider, scope=scope)
        plugin.register(types.SimpleNamespace(state=self.state,
            register_terminal_environment_provider=register,
            register_middleware=lambda kind, fn: setattr(self, 'route', fn),
            register_tool=lambda *a, **kw: setattr(self, 'control', kw['handler']) if kw.get('name') == 'desktop_terminal_session' else None,
            register_command=lambda *a, **kw: None, get_config=lambda key, default: True))

    def tearDown(self):
        from agent import terminal_env_registry
        terminal_env_registry.restore_registration('hermes-desktop-bridge', self.current_provider,
                                                   self.previous_provider, scope=self.registry_scope)
        from hermes_constants import reset_hermes_home_override
        reset_hermes_home_override(self.home_token)
        super().tearDown()

    def dispatch(self, frame):
        if frame['method'] != 'desktop.remote':
            return super().dispatch(frame)
        self.frames.append(frame)
        args = frame['params']['arguments']
        public = self.private.public_key()
        pem = public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        value = {'id': 'device-' + hashlib.sha256(der).hexdigest(), 'publicKey': pem,
                 'name': 'fixture-desktop', 'gatewayScope': self.gateway, 'routingIdentityVersion': 1}
        if frame['params']['action'] == 'routing_identity':
            authorize = args['authorize']
            if authorize:
                self.prompts += 1
            if authorize and not self.approve:
                value = {'error': 'User refused'}
            else:
                fields = ['hermes-desktop-route-v1', args['challenge'], args['conversation'],
                          self.gateway, value['id'], value['name'], authorize]
                value['authorized'] = authorize
                value['signature'] = base64.b64encode(self.private.sign(
                    json.dumps(fields, ensure_ascii=False, separators=(',', ':')).encode())).decode()
                if self.tamper:
                    value['authorized'] = not authorize
        server_requests.resolve_response({'jsonrpc': '2.0', 'id': frame['id'], 'result': {'value': value}}, self.peer)
        if self.change_during_proof:
            self.peers = []

    def restart(self, same_sid=False):
        server_requests.forget(self.peer)
        self.peer = object.__new__(WSTransport)
        self.peers = [self.peer]
        server_requests.advertise(self.peer, True)
        if not same_sid:
            self.sid += '-restarted'
            self.server._sessions = {self.sid: {'session_key': self.key, 'profile_home': self.registry_scope}}

    def test_restart_rebinds_cached_file_environment_without_prompt(self):
        ops = ShellFileOperations(self.env)
        path = str(pathlib.Path(self.temp.name) / 'restart.txt')
        self.restart()
        result = ops.write_file(path, 'reconnected α')
        self.assertIsNone(result.error, result)
        self.assertEqual(pathlib.Path(path).read_text(), 'reconnected α')
        self.assertEqual(self.prompts, 0)
        self.assertEqual(self.env.sid, self.sid)

    def test_same_runtime_new_transport_still_checks_identity(self):
        self.restart(same_sid=True)
        self.private = Ed25519PrivateKey.generate()
        self.approve = False
        self.assertEqual(self.env.execute('touch forbidden')['returncode'], -1)
        self.assertFalse(pathlib.Path(self.temp.name, 'forbidden').exists())
        self.assertEqual(self.prompts, 1)
        self.env.execute('touch forbidden')
        self.assertEqual(self.prompts, 1)  # no approval spam from a model loop

    def test_new_device_approval_never_reuses_old_cwd_or_replays(self):
        self.restart()
        self.private = Ed25519PrivateKey.generate()
        result = self.env.execute('touch should-not-replay')
        self.assertEqual(result['returncode'], -1)
        self.assertEqual(self.prompts, 1)
        self.assertFalse(pathlib.Path(self.temp.name, 'should-not-replay').exists())
        fresh = _create_environment('hermes-desktop-bridge', None, '/workspace', 10)
        self.assertEqual(fresh.execute('printf new-device')['output'], 'new-device')
        self.assertEqual(self.prompts, 1)

    def test_reload_restores_pin_and_disabled_state(self):
        self.load()
        restored = _create_environment('hermes-desktop-bridge', None, '/workspace', 10)
        self.assertEqual(restored.execute('printf restored')['output'], 'restored')
        self.control({'action': 'disable'})
        self.load()
        self.assertEqual(restored.execute('touch disabled')['returncode'], -1)
        self.assertFalse(pathlib.Path(self.temp.name, 'disabled').exists())

    def test_forged_proof_and_ownership_race_refuse_execution(self):
        self.restart()
        self.tamper = True
        self.assertEqual(self.env.execute('touch forged')['returncode'], -1)
        self.assertFalse(pathlib.Path(self.temp.name, 'forged').exists())
        self.tamper = False
        self.change_during_proof = True
        self.assertEqual(self.env.execute('touch race')['returncode'], -1)
        self.assertFalse(pathlib.Path(self.temp.name, 'race').exists())

    def test_real_state_isolated_between_profiles_a_b_a(self):
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        bindings = self.current_provider.bindings
        self.assertTrue(self.state.path.exists())
        token = set_hermes_home_override(pathlib.Path(self.temp.name) / 'profile-b')
        try:
            self.server._sessions[self.sid]['profile_home'] = str(pathlib.Path(self.temp.name) / 'profile-b')
            self.assertFalse(self.state.path.exists())
            bindings.resolve(self.key)
            bindings.disable(self.key, True)
            self.assertTrue(bindings.disabled(self.key))
        finally:
            reset_hermes_home_override(token)
            self.server._sessions[self.sid]['profile_home'] = self.registry_scope
        self.assertFalse(bindings.disabled(self.key))
        self.assertEqual(self.env.execute('printf profile-a')['output'], 'profile-a')

    def test_approved_handoff_routes_stock_file_tools_with_new_environment(self):
        from model_tools import handle_function_call
        from tools.terminal_scope import set_terminal_scope, reset_terminal_scope
        from tools.terminal_tool_lifecycle import cleanup_vm
        task = 'signed-handoff-tools'
        token = set_terminal_scope({'TERMINAL_ENV': 'local', 'TERMINAL_CWD': self.temp.name})
        def call(name, args):
            return json.loads(self.route(name, args,
                lambda final: handle_function_call(name, final, task_id=task, skip_tool_execution_middleware=True), task_id=task))
        try:
            path = str(pathlib.Path(self.temp.name) / 'handoff.txt')
            self.assertFalse(call('write_file', {'path': path, 'content': 'first α\n'}).get('error'))
            self.restart()
            self.private = Ed25519PrivateKey.generate()
            self.assertIn('first α', str(call('read_file', {'path': path})))
            path = str(pathlib.Path(self.temp.name) / 'handoff-new-device.txt')
            result = call('write_file', {'path': path, 'content': 'approved second α\n'})
            self.assertFalse(result.get('error'), result)
            self.assertEqual(pathlib.Path(path).read_text(), 'approved second α\n')
            self.assertEqual(self.prompts, 1)
            self.assertIn('approved second', str(call('read_file', {'path': path})))
            self.assertEqual(self.prompts, 1)
        finally:
            cleanup_vm(task)
            reset_terminal_scope(token)
