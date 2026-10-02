"""Patch-free Hermes backend using the Desktop desktop.exec request bridge."""
import base64
import json
import math
import re
import shlex
import sys
import threading
import uuid

from agent.terminal_env_provider import TerminalEnvironmentProvider


def _session_key():
    from gateway.session_context import get_session_env
    return get_session_env("HERMES_SESSION_KEY", "")


def _owner(key):
    # Never initialize another gateway or infer ownership from a task/cache id.
    server = sys.modules.get("tui_gateway.server")
    if not key or server is None:
        raise RuntimeError("hermes-desktop-terminal requires a live Desktop session")
    with server._sessions_lock:
        matches = [(sid, s) for sid, s in server._sessions.items()
                   if s.get("session_key") == key]
        if len(matches) != 1:
            raise RuntimeError("Desktop session ownership is missing or ambiguous")
        sid, session = matches[0]
        peers = server._session_live_transports(session)
        from tui_gateway import server_requests
        from tui_gateway.ws import WSTransport
        # Requests fan out in stock Hermes. Refuse ambiguity before executing.
        if len(peers) != 1 or not isinstance(peers[0], WSTransport) or not server_requests.answers_requests(peers[0]):
            raise RuntimeError("Exactly one request-capable Desktop client must own this session")
        return sid


def _declare_contract():
    from tui_gateway.contracts.registry import SERVER_REQUESTS, server_request
    from tui_gateway.contracts.server_requests import ServerRequestParams, ValueResult
    if "desktop.exec" in SERVER_REQUESTS:
        return  # Future upstream declaration takes precedence.

    class DesktopExecParams(ServerRequestParams):
        command: str
        cwd: str | None = None
        timeout: int = 10
        shell: str = "bash"

    server_request("desktop.exec", params=DesktopExecParams, result=ValueResult,
                   doc="Execute a bounded command on the session-owning Desktop.")


def _decode(reply):
    if not isinstance(reply, dict):
        raise ValueError("Desktop did not answer; execution outcome is unknown")
    value = reply.get("value", reply)
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("Desktop returned no structured execution result")
    code = value.get("returncode", value.get("exit_code", value.get("code")))
    if type(code) is not int:
        raise ValueError("Desktop returned no integer exit status")
    output = value.get("output")
    if output is None:
        output = value.get("stdout", "") + value.get("stderr", "")
    if not isinstance(output, str):
        raise ValueError("Desktop returned invalid command output")
    if value.get("error") and not output:
        output = str(value["error"])
    result = {"output": output, "returncode": code}
    if value.get("timed_out"):
        result.update(returncode=124, hermes_timed_out=True)
    return result


class DesktopEnvironment:
    def __init__(self, timeout, key, sid):
        self.timeout, self.key, self.sid = timeout, key, sid
        self.cwd = None  # Never send the Ubuntu server's cwd to the Desktop.
        self._lock = threading.RLock()
        self._closed = False

    def execute(self, command, timeout=None, cwd=None, **kwargs):
        # Return errors, rather than raise after dispatch: core retries exceptions.
        with self._lock:
            try:
                if self._closed or _session_key() != self.key or _owner(self.key) != self.sid:
                    raise RuntimeError("Desktop environment is closed or belongs to another session")
                seconds = max(1, min(60, math.ceil(float(self.timeout if timeout is None else timeout))))
                marker = "__ATHENA_CWD_" + uuid.uuid4().hex + "__"
                target = cwd or self.cwd
                if target == "/workspace":
                    target = self.cwd
                prefix = "cd -- " + shlex.quote(target) + " || exit 126\n" if target else ""
                script = prefix + str(command) + '\n__athena_rc=$?\nprintf "\\n' + marker + '%s\\n" "$PWD"\nexit "$__athena_rc"'
                stdin_data = kwargs.get("stdin_data")
                if stdin_data is not None:
                    if isinstance(stdin_data, str):
                        stdin_data = stdin_data.encode("utf-8")
                    encoded = base64.b64encode(stdin_data).decode("ascii")
                    if len(encoded) > 750000:
                        raise ValueError("desktop.exec v0.1 stdin exceeds its 750 KB encoded limit")
                    script = "printf %s " + shlex.quote(encoded) + " | base64 -d | bash -c " + shlex.quote(script)
                # Stock file tools emit POSIX shell commands; require a Bash Desktop runner.
                from tui_gateway import server_requests
                reply = server_requests.send("desktop.exec", self.sid,
                    {"command": script, "cwd": None, "timeout": seconds, "shell": "bash"}, timeout=seconds + 5)
                result = _decode(reply)
                match = re.search(r"\r?\n" + re.escape(marker) + r"([^\r\n]+)\r?\n", result["output"])
                if match:
                    observed = match.group(1)
                    if observed:
                        self.cwd = observed
                        result.update(cwd=observed, cwd_observed=True)
                    result["output"] = result["output"][:match.start()] + result["output"][match.end():]
                if kwargs.get("bounded_capture") and len(result["output"]) > 100000:
                    result["output"] = result["output"][:50000] + "\n[output truncated]\n" + result["output"][-50000:]
                return result
            except Exception as exc:
                return {"output": f"hermes-desktop-terminal: {exc}. No automatic retry or server fallback.", "returncode": -1}

    def cleanup(self):
        self._closed = True  # The Desktop and its files belong to the user.

    def spawn_background(self, *args, **kwargs):
        raise RuntimeError("desktop.exec v0.1 supports foreground execution only")


class HermesDesktopTerminalProvider(TerminalEnvironmentProvider):
    name = "hermes-desktop-terminal"
    display_name = "Hermes Desktop Terminal"
    is_remote = True
    is_container = True  # Select remote shell file operations, not server-native I/O.
    skip_container_guards = False  # Physical Desktop: retain dangerous-command approvals.
    env_description = "the session-owning Hermes Desktop through a Bash runner"

    def is_available(self):
        return True  # Static bridge availability; ownership checked per execution.

    def probe(self):
        return "needs_setup", "Requires a patched Desktop Bash runner and exactly one attached client."

    def create_environment(self, *, cwd, timeout, task_id="default", **kwargs):
        key = _session_key()
        env = DesktopEnvironment(timeout, key, _owner(key))
        result = env.execute(":", timeout=5)
        if result["returncode"] != 0 or not env.cwd:
            raise RuntimeError("Desktop Bash probe failed: " + result["output"])
        # Translate the factory's server-side default to the discovered Desktop cwd.
        env.host_cwd, env.host_cwd_mount = cwd, env.cwd
        return env


def register(ctx):
    _declare_contract()
    ctx.register_terminal_environment_provider(HermesDesktopTerminalProvider())
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('hermes_desktop_terminal_routing', Path(__file__).with_name('routing.py'))
    routing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routing)
    from types import SimpleNamespace
    routing.install(ctx, SimpleNamespace(_session_key=_session_key, _owner=_owner))
    pc_spec = importlib.util.spec_from_file_location('hermes_desktop_pc', Path(__file__).with_name('pc.py'))
    pc = importlib.util.module_from_spec(pc_spec)
    pc_spec.loader.exec_module(pc)
    pc.install(ctx, SimpleNamespace(_session_key=_session_key, _owner=_owner))
    remote_spec = importlib.util.spec_from_file_location('hermes_desktop_remote', Path(__file__).with_name('remote.py'))
    remote = importlib.util.module_from_spec(remote_spec)
    remote_spec.loader.exec_module(remote)
    remote.install(ctx, SimpleNamespace(_session_key=_session_key, _owner=_owner))
