"""Run from this directory with stock Hermes on PYTHONPATH (no live Desktop needed)."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import types
import unittest

from gateway.session_context import set_session_vars, clear_session_vars
from tui_gateway import server_requests
from tui_gateway.ws import WSTransport
from agent import terminal_env_registry
from tools.file_operations import ShellFileOperations
from tools.terminal_tool_backends import _create_environment

spec = importlib.util.spec_from_file_location("athena_desktop", pathlib.Path(__file__).with_name("__init__.py"))
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class BridgeIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="athena-test-")
        self.key, self.sid = "durable-test", "runtime-test"
        self.peer = object.__new__(WSTransport)
        self.peers = [self.peer]
        self.previous = sys.modules.get("tui_gateway.server")
        self.server = types.SimpleNamespace(_sessions_lock=threading.RLock(),
            _sessions={self.sid: {"session_key": self.key}},
            _session_live_transports=lambda s: self.peers)
        sys.modules["tui_gateway.server"] = self.server
        server_requests.advertise(self.peer, True)
        self.tokens = set_session_vars(source="desktop", session_key=self.key, ui_session_id=self.sid)
        self.frames = []
        self.reply_mode = "normal"
        server_requests.bind_sinks(self.dispatch, lambda *args: None, lambda sid: True)
        plugin.register(types.SimpleNamespace(register_terminal_environment_provider=terminal_env_registry.register_provider,
                                             register_middleware=lambda *args: None, register_tool=lambda **kwargs: None))
        self.env = _create_environment("hermes-desktop-terminal", None, "/workspace", 10)

    def dispatch(self, frame):
        self.frames.append(frame)
        if self.reply_mode == "malformed":
            result = {"value": "{}"}
        elif self.reply_mode == "declined":
            result = {"value": ""}
        else:
            p = frame["params"]
            self.assertEqual(p["session_id"], self.sid)
            self.assertEqual(p["shell"], "bash")
            self.assertIsNone(p["cwd"])
            run = subprocess.run(["bash", "-c", p["command"]], cwd=self.temp.name,
                capture_output=True, text=True, timeout=p["timeout"])
            result = {"value": json.dumps({"output": run.stdout + run.stderr, "returncode": run.returncode})}
        server_requests.resolve_response({"jsonrpc": "2.0", "id": frame["id"], "result": result}, self.peer)

    def tearDown(self):
        self.env.cleanup()
        server_requests.forget(self.peer)
        clear_session_vars(self.tokens)
        if self.previous is None:
            sys.modules.pop("tui_gateway.server", None)
        else:
            sys.modules["tui_gateway.server"] = self.previous
        self.temp.cleanup()

    def test_shell_exit_stderr_and_cwd(self):
        result = self.env.execute("mkdir -p 'space dir'; cd 'space dir'; printf hello; printf error >&2; false")
        self.assertEqual(result["returncode"], 1)
        self.assertEqual(result["output"], "helloerror")
        self.assertTrue(self.env.cwd.endswith("/space dir"))
        self.assertEqual(self.env.execute("printf followup")["output"], "followup")

    def test_real_shell_file_roundtrip(self):
        ops = ShellFileOperations(self.env)
        content = "quotes ' and $literal\nUnicode: Athena α\n"
        written = ops.write_file("note.txt", content)
        self.assertIsNone(written.error, written)
        self.assertTrue(written.verified, written)
        read = ops.read_file_raw("note.txt")
        self.assertIsNone(read.error, read)
        self.assertEqual(read.content, content)
        self.assertEqual((pathlib.Path(self.temp.name)/"note.txt").read_text(), content)

    def test_other_session_cannot_dispatch(self):
        clear_session_vars(self.tokens)
        self.tokens = set_session_vars(source="desktop", session_key="other")
        before = len(self.frames)
        self.assertEqual(self.env.execute("touch should-not-exist")["returncode"], -1)
        self.assertEqual(len(self.frames), before)

    def test_disconnected_and_multiple_clients_cannot_dispatch(self):
        for peers in ([], [self.peer, object.__new__(WSTransport)]):
            self.peers = peers
            before = len(self.frames)
            self.assertEqual(self.env.execute("touch should-not-exist")["returncode"], -1)
            self.assertEqual(len(self.frames), before)

    def test_bad_replies_are_not_retried(self):
        for mode in ("malformed", "declined"):
            self.reply_mode = mode
            before = len(self.frames)
            self.assertEqual(self.env.execute("printf once")["returncode"], -1)
            self.assertEqual(len(self.frames), before + 1)

    def test_timeout_normalization_and_approval_policy(self):
        result = plugin._decode({"value": json.dumps({"returncode": 1, "output": "partial", "timed_out": True})})
        self.assertEqual(result["returncode"], 124)
        self.assertTrue(result["hermes_timed_out"])
        self.assertFalse(plugin.HermesDesktopTerminalProvider().skip_container_guards)


if __name__ == "__main__":
    unittest.main(verbosity=2)
