# Hermes Desktop Terminal

An experimental standalone Hermes Terminal Environment Provider that routes terminal and shell file
operations to the session-owning Hermes Desktop over the existing server-request bridge.

**Prototype: not ready for general use.** This requires a custom Desktop `desktop.exec` handler.
Stock Hermes Desktop does not provide that capability. Live terminal and file routing have been
verified with the patched Windows Desktop. Production hardening remains pending.

## Device-control development prototype (0.3.0-dev)

The local development build adds `desktop_pc` through a separate typed
`desktop.pc` request. Its PC driver runs on the owning Desktop over a private,
per-conversation MCP subprocess transport. The server stays stock.

Windows inspection and exact-field background text entry passed live Notepad
tests. Use a fresh editor element token for typing, and verify the value;
process-wide background delivery alone may have no visible effect.

The browser prototype exposes preparation, exact tab binding,
page reading, navigation, clicking and typing through dedicated typed
`desktop_browser_prepare`, `desktop_browser_read`, `desktop_browser_navigate`,
`desktop_browser_click`, `desktop_browser_type`, `desktop_browser_pointer`, and
`desktop_browser_dialog` tools. They accept flat parameters directly and Desktop
supplies the explicit browser lifecycle label internally. Browser setup
supports temporary private profiles, separate persistent Athena account profiles,
and exact existing Chrome/Edge window attachment. Account modes require separate
native approval, once or for the conversation; private grants do not authorize
them. Existing Firefox attachment is unavailable. Chrome passed live launch/bind/navigate/read/click and idle-survival
checks. Set browser="edge" or browser="firefox" during preparation to use the
new adapter, which returns target_id/tab_id directly. Its real Windows browser
tests and bundled-adapter tests pass; visible testing through Athena is pending.
macOS signed-install discovery and Linux root-owned-install discovery are implemented
but have not been tested on those platforms. Linux/Mac packaging and PC control
validation remain pending. The adapter currently reads main-frame dom_refs_v1 pages
and supports reference-based input; scoped reads, semantic snapshots and frames
remain pending.

Native consent discloses forwarding window text and screenshots to the remote
Hermes server and configured AI/vision providers. Screenshots are cached on the
server. Inspection-only access expires after five idle minutes. Input/browser
prompts offer Allow once or Allow for this conversation. Conversation grants
cover subsequent background actions for that chat; focus-changing actions
require a separate grant. Grants are scoped to the chat, owning window and
gateway, and end on revoke, client close or driver failure. `status` reports
active grants. Driver telemetry is disabled. Session ids
and screenshot output paths are owned by Desktop. For a conversation-approved
browser, Desktop renews confirmed live driver lifecycles every minute without
reading pages or performing browser actions; expired lifecycles require an
explicit fresh preparation. Driver lifetime, permission grants, and browser
references remain separate.
Transport failure or timeout
never automatically repeats an action. Existing `computer_use` stays unchanged.

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

### Cross-device terminal prototype

The unpublished prototype adds `desktop_devices` and `desktop_remote_terminal`.
Register the requesting Desktop with `action=register, role=origin`, then register
the destination Desktop with `action=register, role=target`. The destination asks
permission to accept commands signed by the listed origin devices. Both clients
must remain connected to the same authenticated gateway account and profile.

Use the exact destination ID from `desktop_devices` in `desktop_remote_terminal`.
The native approval dialog appears on the requesting computer and names the
destination, directory, timeout and command. Allow once approves that command;
Allow for this conversation covers terminal/file commands on that enrolled
destination. Each approved command has a short-lived signed receipt consumed
once by the destination. Private signing keys remain on their respective devices.

`desktop_devices` with `action=revoke` removes this client's enrollment and native
conversation grants. Closing or reconnecting a client requires registration again.
An unknown execution outcome must not be retried. There is no server fallback.
This first prototype uses one origin or target role per device registration and
routes terminal/file operations only. Browser and native PC tools remain tied to
their current conversation's Desktop. Live cross-device acceptance is pending.

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
hermes --run-module unittest discover -s /path/to/hermes-desktop-terminal -p 'test_*.py' -v
```

The provider and routing fixtures pass integration tests against stock Hermes commit `1ce2cfb7f`,
using the real provider factory, contract validation, request/response settlement, Bash execution,
and shell file write/read. Desktop transport is simulated in those tests; this is not a claim of
live Windows acceptance or production readiness.

The Desktop capability should be contributed upstream separately. Production adoption needs
explicit capability negotiation, native consent and connection authorization, owner targeting,
deduplication, bounded stdin/output, and cancellation of the full process tree.
