"""Фактическая история текущей ветки без подмены авторства/дат."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT).decode('utf-8').strip()


def main():
    rows = []
    for line in git('log','--format=%H%x09%an%x09%aI%x09%s','HEAD').splitlines():
        sha,author,date,subject = line.split('\t',3)
        rows.append(dict(sha=sha,author=author,date=date,subject=subject,
                         diff=git('show','--format=','--shortstat',sha)))
    print(json.dumps(dict(head=git('rev-parse','HEAD'),branch=git('branch','--show-current'),
        shallow=git('rev-parse','--is-shallow-repository')=='true',count=len(rows),commits=rows,
        note='Git metadata does not prove student authorship or compliance with academic deadlines.'),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
