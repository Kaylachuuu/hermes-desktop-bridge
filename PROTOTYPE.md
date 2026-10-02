# Device-control prototype checkpoint

This development snapshot extends the public terminal provider with PC/browser
tools and explicitly enrolled cross-device terminal commands. It requires the
custom Desktop prototype; stock Desktop cannot execute these requests.

Desktop source: https://github.com/Kaylachuuu/hermes-agent/tree/athena-desktop-prototype
Desktop upstream base: `10c6188de188871f64a88dd95bc6b262adb0c307`.

The canonical backend remains stock. Its installed development plugin is the
source of this snapshot; 48 provider/routing/PC/cross-device fixtures passed
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
