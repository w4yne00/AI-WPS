import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Production never returns silent mock results; tests opt in explicitly.
os.environ.setdefault("AI_WPS_ENABLE_MOCK_PROVIDER", "1")
