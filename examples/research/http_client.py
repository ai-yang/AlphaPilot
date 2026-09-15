"""HTTP-only client example; requires Python 3.10+, no AlphaPilot imports.

ALPHAPILOT_RESEARCH_TOKEN=... python examples/research/http_client.py \
    --dataset baostock_cn:day:backward --output /tmp/research-results
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class ResearchClient:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/") + "/api/v1"
        self.token = token

    def request(self, path: str, body=None, *, key: str | None = None):
        headers = {"Authorization": "Bearer " + self.token}
        if key:
            headers["Idempotency-Key"] = key
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with urlopen(req, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode()}") from exc

    def download(self, artifact: dict, directory: Path) -> Path:
        req = Request(self.base + "/artifacts/" + artifact["artifact_id"] + "/content",
                      headers={"Authorization": "Bearer " + self.token})
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (artifact["artifact_id"] + "-" + Path(artifact["name"]).name)
        checksum = hashlib.sha256()
        with urlopen(req, timeout=30) as source, path.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                checksum.update(chunk)
                target.write(chunk)
        if checksum.hexdigest() != artifact["sha256"]:
            raise RuntimeError("Artifact checksum mismatch")
        return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:19901")
    parser.add_argument("--dataset", required=True, help="ID returned by GET /datasets")
    parser.add_argument("--key", default=None, help="Reuse this intent key on retries")
    parser.add_argument("--output", type=Path, default=Path("research-results"))
    args = parser.parse_args()
    client = ResearchClient(args.base_url, os.environ["ALPHAPILOT_RESEARCH_TOKEN"])
    capabilities = client.request("/capabilities")
    if capabilities["api_version"].split(".")[0] != "1":
        raise RuntimeError("Unsupported API major version")
    expression = "TS_MEAN($close,10)/($close+1e-8)-1"
    validation = client.request("/factors/validate", {"expressions": [expression]})
    if not validation["results"][0]["valid"]:
        raise RuntimeError(validation)
    key = args.key or str(uuid.uuid4())
    print("Idempotency-Key:", key, flush=True)
    job = client.request("/jobs", {"kind": "factor_backtest", "input": {
        "dataset_id": args.dataset, "mode": "single_ic", "factor_source": {
            "type": "inline", "factors": [{"name": "momentum_10", "expression": expression}]}},
        "budget": {"timeout_seconds": 3600}}, key=key)
    job_id = job["job_id"]
    print("Job:", job_id, flush=True)
    while job["status"] not in {"succeeded", "failed", "cancelled", "lost"}:
        time.sleep(2)
        job = client.request("/jobs/" + job_id)
    result = client.request("/jobs/" + job_id + "/result")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    for artifact_id in result["artifact_ids"]:
        artifact = client.request("/artifacts/" + artifact_id)
        print("Downloaded:", client.download(artifact, args.output))


if __name__ == "__main__":
    main()
