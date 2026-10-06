"""Submit and track the extraction fine-tuning job on Azure OpenAI.

    python scripts/finetune/azure_finetune.py estimate [--model M] [--epochs 3]
    python scripts/finetune/azure_finetune.py upload
    python scripts/finetune/azure_finetune.py create --confirm-cost-usd 1.07 [--model M]
    python scripts/finetune/azure_finetune.py status [--wait]
    python scripts/finetune/azure_finetune.py cancel

`estimate` is offline. The other commands call the Azure OpenAI resource named by
DOCINTEL_FINETUNE_AZURE_ENDPOINT and DOCINTEL_FINETUNE_AZURE_API_KEY (falling back to the
DOCINTEL_AZURE_OPENAI_* values), read from the environment or .env and never printed.
`create` refuses to submit unless the estimate is under the cap ($30 by default) and
--confirm-cost-usd is at least the estimate. Job state (file and job IDs, status, trained
tokens, cost) is kept in evals/finetune/job.json; no endpoint or key is written there.
Deploying the fine-tuned model is done in the Azure portal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from azure_env import azure_credentials  # noqa: E402

from app.finetune.estimate import (  # noqa: E402
    DEFAULT_COST_CAP_USD,
    check_budget,
    estimate_training,
    training_prices,
)

DATA = ROOT / "evals" / "finetune"
STATE = DATA / "job.json"
DEFAULT_MODEL = "gpt-4.1-nano-2025-04-14"
DEFAULT_EPOCHS = 3
DEFAULT_SEED = 20261006
SUFFIX = "docintel-extract"


def _client() -> Any:
    from openai import AzureOpenAI

    endpoint, key, version = azure_credentials("finetune")
    return AzureOpenAI(azure_endpoint=endpoint, api_key=key, api_version=version)


def _records(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (DATA / name).read_text().splitlines() if line.strip()]


def _sha256(name: str) -> str:
    return hashlib.sha256((DATA / name).read_bytes()).hexdigest()


def _load_state() -> dict[str, Any]:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def _save_state(state: dict[str, Any]) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(STATE)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _estimate(model: str, epochs: int) -> Any:
    import tiktoken

    prices = training_prices(ROOT / "config")
    if model not in prices:
        raise SystemExit(f"no training price for {model} in config/pricing.yaml (fine_tuning)")
    return estimate_training(
        _records("train.jsonl"), model, epochs, prices[model], tiktoken.get_encoding("o200k_base")
    )


def cmd_estimate(args: argparse.Namespace) -> int:
    est = _estimate(args.model, args.epochs)
    print(
        f"{est.examples} training examples, {est.tokens_per_epoch:,} tokens per epoch "
        f"(largest example {est.max_example_tokens:,}), {est.epochs} epochs\n"
        f"billed training tokens ~{est.billed_tokens:,} x ${est.price_per_1m_tokens}/1M "
        f"= ~${est.cost_usd:.2f} for {est.base_model} (cap ${args.cap_usd:.2f})\n"
        "Validation tokens are not billed. Prices are illustrative: check Azure's price list."
    )
    return 0


def _wait_processed(client: Any, file_id: str, timeout_s: float = 900) -> str:
    deadline = time.monotonic() + timeout_s
    while True:
        status = client.files.retrieve(file_id).status
        if status in ("processed", "error", "deleted") or time.monotonic() > deadline:
            return str(status)
        time.sleep(10)


def cmd_upload(args: argparse.Namespace) -> int:
    state = _load_state()
    files = state.setdefault("files", {})
    client = _client()
    for name in ("train.jsonl", "validation.jsonl"):
        digest = _sha256(name)
        known = files.get(name)
        if known and known["sha256"] == digest and not args.force:
            print(f"{name}: already uploaded as {known['id']}")
            continue
        with (DATA / name).open("rb") as fh:
            uploaded = client.files.create(file=fh, purpose="fine-tune")
        status = _wait_processed(client, uploaded.id)
        files[name] = {"id": uploaded.id, "sha256": digest, "status": status, "at": _now()}
        _save_state(state)
        print(f"{name}: uploaded as {uploaded.id} ({status})")
        if status != "processed":
            return 1
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    state = _load_state()
    if state.get("job", {}).get("id") and not args.force:
        raise SystemExit(f"job {state['job']['id']} already exists; use status, or --force")
    files = state.get("files", {})
    for name in ("train.jsonl", "validation.jsonl"):
        if name not in files or files[name]["sha256"] != _sha256(name):
            raise SystemExit(f"{name} is not uploaded or changed since upload: run upload")
    est = _estimate(args.model, args.epochs)
    try:
        check_budget(est.cost_usd, args.confirm_cost_usd, args.cap_usd)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    client = _client()
    job = client.fine_tuning.jobs.create(
        model=args.model,
        training_file=files["train.jsonl"]["id"],
        validation_file=files["validation.jsonl"]["id"],
        hyperparameters={"n_epochs": args.epochs},
        suffix=SUFFIX,
        seed=DEFAULT_SEED,
    )
    manifest = json.loads((DATA / "manifest.json").read_text())
    state["job"] = {
        "id": job.id,
        "base_model": args.model,
        "epochs": args.epochs,
        "seed": DEFAULT_SEED,
        "suffix": SUFFIX,
        "prompt": manifest["prompt"],
        "dataset": {n: manifest["files"][n]["sha256"] for n in manifest["files"]},
        "estimate": est.to_dict(),
        "confirmed_cost_usd": args.confirm_cost_usd,
        "status": job.status,
        "created_at": _now(),
    }
    _save_state(state)
    print(f"created job {job.id} ({job.status}) on {args.model}")
    return 0


def _refresh(client: Any, state: dict[str, Any]) -> dict[str, Any]:
    info = state["job"]
    job = client.fine_tuning.jobs.retrieve(info["id"])
    info["status"] = job.status
    info["fine_tuned_model"] = job.fine_tuned_model
    info["trained_tokens"] = job.trained_tokens
    info["error"] = job.error.message if getattr(job, "error", None) and job.error.message else None
    if job.finished_at:
        info["finished_at"] = datetime.fromtimestamp(job.finished_at, UTC).isoformat()
    if job.trained_tokens:
        price = training_prices(ROOT / "config")[info["base_model"]]
        info["cost_usd_at_listed_price"] = round(job.trained_tokens / 1_000_000 * price, 4)
    events = client.fine_tuning.jobs.list_events(fine_tuning_job_id=info["id"], limit=10)
    info["recent_events"] = [e.message for e in reversed(list(events.data))]
    _save_state(state)
    return info


def cmd_status(args: argparse.Namespace) -> int:
    state = _load_state()
    if not state.get("job"):
        raise SystemExit("no job yet: run create")
    client = _client()
    while True:
        info = _refresh(client, state)
        print(f"{_now()}  {info['id']}  {info['status']}  trained_tokens={info['trained_tokens']}")
        for message in info["recent_events"][-3:]:
            print(f"    {message}")
        if not args.wait or info["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(60)
    if info.get("fine_tuned_model"):
        print(f"fine-tuned model: {info['fine_tuned_model']} (deploy it in the Azure portal)")
    return 0 if info["status"] != "failed" else 1


def cmd_cancel(args: argparse.Namespace) -> int:
    state = _load_state()
    if not state.get("job"):
        raise SystemExit("no job to cancel")
    client = _client()
    client.fine_tuning.jobs.cancel(state["job"]["id"])
    print(f"cancel requested; {_refresh(client, state)['status']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("estimate", "create"):
        p = sub.add_parser(name)
        p.add_argument("--model", default=DEFAULT_MODEL)
        p.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
        p.add_argument("--cap-usd", type=float, default=DEFAULT_COST_CAP_USD)
        if name == "create":
            p.add_argument("--confirm-cost-usd", type=float, default=None)
            p.add_argument("--force", action="store_true", help="create even if a job exists")
    up = sub.add_parser("upload")
    up.add_argument("--force", action="store_true", help="upload again even if unchanged")
    st = sub.add_parser("status")
    st.add_argument("--wait", action="store_true", help="poll every minute until it finishes")
    sub.add_parser("cancel")
    args = parser.parse_args()
    commands = {
        "estimate": cmd_estimate,
        "upload": cmd_upload,
        "create": cmd_create,
        "status": cmd_status,
        "cancel": cmd_cancel,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
