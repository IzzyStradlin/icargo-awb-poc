import os
import sys
import subprocess

def main():
    ui_mode = os.getenv("UI_MODE", "streamlit").lower()

    if ui_mode == "streamlit":
        # Start Streamlit as a child process
        cmd = [sys.executable, "-m", "streamlit", "run", "app/ui/web_streamlit.py"]
        raise SystemExit(subprocess.call(cmd))

    elif ui_mode == "api":
        # Start FastAPI with uvicorn (launcher)
        cmd = [sys.executable, "-m", "uvicorn", "app.ui.web_fastapi:app", "--reload", "--port", "8080"]
        raise SystemExit(subprocess.call(cmd))

    else:
        print(f"Unrecognized UI_MODE: {ui_mode} (use streamlit|api)")
        raise SystemExit(2)

if __name__ == "__main__":
    main()