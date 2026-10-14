"""Start the web server: python3.12 run_web.py [--port 8000]

Adds the project venv's site-packages to sys.path, so it also works when the
interpreter is launched outside the venv (e.g. from an IDE preview runner).
"""

import glob
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [ROOT, *glob.glob(os.path.join(ROOT, ".venv/lib/python3*/site-packages"))]

import uvicorn  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8000
    uvicorn.run("web.server:app", host="127.0.0.1", port=port)
