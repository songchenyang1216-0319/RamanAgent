from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.evaluation.rag_eval.evaluator import RAGEvaluator


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RamanAgent RAG evaluation.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--user-id", default="default_user")
    parser.add_argument("--conversation-id", default="")
    args = parser.parse_args()
    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    if isinstance(dataset, dict):
        dataset = dataset.get("items") or []
    result = RAGEvaluator().evaluate(dataset, user_id=args.user_id, conversation_id=args.conversation_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

