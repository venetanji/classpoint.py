from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


@dataclass(repr=False)
class Profile:
    presenter: dict = field(repr=False)
    class_options: dict
    region: str
    storage_origin: str
    storage_query: str = field(repr=False)

    @property
    def hub_url(self) -> str:
        return f"https://{self.region}.classpoint.app/classsession"


def load_profile(capture: Path, key_log: Path) -> Profile:
    if not capture.is_file():
        raise ValueError("Capture not found. Pass --capture with your decrypted test capture.")
    if not key_log.is_file():
        raise ValueError("TLS key log not found. Pass --key-log with the matching key log.")
    if not shutil.which("tshark"):
        raise ValueError("tshark is not on PATH. Install Wireshark's command-line tools.")

    fields = [
        "tcp.stream",
        "tcp.srcport",
        "tls.handshake.extensions_server_name",
        "http.request.method",
        "http.host",
        "http.request.uri",
        "websocket.payload",
    ]
    command = [
        "tshark", "-r", str(capture), "-o", f"tls.keylog_file:{key_log}",
        "-Y", "tls.handshake.extensions_server_name or http.request or websocket",
        "-T", "json",
    ]
    for name in fields:
        command.extend(["-e", name])
    result = subprocess.run(command, capture_output=True, timeout=60, encoding="utf-8")
    if result.returncode:
        raise ValueError("tshark could not read/decrypt the capture. Check the capture and key-log paths.")
    try:
        packets = [packet["_source"]["layers"] for packet in json.loads(result.stdout)]
    except (ValueError, KeyError) as error:
        raise ValueError("tshark returned an unexpected capture format.") from error

    hosts = {}
    for layers in packets:
        names = layers.get("tls.handshake.extensions_server_name", [])
        if names:
            hosts[layers.get("tcp.stream", [""])[0]] = names[0]

    presenters = {}
    options = {}
    region = None
    storage_origin = None
    storage_query = None
    for layers in packets:
        host = layers.get("http.host", [""])[0]
        if layers.get("http.request.method") == ["PUT"] and re.fullmatch(
            r"cpblob\d+\.blob\.core\.windows\.net", host
        ):
            uri = urlsplit(layers.get("http.request.uri", [""])[0])
            query = parse_qs(uri.query)
            if uri.path.startswith("/slides/") and query.get("sig") and "w" in query.get("sp", [""])[0]:
                storage_origin = f"https://{host}"
                storage_query = uri.query

        for payload in layers.get("websocket.payload", []):
            try:
                chunks = bytes.fromhex(payload.replace(":", "")).decode("utf-8").split("\x1e")
            except (ValueError, UnicodeDecodeError):
                continue
            for chunk in chunks:
                if not chunk:
                    continue
                try:
                    message = json.loads(chunk)
                except ValueError:
                    continue
                arguments = message.get("arguments", [])
                if (
                    message.get("target") == "PresenterStartSlideshow"
                    and layers.get("tcp.srcport") != ["443"]
                    and len(arguments) == 3
                    and isinstance(arguments[0], dict)
                    and isinstance(arguments[2], dict)
                ):
                    user = arguments[0]
                    if user.get("userId") and user.get("email"):
                        presenters[user["userId"]] = {
                            key: user.get(key, "") for key in ["userId", "email", "name", "country"]
                        }
                        options = arguments[2]
                        hub_host = hosts.get(layers.get("tcp.stream", [""])[0], "")
                        if re.fullmatch(r"cpcs(?:-\d+)?\.classpoint\.app", hub_host):
                            region = hub_host.removesuffix(".classpoint.app")
                if message.get("target") == "ClassSessionUpdated" and arguments:
                    candidate = arguments[0].get("cpcsRegion") if isinstance(arguments[0], dict) else None
                    if isinstance(candidate, str) and re.fullmatch(r"cpcs(?:-\d+)?", candidate):
                        region = candidate

    if len(presenters) != 1:
        raise ValueError("Expected exactly one instructor profile in this capture; use your own isolated test capture.")
    if not region or not storage_origin or not storage_query:
        raise ValueError("Missing decrypted class startup or slide-upload settings. Capture both actions with matching TLS keys.")
    class_limit = options.get("classLimit")
    if isinstance(class_limit, bool) or not isinstance(class_limit, int) or class_limit < 1:
        raise ValueError("The capture does not contain a usable class limit.")
    return Profile(
        presenter=next(iter(presenters.values())),
        class_options={
            "classCode": None,
            "classLimit": class_limit,
            "savedClassId": None,
            "isAllowGuests": True,
            "platform": options.get("platform", "vsto"),
        },
        region=region,
        storage_origin=storage_origin,
        storage_query=storage_query,
    )
