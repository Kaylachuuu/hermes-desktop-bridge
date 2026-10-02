"""Model-free, bounded Desktop file-transport diagnostic."""
import hashlib
import json
import shlex
import sys
import uuid


def install(ctx, provider, route):
    def check(raw_args):
        if raw_args.strip():
            return 'Use /desktop-bridge-test without arguments.'
        key = provider._session_key()
        sid = provider._owner(key)
        from tui_gateway.transport import current_transport
        server = sys.modules['tui_gateway.server']
        peer = server._session_live_transports(server._sessions[sid])[0]
        if current_transport() is not peer:
            return 'Refused: invoke this diagnostic from the conversation-owning Desktop.'
        from model_tools import handle_function_call
        task = key + '-bridge-diagnostic-' + uuid.uuid4().hex
        def call(name, args):
            result = route(name, args, lambda final: handle_function_call(
                name, final, task_id=task, skip_tool_execution_middleware=True), task_id=task)
            return json.loads(result) if isinstance(result, str) else result
        probe = call('terminal', {'command': 'pwd', 'timeout': 10})
        if probe.get('error') or probe.get('exit_code', -1) != 0:
            return json.dumps({'stage': 'probe', 'result': probe})
        cwd = probe['output'].strip()
        if not cwd.startswith('/') or '\n' in cwd:
            return 'Refused: Desktop returned no unambiguous absolute working directory.'
        path = cwd.rstrip('/') + '/athena-desktop-tests/bridge-large-' + uuid.uuid4().hex + '.txt'
        content = 'Athena larger file bridge test — α\n' * 300
        expected = hashlib.sha256(content.encode('utf-8')).hexdigest()
        written = call('write_file', {'path': path, 'content': content})
        if written.get('error'):
            return json.dumps({'stage': 'write', 'path': path, 'result': written})
        read = call('read_file', {'path': path, 'offset': 1, 'limit': 2})
        if read.get('error'):
            return json.dumps({'stage': 'read', 'path': path, 'result': read})
        observed = call('terminal', {'command': 'wc -lc ' + shlex.quote(path) + '; sha256sum ' + shlex.quote(path), 'timeout': 10})
        output = observed.get('output', '')
        matches = observed.get('exit_code') == 0 and expected in output
        return json.dumps({'passed': matches, 'path': path, 'expected_lines': 300,
                           'expected_bytes': len(content.encode('utf-8')), 'expected_sha256': expected,
                           'write': written, 'read': read, 'terminal': observed}, ensure_ascii=False)
    ctx.register_command('desktop-bridge-test', check,
                         description='Write a unique 300-line diagnostic file on this Desktop and verify its bytes; no model generation or project edits.')
