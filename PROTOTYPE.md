# Device-control prototype checkpoint

This development snapshot extends the public terminal provider with PC/browser
tools and explicitly enrolled cross-device terminal commands. It requires the
custom Desktop prototype; stock Desktop cannot execute these requests.

Desktop source: https://github.com/Kaylachuuu/hermes-agent/tree/athena-desktop-prototype
Desktop upstream base: `10c6188de188871f64a88dd95bc6b262adb0c307`.

The canonical backend remains stock. Its installed development plugin is the
source of this snapshot; 52 provider/routing/PC/cross-device/guidance fixtures passed
against that backend. Client native tests and latest-upstream Desktop type checks
and builds passed separately. Live terminal/file checks passed on Windows,
Linux x64, Intel Mac and Raspberry Pi ARM64; latest-upstream Pi Firefox prepared,
navigated, inspected and clicked through Example Domain to IANA.

Settings controls enroll an origin or destination, show registered devices, and
revoke access locally even when gateway cleanup cannot be confirmed. Destination
registration pins the enrolled origins; enabling arbitrary bidirectional roles
and approval by devices registered later remains unfinished and is excluded.

Do not install this snapshot into an unrelated production account without
reviewing its custom native capability and consent requirements. General Linux
Wayland PC capture/input, Safari, custom Mac browser paths, and Firefox Sync
remain incomplete or unverified. Browser and PC tools are conversation-local;
only terminal/file execution currently supports cross-device routing.

The public `main` branch remains the earlier terminal-only checkpoint. This
prototype branch is experimental and is not a stable release.

## October 2 morning checkpoint

New Desktop chats receive plugin-owned guidance distinguishing ordinary terminal/file
access on the conversation-owning device from cross-device tools. The former needs
no destination ID; the latter requires target_device and command. List enrolled IDs
with desktop_devices and {"action":"list"}. Existing chats retain their saved
system prompts. All 52 regression checks passed against the stock backend.

Scopuli live checks confirmed hostname/OS/cwd, reading local project source and
creating directories. Quote paths containing spaces; the reported mkdir failure was
resolved by shell quoting without a bridge code change.

## Windows file-write transport fix

A disposable-file reproduction found that passing a larger base64-bearing Bash
script on the Windows command line failed with unmatched quotes. Desktop now sends
Bash scripts through stdin, reading the complete script before evaluation so
commands inside see EOF. Exact Unicode/quote/dollar/backslash roundtrips passed
through 12,900-byte payloads. The real Desktop IPC test also verifies nonzero
exit status and EOF semantics. Native type checks and Windows build/package passed.
Scopuli's installed client was updated with application/profile backups.

The plugin now preserves error-only Desktop refusal messages rather than reporting
only a missing exit status; 52 plugin checks passed. Post-update live file-write
acceptance is pending. An earlier write-success/missing-file discrepancy remains
unconfirmed; these tests do not establish that every reported issue is resolved.
