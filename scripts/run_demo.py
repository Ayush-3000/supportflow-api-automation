"""Run two independent HTTP services. Stop both with Ctrl+C."""

import os
import subprocess
import sys
import time
from urllib.request import urlopen


def main():
    env = os.environ.copy()
    env["SUPPORTFLOW_MODE"] = "demo"
    env["SUPPORTFLOW_API_KEY"] = "demo-local-key"
    env["SUPPORTFLOW_WEBHOOK_SECRET"] = "demo-webhook-secret"
    env["SUPPORTFLOW_DB"] = env.get("SUPPORTFLOW_DEMO_DB", "runtime/supportflow-demo.sqlite")
    env["HELPDESK_URL"] = "http://127.0.0.1:8001"
    env["SHOPIFY_ACCESS_TOKEN"] = "demo-order-token"
    env["HELPDESK_API_KEY"] = "demo-helpdesk-token"
    env["SUPPORTFLOW_DRAFTER"] = "rules"
    mock = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "supportflow.mock_api:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
        ],
        env=env,
    )
    web = None
    try:
        for _ in range(50):
            if mock.poll() is not None:
                raise RuntimeError("Demo provider API could not start; check port 8001")
            try:
                with urlopen("http://127.0.0.1:8001/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Demo provider API did not become ready")
        print(
            "\nSupportFlow: http://127.0.0.1:8000\nOperator key: demo-local-key\nFictional data / no external messages\n",
            flush=True,
        )
        web = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "supportflow.app:create_app",
                "--factory",
                "--host",
                env.get("SUPPORTFLOW_HOST", "127.0.0.1"),
                "--port",
                "8000",
            ],
            env=env,
        )
        web.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for process in [web, mock]:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    main()
