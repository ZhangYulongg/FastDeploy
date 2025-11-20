import os
import shutil
import signal
import socket
import subprocess
import sys
import time

import requests

# Read ports from environment variables; use default values if not set
FD_API_PORT = int(os.getenv("FD_API_PORT", 8188))
FD_ENGINE_QUEUE_PORT = int(os.getenv("FD_ENGINE_QUEUE_PORT", 8133))
FD_METRICS_PORT = int(os.getenv("FD_METRICS_PORT", 8233))
FD_CACHE_QUEUE_PORT = int(os.getenv("FD_CACHE_QUEUE_PORT", 8333))

# List of ports to clean before and after tests
PORTS_TO_CLEAN = [FD_API_PORT, FD_ENGINE_QUEUE_PORT, FD_METRICS_PORT, FD_CACHE_QUEUE_PORT]


def is_port_open(host: str, port: int, timeout=1.0):
    """
    Check if a TCP port is open on the given host.
    Returns True if connection succeeds, False otherwise.
    """
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except Exception:
        return False


def kill_process_on_port(port: int):
    """
    Kill processes that are listening on the given port.
    Uses multiple methods to ensure thorough cleanup.
    """
    current_pid = os.getpid()
    parent_pid = os.getppid()

    # Method 1: Use lsof to find processes
    try:
        output = subprocess.check_output(f"lsof -i:{port} -t", shell=True).decode().strip()
        for pid in output.splitlines():
            pid = int(pid)
            if pid in (current_pid, parent_pid):
                print(f"Skip killing current process (pid={pid}) on port {port}")
                continue
            try:
                # First try SIGTERM for graceful shutdown
                os.kill(pid, signal.SIGTERM)
                time.sleep(1)
                # Then SIGKILL if still running
                os.kill(pid, signal.SIGKILL)
                print(f"Killed process on port {port}, pid={pid}")
            except ProcessLookupError:
                pass  # Process already terminated
    except subprocess.CalledProcessError:
        pass

    # Method 2: Use netstat and fuser as backup
    try:
        # Find processes using netstat and awk
        cmd = f"netstat -tulpn 2>/dev/null | grep :{port} | awk '{{print $7}}' | cut -d'/' -f1"
        output = subprocess.check_output(cmd, shell=True).decode().strip()
        for pid in output.splitlines():
            if pid and pid.isdigit():
                pid = int(pid)
                if pid in (current_pid, parent_pid):
                    continue
                try:
                    os.kill(pid, signal.SIGKILL)
                    print(f"Killed process (netstat) on port {port}, pid={pid}")
                except ProcessLookupError:
                    pass
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Method 3: Use fuser if available
    try:
        subprocess.run(f"fuser -k {port}/tcp", shell=True, timeout=5)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        pass


def clean_ports(ports=None):
    """
    Kill all processes occupying the ports
    """
    if ports is None:
        ports = PORTS_TO_CLEAN

    print(f"Cleaning ports: {ports}")
    for port in ports:
        kill_process_on_port(port)

    # Double check and retry if ports are still in use
    time.sleep(2)
    for port in ports:
        if is_port_open("127.0.0.1", port, timeout=0.1):
            print(f"Port {port} still in use, retrying cleanup...")
            kill_process_on_port(port)
            time.sleep(1)


def check_service_health(base_url: str, timeout: int = 3) -> bool:
    """
    Check the health status of a service.

    Args:
        base_url (str): The base URL of the service, e.g. "http://127.0.0.1:8080"
        timeout (int): Request timeout in seconds.

    Returns:
        bool: True if the service is healthy, False otherwise.
    """
    if not base_url.startswith("http"):
        base_url = f"http://{base_url}"
    url = f"{base_url.rstrip('/')}/health"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return True
        else:
            return False
    except Exception:
        return False


def get_registered_number(router_url) -> dict:
    """
    Get the registered model counts by type from the router.

    Args:
        router_url (str): The base URL of the router, e.g. "http://localhost:8080".

    Returns:
        dict: A dictionary containing registered model counts with keys "mixed", "prefill", and "decode".
    """
    if not router_url.startswith("http"):
        router_url = f"http://{router_url}"

    try:
        response = requests.get(f"{router_url}/registered_number", timeout=60)
        registered_numbers = response.json()
        return registered_numbers
    except Exception:
        return {"mixed": 0, "prefill": 0, "decode": 0}


class FDServer:
    def __init__(
        self,
        model_path: str,
        fd_serve_args: list[str],
        env_dict: dict = None,
        max_wait_seconds: int = 300,
    ) -> None:
        print("Pre-test port cleanup...")
        clean_ports()
        print("log dir clean ")
        if os.path.exists("log") and os.path.isdir("log"):
            shutil.rmtree("log")

        self._start_server(model_path, fd_serve_args, env_dict)
        self._wait_for_server(timeout=max_wait_seconds)

    def _start_server(self, model_path: str, fd_serve_args: list[str], env_dict=None) -> None:
        """start FD Server"""
        log_path = "server.log"
        env = os.environ.copy()
        if env_dict is not None:
            env.update(env_dict)
        serve_cmd = [
            sys.executable,
            "-m",
            "fastdeploy.entrypoints.openai.api_server",
            "--model",
            model_path,
            "--port",
            str(FD_API_PORT),
            "--engine-worker-queue-port",
            str(FD_ENGINE_QUEUE_PORT),
            "--metrics-port",
            str(FD_METRICS_PORT),
            "--cache-queue-port",
            str(FD_CACHE_QUEUE_PORT),
            *fd_serve_args,
        ]
        print(f"Launching FDServer with: {' '.join(serve_cmd)}")
        # Start subprocess in new process group
        with open(log_path, "w") as logfile:
            self.process = subprocess.Popen(
                serve_cmd,
                stdout=logfile,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # Enables killing full group via os.killpg
                env=env,
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        print("\n===== Post-test server cleanup... =====")
        clean_ports()
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
            print(f"API server (pid={self.process.pid}) terminated")
        except Exception as e:
            print(f"Failed to terminate API server: {e}")

    def _wait_for_server(self, timeout: int):
        for _ in range(timeout):
            if check_service_health(f"127.0.0.1:{FD_API_PORT}"):
                print(f"API server is up on port {FD_API_PORT}")
                break
            time.sleep(1)
        else:
            print(f"[TIMEOUT] API server failed to start in {timeout} seconds. Cleaning up...")
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except Exception as e:
                print(f"Failed to kill process group: {e}")
            raise RuntimeError(f"API server did not start on port {FD_API_PORT}")
