import uvicorn
import os
import sys

# Ensure app is in path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)

# Add project root so 'trading_bot' package is importable from the backend venv
project_root = os.path.dirname(backend_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
