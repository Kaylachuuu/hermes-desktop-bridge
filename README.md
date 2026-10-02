# Hermes Desktop Bridge

The repository and internal plugin ID are now `hermes-desktop-bridge`.
Existing installations using `hermes-desktop-terminal` must migrate their plugin
folder and `plugins.enabled` / `plugins.entries` settings together.
The experimental PC/browser/cross-device source is on [desktop-control-prototype](https://github.com/Kaylachuuu/hermes-desktop-bridge/tree/desktop-control-prototype).

An experimental standalone Hermes Terminal Environment Provider that routes terminal and shell file
operations to the session-owning Hermes Desktop over the existing server-request bridge.

**Prototype: not ready for general use.** This requires a custom Desktop `desktop.exec` handler.
Stock Hermes Desktop does not provide that capability. Live terminal and file routing have been
verified with the patched Windows Desktop. Production hardening remains pending.

## Architecture

The remote Hermes installation retains canonical conversations, identity, and memory. The provider
registers its bridge contract at plugin load without patching tracked backend source. The Desktop
executes the command locally using Bash.

## Session controls (0.2.0)

Set the plugin's `default_for_desktop` setting to `true` to automatically route Desktop
conversations to their owning device. The setting defaults to false for new installations.
Reload the plugin and start a new conversation after changing it. Desktop sessions with no
valid owner refuse execution; messaging and CLI sessions keep their existing policy.
The per-conversation disable control still works when the default is on.

Enable this plugin, ensure the `terminal` and `file` toolsets are available, and start a new
Desktop conversation. Call the plugin tool `desktop_terminal_session` with
`{"action":"enable"}`. Use tool search if the tool is deferred. This is a tool call, not a shell command.

Ordinary `terminal`, `read_file`, `write_file`, `patch`, and `search_files` calls then run with
the Desktop provider under a temporary terminal policy that is restored after each call.
Shared profile terminal configuration is not changed. Sessions that never opt in retain their
existing policy. Browser and code execution tools are outside this routing set.

`{"action":"status"}` reports the opt-in state. `{"action":"disable"}` blocks the routed tools
in this conversation until re-enabled; start a new conversation to return to the default policy.
Routing is held only in memory. Plugin reload or server restart clears opt-ins. Reconnection that
changes the runtime owner requires enabling again. Do not reload routing plugins mid-conversation;
use a fresh conversation after switching plugins or restarting the backend.

The control tool is an experimental operator opt-in, not a replacement for a future native Desktop
capability consent model. Native consent, authorization, and capability negotiation still need work.

The prototype refuses missing or ambiguous session ownership, disconnected clients, and more than
one attached live transport. Command approvals remain enabled. Uncertain execution outcomes never
trigger automatic retries or fallback execution on the server.

## Limitations

- Requires the custom, opt-in Desktop capability; generic server-request support alone is insufficient
  for a production permission model.
- Foreground execution only, bounded to 60 seconds by the current Desktop handler.
- Windows needs a configured Git Bash executable and renderer forwarding of `shell: 'bash'`.
- Output and stdin are bounded; large transfers and streaming need further work.
- Persistent shell exports, background processes, full process-tree cancellation, request
  deduplication, and ownership-change races need additional implementation.
- Profile configuration can override launch environment settings. Do not globally switch a shared
  profile's terminal backend when a messaging gateway uses that profile. An isolated activation
  mechanism is provided by the opt-in execution middleware below.

## Development validation

Run these tests using the canonical Hermes launcher, from an installed development copy:

```bash
hermes --run-module unittest discover -s /path/to/hermes-desktop-bridge -p 'test_*.py' -v
```

The provider and routing fixtures pass integration tests against stock Hermes commit `1ce2cfb7f`,
using the real provider factory, contract validation, request/response settlement, Bash execution,
and shell file write/read. Desktop transport is simulated in those tests; this is not a claim of
live Windows acceptance or production readiness.

The Desktop capability should be contributed upstream separately. Production adoption needs
explicit capability negotiation, native consent and connection authorization, owner targeting,
deduplication, bounded stdin/output, and cancellation of the full process tree.
