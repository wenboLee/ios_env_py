# Python Script Project

This CLI connects to a remote host over SSH, runs `fastlane spaceauth -u <email>`,
lets you complete the interactive 2FA flow, then updates `FASTLANE_SESSION` in the
remote `$HOME/workspace/.env`.

## Install

```bash
pip install -r requirements.txt
```

## Package Executables

This project can be packaged into standalone executables with `PyInstaller`.

Build on the target operating system:

- Windows builds `.exe` on Windows
- macOS builds the macOS executable on macOS

Run:

```bash
python scripts/build.py
```

Optional arguments:

```bash
python scripts/build.py --clean
python scripts/build.py --name spaceauth-cli
python scripts/build.py --onefile
```

Build output is written to `dist/<platform>/`.

## Configure

Copy `spaceauth.config.example.json` to `spaceauth.config.json` and fill in:

- SSH host/IP
- SSH port
- SSH username
- SSH password
- Apple ID email
- Remote `.env` path if you do not want the default `$HOME/workspace/.env`

## Run

```bash
python main.py
```

You can also override config values on the command line:

```bash
python main.py --host 10.0.0.8 --port 22 --username admin --email your_email@example.com
```
