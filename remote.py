"""Explicitly enrolled, origin-approved commands between live Desktop clients."""
import json
import sys
import threading
import time
import uuid


def install(ctx, provider):
    from tui_gateway.contracts.registry import SERVER_REQUESTS, server_request
    from tui_gateway.contracts.server_requests import ServerRequestParams, ValueResult
    if 'desktop.remote' not in SERVER_REQUESTS:
        class RemoteParams(ServerRequestParams):
            action: str
            arguments: dict = {}
        server_request('desktop.remote', params=RemoteParams, result=ValueResult,
                       doc='Enroll a device, request origin approval, or consume a signed remote command.')
    devices, lock = {}, threading.RLock()

    def context(key=None):
        key = key or provider._session_key()
        sid = provider._owner(key)
        server = sys.modules['tui_gateway.server']
        with server._sessions_lock:
            session = server._sessions[sid]
            peer = server._session_live_transports(session)[0]
            group = (session.get('auth_user_id'), session.get('profile_home'))
        return key, sid, peer, group

    def send(sid, action, arguments, timeout=110):
        from tui_gateway import server_requests
        result = server_requests.send('desktop.remote', sid, {'action': action, 'arguments': arguments}, timeout=timeout)
        if not isinstance(result, dict):
            raise RuntimeError('Desktop did not answer; outcome is unknown. Do not replay.')
        value = result.get('value', result)
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict) or value.get('error'):
            raise RuntimeError(value.get('error', 'Desktop returned an invalid result') if isinstance(value, dict) else 'Desktop returned an invalid result')
        return value

    def live(record):
        try:
            _, sid, peer, group = context(record['key'])
            return sid == record['sid'] and peer is record['peer'] and group == record['group']
        except Exception:
            return False

    def public(record):
        return {**record['descriptor'], 'role': record['role'], 'online': live(record)}

    def registry(args, **kwargs):
        try:
            key, sid, peer, group = context()
            action = args['action']
            if action == 'list':
                with lock:
                    return json.dumps({'devices': [public(r) for r in devices.values() if r['group'] == group]})
            if action == 'revoke':
                revoked = send(sid, 'revoke', {})
                with lock:
                    for device in [d for d, r in devices.items() if r['group'] == group and
                                   (r['peer'] is peer or r['descriptor']['id'] == revoked.get('id'))]:
                        del devices[device]
                return json.dumps({'revoked': True})
            role = args.get('role', 'origin')
            if action != 'register' or role not in ('origin', 'target'):
                raise ValueError('Use register, list, or revoke, and origin or target role.')
            with lock:
                origins = [r['descriptor'] for r in devices.values() if r['role'] == 'origin' and r['group'] == group and live(r)]
            # Changing to an approving role must not retain old receiving credentials.
            if role == 'origin':
                send(sid, 'revoke', {})
            result = send(sid, 'enroll_target' if role == 'target' else 'describe', {'origins': origins})
            descriptor = {field: result[field] for field in ('id', 'name', 'platform', 'publicKey')}
            record = dict(descriptor=descriptor, role=role, key=key, sid=sid, peer=peer, group=group,
                          token=result.get('token'), enrollment=result.get('enrollment'))
            if role == 'target' and (not record['token'] or not record['enrollment']):
                raise RuntimeError('Target enrollment was not confirmed.')
            with lock:
                old = devices.get(descriptor['id'])
                if old and old['group'] != group:
                    raise RuntimeError('Device already belongs to another profile or account.')
                devices[descriptor['id']] = record
            return json.dumps(public(record))
        except Exception as exc:
            return json.dumps({'error': str(exc), 'retry': False})

    def execute(args, **kwargs):
        try:
            key, sid, peer, group = context()
            with lock:
                origins = [r for r in devices.values() if r['peer'] is peer and r['group'] == group and r['role'] == 'origin' and live(r)]
                target = devices.get(args['target_device'])
            if len(origins) != 1 or not target or target['group'] != group or target['role'] != 'target' or not live(target):
                raise RuntimeError('An enrolled origin and an online enrolled destination are required.')
            origin = origins[0]
            command = {'version': 1, 'requestId': str(uuid.uuid4()), 'originDevice': origin['descriptor']['id'],
                       'targetDevice': target['descriptor']['id'], 'enrollment': target['enrollment'], 'conversation': key,
                       'command': args['command'], 'cwd': args.get('cwd'), 'timeout': args.get('timeout', 10),
                       'expiresAt': int(time.time() * 1000) + 120000}
            approval = send(sid, 'approve', {'targetName': target['descriptor']['name'], 'command': command})
            if approval.get('command') != command or not approval.get('signature'):
                raise RuntimeError('Origin approval did not match this command and destination.')
            if not live(origin) or not live(target):
                raise RuntimeError('A device disconnected before dispatch. No command was sent.')
            result = send(target['sid'], 'execute', {'token': target['token'], 'approval': approval}, timeout=command['timeout'] + 15)
            return json.dumps({'destination': target['descriptor']['name'], 'result': result, 'retry': False, 'server_fallback': False})
        except Exception as exc:
            return json.dumps({'error': str(exc), 'retry': False, 'server_fallback': False})

    def settings_command(raw):
        """Stock command.dispatch binds the live chat; no model turn is needed."""
        try:
            from tui_gateway.transport import current_transport
            _, _, peer, _ = context()
            if current_transport() is not peer:
                raise RuntimeError('The Settings connection must own the enrollment conversation.')
            actions = {'list': {'action': 'list'}, 'origin': {'action': 'register', 'role': 'origin'},
                       'target': {'action': 'register', 'role': 'target'}, 'revoke': {'action': 'revoke'}}
            if raw.strip() not in actions:
                raise ValueError('Use list, origin, target, or revoke.')
            return registry(actions[raw.strip()])
        except Exception as exc:
            return json.dumps({'error': str(exc), 'retry': False})

    ctx.register_command('desktop-devices', settings_command,
                         description='Manage this Desktop cross-device enrollment without a model turn.',
                         args_hint='list|origin|target|revoke')

    ctx.register_tool('desktop_devices', 'hermes-desktop-bridge', {
        'name': 'desktop_devices', 'description': 'Register this live Desktop as an origin first, then register another Desktop as a target. Target enrollment requires native consent for listed origin keys and ends when its client closes or changes gateway. List gives exact device IDs; revoke removes this client. No remote device is discovered or enabled silently.',
        'parameters': {'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['register', 'list', 'revoke']},
                       'role': {'type': 'string', 'enum': ['origin', 'target']}}, 'required': ['action'], 'additionalProperties': False}}, registry)
    ctx.register_tool('desktop_remote_terminal', 'hermes-desktop-bridge', {
        'name': 'desktop_remote_terminal', 'description': 'Run one bounded Bash command on an explicitly enrolled destination ID from desktop_devices. Native approval appears on the originating Desktop and names the destination. File operations may use this terminal. Never retry unknown outcomes, select another device, or fall back to the server.',
        'parameters': {'type': 'object', 'properties': {'target_device': {'type': 'string'}, 'command': {'type': 'string', 'minLength': 1, 'maxLength': 64000},
                       'cwd': {'type': 'string'}, 'timeout': {'type': 'integer', 'minimum': 1, 'maximum': 60}},
                       'required': ['target_device', 'command'], 'additionalProperties': False}}, execute)
