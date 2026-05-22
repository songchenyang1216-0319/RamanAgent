#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
A safe diagnostic script for Agent Skill upload testing.

It does not access the network.
It does not modify user files.
It only prints a deterministic JSON result.
"""

import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Skill packaged script test.")
    parser.add_argument("--input", default="", help="Original user message or test input.")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parents[1]
    skill_md_exists = (skill_root / "SKILL.md").exists()
    manifest_exists = (skill_root / "manifest.json").exists()

    input_text = args.input or ""
    input_sha256 = hashlib.sha256(input_text.encode("utf-8")).hexdigest()

    result = {
        "marker": "SKILL_SCRIPT_EXEC_OK_v1",
        "skill_name": "agent-skill-upload-test",
        "skill_version": "1.0.0",
        "script_executed": True,
        "skill_md_exists": skill_md_exists,
        "manifest_exists": manifest_exists,
        "input_char_count": len(input_text),
        "input_sha256_first16": input_sha256[:16],
        "utc_time": datetime.now(timezone.utc).isoformat()
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
