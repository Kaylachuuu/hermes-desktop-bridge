"""Persistent device pins and fresh, native-signed reconnect/handoff proofs."""
import base64
import hashlib
import json
import secrets
import sys
import threading


class Bindings:
    def __init__(self, state, owner):
        self.state, self.owner = state, owner
        self.cache, self.locks, self.refusals = {}, {}, {}
        self.lock = threading.RLock()

    def context(self, key):
        sid = self.owner(key)
        server = sys.modules['tui_gateway.server']
        with server._sessions_lock:
            session = server._sessions[sid]
            peer = server._session_live_transports(session)[0]
            scope = [session.get('auth_user_id'), session.get('profile_home'), key]
        storage = 'routing.' + hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
        return sid, peer, storage

    @staticmethod
    def send(sid, action, arguments):
        from tui_gateway import server_requests
        reply = server_requests.send('desktop.remote', sid,
            {'action': action, 'arguments': arguments}, timeout=110 if arguments.get('authorize') else 10)
        value = reply.get('value', reply) if isinstance(reply, dict) else None
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict) or value.get('error'):
            raise RuntimeError((value or {}).get('error', 'Desktop identity did not answer. Stop; do not retry automatically.'))
        return value

    @staticmethod
    def verify(value, challenge, conversation, authorize):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        public = serialization.load_pem_public_key(value['publicKey'].encode())
        if not isinstance(public, Ed25519PublicKey):
            raise ValueError('Desktop identity must use Ed25519')
        der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        device = 'device-' + hashlib.sha256(der).hexdigest()
        if value.get('id') != device or value.get('authorized') is not authorize:
            raise ValueError('Desktop identity or authorization does not match')
        gateway = value['gatewayScope']
        name = value['name']
        if not isinstance(gateway, str) or len(gateway) != 64 or not isinstance(name, str) or len(name) > 256:
            raise ValueError('Invalid Desktop identity scope')
        fields = ['hermes-desktop-route-v1', challenge, conversation, gateway, device, name, authorize]
        public.verify(base64.b64decode(value['signature'], validate=True),
                      json.dumps(fields, ensure_ascii=False, separators=(',', ':')).encode())
        return {field: value[field] for field in ('id', 'publicKey', 'gatewayScope', 'name')}

    def disabled(self, key):
        return self.state.get(self.context(key)[2], {}).get('disabled', False) is True

    def disable(self, key, disabled):
        _, _, storage = self.context(key)
        with self.lock:
            record = dict(self.state.get(storage, {}))
            record['disabled'] = disabled
            record['revision'] = secrets.token_hex(16)
            self.state.set(storage, record)
            self.cache.pop(storage, None)
            self.refusals.pop(storage, None)

    def resolve(self, key):
        sid, peer, storage = self.context(key)
        with self.lock:
            lock = self.locks.setdefault(storage, threading.RLock())
        with lock:
            record = self.state.get(storage, {})
            if record.get('disabled'):
                raise RuntimeError('Desktop routing is disabled for this conversation')
            refused = self.refusals.get(storage)
            if refused and refused[:2] == (sid, peer):
                raise RuntimeError(refused[2])
            cached = self.cache.get(storage)
            if cached and cached[0] == sid and cached[1] is peer:
                return sid
            descriptor = self.send(sid, 'describe', {})
            if descriptor.get('routingIdentityVersion') != 1:
                # Older clients retain manual reconnect behavior; never discard a pin.
                if record.get('pin') or (cached and (cached[0] != sid or cached[1] is not peer)):
                    raise RuntimeError('Update this Desktop client or explicitly re-enable legacy routing')
                self.cache[storage] = (sid, peer, None)
                return sid
            challenge = secrets.token_hex(32)
            proof = self.send(sid, 'routing_identity',
                              {'challenge': challenge, 'conversation': key, 'authorize': False})
            pin = self.verify(proof, challenge, key, False)
            previous = record.get('pin')
            if previous and any(previous.get(field) != pin[field] for field in ('id', 'publicKey', 'gatewayScope')):
                challenge = secrets.token_hex(32)
                try:
                    approved = self.send(sid, 'routing_identity',
                                         {'challenge': challenge, 'conversation': key, 'authorize': True})
                except Exception:
                    message = 'Desktop handoff was refused or unanswered. Stop and wait for the user; do not repeat tools. Explicitly enable routing to request authorization again.'
                    self.refusals[storage] = (sid, peer, message)
                    raise RuntimeError(message)
                if self.verify(approved, challenge, key, True) != pin:
                    raise RuntimeError('Desktop changed while handoff approval was pending. Stop.')
            if self.context(key) != (sid, peer, storage):
                raise RuntimeError('Desktop owner changed during authorization. No command was sent.')
            with self.lock:
                latest = self.state.get(storage, {})
                if latest.get('disabled') or latest.get('revision') != record.get('revision'):
                    raise RuntimeError('Desktop routing was changed while authorization was pending. No command was sent.')
                self.state.set(storage, {**latest, 'pin': pin, 'disabled': False})
                self.cache[storage] = (sid, peer, pin)
            return sid

    def device(self, key):
        cached = self.cache.get(self.context(key)[2])
        return cached[2]['id'] if cached and cached[2] else None
