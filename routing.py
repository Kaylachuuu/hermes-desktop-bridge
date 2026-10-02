"""Experimental opt-in routing through stock execution middleware."""
import json
import threading

ROUTED_TOOLS = frozenset({'terminal', 'read_file', 'write_file', 'patch', 'search_files'})


def install(ctx, provider):
    owners = {}
    lock = threading.RLock()
    default_enabled = getattr(ctx, 'get_config', lambda key, default: default)('default_for_desktop', False) is True

    def desktop_guidance(session):
        if session.get('platform') != 'desktop':
            return ''
        routing_note = ('Desktop routing is enabled by default.' if default_enabled else
                        'First call desktop_terminal_session with {"action":"enable"}.')
        return ('Hermes Desktop Bridge: "local files", "this computer", and "my laptop" mean the '
                'Desktop owning this conversation, not the backend server. ' + routing_note +
                ' Use the normal terminal, read_file, write_file, patch, and search_files tools; '
                'the bridge routes them to that Desktop. The plugin name is not a tool or shell command. '
                'To check routing, call desktop_terminal_session with {"action":"status"}. '
                'Use desktop_remote_terminal only when the user explicitly requests a DIFFERENT '
                'registered device. That tool requires target_device and command. To list registered '
                'devices, call desktop_devices with {"action":"list"}; never invent a device ID. '
                'If a call was not invoked because arguments were missing, correct the tool selection '
                'and required arguments. Stop on refused or unknown execution outcomes; never fall back '
                'to the backend server for a Desktop request.')

    register_prompt = getattr(ctx, 'register_system_prompt_section', None)
    if register_prompt:
        register_prompt('hermes-desktop-bridge.routing', desktop_guidance, max_chars=1800)

    def automatic_session():
        from gateway.session_context import get_session_env
        return default_enabled and get_session_env('HERMES_SESSION_SOURCE', '') == 'desktop'

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
                return json.dumps({'enabled': bool(state) or (state is None and automatic_session()), 'blocked': state is False,
                                   'default_for_desktop': default_enabled,
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
        if sid is None and not automatic_session():
            return next_call(args)
        if sid is False:
            return json.dumps({'error': 'Desktop routing disabled for this conversation. Re-enable it or start a new conversation.', 'server_fallback': False})
        from tools.terminal_scope import get_terminal_scope, set_terminal_scope, reset_terminal_scope, enforce_no_refusal
        token = None
        try:
            enforce_no_refusal()
            actual_owner = provider._owner(key)
            if sid is None:
                with lock:
                    owners[key] = actual_owner
                sid = actual_owner
            if actual_owner != sid:
                raise RuntimeError('Desktop owner changed; re-enable routing for this conversation')
            policy = dict(get_terminal_scope() or {})
            policy.update(TERMINAL_ENV='hermes-desktop-bridge', TERMINAL_CWD='/workspace')
            token = set_terminal_scope(policy)
            from tools.terminal_tool_lifecycle import get_active_env
            existing = get_active_env(kwargs.get('task_id'))
            if existing is not None and getattr(existing, 'env_type', None) != 'hermes-desktop-bridge':
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
                'description': 'Control routing of the NORMAL terminal and file tools to THIS computer (the Desktop owning this chat). Call with {"action":"status"} to check, {"action":"enable"} to enable, or {"action":"disable"} to block. When default routing is enabled, use normal terminal/read_file/write_file/search_files directly. No device registration or target_device is needed for this computer. Disable never switches execution to the backend server.',
                'parameters': {'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['enable', 'disable', 'status']}}, 'required': ['action'], 'additionalProperties': False}},
    )
    return enable, route
