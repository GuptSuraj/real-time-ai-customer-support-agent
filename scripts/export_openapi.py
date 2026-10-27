import json
from pathlib import Path
from support_api.main import app

Path("docs/openapi.json").write_text(json.dumps(app.openapi(), indent=2) + "\n")
