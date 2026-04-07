#!/usr/bin/env python3

import json
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import psutil

if __package__:
    from .local_vpn_proxy import LocalBoundProxy
else:
    from local_vpn_proxy import LocalBoundProxy


def get_repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_vpn_configs_dir():
    repo_root = get_repo_root()
    candidates = [
        os.path.join(repo_root, "ovpn"),
        os.path.join(repo_root, "data", "vpn_configs"),
        os.path.join(repo_root, "scripts", "data", "vpn_configs"),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    return candidates[0]


def create_vpngate_auth_file(auth_path):
    try:
        os.makedirs(os.path.dirname(auth_path), exist_ok=True)
        with open(auth_path, "w", encoding="utf-8") as handle:
            handle.write("vpn\nvpn\n")
        os.chmod(auth_path, 0o600)
        return True
    except OSError:
        return False


class VPNManager:
    def __init__(self):
        self.repo_root = get_repo_root()
        self.scripts_dir = os.path.dirname(os.path.abspath(__file__))
        self.vpn_configs_dir = get_vpn_configs_dir()
        self.logs_dir = os.path.join(self.repo_root, "data", "vpn_logs")
        self.pid_dir = os.path.join(self.repo_root, "data", "vpn_pids")
        self.health_path = os.path.join(self.repo_root, "data", "vpn_health.json")
        self.port_base = 1090
        self.proxy_port_base = 14090
        self.vpn_processes = {}
        self.proxy_processes = {}
        self.failover_configs = []
        self.failover_cursor = 0
        self.primary_config = None
        self.monitor_stop_event = threading.Event()
        self.monitor_thread = None
        self.health_cache = self.load_health_cache()

        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.pid_dir, exist_ok=True)
        os.makedirs(self.vpn_configs_dir, exist_ok=True)
        
        # Network namespace isolation (for crawlers only)
        self.use_namespace = False  # Set to True to isolate VPN to crawler only
        self.namespace_name = "aurora_crawler"

    def can_manage_tun_devices(self):
        return os.geteuid() == 0
    
    def setup_network_namespace(self):
        """
        Create isolated network namespace for crawler (VPN won't affect host PC).
        
        Requires: root privileges
        
        Usage:
            vpn_mgr.use_namespace = True
            vpn_mgr.setup_network_namespace()
            # Crawler will run in isolated namespace with only VPN access
        """
        if not self.can_manage_tun_devices():
            print("   ⚠ Namespace isolation requires root. Skipping namespace setup.")
            return False
        
        try:
            # Create namespace if it doesn't exist
            result = subprocess.run(
                ["ip", "netns", "add", self.namespace_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0 and "already exists" not in result.stderr:
                print(f"   ⚠ Failed to create namespace: {result.stderr}")
                return False
            
            # Create loopback interface in namespace
            subprocess.run(
                ["ip", "netns", "exec", self.namespace_name, "ip", "link", "set", "lo", "up"],
                capture_output=True,
                timeout=5
            )
            
            print(f"   ✓ Network namespace '{self.namespace_name}' ready (crawler traffic isolated)")
            self.use_namespace = True
            return True
        except Exception as e:
            print(f"   ⚠ Namespace setup failed: {e}")
            return False
    
    def get_crawler_command_prefix(self):
        """
        Returns command prefix to run crawler in isolated namespace.
        
        Returns:
            List of command components to prepend to crawler command
            
        Example:
            cmd = vpn_mgr.get_crawler_command_prefix() + ["python3", "crawler.py"]
            subprocess.run(cmd)
        """
        if self.use_namespace:
            return ["ip", "netns", "exec", self.namespace_name]
        return []
    
    def cleanup_network_namespace(self):
        """Delete the isolated network namespace."""
        if not self.can_manage_tun_devices():
            return
        
        try:
            subprocess.run(
                ["ip", "netns", "delete", self.namespace_name],
                capture_output=True,
                timeout=5
            )
        except Exception:
            pass

    def openvpn_command(self):
        return ["openvpn"]
    
    def should_abort_failover(self, reason):
        lowered = (reason or "").lower()
        return "cannot ioctl tunsetiff" in lowered or "operation not permitted" in lowered

    def compatibility_args(self, config_file):
        args = [
            "--pull-filter",
            "ignore",
            "block-outside-dns",
            "--pull-filter",
            "ignore",
            "dhcp-option",
            "--pull-filter",
            "ignore",
            "redirect-gateway",
            "--auth-nocache",
        ]
        metadata = self.parse_config_metadata(config_file)
        if metadata.get("proto") in {"tcp", "tcp-client"}:
            args.extend(
                [
                    "--connect-retry",
                    "2",
                    "5",
                ]
            )
        return args

    def find_vpn_configs(self):
        if not os.path.exists(self.vpn_configs_dir):
            return []
        configs = [name for name in os.listdir(self.vpn_configs_dir) if name.endswith(".ovpn")]
        return sorted(configs, key=self.config_sort_key, reverse=True)

    def load_health_cache(self):
        if not os.path.exists(self.health_path):
            return {}
        try:
            with open(self.health_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save_health_cache(self):
        try:
            with open(self.health_path, "w", encoding="utf-8") as handle:
                json.dump(self.health_cache, handle, indent=2, sort_keys=True)
        except OSError:
            pass

    def classify_health_outcome(self, detail):
        lowered = (detail or "").lower()
        if "initialization sequence completed" in lowered:
            return "success"
        if "cannot ioctl tunsetiff" in lowered or "operation not permitted" in lowered:
            return "permission_error"
        if "authentication failed" in lowered or "auth_failed" in lowered:
            return "auth_failed"
        if "missing support files" in lowered:
            return "missing_support_files"
        if "needs auth" in lowered:
            return "missing_auth"
        if "host resolution failed" in lowered:
            return "resolve_failed"
        if "no route to host" in lowered:
            return "no_route"
        if "cannot open tun" in lowered:
            return "tun_error"
        if "connection refused" in lowered:
            return "connection_refused"
        if "connection timed out" in lowered:
            return "connection_timeout"
        if "tls key negotiation failed" in lowered or "tls handshake failed" in lowered:
            return "tls_error"
        if "fatal openvpn error" in lowered or "options error" in lowered:
            return "fatal_error"
        return "unknown_failure"

    def record_health_result(self, config, detail, success=False):
        outcome = "success" if success else self.classify_health_outcome(detail)
        entry = self.health_cache.setdefault(config, {})
        entry.update(
            {
                "last_outcome": outcome,
                "last_detail": detail,
                "last_checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        if success:
            entry["success_count"] = int(entry.get("success_count", 0)) + 1
            entry["failure_count"] = int(entry.get("failure_count", 0))
        else:
            entry["failure_count"] = int(entry.get("failure_count", 0)) + 1
            entry["success_count"] = int(entry.get("success_count", 0))
        self.save_health_cache()

    def parse_config_metadata(self, config_file):
        config_path = os.path.join(self.vpn_configs_dir, config_file)
        metadata = {
            "proto": "",
            "remote_host": "",
            "remote_port": None,
            "has_inline_ca": False,
            "has_ca_directive": False,
            "has_inline_cert": False,
            "has_inline_key": False,
            "cipher": "",
            "is_vpngate": False,
        }
        try:
            with open(config_path, "r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    lowered = line.lower()
                    if "softether vpn server" in lowered or "packeti x vpn" in lowered or "vpngate" in lowered:
                        metadata["is_vpngate"] = True
                    if lowered.startswith("proto "):
                        parts = line.split()
                        if len(parts) >= 2:
                            metadata["proto"] = parts[1].lower()
                    elif lowered.startswith("remote "):
                        parts = line.split()
                        if len(parts) >= 3:
                            metadata["remote_host"] = parts[1]
                            try:
                                metadata["remote_port"] = int(parts[2])
                            except ValueError:
                                metadata["remote_port"] = None
                    elif lowered.startswith("cipher "):
                        parts = line.split()
                        if len(parts) >= 2:
                            metadata["cipher"] = parts[1].upper()
                    elif lowered == "<ca>":
                        metadata["has_inline_ca"] = True
                    elif lowered.startswith("ca "):
                        metadata["has_ca_directive"] = True
                    elif lowered == "<cert>":
                        metadata["has_inline_cert"] = True
                    elif lowered == "<key>":
                        metadata["has_inline_key"] = True
        except OSError:
            pass
        return metadata

    def system_ca_bundle(self):
        candidates = [
            "/etc/ssl/certs/ca-certificates.crt",
            "/etc/pki/tls/certs/ca-bundle.crt",
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return None

    def preferred_ca_bundle(self):
        repo_ca = os.path.join(self.vpn_configs_dir, "ca.crt")
        if os.path.exists(repo_ca):
            return repo_ca
        return self.system_ca_bundle()

    def preferred_data_ciphers(self, config_file):
        """
        Build cipher list for OpenVPN 2.6+
        
        OpenVPN 2.6 requires explicit cipher declaration.
        VPNGate configs often use old AES-128-CBC, so we must include it.
        """
        metadata = self.parse_config_metadata(config_file)
        
        # Start with modern, secure ciphers
        ciphers = [
            "AES-256-GCM",
            "AES-128-GCM",
            "CHACHA20-POLY1305",
        ]
        
        # VPNGate and old servers often use AES-128-CBC
        # Always add it if it's a VPNGate config or explicitly specified
        legacy_cipher = metadata.get("cipher")
        if metadata.get("is_vpngate") and "AES-128-CBC" not in ciphers:
            ciphers.append("AES-128-CBC")
        
        # Add any other legacy cipher found in the config
        if legacy_cipher and legacy_cipher not in ciphers:
            ciphers.append(legacy_cipher)
        
        return ":".join(ciphers)

    def quick_probe_config(self, config_file, timeout=1):
        metadata = self.parse_config_metadata(config_file)
        host = metadata.get("remote_host")
        port = metadata.get("remote_port")
        proto = metadata.get("proto", "").lower()

        if not host:
            return {"state": "unknown", "reason": "missing remote host"}

        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM if proto == "tcp" else socket.SOCK_DGRAM)
        except socket.gaierror:
            return {"state": "bad", "reason": "host resolution failed"}

        if proto == "tcp" and port:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return {"state": "good", "reason": "tcp endpoint accepted a connection"}
            except socket.timeout:
                return {"state": "bad", "reason": "tcp endpoint timed out"}
            except OSError as exc:
                text = str(exc).lower()
                if "refused" in text:
                    return {"state": "bad", "reason": "tcp endpoint refused the connection"}
                return {"state": "weak", "reason": f"tcp probe failed: {exc}"}

        if addresses:
            return {"state": "weak", "reason": "remote host resolves"}
        return {"state": "unknown", "reason": "probe could not classify the endpoint"}

    def config_sort_key(self, config_file):
        score = 0
        reasons = []
        metadata = self.parse_config_metadata(config_file)
        health = self.health_cache.get(config_file, {})
        missing_support_files = self.required_support_files(config_file)
        requires_auth, auth_file = self.resolve_auth_file(config_file)

        if missing_support_files:
            score -= 1000
            reasons.append("missing support files")
        if requires_auth and not auth_file:
            score -= 600
            reasons.append("needs auth file")
        if metadata["has_inline_ca"] or metadata["has_ca_directive"]:
            score += 50
        elif self.system_ca_bundle():
            score += 10
            reasons.append("can use system CA bundle")
        if metadata["has_inline_cert"] and metadata["has_inline_key"]:
            score += 25

        probe = self.quick_probe_config(config_file)
        if probe["state"] == "good":
            score += 200
            reasons.append(probe["reason"])
        elif probe["state"] == "weak":
            score += 40
            reasons.append(probe["reason"])
        elif probe["state"] == "bad":
            score -= 180
            reasons.append(probe["reason"])

        outcome = health.get("last_outcome")
        success_count = int(health.get("success_count", 0))
        failure_count = int(health.get("failure_count", 0))
        score += success_count * 120
        score -= failure_count * 20

        if outcome == "success":
            score += 400
        elif outcome == "permission_error":
            if self.can_manage_tun_devices():
                score += 140
                reasons.append("previous permission issue is ignored while running as root")
            else:
                score -= 260
        elif outcome == "unknown_failure":
            score -= 140
        elif outcome in {"connection_timeout", "connection_refused", "resolve_failed"}:
            score -= 220
        elif outcome in {"tls_error", "auth_failed", "fatal_error", "missing_support_files", "missing_auth", "no_route"}:
            score -= 280

        return (score, config_file.lower())

    def check_openvpn_installed(self):
        try:
            subprocess.run(
                ["openvpn", "--version"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def inspect_auth_requirement(self, config_file):
        config_path = os.path.join(self.vpn_configs_dir, config_file)
        requires_auth = False
        referenced_file = None

        try:
            with open(config_path, "r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or line.startswith(";"):
                        continue
                    if line.startswith("auth-user-pass"):
                        requires_auth = True
                        parts = line.split(maxsplit=1)
                        if len(parts) == 2:
                            referenced_file = parts[1].strip()
                        break
        except OSError:
            pass

        return requires_auth, referenced_file

    def resolve_auth_file(self, config_file):
        requires_auth, referenced_file = self.inspect_auth_requirement(config_file)
        metadata = self.parse_config_metadata(config_file)
        if not requires_auth and metadata.get("is_vpngate"):
            requires_auth = True

        if not requires_auth:
            return False, None

        per_config_auth = os.path.join(self.vpn_configs_dir, f".auth_{config_file}.txt")
        if os.path.exists(per_config_auth):
            return True, per_config_auth

        if metadata.get("is_vpngate"):
            if create_vpngate_auth_file(per_config_auth):
                return True, per_config_auth

        if referenced_file:
            referenced_path = os.path.join(self.vpn_configs_dir, referenced_file)
            if os.path.exists(referenced_path):
                return True, referenced_path

        shared_auth = os.path.join(self.vpn_configs_dir, "auth.txt")
        if os.path.exists(shared_auth):
            return True, shared_auth

        return True, None

    def secure_auth_file(self, auth_file):
        if not auth_file or not os.path.exists(auth_file):
            return
        try:
            os.chmod(auth_file, 0o600)
        except OSError:
            pass

    def required_support_files(self, config_file):
        config_path = os.path.join(self.vpn_configs_dir, config_file)
        required_files = []
        directives = {"ca", "cert", "key", "tls-auth", "tls-crypt", "pkcs12", "secret"}

        try:
            with open(config_path, "r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or line.startswith(";"):
                        continue
                    parts = line.split()
                    if not parts:
                        continue
                    directive = parts[0]
                    if directive == "tlsauth":
                        directive = "tls-auth"
                    if directive in directives and len(parts) >= 2:
                        required_files.append(parts[1])
        except OSError:
            return []

        missing = []
        for filename in required_files:
            full_path = os.path.join(self.vpn_configs_dir, filename)
            if not os.path.exists(full_path):
                missing.append(filename)
        return missing

    def _pid_path(self, port):
        return os.path.join(self.pid_dir, f"vpn_{port}.pid")

    def _log_path(self, config_file):
        safe_name = config_file.replace(os.sep, "_")
        return os.path.join(self.logs_dir, f"{safe_name}.log")

    def _device_name(self, port):
        return f"aur{port}"

    def _proxy_port(self, port):
        return self.proxy_port_base + (port - self.port_base)

    def _read_log_tail(self, log_path, max_bytes=12000):
        if not os.path.exists(log_path):
            return ""
        try:
            with open(log_path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - max_bytes))
                return handle.read().replace(b"\x00", b"\n").decode("utf-8", errors="ignore")
        except OSError:
            return ""

    def truncate_log(self, log_path):
        try:
            with open(log_path, "w", encoding="utf-8"):
                pass
        except OSError:
            pass

    def has_completed_initialization(self, info):
        return "Initialization Sequence Completed" in self._read_log_tail(info["log_path"])

    def get_recent_failure_reason(self, info):
        tail = self._read_log_tail(info["log_path"])
        if not tail:
            return None

        patterns = [
            ("device or resource busy", "device busy"),
            ("cannot ioctl tunsetiff", "permission error"),
            ("operation not permitted", "permission error"),
            ("auth_failed", "authentication failed"),
            ("cannot open tun", "cannot open TUN device"),
            ("connection refused", "connection refused"),
            ("tls key negotiation failed", "TLS key negotiation failed"),
            ("tls handshake failed", "TLS handshake failed"),
            ("connection timed out", "connection timed out"),
            ("no route to host", "no route to host"),
            ("inactivity timeout", "inactivity timeout"),
            ("resolve: cannot resolve host address", "host resolution failed"),
            ("exiting due to fatal error", "fatal OpenVPN error"),
            ("options error", "OpenVPN options error"),
        ]

        last_match = None
        for line in tail.splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            normalized = cleaned.lower()
            for needle, label in patterns:
                if needle in normalized:
                    last_match = f"{label}: {cleaned}"
        return last_match

    def cleanup_stale_runtime(self):
        for proxy in self.proxy_processes.values():
            proxy.stop()
        self.proxy_processes.clear()

        for pid_file in Path(self.pid_dir).glob("vpn_*.pid"):
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pid = None

            if pid and psutil.pid_exists(pid):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
                time.sleep(0.2)
                if psutil.pid_exists(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass

            try:
                pid_file.unlink()
            except OSError:
                pass

        for index in range(0, 256):
            device_name = self._device_name(self.port_base + index)
            subprocess.run(
                ["ip", "link", "delete", device_name],
                capture_output=True,
                text=True,
            )

        self.vpn_processes.clear()

    def get_interface_addr_info(self, interface_name):
        try:
            result = subprocess.run(
                ["ip", "-j", "addr", "show", "dev", interface_name],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            payload = json.loads(result.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            return None

        for entry in payload:
            for addr_info in entry.get("addr_info", []):
                if addr_info.get("family") == "inet":
                    return {
                        "local": addr_info.get("local"),
                        "peer": addr_info.get("peer"),
                    }
        return {"local": None, "peer": None}

    def get_interface_ipv4(self, interface_name):
        return self.get_interface_addr_info(interface_name).get("local")

    def route_table_id(self, info):
        return 20000 + int(info["port"])

    def setup_policy_route(self, info):
        source_ip = info.get("tunnel_ip")
        peer_ip = info.get("peer_ip")
        device = info.get("device")
        if not source_ip or not peer_ip or not device:
            return False

        table_id = self.route_table_id(info)
        info["route_table"] = table_id

        route_result = subprocess.run(
            ["ip", "route", "replace", "default", "via", peer_ip, "dev", device, "table", str(table_id)],
            capture_output=True,
            text=True,
        )
        if route_result.returncode != 0:
            print(
                f"   Failed to install default route for {info['config']}: "
                f"{route_result.stderr.strip() or route_result.stdout.strip()}"
            )
            return False

        rule_result = subprocess.run(
            ["ip", "rule", "add", "from", f"{source_ip}/32", "table", str(table_id), "priority", str(table_id)],
            capture_output=True,
            text=True,
        )
        if rule_result.returncode != 0 and "file exists" not in (rule_result.stderr or "").lower():
            print(
                f"   Failed to install source rule for {info['config']}: "
                f"{rule_result.stderr.strip() or rule_result.stdout.strip()}"
            )
            return False

        print(f"   Installed crawler-only VPN route for {info['config']} via {device} ({source_ip} -> {peer_ip})")
        return True

    def cleanup_policy_route(self, info):
        source_ip = info.get("tunnel_ip")
        table_id = info.get("route_table")
        if not source_ip or table_id is None:
            return

        subprocess.run(
            ["ip", "rule", "del", "from", f"{source_ip}/32", "table", str(table_id), "priority", str(table_id)],
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["ip", "route", "flush", "table", str(table_id)],
            capture_output=True,
            text=True,
        )

    def start_proxy_for_connection(self, config, info):
        if config in self.proxy_processes:
            return True

        source_ip = info.get("tunnel_ip")
        if not source_ip:
            return False

        listen_port = self._proxy_port(info["port"])

        proxy = LocalBoundProxy(source_ip=source_ip, listen_port=listen_port)
        try:
            listen_port = proxy.start()
        except OSError as exc:
            print(f"   Failed to start local proxy for {config}: {exc}")
            return False

        self.proxy_processes[config] = proxy
        info["proxy_url"] = f"http://127.0.0.1:{listen_port}"
        print(f"   Local VPN proxy ready for {config}: {info['proxy_url']} via {source_ip}")
        return True

    def start_vpn(self, config_file, port):
        config_path = os.path.join(self.vpn_configs_dir, config_file)
        if not os.path.exists(config_path):
            print(f"   Skipped missing config: {config_file}")
            self.record_health_result(config_file, "missing config file")
            return False

        missing_support_files = self.required_support_files(config_file)
        if missing_support_files:
            detail = f"missing support files ({', '.join(missing_support_files)})"
            print(f"   Skipped {config_file}: {detail}")
            self.record_health_result(config_file, detail)
            return False

        requires_auth, auth_file = self.resolve_auth_file(config_file)
        if requires_auth and not auth_file:
            detail = "needs auth and no auth file was found"
            print(f"   Skipped {config_file}: {detail}.")
            self.record_health_result(config_file, detail)
            return False
        if auth_file:
            self.secure_auth_file(auth_file)

        pid_path = self._pid_path(port)
        log_path = self._log_path(config_file)
        self.truncate_log(log_path)
        metadata = self.parse_config_metadata(config_file)
        ca_bundle = None if metadata["has_inline_ca"] else self.preferred_ca_bundle()

        cmd = [
            *self.openvpn_command(),
            "--cd",
            self.vpn_configs_dir,
            "--config",
            config_path,
            "--dev-type",
            "tun",
            "--dev",
            self._device_name(port),
            "--log",
            log_path,
            "--daemon",
            "--writepid",
            pid_path,
            "--script-security",
            "2",
        ]
        cmd.extend(self.compatibility_args(config_file))
        cmd.extend(["--data-ciphers", self.preferred_data_ciphers(config_file)])
        if requires_auth and auth_file:
            cmd.extend(["--auth-user-pass", auth_file])
        if ca_bundle:
            cmd.extend(["--ca", ca_bundle])
            print(f"   {config_file} will use CA verification from {ca_bundle}")

        try:
            print(f"   Starting VPN tunnel: {config_file}")
            # FIXED: Use Popen() for background process instead of run()
            # With --daemon flag, OpenVPN should fork and return immediately
            # But subprocess.run() waits for process completion, which blocks indefinitely
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            
            # Give OpenVPN a moment to daemonize and check for immediate errors
            time.sleep(0.5)
            
            # Check if process exited immediately (indicates an error)
            poll_result = process.poll()
            if poll_result is not None and poll_result != 0:
                # Process exited with error before daemonizing
                error_tail = self._read_log_tail(log_path, 500) or f"OpenVPN exited with code {poll_result}"
                print(f"   Failed to start {config_file}: {error_tail}")
                self.record_health_result(config_file, error_tail)
                return False
            
            # Check if PID file was created (indicates daemon started)
            time.sleep(0.5)
            if not os.path.exists(pid_path):
                # Daemon didn't create PID file
                error_tail = self._read_log_tail(log_path, 500) or "OpenVPN daemon did not create PID file"
                print(f"   Failed to start {config_file}: {error_tail}")
                self.record_health_result(config_file, error_tail)
                return False

            self.vpn_processes[config_file] = {
                "port": port,
                "config": config_file,
                "status": "starting",
                "requires_auth": requires_auth,
                "auth_file": auth_file,
                "pid_path": pid_path,
                "log_path": log_path,
                "device": self._device_name(port),
                "tunnel_ip": None,
                "peer_ip": None,
                "route_table": None,
                "proxy_url": None,
            }
            return True
        except Exception as exc:
            print(f"   Failed to start {config_file}: {exc}")
            self.record_health_result(config_file, str(exc))
            return False

    def stop_vpn(self, config, remove=False):
        info = self.vpn_processes.get(config)
        if not info:
            return

        self.cleanup_policy_route(info)
        proxy = self.proxy_processes.pop(config, None)
        if proxy:
            proxy.stop()

        pid_path = info["pid_path"]
        pid = None
        if os.path.exists(pid_path):
            try:
                with open(pid_path, "r", encoding="utf-8") as handle:
                    pid = int(handle.read().strip())
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pid = None

        if pid:
            deadline = time.time() + 5
            while time.time() < deadline and psutil.pid_exists(pid):
                time.sleep(0.1)
            if psutil.pid_exists(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

        info["status"] = "dead"
        info["proxy_url"] = None
        device = info.get("device")
        if device:
            subprocess.run(
                ["ip", "link", "delete", device],
                capture_output=True,
                text=True,
            )
        if os.path.exists(pid_path):
            try:
                os.remove(pid_path)
            except OSError:
                pass
        if remove:
            self.vpn_processes.pop(config, None)

    def wait_for_activation(self, config, timeout=120, poll_interval=2):
        deadline = time.time() + timeout
        start_time = time.time()
        print(f"   Waiting for {config} to initialize (up to {timeout}s)...")
        while time.time() < deadline and not self.monitor_stop_event.is_set():
            active = self.check_vpn_status()
            if config in active:
                elapsed = time.time() - start_time
                print(f"   ✓ {config} is active (took {elapsed:.1f}s)")
                return True, None

            info = self.vpn_processes.get(config)
            if not info:
                return False, "VPN process disappeared"

            reason = self.get_recent_failure_reason(info)
            if reason:
                return False, reason
            
            # Show progress every 10 seconds
            elapsed = time.time() - start_time
            if int(elapsed) % 10 == 0:
                status = info.get("status", "unknown")
                print(f"   ... {config} still initializing ({elapsed:.0f}s, status: {status})")
            
            self.monitor_stop_event.wait(poll_interval)
        if self.monitor_stop_event.is_set():
            return False, "VPN startup cancelled"
        info = self.vpn_processes.get(config)
        if info:
            reason = self.get_recent_failure_reason(info)
            if reason:
                return False, reason
        return False, "did not become active before the startup wait expired"

    def start_failover_chain(self):
        if not self.can_manage_tun_devices():
            print("   VPN startup needs root privileges to create TUN devices.")
            print("   Run Aurora with: sudo python3 app.py")
            return None

        self.failover_configs = self.find_vpn_configs()
        self.failover_cursor = 0
        self.primary_config = None
        if self.failover_configs:
            print("   Ranked VPN order:")
            for config in self.failover_configs[:8]:
                probe = self.quick_probe_config(config)
                health = self.health_cache.get(config, {})
                summary = probe["reason"]
                if health.get("last_outcome"):
                    summary = f"{summary}; last={health['last_outcome']}"
                if health.get("last_detail"):
                    summary = f"{summary} ({health['last_detail'][:120]})"
                print(f"      {config} -> {summary}")
        return self.start_next_failover_candidate()

    def start_next_failover_candidate(self):
        while self.failover_cursor < len(self.failover_configs):
            config = self.failover_configs[self.failover_cursor]
            port = self.port_base + self.failover_cursor
            self.failover_cursor += 1

            if not self.start_vpn(config, port):
                continue

            activated, reason = self.wait_for_activation(config)
            if activated:
                self.primary_config = config
                return config

            print(f"   {config} failed: {reason}. Trying next VPN config...")
            self.record_health_result(config, reason)
            self.stop_vpn(config, remove=True)
            if self.should_abort_failover(reason):
                print("   VPN startup cannot continue without root privileges for TUN/TAP.")
                print("   Run Aurora with: sudo python3 app.py")
                break

        self.primary_config = None
        return None

    def check_vpn_status(self):
        active = []

        for config, info in self.vpn_processes.items():
            pid_path = info["pid_path"]
            if not os.path.exists(pid_path):
                info["status"] = "dead"
                continue

            try:
                with open(pid_path, "r", encoding="utf-8") as handle:
                    pid = int(handle.read().strip())
            except (OSError, ValueError):
                info["status"] = "unknown"
                continue

            if not psutil.pid_exists(pid):
                info["status"] = "dead"
                continue

            info["pid"] = pid
            if not self.has_completed_initialization(info):
                info["status"] = "starting"
                continue

            addr_info = self.get_interface_addr_info(info["device"])
            tunnel_ip = addr_info.get("local")
            if not tunnel_ip:
                info["status"] = "starting"
                continue

            info["tunnel_ip"] = tunnel_ip
            info["peer_ip"] = addr_info.get("peer")
            if not info.get("route_table") and not self.setup_policy_route(info):
                info["status"] = "error"
                continue
            info["status"] = "active"
            self.start_proxy_for_connection(config, info)
            if self.health_cache.get(config, {}).get("last_outcome") != "success":
                self.record_health_result(config, "Initialization Sequence Completed", success=True)
            active.append(config)

        return active

    def list_vpn_connections(self):
        if not self.vpn_processes:
            print("No VPN processes are registered.")
            return

        print(f"\n{'Config':<35} {'Auth':<8} {'Status':<12} {'Tunnel IP':<16} {'Proxy'}")
        print("=" * 120)
        for config, info in self.vpn_processes.items():
            auth = "yes" if info.get("requires_auth") else "no"
            status = info.get("status", "unknown")
            tunnel_ip = info.get("tunnel_ip") or "-"
            proxy_url = info.get("proxy_url") or "-"
            print(f"{config:<35} {auth:<8} {status:<12} {tunnel_ip:<16} {proxy_url}")

    def start_all(self):
        configs = self.find_vpn_configs()
        if not configs:
            print(f"No VPN configs found in {self.vpn_configs_dir}")
            return []

        if not self.can_manage_tun_devices():
            print("   VPN startup needs root privileges to create TUN devices.")
            print("   Run Aurora with: sudo python3 app.py")
            return []

        self.cleanup_stale_runtime()

        active_configs = []
        attempted = 0
        for index, config in enumerate(configs):
            if self.monitor_stop_event.is_set():
                break
            port = self.port_base + index
            attempted += 1
            if not self.start_vpn(config, port):
                continue

            activated, reason = self.wait_for_activation(config, timeout=35, poll_interval=2)
            if activated:
                active_configs.append(config)
                print(f"   {config} is active and ready for crawler proxy rotation.")
                continue

            print(f"   {config} failed: {reason}. Skipping it.")
            self.record_health_result(config, reason)
            self.stop_vpn(config, remove=True)

        latest_active = self.check_vpn_status()
        if latest_active:
            print(f"Started {len(latest_active)} working VPN tunnel(s) out of {attempted} attempted config(s).")
        return latest_active

    def start_first_available(self):
        configs = self.find_vpn_configs()
        if not configs:
            print(f"No VPN configs found in {self.vpn_configs_dir}")
            return None

        for index, config in enumerate(configs):
            port = self.port_base + index
            if not self.start_vpn(config, port):
                continue
            time.sleep(8)
            active = self.check_vpn_status()
            if config in active:
                return config

        return None

    def stop_all_vpns(self):
        print("Stopping VPN connections...")
        self.monitor_stop_event.set()

        for _, info in self.vpn_processes.items():
            self.cleanup_policy_route(info)

        for _, proxy in self.proxy_processes.items():
            proxy.stop()
        self.proxy_processes.clear()

        for _, info in self.vpn_processes.items():
            pid_path = info["pid_path"]
            if not os.path.exists(pid_path):
                continue

            try:
                with open(pid_path, "r", encoding="utf-8") as handle:
                    pid = int(handle.read().strip())
                os.kill(pid, signal.SIGTERM)
            except Exception:
                continue

    def generate_proxy_list(self):
        active_configs = self.check_vpn_status()
        proxies = []
        for config in active_configs:
            info = self.vpn_processes.get(config, {})
            if info.get("status") == "active" and info.get("proxy_url"):
                proxies.append(info["proxy_url"])
        return "|".join(proxies)

    def start_monitoring(self, interval=5):
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        def _monitor():
            previous_active = set()
            while not self.monitor_stop_event.is_set():
                active = set(self.check_vpn_status())
                if active != previous_active:
                    print(f"VPN status update: {len(active)} active tunnel(s).")
                    previous_active = active
                time.sleep(interval)

        self.monitor_thread = threading.Thread(target=_monitor, daemon=True)
        self.monitor_thread.start()

    def print_banner(self):
        print(
            """
╔════════════════════════════════════════════════════════════════════╗
║                  AURORA SEARCH VPN MANAGER                        ║
╚════════════════════════════════════════════════════════════════════╝
"""
        )

    def main(self):
        self.print_banner()

        if not self.check_openvpn_installed():
            print("OpenVPN is not installed or not available on PATH.")
            return False

        configs = self.find_vpn_configs()
        if not configs:
            print(f"No VPN configs found in {self.vpn_configs_dir}")
            return False

        print(f"Found {len(configs)} VPN config(s) in {self.vpn_configs_dir}")
        choice = input("Start all VPN configs? (y/n): ").strip().lower()
        if choice != "y":
            print("Skipped VPN startup.")
            return False

        active = self.start_all()
        self.list_vpn_connections()

        if not active:
            print("No VPN tunnels became active.")
            return False

        print("\nAurora can rotate across local proxies bound to the active VPN tunnel(s).")
        proxy_list = self.generate_proxy_list()
        if proxy_list:
            print("Local rotating proxies:")
            for proxy in proxy_list.split("|"):
                print(f"  {proxy}")
        print("Press Ctrl+C to stop the VPN manager.")

        self.start_monitoring()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping VPN manager...")
            self.stop_all_vpns()
            return True


if __name__ == "__main__":
    VPNManager().main()
