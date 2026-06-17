from __future__ import annotations

import argparse
import json

from .dataset_schema import load_agent_eval_dataset
from .evaluator import AgentEvaluator


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RamanAgent Agent eval dataset.")
    parser.add_argument("--dataset", required=True, help="Path to agent eval JSON dataset.")
    args = parser.parse_args()
    dataset = load_agent_eval_dataset(args.dataset)
    result = AgentEvaluator().evaluate(dataset)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
