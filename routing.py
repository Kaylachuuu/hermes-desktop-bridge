"""Experimental opt-in routing through stock execution middleware."""
import json
import threading

ROUTED_TOOLS = frozenset({'terminal', 'read_file', 'write_file', 'patch', 'search_files'})


def install(ctx, provider):
    owners = {}
    lock = threading.RLock()

    def enable(args, **kwargs):
        action = args.get('action')
        if set(args) != {'action'} or action not in {'enable', 'disable', 'status'}:
            return json.dumps({'error': 'Provide action: enable, disable, or status.'})
        try:
            key = provider._session_key()
            if not key:
                raise RuntimeError('A live Desktop conversation is required')
            if action in {'disable', 'status'}:
                with lock:
                    if action == 'disable':
                        owners[key] = False
                    state = owners.get(key)
                return json.dumps({'enabled': bool(state), 'blocked': state is False,
                                   'scope': 'this live conversation',
                                   'note': 'Disable blocks routed tools until re-enabled or a new conversation is started.'})
            sid = provider._owner(key)
            with lock:
                owners[key] = sid
            return json.dumps({'enabled': True, 'scope': 'this live Desktop conversation only',
                               'tools': sorted(ROUTED_TOOLS), 'server_fallback': False})
        except Exception as exc:
            return json.dumps({'enabled': False, 'error': str(exc)})

    def route(tool_name, args, next_call, **kwargs):
        if tool_name not in ROUTED_TOOLS:
            return next_call(args)
        key = provider._session_key()
        with lock:
            sid = owners.get(key)
        if sid is None:
            return next_call(args)
        if sid is False:
            return json.dumps({'error': 'Desktop routing disabled for this conversation. Re-enable it or start a new conversation.', 'server_fallback': False})
        from tools.terminal_scope import get_terminal_scope, set_terminal_scope, reset_terminal_scope, enforce_no_refusal
        token = None
        try:
            enforce_no_refusal()
            if provider._owner(key) != sid:
                raise RuntimeError('Desktop owner changed; re-enable routing for this conversation')
            policy = dict(get_terminal_scope() or {})
            policy.update(TERMINAL_ENV='hermes-desktop-terminal', TERMINAL_CWD='/workspace')
            token = set_terminal_scope(policy)
            from tools.terminal_tool_lifecycle import get_active_env
            existing = get_active_env(kwargs.get('task_id'))
            if existing is not None and getattr(existing, 'env_type', None) != 'hermes-desktop-terminal':
                raise RuntimeError('This conversation already has another terminal environment; use a new conversation')
            return next_call(args)
        except Exception as exc:
            # Middleware exceptions before next_call fail open in core. Return a refusal instead.
            return json.dumps({'error': 'Desktop routing refused: ' + str(exc), 'server_fallback': False})
        finally:
            if token is not None:
                reset_terminal_scope(token)

    ctx.register_middleware('tool_execution', route)
    ctx.register_tool(
        name='desktop_terminal_session', toolset='terminal', handler=enable,
        schema={'name': 'desktop_terminal_session',
                'description': 'Enable, disable, or inspect experimental laptop routing for this live Desktop conversation. Enable requires one attached Desktop owner. Disable blocks terminal and file tools until re-enabled or a new conversation is started; it never switches an existing conversation to server execution. Shared terminal configuration is unchanged.',
                'parameters': {'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['enable', 'disable', 'status']}}, 'required': ['action'], 'additionalProperties': False}},
    )
    return enable, route
