# Security

private-desktop 0.1 is a developer preview with a deliberately narrow offline desktop workflow. Read [the threat model](docs/THREAT_MODEL.md) before using real data. This project does not offer a guarantee of zero leakage or an audited security boundary.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/TianShen513/private-desktop/security/advisories/new) for this repository. If that form is unavailable, request a private reporting channel from the maintainer without publishing exploit details.

Include the affected commit or release, host platform, Python and Docker versions, expected boundary, and a reproduction using synthetic data. Useful findings include a way to bypass the tool allowlist, expose private values through results or errors, act on unissued references, escape the intended container configuration, or transmit data from the offline runtime.

Do not attach real desktop snapshots, screenshots, token mappings, personal data, credentials, or private AI transcripts to public issues. Remove such content from proof-of-concept files before sharing them.

## Supported versions

Security fixes target the latest 0.1.x release. Update both the gateway and its locally built image when a security fix changes sandbox assets. Dependencies, Docker Desktop, and the host operating system need their own updates.
