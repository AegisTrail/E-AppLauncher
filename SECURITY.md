# Security Policy

## Supported Versions

Security fixes are provided for the latest minor release line:

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| < 0.2   | :x:                |

## Reporting a Vulnerability

Report vulnerabilities through **GitHub Private Vulnerability Reporting**
(Security tab → Report a vulnerability). Include:

- A description of the issue and its impact
- Steps to reproduce (commands, sample files, or a minimal proof of concept)
- The E-AppLauncher version and how it was installed (binary, `uv tool`, source)

You will receive an initial response within 7 days. If the issue is confirmed,
a fix and a release will be prepared before any public disclosure. Please do
not open public issues for unpatched vulnerabilities.

## Scope and Trust Model

E-AppLauncher is a local launcher: it scans, launches, and integrates
AppImage files on your own machine.

- AppImages are executable code. Only launch files from sources you trust;
  launching an AppImage runs it with your user privileges.
- Desktop integration extracts icons and `.desktop` entries from the
  AppImage itself. Integration writes only under `~/.local/share`
  (`applications`, `icons`) and never touches system directories.
- The update check inspects local binaries for embedded update metadata.
  It opens no network connections.
- Release binaries are built by CI from tagged commits and ship with a
  SHA256 checksum. The installer refuses to proceed when verification fails.
