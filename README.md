# Hermes Desktop Terminal

An experimental standalone Hermes Terminal Environment Provider that routes terminal and shell file
operations to the session-owning Hermes Desktop over the existing server-request bridge.

**Prototype: not ready for general use.** This requires a custom Desktop `desktop.exec` handler.
Stock Hermes Desktop does not provide that capability. Live Windows-to-server validation and
session-scoped activation remain pending.

## Architecture

The remote Hermes installation retains canonical conversations, identity, and memory. The provider
registers its bridge contract at plugin load without patching tracked backend source. The Desktop
executes the command locally using Bash.

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
  mechanism must be validated first.

## Development validation

Run these tests using the canonical Hermes launcher, from an installed development copy:

```bash
hermes --run-module unittest discover -s /path/to/hermes-desktop-terminal -p test_backend.py -v
```

The plugin passed six integration tests against stock Hermes commit `1ce2cfb7f`,
using the real provider factory, contract validation, request/response settlement, Bash execution,
and shell file write/read. Desktop transport is simulated in those tests; this is not a claim of
live Windows acceptance or production readiness.

The Desktop capability should be contributed upstream separately. Production adoption needs
explicit capability negotiation, native consent and connection authorization, owner targeting,
deduplication, bounded stdin/output, and cancellation of the full process tree.
