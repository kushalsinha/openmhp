# Security Policy# Security Policy

OpenMHP servers and drivers can operate physical lab and factory hardware, so a vulnerability here can mean more than a data leak: it can mean an instrument doing something unsafe. Please report security issues privately and promptly.

## Reporting a vulnerability

Do not open a public GitHub issue for a security report.

Instead, use GitHub's private vulnerability reporting for this repository: go to the Security tab, then "Report a vulnerability". This opens a private draft advisory that only maintainers can see.

Please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce it, including any device package, descriptor, or script involved
- Whether it affects the protocol/spec, the reference implementation (openmhp/), an adapter, or a bundled device package
- Whether the issue could let an agent bypass a safety gate (state, approval, interlocks, typed parameters, lease, or busy checks); flag these as high severity

We aim to acknowledge reports within 3 business days and to provide a remediation timeline within 10 business days.

## Scope

In scope:

- The reference server, client, and MCP bridge in openmhp/
- The adapters in openmhp/adapters/
- The npx openmhp-cli and npx openmhp-node launchers
- The bundled reference device packages in openmhp/devices/ and packages/

Generally out of scope:

- Vulnerabilities in a third-party vendor SDK, driver, or control system that OpenMHP wraps but does not maintain
- Device packages you or your lab wrote and host in your own repository

## Supported versions

OpenMHP is pre-1.0 and experimental. Security fixes are made against the latest released version on PyPI and npm; there is no long-term-support branch yet.

## Safety vs. security

A hardware safety issue, such as a limit, interlock, or e-stop behavior that does not work as documented, that does not involve exploiting the software is still important, but can be filed as a normal GitHub issue. Use this security process when the report involves bypassing a safety gate through a software vulnerability, not just proposing a design change.
