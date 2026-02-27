import os
import sys
import subprocess

def main():
    ui_mode = os.getenv("UI_MODE", "streamlit").lower()

    if ui_mode == "streamlit":
        # Avvia Streamlit come processo figlio
        cmd = [sys.executable, "-m", "streamlit", "run", "app/ui/web_streamlit.py"]
        raise SystemExit(subprocess.call(cmd))

    elif ui_mode == "api":
        # Avvia FastAPI con uvicorn (launcher)
        cmd = [sys.executable, "-m", "uvicorn", "app.ui.web_fastapi:app", "--reload", "--port", "8080"]
        raise SystemExit(subprocess.call(cmd))

    else:
        print(f"UI_MODE non riconosciuto: {ui_mode} (usa streamlit|api)")
        raise SystemExit(2)

if __name__ == "__main__":
    main()