# MCP client setup

The gateway is a local stdio MCP server. The AI client starts the process and reads its filtered tool results; it does not connect directly to the desktop container.

## Start the sandbox

Run `private-desktop doctor`, `private-desktop build`, and `private-desktop start` once before connecting. Building needs internet access. The running container has no network interface other than loopback.

`private-desktop status` reports the launcher's sandbox. `private-desktop stop` removes that sandbox and its temporary desktop state. An MCP connection does not implicitly build or start a container.

## Generate the configuration

Run:

```sh
private-desktop client-config
```

For a downloaded archive:

```sh
python3 /absolute/path/private-desktop.pyz client-config
```

On Windows, use `py -3 C:\absolute\path\private-desktop.pyz client-config`. Copy the generated `mcpServers` entry into the MCP settings supported by your client. Keep the archive at that path. Restart or reconnect the client after changing its settings.

The actual server command is `private-desktop mcp`, or the same Python archive with the `mcp` subcommand. Normal protocol output is JSON on stdout. Troubleshooting should use `doctor` and `status` in a separate terminal.

## First task

Ask the client to call `desktop_snapshot`, then act on a reference returned by that observation. A suitable first task is to inspect the bundled demo and enter public sample text into a text field. Re-observe after each action because references are bound to the latest observation and UI changes can make them stale.

The demo intentionally includes synthetic private text. Unapproved labels and values are replaced with placeholders. The model cannot retrieve a token's underlying text and cannot ask the server to expand it into an outgoing action.

## Preserve the boundary

- Keep tool confirmations enabled, especially for typing and clicking.
- Do not connect raw agent-desktop or Docker tools to the same agent.
- Do not grant the agent direct host filesystem, shell, browser, or unrestricted container execution access.
- Do not paste private prompts or attach private files to a cloud client and assume this gateway will filter them. It filters only these desktop tool results.
- Review the cloud provider and client settings for the data you choose to send. This project neither changes those settings nor proxies the client's entire model connection.

The first release is an offline Linux desktop demo. It does not automate your host's existing applications, expose a VNC viewer, connect email accounts, or support arbitrary app installation through MCP.
