"""Воспроизводимые вспомогательные метрики; не официальная методика вуза."""
import ast
from collections import defaultdict
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import tokenize

ROOT = Path(__file__).resolve().parents[1]


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.count = 0

    def handle_starttag(self, tag, attrs):
        self.count += 1


def metric(path):
    source = path.read_text(encoding='utf-8-sig')
    language = {'.py':'Python','.js':'JavaScript','.cjs':'JavaScript','.css':'CSS','.html':'HTML'}[path.suffix]
    code = source
    if language == 'Python':
        tree = ast.parse(source)
        docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str) for n in [n.body[0]]}
        units = sum(isinstance(n, ast.stmt) and not (isinstance(n, ast.Expr) and id(n.value) in docs) for n in ast.walk(tree))
        rows = set()
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER) and not re.fullmatch(r'[\s{}\[\]();,:]+', token.string):
                rows.update(range(token.start[0], token.end[0]+1))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and id(n) in docs:
                rows.difference_update(range(n.lineno,n.end_lineno+1))
        physical = len(rows)
        method = 'AST statements без docstrings (вложенные считаются отдельно)'
    else:
        # Preserve strings/template markup while removing only source comments.
        pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|/\*[\s\S]*?\*/|//[^\n]*' if language == 'JavaScript' else r'/\*[\s\S]*?\*/|<!--[\s\S]*?-->'
        code = re.sub(pattern, lambda m: '\n'*m[0].count('\n') if m[0].startswith(('//','/*','<!--')) else m[0], source)
        physical = sum(bool(line.strip()) and not re.fullmatch(r'[\s{}\[\]();,]+',line) for line in code.splitlines())
        if language == 'HTML':
            parser = Tags(); parser.feed(code); units = parser.count
            method = 'открывающие HTML-элементы; Jinja-выражения не операторы'
        elif language == 'CSS':
            units = len(re.findall(r'(?:\{|;)\s*[\w-]+\s*:', code))
            method = 'CSS-декларации свойств'
        else:
            # No AST parser shipped with the app: explicitly do not call this a logical LOC count.
            stripped = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`', '', code)
            units = stripped.count(';')
            method = 'разделители ; вне строк: ориентир, не число операторов; template expressions исключены'
    return {'file':str(path.relative_to(ROOT)).replace('\\','/'), 'language':language,
            'physical_total':len(source.splitlines()),'physical_code':physical,'auxiliary_units':units,'unit_method':method}


def main():
    groups = {}
    for group, folders in {'application':['hydroflow','static','templates'], 'tests':['tests'], 'tools':['scripts']}.items():
        files = sorted(p for folder in folders for p in (ROOT/folder).rglob('*') if p.suffix in {'.py','.js','.cjs','.html','.css'} and '__pycache__' not in p.parts)
        # Old index.html is not a Flask entry point; exclude if present in a historical checkout.
        files = [p for p in files if p != ROOT/'static/index.html']
        rows = [metric(p) for p in files]
        totals = defaultdict(lambda: {'physical_total':0,'physical_code':0,'auxiliary_units':0})
        for row in rows:
            for key in totals[row['language']]:
                totals[row['language']][key] += row[key]
        groups[group] = {'totals':dict(totals), 'files':rows}
    print(json.dumps({'method':'HF-metrics-1; auxiliary units across languages must not be summed as official logical LOC', 'excludes':['docs/mockups (generated design artifacts)','dependencies','data','comments','blank/control-only lines','SVG icon'], 'groups':groups},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
