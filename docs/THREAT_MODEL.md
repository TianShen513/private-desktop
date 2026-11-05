# Threat model

Version 0.1 protects a narrow boundary: observations and actions between a cloud AI client and one offline Linux desktop demo. It is a starting point for inspecting how desktop agents can work with less data, not a universal privacy layer for arbitrary computer use.

## Trust boundaries

Trusted components are the local Python gateway, its interpreter and source, the host operating system, Docker Desktop and its Linux VM, the built sandbox image, and the user controlling them. The model, proposed tool arguments, and app-supplied desktop text are untrusted.

The model receives only the four gateway tools. It must have no alternative route to Docker, the raw CLI, host files, a shell, the guest network, or the local memory of the gateway. The gateway runs outside the container, so a desktop app cannot rewrite its policy. Docker administrative access can bypass every container boundary described here.

On macOS and Windows, Docker Desktop provides a shared Linux VM. A container is isolated from the host and other containers using Docker's normal security mechanisms. There is not a dedicated hardware VM for each task. A Docker, kernel, hypervisor, or host compromise is outside this project's protection.

## Data leaving the gateway

The gateway constructs an allowlisted projection of an observation. It does not recursively return arbitrary upstream JSON. Approved structural information and a small exact list of safe UI labels remain readable. Unapproved text becomes a random, session-local token. Private values are hidden even when numeric rather than strings. The raw observation and token mappings stay local.

Tokens are pseudonyms. They can reveal that two observed values are the same within a session. UI shape, roles, allowed labels, reference counts, actions, and timing also reveal information. This release does not claim anonymity, differential privacy, encrypted inference, or resistance to all inferences from context.

There is no automatic restoration of secrets. The gateway refuses token-shaped input in typing commands. A future restoration feature would need local authorization bound to the secret, action, app, target, and intended destination. Blindly restoring a token into model-selected content would enable exfiltration without revealing plaintext to the model first.

## Actions entering the gateway

Only `desktop_snapshot`, `desktop_click`, `desktop_type`, and `desktop_status` are exposed. Unexpected tools, arguments, types, and malformed protocol messages are refused. The application selector is fixed by the launcher, not supplied by the model. Action references must have been issued by the current gateway's latest snapshot; raw or foreign references are refused.

There is no arbitrary command passthrough. Screenshots, clipboard access, `get`, batches, app launching, trace exports, debug files, global keyboard/mouse actions, and token restoration are not exposed. Upstream adding a new CLI command does not automatically add a gateway tool.

Tool and process errors use stable generic messages instead of forwarding arbitrary raw diagnostics. Input and output size and nesting limits bound resource usage. These controls reduce available paths; they do not make every allowed click harmless. Client action confirmation and scope review still matter.

## Sandbox controls

The launcher creates its own labeled container and checks ownership before operating on it. The intended runtime has:

- No host mounts, volumes, Docker socket, devices, or published ports.
- `--network none`, covering desktop apps as well as agent-desktop.
- A non-root user, all Linux capabilities dropped, and `no-new-privileges`.
- A read-only root filesystem with temporary writable desktop storage.
- CPU, memory, and process-count limits.
- A pinned upstream agent-desktop release and pinned download checksums.

The image build downloads packages and release artifacts. Build-time networking is separate from the offline runtime. Ubuntu repositories remain a supply-chain dependency; image tags and package repository contents are not an independent reproducible-build guarantee.

The initial image contains a synthetic GTK demo. Importing real data, adding apps, enabling network access, or mounting folders would change this threat model and require new enforcement and tests. There is no supported network-enable flag in version 0.1.

## Local storage and logging

Raw snapshot data remains in guest temporary storage; token mappings remain in gateway memory. Stopping the managed container discards its temporary desktop state. The launcher's ownership identifier is persistent local metadata, not a token vault or desktop transcript.

This does not defend against host administrators, malware on the host, memory inspection, swap, crash dumps, operating-system backups, or an AI client retaining filtered transcripts. The project does not provide an encryption-at-rest system for the host. Transport to a cloud provider is managed by the AI client.

## Outside this filter

User prompts, attachments, other tools, and conversation history sent directly by an AI client do not pass through this gateway. A user can therefore disclose private information independently of a perfectly filtered desktop result. A complete model-traffic gateway would be a separate component.

Confidential prose cannot remain completely hidden while a conventional cloud model reasons about its meaning. Such reasoning must happen locally, or the user must deliberately disclose enough content for the task. Pattern-based PII detection alone would not solve this because confidential data can be arbitrary text.

## Verification

Unit tests should exercise nested and non-string secrets, unknown output fields, errors, oversized messages, unsupported tools, unknown arguments, stale and foreign references, and attempted token restoration. A real-container smoke test should exercise actual accessibility observations and actions, runtime hardening, and filtered results.

Cross-platform Python tests do not establish that every Docker Desktop release behaves identically. A Linux Docker smoke test is useful runtime evidence, but macOS and Windows Docker Desktop should also be checked on supported host configurations. There has been no independent security audit.
