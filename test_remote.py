import importlib.util
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch

from tui_gateway import server_requests

spec = importlib.util.spec_from_file_location('desktop_remote_test', Path(__file__).with_name('remote.py'))
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)


class RemoteRouting(unittest.TestCase):
    def setUp(self):
        self.current = 'origin'
        self.frames, self.tools, self.commands = [], {}, {}
        self.peers = {name: object() for name in ('origin', 'target')}
        self.sessions = {name: {'session_key': name, 'auth_user_id': 'kayla', 'profile_home': None, 'peer': peer} for name, peer in self.peers.items()}
        server = types.SimpleNamespace(_sessions=self.sessions, _sessions_lock=threading.RLock(), _session_live_transports=lambda s: [s['peer']])
        self.modules = patch.dict(sys.modules, {'tui_gateway.server': server})
        self.modules.start()
        self.transport = patch.object(server_requests, 'send', side_effect=self.send)
        self.transport.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(self.transport.stop)
        remote.install(types.SimpleNamespace(register_tool=lambda name, toolset, schema, handler: self.tools.update({name: handler}),
                                             register_command=lambda name, handler, **kwargs: self.commands.update({name: handler})),
                       types.SimpleNamespace(_session_key=lambda: self.current, _owner=lambda key: key))
        self.tamper = False
        self.tools['desktop_devices']({'action': 'register', 'role': 'origin'})
        self.current = 'target'
        self.tools['desktop_devices']({'action': 'register', 'role': 'target'})
        self.current = 'origin'
        self.frames.clear()

    def send(self, method, sid, params, **kwargs):
        self.frames.append((sid, params))
        action = params['action']
        if action in ('describe', 'enroll_target'):
            value = {'id': 'device-' + sid, 'name': 'Scopuli' if sid == 'origin' else 'Athenaeum', 'platform': 'win32' if sid == 'origin' else 'linux', 'publicKey': 'test-key-' + sid}
            if action == 'enroll_target':
                self.assertEqual(params['arguments']['origins'][0]['name'], 'Scopuli')
                value.update(token='private-token', enrollment='a' * 64)
        elif action == 'approve':
            self.assertEqual(sid, 'origin')
            self.assertEqual(params['arguments']['targetName'], 'Athenaeum')
            command = dict(params['arguments']['command'])
            if self.tamper:
                command['command'] = 'different command'
            value = {'command': command, 'signature': 'native-signature'}
        elif action == 'execute':
            self.assertEqual(sid, 'target')
            self.assertEqual(params['arguments']['token'], 'private-token')
            value = {'success': True, 'returncode': 0, 'output': 'Athenaeum\n'}
        elif action == 'revoke':
            value = {'revoked': True, 'id': 'device-' + sid}
        else:
            raise AssertionError(action)
        return {'value': value}

    def execute(self):
        return json.loads(self.tools['desktop_remote_terminal']({'target_device': 'device-target', 'command': 'hostname'}))

    def test_approval_goes_to_origin_and_execution_to_destination(self):
        result = self.execute()
        self.assertEqual(result['result']['output'], 'Athenaeum\n')
        self.assertEqual([sid for sid, _ in self.frames], ['origin', 'target'])
        self.assertFalse(result['retry'])
        self.assertFalse(result['server_fallback'])

    def test_changed_approval_is_never_dispatched(self):
        self.tamper = True
        self.assertIn('did not match', self.execute()['error'])
        self.assertEqual([p['action'] for _, p in self.frames], ['approve'])

    def test_reconnected_target_requires_new_enrollment(self):
        self.sessions['target']['peer'] = object()
        self.assertIn('online enrolled destination', self.execute()['error'])
        self.assertEqual(self.frames, [])

    def test_other_account_destination_is_refused_before_approval(self):
        self.sessions['target']['auth_user_id'] = 'other-user'
        self.assertIn('online enrolled destination', self.execute()['error'])
        self.assertEqual(self.frames, [])

    def test_private_enrollment_token_is_not_returned_by_device_listing(self):
        listing = self.tools['desktop_devices']({'action': 'list'})
        self.assertNotIn('private-token', listing)

    def test_settings_commands_require_the_owning_transport(self):
        with patch('tui_gateway.transport.current_transport', return_value=object()):
            result = json.loads(self.commands['desktop-devices']('target'))
        self.assertIn('own the enrollment', result['error'])
        self.assertEqual(self.frames, [])

    def test_settings_list_and_revoke_share_registry_without_a_model_turn(self):
        with patch('tui_gateway.transport.current_transport', return_value=self.peers['origin']):
            listing = json.loads(self.commands['desktop-devices']('list'))
            self.assertEqual(len(listing['devices']), 2)
            self.assertNotIn('private-token', json.dumps(listing))
            self.assertIn('Use list', json.loads(self.commands['desktop-devices']('execute hostname'))['error'])
            self.assertTrue(json.loads(self.commands['desktop-devices']('revoke'))['revoked'])
            listing = json.loads(self.commands['desktop-devices']('list'))
            self.assertEqual([d['name'] for d in listing['devices']], ['Athenaeum'])
        self.assertEqual([p['action'] for _, p in self.frames], ['revoke'])

    def test_revoke_cleans_the_same_device_after_a_connection_generation_changes(self):
        self.sessions['origin']['peer'] = object()
        result = json.loads(self.tools['desktop_devices']({'action': 'revoke'}))
        self.assertTrue(result['revoked'])
        listing = json.loads(self.tools['desktop_devices']({'action': 'list'}))
        self.assertEqual([d['name'] for d in listing['devices']], ['Athenaeum'])


if __name__ == '__main__':
    unittest.main()
