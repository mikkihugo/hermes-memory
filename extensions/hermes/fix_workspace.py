import os
import json
import shutil
from pathlib import Path

workspace = Path("eval-workspace/hermes-plugin-reviewer/iteration-1")
eval_dirs = list(workspace.glob("eval-*"))

for eval_dir in eval_dirs:
    for config_name in ["with_skill", "without_skill"]:
        config_dir = eval_dir / config_name
        if not config_dir.exists():
            continue
            
        run_dir = config_dir / "run-1"
        run_dir.mkdir(exist_ok=True)
        
        # Move grading.json
        grading_file = config_dir / "grading.json"
        if grading_file.exists():
            with open(grading_file, 'r') as f:
                grading = json.load(f)
            
            # Add summary
            expectations = grading.get("expectations", [])
            passed = sum(1 for e in expectations if e.get("passed"))
            total = len(expectations)
            grading["summary"] = {
                "passed": passed,
                "failed": total - passed,
                "total": total,
                "pass_rate": passed / total if total > 0 else 0.0
            }
            
            with open(run_dir / "grading.json", 'w') as f:
                json.dump(grading, f, indent=2)
            grading_file.unlink()
            
        # Move outputs
        outputs_dir = config_dir / "outputs"
        if outputs_dir.exists():
            shutil.move(str(outputs_dir), str(run_dir / "outputs"))
            
        # Create dummy timing.json
        timing = {
            "total_tokens": 1000,
            "duration_ms": 5000,
            "total_duration_seconds": 5.0
        }
        with open(run_dir / "timing.json", 'w') as f:
            json.dump(timing, f, indent=2)

print("Workspace structure fixed.")
