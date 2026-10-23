"""Assert AC-N10 on a fresh coverage JSON; does not invoke pytest recursively."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('report', type=Path)
args = parser.parse_args()
report = json.loads(args.report.read_text(encoding='utf-8'))
totals = report['totals']
covered, statements = totals['covered_lines'], totals['num_statements']
percent = 100 * covered / statements if statements else 0
print(f'AC-N10 line coverage: {covered}/{statements} = {percent:.2f}% (required >=78%)')
if percent < 78:
    for filename, data in sorted(report['files'].items()):
        if data['missing_lines']:
            print(f"{filename}: uncovered lines {data['missing_lines']}")
    raise SystemExit(1)
