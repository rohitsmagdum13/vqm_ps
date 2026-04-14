"""One-time script to strip all comments and docstrings from Python files."""

import ast
import os
import re
import sys
from pathlib import Path


PRESERVED_COMMENT_PATTERNS = [
    re.compile(r"#\s*type:\s*ignore"),
    re.compile(r"#\s*noqa"),
    re.compile(r"#\s*pragma"),
]

SHEBANG_PATTERN = re.compile(r"^#!")


def find_docstring_ranges(source: str) -> list[tuple[int, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    ranges = []

    def check_docstring(node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            doc_node = node.body[0]
            ranges.append((doc_node.lineno, doc_node.end_lineno))

    if isinstance(tree, ast.Module):
        check_docstring(tree)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            check_docstring(node)

    return ranges


def needs_pass(source: str, docstring_ranges: list[tuple[int, int]]) -> set[int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    pass_lines = set()

    def check_needs_pass(node):
        if not node.body:
            return
        if not (
            isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            return

        doc_node = node.body[0]

        remaining_body = node.body[1:]
        has_real_code = False
        for stmt in remaining_body:
            if isinstance(stmt, ast.Pass):
                continue
            has_real_code = True
            break

        if not has_real_code:
            pass_lines.add(doc_node.end_lineno)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            check_needs_pass(node)

    return pass_lines


def is_in_docstring(line_num: int, ranges: list[tuple[int, int]]) -> bool:
    for start, end in ranges:
        if start <= line_num <= end:
            return True
    return False


def is_preserved_comment(comment_text: str) -> bool:
    for pattern in PRESERVED_COMMENT_PATTERNS:
        if pattern.search(comment_text):
            return True
    return False


def strip_comment_from_line(line: str) -> str | None:
    if SHEBANG_PATTERN.match(line):
        return line

    stripped = line.rstrip()
    if not stripped:
        return line

    lstripped = stripped.lstrip()
    if not lstripped.startswith("#"):
        hash_pos = find_comment_hash(stripped)
        if hash_pos == -1:
            return line
        comment_part = stripped[hash_pos:]
        if is_preserved_comment(comment_part):
            return line
        new_line = stripped[:hash_pos].rstrip()
        if not new_line.strip():
            return None
        return new_line + "\n"
    else:
        if is_preserved_comment(lstripped):
            return line
        return None


def find_comment_hash(line: str) -> int:
    in_single = False
    in_double = False
    in_triple_single = False
    in_triple_double = False
    i = 0
    while i < len(line):
        c = line[i]

        if in_triple_double:
            if line[i:i+3] == '"""':
                in_triple_double = False
                i += 3
                continue
        elif in_triple_single:
            if line[i:i+3] == "'''":
                in_triple_single = False
                i += 3
                continue
        elif in_double:
            if c == '\\':
                i += 2
                continue
            if c == '"':
                in_double = False
        elif in_single:
            if c == '\\':
                i += 2
                continue
            if c == "'":
                in_single = False
        else:
            if line[i:i+3] == '"""':
                in_triple_double = True
                i += 3
                continue
            elif line[i:i+3] == "'''":
                in_triple_single = True
                i += 3
                continue
            elif c == '"':
                in_double = True
            elif c == "'":
                in_single = True
            elif c == '#':
                return i
        i += 1
    return -1


def process_file(filepath: Path) -> tuple[int, int]:
    with open(filepath, "r", encoding="utf-8") as f:
        original_content = f.read()

    original_lines = original_content.splitlines(keepends=True)
    original_count = len(original_lines)

    docstring_ranges = find_docstring_ranges(original_content)
    pass_needed = needs_pass(original_content, docstring_ranges)

    new_lines = []
    for i, line in enumerate(original_lines, start=1):
        if is_in_docstring(i, docstring_ranges):
            if i in pass_needed:
                for start, end in docstring_ranges:
                    if end == i:
                        first_line = original_lines[start - 1]
                        indent = ""
                        for ch in first_line:
                            if ch in (" ", "\t"):
                                indent += ch
                            else:
                                break
                        break

                new_lines.append(indent + "pass\n")
            continue

        result = strip_comment_from_line(line)
        if result is not None:
            new_lines.append(result)

    cleaned = collapse_blank_lines(new_lines)

    new_content = "".join(cleaned)
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    new_count = len(new_content.splitlines())
    return original_count, new_count


def collapse_blank_lines(lines: list[str]) -> list[str]:
    result = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)

    while result and result[0].strip() == "":
        result.pop(0)
    while result and result[-1].strip() == "":
        result.pop()

    return result


def main():
    project_root = Path(__file__).resolve().parent.parent

    exclude_dirs = {".venv", "__pycache__", "node_modules", "frontend", "local_vqm"}

    py_files = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in files:
            if f.endswith(".py") and f != "strip_docs.py":
                py_files.append(Path(root) / f)

    py_files.sort()

    total_before = 0
    total_after = 0
    files_processed = 0

    for filepath in py_files:
        try:
            before, after = process_file(filepath)
            removed = before - after
            total_before += before
            total_after += after
            files_processed += 1
            if removed > 0:
                rel = filepath.relative_to(project_root)
                print(f"  {rel}: {before} -> {after} ({removed} lines removed)")
        except Exception as e:
            print(f"  ERROR processing {filepath}: {e}", file=sys.stderr)

    total_removed = total_before - total_after
    print(f"\n{'='*60}")
    print(f"Files processed: {files_processed}")
    print(f"Lines before:    {total_before}")
    print(f"Lines after:     {total_after}")
    print(f"Lines removed:   {total_removed}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
