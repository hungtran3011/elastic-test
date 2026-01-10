import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

def build_command(py: str, project_root: str, category: str, args: argparse.Namespace) -> list:
    cmd = [py, str(Path(project_root) / "scraper.py"), "--category", category, "--max-pages", str(args.max_pages), "--chapters", str(args.chapters), "--delay", str(args.delay), "--job-id", category]
    if args.no_files:
        cmd.append("--no-files")
    if args.resume:
        cmd.append("--resume")
    return cmd
def run_category(cmd: list) -> tuple:
    category = None
    try:
        if "--category" in cmd:
            category = cmd[cmd.index("--category") + 1]
    except Exception:
        category = "unknown"
    print(f"Starting crawl for {category}: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = proc.returncode == 0
    print(f"Finished {category}: exit={proc.returncode}; stdout_len={len(proc.stdout)}; stderr_len={len(proc.stderr)}")
    return category, ok, proc.returncode, proc.stdout, proc.stderr


def main():
    parser = argparse.ArgumentParser(description="Run multiple category crawls in parallel (wrapper around scraper.py)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--categories", type=str, help="Comma-separated category slugs (e.g. 'kiem-hiep,ngon-tinh')")
    group.add_argument("--file", type=str, help="Text file with one category slug per line")
    parser.add_argument("--concurrency", type=int, default=3, help="Number of parallel crawls (default 3)")
    parser.add_argument("--max-pages", type=int, default=6)
    parser.add_argument("--chapters", type=int, default=200)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--no-files", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--project-root", type=str, default=".", help="Path to project root (where scraper.py lives)")
    args = parser.parse_args()

    if args.categories:
        cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    else:
        p = Path(args.file)
        cats = [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

    if not cats:
        print("No categories provided")
        sys.exit(1)

    python_exe = sys.executable
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = {ex.submit(run_category, build_command(python_exe, args.project_root, cat, args)): cat for cat in cats}
        for fut in as_completed(futures):
            results.append(fut.result())

    # Summary
    ok_count = sum(1 for r in results if r[1])
    print(f"All done: {ok_count}/{len(results)} succeeded")
    for cat, ok, rc, out, err in results:
        status = "OK" if ok else f"FAIL({rc})"
        print(f"- {cat}: {status}")


if __name__ == "__main__":
    main()


