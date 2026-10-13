import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_importing_the_p2p_layer_does_not_load_a_dotenv_file(tmp_path):
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("JC_DOTENV_PROBE=loaded\n")
    code = (
        "import os, dotenv.main\n"
        f"dotenv.main.find_dotenv = lambda *a, **k: {str(dotenv_file)!r}\n"
        "import jarviscore.p2p.swim_manager\n"
        "print(os.environ.get('JC_DOTENV_PROBE'), os.environ.get('PYTHON_DOTENV_DISABLED'))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHON_DOTENV_DISABLED"}
    env["PYTHONPATH"] = str(ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)

    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["None", "None"]
