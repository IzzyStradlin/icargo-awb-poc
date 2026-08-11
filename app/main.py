import os
import sys
import subprocess


def _run_child(cmd: list[str]) -> int:
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        # Match shell conventions for interrupted process (SIGINT).
        return 130


def main():
    ui_mode = os.getenv("UI_MODE", "streamlit").lower()

    if ui_mode == "streamlit":
        # Start Streamlit as a child process
        cmd = [sys.executable, "-m", "streamlit", "run", "app/ui/web_streamlit.py"]
        raise SystemExit(_run_child(cmd))

    elif ui_mode == "api":
        # Start FastAPI with uvicorn (launcher)
        cmd = [sys.executable, "-m", "uvicorn", "app.ui.web_fastapi:app", "--reload", "--port", "8080"]
        raise SystemExit(_run_child(cmd))

    else:
        print(f"Unrecognized UI_MODE: {ui_mode} (use streamlit|api)")
        raise SystemExit(2)

if __name__ == "__main__":
    main()