#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import select
import shlex
import sys
import time
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import termios
    import tty


DEFAULT_CONFIG_PATH = Path("spaceauth.config.json")


@dataclass
class AppConfig:
    host: str
    port: int
    username: str
    password: str
    email: str
    remote_env_path: str = "$HOME/workspace/.env"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run fastlane spaceauth on a remote host and update FASTLANE_SESSION."
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to a JSON config file. Defaults to %(default)s.",
    )
    parser.add_argument("--host", help="SSH host or IP address.")
    parser.add_argument("--port", type=int, help="SSH port.")
    parser.add_argument("--username", help="SSH username.")
    parser.add_argument("--password", help="SSH password.")
    parser.add_argument("--email", help="Apple ID email used with fastlane spaceauth.")
    parser.add_argument(
        "--remote-env-path",
        help="Remote .env path. Defaults to $HOME/workspace/.env.",
    )
    return parser


def load_json_config(path: str) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        return {}

    with config_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a JSON object: {config_path}")

    return data


def resolve_config(args: argparse.Namespace) -> AppConfig:
    file_config = load_json_config(args.config)

    ssh_config = file_config.get("ssh", {})
    fastlane_config = file_config.get("fastlane", {})
    remote_config = file_config.get("remote", {})

    host = args.host or ssh_config.get("host")
    port = args.port or ssh_config.get("port") or 22
    username = args.username or ssh_config.get("username")
    password = args.password or ssh_config.get("password")
    email = args.email or fastlane_config.get("email")
    remote_env_path = (
        args.remote_env_path
        or remote_config.get("env_path")
        or "$HOME/workspace/.env"
    )

    missing = [
        name
        for name, value in (
            ("host", host),
            ("username", username),
            ("email", email),
        )
        if not value
    ]
    if missing:
        missing_fields = ", ".join(missing)
        raise ValueError(f"Missing required configuration: {missing_fields}")

    if not password:
        password = getpass("SSH password: ")

    return AppConfig(
        host=host,
        port=int(port),
        username=username,
        password=password,
        email=email,
        remote_env_path=remote_env_path,
    )


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def read_channel_until_exit(channel, command: str) -> str:
    output_chunks: list[str] = []
    exit_marker = "__SPACEAUTH_EXIT__:"
    wrapped_command = f"{command}; printf '\\n{exit_marker}%s\\n' \"$?\"\n"
    channel.send(wrapped_command)

    if os.name == "nt":
        _stream_channel_windows(channel, output_chunks, exit_marker)
    else:
        _stream_channel_posix(channel, output_chunks, exit_marker)

    sys.stdout.write("\n")
    sys.stdout.flush()

    return "".join(output_chunks)


def _stream_channel_windows(channel, output_chunks: list[str], exit_marker: str) -> None:
    while True:
        if channel.recv_ready():
            data = channel.recv(4096)
            if not data:
                break

            text = data.decode("utf-8", errors="replace")
            output_chunks.append(text)
            sys.stdout.write(text)
            sys.stdout.flush()

            if exit_marker in "".join(output_chunks):
                break

        while msvcrt.kbhit():
            key = msvcrt.getwch()
            if key == "\r":
                channel.send("\n")
                sys.stdout.write("\n")
                sys.stdout.flush()
            elif key == "\003":
                raise KeyboardInterrupt
            elif key == "\b":
                channel.send("\b")
            else:
                channel.send(key)

        if channel.exit_status_ready() and not channel.recv_ready():
            break

        time.sleep(0.02)


def _stream_channel_posix(channel, output_chunks: list[str], exit_marker: str) -> None:
    stdin_fd = sys.stdin.fileno()
    old_tty = termios.tcgetattr(stdin_fd)
    tty.setraw(stdin_fd)

    try:
        while True:
            readers = [channel, stdin_fd]
            ready, _, _ = select.select(readers, [], [])

            if channel in ready:
                data = channel.recv(4096)
                if not data:
                    break

                text = data.decode("utf-8", errors="replace")
                output_chunks.append(text)
                sys.stdout.write(text)
                sys.stdout.flush()

                if exit_marker in "".join(output_chunks):
                    break

            if stdin_fd in ready:
                user_input = os.read(stdin_fd, 1024)
                if not user_input:
                    break
                channel.send(user_input)
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_tty)


def extract_fastlane_session(output: str) -> str:
    patterns = [
        re.compile(r"FASTLANE_SESSION=([^\r\n]+)"),
        re.compile(r"FASTLANE_SESSION['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"export FASTLANE_SESSION=(['\"])(.*?)\1", re.DOTALL),
    ]

    for pattern in patterns:
        match = pattern.search(output)
        if not match:
            continue

        session = match.group(match.lastindex or 1).strip()
        if len(match.groups()) >= 2 and match.group(2):
            session = match.group(2).strip()
        if session:
            return session

    raise RuntimeError(
        "FASTLANE_SESSION was not found in fastlane output. Check the remote output above."
    )


def update_remote_env(ssh, remote_env_path: str, session: str) -> None:
    remote_path_quoted = shell_quote(remote_env_path)
    session_quoted = shell_quote(session)
    update_script = f"""
RAW_ENV_PATH={remote_path_quoted}
SESSION_VALUE={session_quoted}
case "$RAW_ENV_PATH" in
  '$HOME'/*)
    ENV_PATH="$HOME/${{RAW_ENV_PATH#'$HOME/'}}"
    ;;
  '~'/*)
    ENV_PATH="$HOME/${{RAW_ENV_PATH#'~/'}}"
    ;;
  *)
    ENV_PATH="$RAW_ENV_PATH"
    ;;
esac
mkdir -p "$(dirname "$ENV_PATH")"
SESSION_LINE="FASTLANE_SESSION=$SESSION_VALUE"
if [ -f "$ENV_PATH" ]; then
  awk -v new_line="$SESSION_LINE" '
    BEGIN {{ replaced = 0 }}
    /^FASTLANE_SESSION=/ {{
      if (!replaced) {{
        print new_line
        replaced = 1
      }}
      next
    }}
    {{ print }}
    END {{
      if (!replaced) {{
        print new_line
      }}
    }}
  ' "$ENV_PATH" > "$ENV_PATH.tmp"
  mv "$ENV_PATH.tmp" "$ENV_PATH"
else
  printf '%s\\n' "$SESSION_LINE" > "$ENV_PATH"
fi
"""
    _, stdout, stderr = ssh.exec_command(f"bash -lc {shell_quote(update_script)}")
    exit_code = stdout.channel.recv_exit_status()
    stderr_text = stderr.read().decode("utf-8", errors="replace").strip()
    if exit_code != 0:
        raise RuntimeError(f"Failed to update remote .env: {stderr_text or exit_code}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        import paramiko
    except ModuleNotFoundError:
        print(
            "Missing dependency: paramiko. Install it with `pip install -r requirements.txt`.",
            file=sys.stderr,
        )
        return 2

    try:
        config = resolve_config(args)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print(f"Connecting to {config.username}@{config.host}:{config.port} ...")
        ssh.connect(
            hostname=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
        )

        channel = ssh.invoke_shell(width=160, height=40)
        command = f"fastlane spaceauth -u {shell_quote(config.email)}"
        print("Remote fastlane session started. Complete the prompts, including 2FA.")
        output = read_channel_until_exit(channel, command)
        session = extract_fastlane_session(output)
        update_remote_env(ssh, config.remote_env_path, session)
        print(f"FASTLANE_SESSION updated in {config.remote_env_path}")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
