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


def test_swim_metrics_stay_on_but_never_print(capsys):
    """SWIM printed a "Metrics Report" dict to stdout every minute in every mesh.
    Lifeguard reads the metrics, so they stay; only the printing reporter stops."""
    from swim.metrics.collector import MetricsCollector

    from jarviscore.p2p.swim_manager import _quiet_swim_metrics

    class Node:
        metrics_collector = MetricsCollector("127.0.0.1:7946")

    collector = Node.metrics_collector
    collector._running = True
    _quiet_swim_metrics(Node)
    collector.record_gauge(name="member_count", value=3)

    assert collector._running is False, "the reporting loop exits"
    assert collector.report_metrics() == {}
    assert collector._metrics["member_count"], "metrics are still recorded for Lifeguard"
    assert "Metrics Report" not in capsys.readouterr().out
    _quiet_swim_metrics(type("Bare", (), {"metrics_collector": None}))
