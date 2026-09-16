#!/usr/bin/env python3
# ruff: noqa: E501
# BSD 3-Clause License
#
# Copyright (c) 2026, Martin Urban, Hannah Kullik
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""Run deterministic, standard-library Google Python Style checks."""

from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import pathlib
import re
import sys
import textwrap
import tokenize


@dataclasses.dataclass(frozen=True)
class Finding:
    """Represent one audit result."""

    level: str
    rule: str
    file: str
    line: int
    column: int
    message: str


EXCLUDED = frozenset(
    {
        ".git",
        ".agents",
        ".mypy_cache",
        ".pytest_cache",
        ".pyrefly",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "cache",
        ".cache",
        "build",
        "dist",
        "generated",
        "gen",
        "node_modules",
        "site-packages",
        "vendor",
    }
)
DUNDER = re.compile(r"^__[^_].*__$")
TYPE_COMMENT = re.compile(r"#\s*type:\s*(?!ignore\b)")
TODO = re.compile(r"#\s*TODO(?!\s*:\s*\S+\s+-\s+\S+)", re.IGNORECASE)
PYLINT = re.compile(r"#\s*pylint\s*:", re.IGNORECASE)
SECTION = re.compile(r"^(Args|Raises|Returns|Yields):$")
STRING_TOKEN_TYPES = frozenset(
    {tokenize.STRING}
    | {
        getattr(tokenize, name)
        for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
        if hasattr(tokenize, name)
    }
)
# Structural pattern matching landed in 3.10, but this checker runs on the
# user's own python3 and is held to the repository's 3.9 floor (see
# pyproject.toml), so the node types are resolved defensively the same way
# type_params is below. An empty tuple makes every isinstance check false,
# which is correct on 3.9: a match statement cannot parse there at all.
MATCH_NAME_PATTERNS = tuple(
    node_type
    for node_type in (getattr(ast, "MatchAs", None), getattr(ast, "MatchStar", None))
    if node_type is not None
)
MATCH_MAPPING_PATTERNS = tuple(
    node_type
    for node_type in (getattr(ast, "MatchMapping", None),)
    if node_type is not None
)


def leading_comment_lines(source):
    """Return comment lines before the first Python statement.

    Args:
        source: Python source text.
    Returns:
        Leading comment line numbers.
    """
    lines = set()
    try:
        tokens = tokenize.generate_tokens(
            iter(source.splitlines(keepends=True)).__next__
        )
        for token in tokens:
            if token.type == tokenize.COMMENT:
                lines.add(token.start[0])
                continue
            if token.type in {tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER}:
                continue
            break
    except (tokenize.TokenError, IndentationError):
        pass
    return lines


def section_or_fold_comment(text):
    """Return whether a comment is a genuine section or fold marker.

    Args:
        text: Comment text without its hash.
    Returns:
        Whether punctuation is exempt.
    """
    lowered = text.lower().strip()
    return bool(
        re.fullmatch(r"<editor-fold(?:\s+desc=\"[^\"<>]*\")?>", lowered)
        or lowered == "</editor-fold>"
        or lowered in {"region", "endregion"}
        or re.fullmatch(r"-{3,}", lowered)
        or re.fullmatch(r"={3,}", lowered)
        or re.fullmatch(r"---\s+.+\s+---", lowered)
        or re.fullmatch(r"===\s+.+\s+===", lowered)
    )


def add(results, root, path, node, rule, level, message, line=None):
    """Append a finding with a stable relative location.

    Args:
        results: Finding collection.
        root: Audit root.
        path: Source path.
        node: Source node.
        rule: Rule identifier.
        level: Finding severity.
        message: Finding message.
        line: Optional source line.
    """
    results.append(
        Finding(
            level,
            rule,
            path.relative_to(root).as_posix(),
            line or getattr(node, "lineno", 1),
            getattr(node, "col_offset", 0) + 1,
            message,
        )
    )


def valid_snake(name):
    """Return whether a function or binding uses snake case.

    Args:
        name: Candidate name.
    Returns:
        Whether the name is valid.
    """
    return name == "_" or bool(
        re.fullmatch(r"_+[a-z][a-z0-9_]*|[a-z][a-z0-9_]*|__[^_].*__", name)
    )


def valid_class(name):
    """Return whether a class uses PascalCase.

    Args:
        name: Candidate name.
    Returns:
        Whether the name is valid.
    """
    return bool(re.fullmatch(r"_?[A-Z][A-Za-z0-9]*", name))


def confirmed_class_usages(tree):
    """Return names confirmed as classes by a constructor call or base class.

    PascalCase imports can also be modules, such as QtCore. Requiring a call or
    base-class use prevents the module-only import rule from guessing based on
    spelling alone.

    Args:
        tree: Parsed module syntax tree.
    Returns:
        Names used to construct an instance or as a class base.
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node, ast.ClassDef):
            names.update(base.id for base in node.bases if isinstance(base, ast.Name))
    return names


def type_alias_bindings(tree):
    """Return CapWords names bound to a type alias or a class-producing call.

    The guide names type aliases in CapWords, so the ordinary snake_case
    binding rule would demand renaming an alias bound to a class or to a
    class-producing call, breaking every importer. Literal values stay subject
    to that rule: only a name bound to another name, attribute, call,
    subscript, or type union is exempt.

    Args:
        tree: Parsed module syntax tree.
    Returns:
        Names bound at least once to an alias-shaped value.
    """
    alias_values = (ast.Name, ast.Attribute, ast.Call, ast.Subscript, ast.BinOp)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, alias_values):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, alias_values):
            targets = [node.target]
        elif isinstance(node, getattr(ast, "TypeAlias", ())):
            targets = [node.name]
        else:
            continue
        names.update(
            target.id
            for target in targets
            if isinstance(target, ast.Name) and valid_class(target.id)
        )
    return names


def module_only_exempt(module):
    """Return whether the guide exempts a module from its modules-only rule.

    Args:
        module: Dotted module path from a from-import statement.
    Returns:
        Whether Google Python Style Guide section 2.2 exempts this module.
    """
    if module in {"typing", "typing_extensions", "collections.abc"}:
        return True
    return module == "six.moves" or module.startswith("six.moves.")


def module_only_import(module):
    """Return the module-only import and bound name for a dotted module.

    Args:
        module: Dotted module path from a from-import statement.
    Returns:
        The replacement import statement and the name it binds.
    """
    if "." in module:
        parent, _, child = module.rpartition(".")
        return f"from {parent} import {child}", child
    return f"import {module}", module


def meaningful_args(node):
    """Return function parameters that need Args entries.

    Args:
        node: Function syntax node.
    Returns:
        Parameter names.
    """
    args = [
        *getattr(node.args, "posonlyargs", []),
        *node.args.args,
        *node.args.kwonlyargs,
    ]
    names = [arg.arg for arg in args if arg.arg not in {"self", "cls"}]
    if node.args.vararg:
        names.append(node.args.vararg.arg)
    if node.args.kwarg:
        names.append(node.args.kwarg.arg)
    return names


def has_value_return(node):
    """Return whether a function returns a value.

    Args:
        node: Function syntax node.
    Returns:
        Whether a value is returned.
    """
    if _contains_current_scope(node, ast.Return, lambda item: item.value is not None):
        return True
    return _has_value_return_annotation(node.returns)


def _has_value_return_annotation(annotation):
    """Return whether an annotation represents a value-returning contract.

    Args:
        annotation: Return annotation node, if present.
    Returns:
        Whether Returns documentation is applicable.
    """
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant):
        return annotation.value not in {None, "None", "NoReturn", "Never"}
    if isinstance(annotation, ast.Name):
        return annotation.id not in {"None", "NoReturn", "Never"}
    if isinstance(annotation, ast.Attribute):
        return annotation.attr not in {"NoReturn", "Never"}
    return True


def has_yield(node):
    """Return whether a function yields values.

    Args:
        node: Function syntax node.
    Returns:
        Whether values are yielded.
    """
    return _contains_current_scope(node, (ast.Yield, ast.YieldFrom), lambda item: True)


def _contains_current_scope(node, node_types, predicate):
    """Find a matching node without entering nested executable scopes.

    Args:
        node: Current function node.
        node_types: AST type or types to find.
        predicate: Additional matching predicate.
    Returns:
        Whether a matching node exists in the current scope.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if isinstance(child, node_types) and predicate(child):
            return True
        if _contains_current_scope(child, node_types, predicate):
            return True
    return False


def current_scope_raises(node):
    """Return normalized exception names raised in the current scope.

    Args:
        node: Current function node.
    Returns:
        Qualified, leaf, or callable-raise markers.
    """
    names = []

    def walk(current):
        """Walk current executable scope only.

        Args:
            current: Current AST node.
        """
        for child in ast.iter_child_nodes(current):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            ):
                continue
            if isinstance(child, ast.Raise) and child.exc is not None:
                expression = (
                    child.exc.func if isinstance(child.exc, ast.Call) else child.exc
                )
                if isinstance(expression, ast.Name) and expression.id[:1].isupper():
                    names.append(expression.id)
                elif (
                    isinstance(expression, ast.Attribute)
                    and expression.attr[:1].isupper()
                ):
                    names.extend((ast.unparse(expression), expression.attr))
                else:
                    names.append("__callable_raise__")
            walk(child)

    walk(node)
    return names


def _is_test_file(path):
    """Return whether a path conventionally identifies a test module.

    Args:
        path: Source path.
    Returns:
        Whether the path is a test file.
    """
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def _is_mutable_value(node):
    """Return whether an expression likely creates mutable state.

    Args:
        node: Expression node.
    Returns:
        Whether the expression is likely mutable.
    """
    if isinstance(
        node, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
    ):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"dict", "list", "set"}
    )


def _mutable_defaults(node):
    """Return known mutable defaults from a function signature.

    Args:
        node: Function syntax node.
    Returns:
        Mutable positional and keyword-only defaults.
    """
    defaults = [*node.args.defaults, *node.args.kw_defaults]
    return [
        default
        for default in defaults
        if default is not None and _is_mutable_value(default)
    ]


def _scope_bindings(node):
    """Return names and wildcard imports bound in one lexical scope.

    Args:
        node: Module, class, or function syntax node.
    Returns:
        Bound names and whether a wildcard import makes resolution uncertain.
    """
    names = set()
    wildcard_import = False
    comprehension_types = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)

    def walk_comprehension(current):
        """Collect containing-scope bindings from a comprehension.

        Args:
            current: Comprehension syntax node.
        """
        if isinstance(current, ast.Lambda):
            return
        if isinstance(current, ast.NamedExpr):
            walk(current.target)
            walk_comprehension(current.value)
            return
        if isinstance(current, ast.comprehension):
            walk_comprehension(current.iter)
            for condition in current.ifs:
                walk_comprehension(condition)
            return
        for child in ast.iter_child_nodes(current):
            walk_comprehension(child)

    def walk_definition_expressions(current):
        """Collect bindings evaluated while defining a child scope.

        Args:
            current: Function, class, or lambda syntax node.
        """
        expressions = [*getattr(current, "decorator_list", [])]
        if isinstance(current, ast.ClassDef):
            expressions.extend(current.bases)
            expressions.extend(keyword.value for keyword in current.keywords)
        else:
            arguments = current.args
            expressions.extend(arguments.defaults)
            expressions.extend(
                default for default in arguments.kw_defaults if default is not None
            )
            function_args = [
                *getattr(arguments, "posonlyargs", []),
                *arguments.args,
                *arguments.kwonlyargs,
            ]
            if arguments.vararg:
                function_args.append(arguments.vararg)
            if arguments.kwarg:
                function_args.append(arguments.kwarg)
            expressions.extend(
                argument.annotation
                for argument in function_args
                if argument.annotation is not None
            )
            returns = getattr(current, "returns", None)
            if returns is not None:
                expressions.append(returns)
        expressions.extend(getattr(current, "type_params", []))
        for expression in expressions:
            walk(expression)

    def walk(current):
        """Collect bindings without descending into child lexical scopes.

        Args:
            current: Syntax node to collect bindings from.
        """
        nonlocal wildcard_import
        if current is not node and isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            if hasattr(current, "name"):
                names.add(current.name)
            walk_definition_expressions(current)
            return
        if isinstance(current, comprehension_types):
            walk_comprehension(current)
            return
        if isinstance(current, ast.Name) and isinstance(
            current.ctx, (ast.Store, ast.Del)
        ):
            names.add(current.id)
        elif isinstance(current, ast.arg):
            names.add(current.arg)
        elif isinstance(current, ast.Import):
            names.update(
                alias.asname or alias.name.split(".", 1)[0] for alias in current.names
            )
        elif isinstance(current, ast.ImportFrom):
            wildcard_import = wildcard_import or any(
                alias.name == "*" for alias in current.names
            )
            names.update(
                alias.asname or alias.name
                for alias in current.names
                if alias.name != "*"
            )
        elif isinstance(current, ast.ExceptHandler) and current.name:
            names.add(current.name)
        elif isinstance(current, MATCH_NAME_PATTERNS) and current.name:
            names.add(current.name)
        elif isinstance(current, MATCH_MAPPING_PATTERNS) and current.rest:
            names.add(current.rest)
        for child in ast.iter_child_nodes(current):
            walk(child)

    names.update(
        type_parameter.name
        for type_parameter in getattr(node, "type_params", [])
        if getattr(type_parameter, "name", None)
    )
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        arguments = node.args
        function_args = [
            *getattr(arguments, "posonlyargs", []),
            *arguments.args,
            *arguments.kwonlyargs,
        ]
        if arguments.vararg:
            function_args.append(arguments.vararg)
        if arguments.kwarg:
            function_args.append(arguments.kwarg)
        names.update(argument.arg for argument in function_args)
        body = node.body if isinstance(node.body, list) else [node.body]
    else:
        body = node.body
    for statement in body:
        walk(statement)
    return names, wildcard_import


def _is_ast_visitor_hook(name):
    """Return whether a name is an exact AST visitor dispatch override.

    Args:
        name: Candidate method name.
    Returns:
        Whether the name maps to an AST node class.
    """
    if not name.startswith("visit_"):
        return False
    node_type = getattr(ast, name[6:], None)
    return isinstance(node_type, type) and issubclass(node_type, ast.AST)


def doc_findings(results, root, path, node, kind):
    """Check documentation and naming for one documentable symbol.

    Args:
        results: Finding collection.
        root: Audit root.
        path: Source path.
        node: Documentable syntax node.
        kind: Symbol kind.
    """
    doc = ast.get_docstring(node, clean=False)
    if doc is None:
        add(
            results,
            root,
            path,
            node,
            f"{kind}-docstring",
            "violation",
            f"Add a docstring for this {kind}.",
        )
        doc = ""
    doc = textwrap.dedent(doc)
    lines = doc.splitlines()
    if not lines or not lines[0].strip().endswith("."):
        add(
            results,
            root,
            path,
            node,
            "docstring-summary",
            "violation",
            "Docstring summary must end with a period.",
        )
    if "`" in doc or ":class:" in doc:
        add(
            results,
            root,
            path,
            node,
            "docstring-markup",
            "violation",
            "Docstrings must not contain backticks or Sphinx class markup.",
        )
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        required = (
            "Yields"
            if has_yield(node)
            else "Returns"
            if has_value_return(node)
            else None
        )
        sections = _doc_sections(lines)
        if meaningful_args(node):
            _check_section_entries(
                results, root, path, node, sections, "Args", meaningful_args(node)
            )
        if required:
            _check_section_entries(results, root, path, node, sections, required, None)
        raised = current_scope_raises(node)
        if raised and "Raises" not in sections:
            add(
                results,
                root,
                path,
                node,
                "docstring-raises",
                "violation",
                "Document current-scope raises in a Raises section.",
            )
        if raised and "Raises" in sections:
            found = {name for name, _description in sections["Raises"]}
            if "__callable_raise__" in raised and (
                len(sections["Raises"]) != 1 or found != {"Exception"}
            ):
                add(
                    results,
                    root,
                    path,
                    node,
                    "docstring-raises",
                    "violation",
                    "Dynamic raises require exactly one Exception entry.",
                )
            missing = [
                name
                for name in raised
                if name != "__callable_raise__"
                and not (
                    name in found
                    or name.rsplit(".", 1)[-1] in found
                    or any(
                        entry.rsplit(".", 1)[-1] == name.rsplit(".", 1)[-1]
                        for entry in found
                    )
                )
            ]
            if missing:
                add(
                    results,
                    root,
                    path,
                    node,
                    "docstring-raises",
                    "violation",
                    f"Raises entries do not match: {', '.join(missing)}.",
                )
        if "Raises" in sections:
            _check_section_entries(results, root, path, node, sections, "Raises", None)


def _doc_sections(lines):
    """Parse Google-style documentation sections and their logical entries.

    Args:
        lines: Dedented docstring lines.
    Returns:
        Section names mapped to entry descriptions.
    """
    sections = {}
    current = None
    current_name = None
    entry_indent = 0
    for line in lines:
        heading = re.match(r"^\s*(Args|Raises|Returns|Yields):\s*$", line)
        if heading:
            current_name = heading.group(1)
            current = []
            sections[current_name] = current
            entry_indent = 0
            continue
        if current is None or not line.strip():
            continue
        # The name must start with a non-space character, otherwise a
        # colon-leading line inside a section, such as a leftover reST param
        # directive, matches with the indentation alone as its name.
        entry = re.match(r"^\s*([^:\s][^:]*):\s*(.*)$", line)
        if entry:
            current.append([entry.group(1).strip(), entry.group(2).strip()])
            entry_indent = len(line) - len(line.lstrip())
            continue
        if current_name in {"Returns", "Yields"} and not current:
            current.append(["__prose__", line.strip()])
            continue
        if not current:
            continue
        # A description may start on the line after its name, which is the
        # form the guide itself uses when one line is not enough. Requiring a
        # deeper indent than the name keeps a malformed sibling entry out.
        indent = len(line) - len(line.lstrip())
        if current[-1][1] or indent > entry_indent:
            current[-1][1] = f"{current[-1][1]} {line.strip()}".strip()
    return sections


def _check_section_entries(results, root, path, node, sections, section, required):
    """Validate required section entries and punctuation.

    Args:
        results: Finding collection.
        root: Audit root.
        path: Source path.
        node: Documentable node.
        sections: Parsed documentation sections.
        section: Section name.
        required: Required parameter names, or None for prose sections.
    """
    entries = sections.get(section)
    if not entries:
        rule = "docstring-args" if section == "Args" else f"docstring-{section.lower()}"
        add(
            results,
            root,
            path,
            node,
            rule,
            "violation",
            f"Document non-empty entries in {section}.",
        )
        return
    if required:
        found = set()
        for entry in entries:
            name = entry[0].lstrip("*").split()
            if name:
                found.add(name[0])
        missing = [name for name in required if name not in found]
        if missing:
            add(
                results,
                root,
                path,
                node,
                "docstring-args",
                "violation",
                f"Document every parameter in Args; missing {', '.join(missing)}.",
            )
    if any(
        not description or not description.endswith(".") for _, description in entries
    ):
        add(
            results,
            root,
            path,
            node,
            "docstring-section-punctuation",
            "violation",
            f"Descriptions in {section} must be non-empty and end with a period.",
        )


class Visitor(ast.NodeVisitor):
    """Collect AST-based audit findings without treating methods as nested functions."""

    def __init__(self, root, path, class_usages, type_aliases=frozenset()):
        """Initialize the visitor.

        Args:
            root: Audit root.
            path: Source path.
            class_usages: Names confirmed as classes by call or base-class usage.
            type_aliases: CapWords names bound to an alias-shaped value.
        """
        self.root, self.path, self.results, self.scopes = root, path, [], ["module"]
        self.bindings = []
        self.class_usages = class_usages
        self.type_aliases = type_aliases

    def visit_Module(self, node):
        """Track names that can shadow built-ins at module scope.

        Args:
            node: Module syntax node.
        """
        self.bindings.append(_scope_bindings(node))
        self.generic_visit(node)
        self.bindings.pop()

    def visit_Import(self, node):
        """Check ordinary import statements.

        Args:
            node: Import syntax node.
        """
        if len(node.names) > 1:
            add(
                self.results,
                self.root,
                self.path,
                node,
                "multiple-imports",
                "violation",
                "Each import statement must contain one module.",
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        """Check from-import statements.

        Args:
            node: Import syntax node.
        """
        if len(node.names) > 1:
            add(
                self.results,
                self.root,
                self.path,
                node,
                "multiple-from-imports",
                "violation",
                "Each from-import statement must contain one symbol.",
            )
        if any(alias.name == "*" for alias in node.names):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "no-wildcard-imports",
                "violation",
                "Wildcard imports are forbidden.",
            )
        if node.level:
            add(
                self.results,
                self.root,
                self.path,
                node,
                "absolute-imports",
                "violation",
                "Use an absolute import path.",
            )
        if (
            not node.level
            and node.module
            and node.module != "__future__"
            and not module_only_exempt(node.module)
        ):
            for alias in node.names:
                bound_name = alias.asname or alias.name
                if (
                    alias.name != "*"
                    and valid_class(alias.name)
                    and bound_name in self.class_usages
                ):
                    new_import, module_ref = module_only_import(node.module)
                    add(
                        self.results,
                        self.root,
                        self.path,
                        node,
                        "import-class-not-module",
                        "violation",
                        f"Import the module: use `{new_import}` and reference "
                        f"`{module_ref}.{alias.name}`.",
                    )
        if node.module == "typing" and any(
            alias.name == "Text" for alias in node.names
        ):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "no-typing-text",
                "violation",
                "Use str instead of typing.Text.",
            )
        if node.module in {"typing", "typing_extensions"} and any(
            alias.name in {"List", "Dict", "Set", "Tuple"} for alias in node.names
        ):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "legacy-typing-alias",
                "review",
                "Prefer built-in collection types when supported.",
            )
        self.generic_visit(node)

    def visit_Attribute(self, node):
        """Check qualified legacy typing names.

        Args:
            node: Attribute syntax node.
        """
        qualified_typing = (
            isinstance(node.value, ast.Name) and node.value.id == "typing"
        )
        if qualified_typing and node.attr == "Text":
            add(
                self.results,
                self.root,
                self.path,
                node,
                "no-typing-text",
                "violation",
                "Use str instead of typing.Text.",
            )
        if qualified_typing and node.attr in {"List", "Dict", "Set", "Tuple"}:
            add(
                self.results,
                self.root,
                self.path,
                node,
                "legacy-typing-alias",
                "review",
                "Prefer built-in collection types when supported.",
            )
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        """Flag broad exception handlers for review.

        Args:
            node: Exception handler node.
        """
        if node.type is None or (
            isinstance(node.type, ast.Name)
            and node.type.id in {"Exception", "BaseException"}
        ):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "broad-exception",
                "review",
                "Confirm that catching a broad exception is justified.",
            )
        self.generic_visit(node)

    def visit_Assert(self, node):
        """Flag assertions outside conventional tests.

        Args:
            node: Assertion node.
        """
        if not _is_test_file(self.path):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "assertion-control-flow",
                "review",
                "Confirm that assert is not application control flow.",
            )
        self.generic_visit(node)

    def visit_Lambda(self, node):
        """Flag lambdas for readability review.

        Args:
            node: Lambda node.
        """
        add(
            self.results,
            self.root,
            self.path,
            node,
            "lambda-expression",
            "review",
            "Confirm that a lambda is clearer than a named function.",
        )
        self.generic_visit(node)

    def visit_Name(self, node):
        """Check variable and binding names.

        Args:
            node: Name syntax node.
        """
        if isinstance(node.ctx, (ast.Store, ast.Del)) and node.id.startswith("tmp_"):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "tmp-prefix",
                "violation",
                "Bindings must not use the tmp_ prefix.",
            )
        if isinstance(node.ctx, (ast.Store, ast.Del)) and not (
            node.id.isupper() or valid_snake(node.id) or node.id in self.type_aliases
        ):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "binding-naming",
                "violation",
                "Bindings must use snake_case or an uppercase constant name.",
            )

    def visit_arg(self, node):
        """Check parameter names.

        Args:
            node: Parameter syntax node.
        """
        if node.arg.startswith("tmp_"):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "tmp-prefix",
                "violation",
                "Parameters must not use the tmp_ prefix.",
            )
        if not valid_snake(node.arg):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "parameter-naming",
                "violation",
                "Parameters must use snake_case.",
            )
        # Without this the visitor never reaches a parameter annotation, so
        # typing.Text on a parameter went unreported while the same
        # annotation on a variable was caught.
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        """Check synchronous function documentation and names.

        Args:
            node: Function syntax node.
        """
        self._function(node)

    def visit_AsyncFunctionDef(self, node):
        """Check asynchronous function documentation and names.

        Args:
            node: Function syntax node.
        """
        self._function(node)

    def _function(self, node):
        """Check one function node.

        Args:
            node: Function syntax node.
        """
        if node.name.startswith("tmp_"):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "tmp-prefix",
                "violation",
                "Functions must not use the tmp_ prefix.",
            )
        if not (
            _is_ast_visitor_hook(node.name)
            or DUNDER.fullmatch(node.name)
            or valid_snake(node.name)
        ):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "function-naming",
                "violation",
                "Functions and methods must use snake_case.",
            )
        for default in _mutable_defaults(node):
            constructor = default.func.id if isinstance(default, ast.Call) else None
            confirmed_builtin = constructor and all(
                not wildcard and constructor not in names
                for names, wildcard in self.bindings
            )
            if confirmed_builtin or constructor is None:
                add(
                    self.results,
                    self.root,
                    self.path,
                    default,
                    "mutable-default",
                    "violation",
                    "Function defaults must not create mutable objects.",
                )
            else:
                add(
                    self.results,
                    self.root,
                    self.path,
                    default,
                    "mutable-default",
                    "review",
                    "Confirm that this constructor resolves to an immutable default value.",
                )
        doc_findings(self.results, self.root, self.path, node, "function")
        if self.scopes[-1] == "function":
            add(
                self.results,
                self.root,
                self.path,
                node,
                "nested-function",
                "review",
                "Review whether this nested function is necessary.",
            )
        if node.end_lineno is not None and node.end_lineno - node.lineno + 1 > 40:
            add(
                self.results,
                self.root,
                self.path,
                node,
                "function-length",
                "review",
                "Review whether this function can remain focused below about 40 lines.",
            )
        self.scopes.append("function")
        self.bindings.append(_scope_bindings(node))
        self.generic_visit(node)
        self.bindings.pop()
        self.scopes.pop()

    def visit_Assign(self, node):
        """Flag likely mutable module and class state.

        Args:
            node: Assignment node.
        """
        if self.scopes[-1] in {"module", "class"} and _is_mutable_value(node.value):
            names = [
                target.id for target in node.targets if isinstance(target, ast.Name)
            ]
            if not names or any(not name.isupper() for name in names):
                add(
                    self.results,
                    self.root,
                    self.path,
                    node,
                    "mutable-global-state",
                    "review",
                    "Review mutable module or class state and document its justification.",
                )
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        """Check class documentation and names.

        Args:
            node: Class syntax node.
        """
        if not valid_class(node.name):
            add(
                self.results,
                self.root,
                self.path,
                node,
                "class-naming",
                "violation",
                "Classes must use PascalCase.",
            )
        if self.scopes[-1] != "module":
            add(
                self.results,
                self.root,
                self.path,
                node,
                "nested-class",
                "review",
                "Review whether this nested class is necessary.",
            )
        doc_findings(self.results, self.root, self.path, node, "class")
        self.scopes.append("class")
        self.bindings.append(_scope_bindings(node))
        self.generic_visit(node)
        self.bindings.pop()
        self.scopes.pop()


def _inside_string(position, regions):
    """Return whether a source position falls inside a string literal.

    Args:
        position: Row and column pair.
        regions: Start and end pairs for every string token.
    Returns:
        Whether the position is covered by a string token.
    """
    return any(start <= position < end for start, end in regions)


def _comment_blocks(comments, lines):
    """Group consecutive own-line comments into one logical comment.

    A comment wrapped over several lines is one sentence, so only its last
    line carries the closing period. Checking each physical line separately
    reported a violation on every line but the last.

    Args:
        comments: Comment tokens in source order.
        lines: Source lines.
    Returns:
        Lists of comment tokens, one list per logical comment.
    """
    blocks = []
    previous_row = None
    previous_own_line = False
    for token in comments:
        row, column = token.start
        own_line = not lines[row - 1][:column].strip()
        if blocks and own_line and previous_own_line and row == previous_row + 1:
            blocks[-1].append(token)
        else:
            blocks.append([token])
        previous_row, previous_own_line = row, own_line
    return blocks


def token_findings(source, root, path):
    """Check comments, punctuation, and tokenization.

    Args:
        source: Python source text.
        root: Audit root.
        path: Source path.
    Returns:
        Token findings.
    """
    results = []
    excluded_comment_lines = leading_comment_lines(source)
    lines = source.splitlines()
    # One tokenization pass feeds every check below. The comment rules used to
    # run as regexes over raw lines, which cannot tell code from string data,
    # so a type comment quoted inside a string literal was reported as real.
    tokens = []
    try:
        for token in tokenize.generate_tokens(
            iter(source.splitlines(keepends=True)).__next__
        ):
            tokens.append(token)
    except (tokenize.TokenError, IndentationError) as error:
        add(
            results,
            root,
            path,
            ast.Constant(value=None),
            "tokenization",
            "violation",
            f"Tokenization failed: {error}.",
        )
    string_regions = [
        (token.start, token.end) for token in tokens if token.type in STRING_TOKEN_TYPES
    ]
    for line_number, line in enumerate(lines, start=1):
        if line_number in excluded_comment_lines:
            continue
        if len(line) > 80:
            add(
                results,
                root,
                path,
                ast.Constant(value=None),
                "line-length",
                "review",
                "Review this line over the Google 80-character limit.",
                line_number,
            )
        continuation = re.search(r"\\\s*$", line)
        if (
            continuation
            and not line.lstrip().startswith("#")
            and not _inside_string((line_number, continuation.start()), string_regions)
        ):
            add(
                results,
                root,
                path,
                ast.Constant(value=None),
                "explicit-line-continuation",
                "review",
                "Prefer implicit line joining.",
                line_number,
            )
    for token in tokens:
        if token.type == tokenize.OP and token.string == ";":
            add(
                results,
                root,
                path,
                token,
                "semicolons",
                "violation",
                "Do not use statement semicolons.",
                token.start[0],
            )
    comments = [
        token
        for token in tokens
        if token.type == tokenize.COMMENT
        and token.string.lstrip("#").strip()
        and token.start[0] not in excluded_comment_lines
    ]
    for token in comments:
        text = token.string.lstrip("#").strip()
        if TYPE_COMMENT.search(token.string):
            add(
                results,
                root,
                path,
                token,
                "type-comments",
                "violation",
                "Use annotations instead of type comments.",
                token.start[0],
            )
        if TODO.search(token.string):
            add(
                results,
                root,
                path,
                token,
                "todo-format",
                "review",
                "Use TODO: context - explanation with a traceable context link.",
                token.start[0],
            )
        if PYLINT.search(token.string):
            add(
                results,
                root,
                path,
                token,
                "ruff-suppression",
                "review",
                "Review whether this Pylint suppression should be replaced with scoped Ruff syntax.",
                token.start[0],
            )
        if "`" in text or ":class:" in text:
            add(
                results,
                root,
                path,
                token,
                "comment-markup",
                "violation",
                "Comments must not contain backticks or Sphinx class markup.",
                token.start[0],
            )
    for block in _comment_blocks(comments, lines):
        last = block[-1]
        text = last.string.lstrip("#").strip()
        if section_or_fold_comment(text):
            continue
        if not text.endswith("."):
            add(
                results,
                root,
                path,
                last,
                "comment-punctuation",
                "violation",
                "Code comments must end with a period.",
                last.start[0],
            )
    return results


def audit(path, root):
    """Audit one Python file.

    Args:
        path: Source path.
        root: Audit root.
    Returns:
        Findings for the file.
    """
    try:
        with tokenize.open(path) as source_file:
            source = source_file.read()
    except (OSError, UnicodeError, SyntaxError) as error:
        return [
            Finding(
                "violation",
                "source-read",
                path.relative_to(root).as_posix(),
                1,
                1,
                f"Could not read source: {error}.",
            )
        ]
    results = token_findings(source, root, path)
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        results.append(
            Finding(
                "violation",
                "syntax",
                path.relative_to(root).as_posix(),
                error.lineno or 1,
                error.offset or 1,
                error.msg,
            )
        )
    else:
        visitor = Visitor(
            root, path, confirmed_class_usages(tree), type_alias_bindings(tree)
        )
        visitor.visit(tree)
        results.extend(visitor.results)
        if ast.get_docstring(tree) is None:
            results.append(
                Finding(
                    "violation",
                    "module-docstring",
                    path.relative_to(root).as_posix(),
                    1,
                    1,
                    "Add a module docstring.",
                )
            )
        else:
            doc_findings(results, root, path, tree, "module")
    return results


def main():
    """Emit JSON-lines findings and return nonzero for violations.

    Returns:
        Process exit status: 0 when clean, 1 when any violation was found.
        An unusable --root exits 2 through argparse instead.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd())
    root = parser.parse_args().root.resolve()
    # The caller derives --root from pyproject.toml, setup.py or src/, so a bad
    # guess is the expected failure mode. Every one below used to scan nothing
    # and exit 0, which reads as a clean audit rather than as a missed one.
    if not root.exists():
        parser.error(f"--root does not exist: {root}")
    if not root.is_dir():
        parser.error(f"--root must be a directory, not a file: {root}")
    paths = sorted(
        path
        for path in root.rglob("*.py")
        if not any(part.lower() in EXCLUDED for part in path.relative_to(root).parts)
    )
    if not paths:
        parser.error(f"--root contains no Python files to check: {root}")
    findings = [finding for path in paths for finding in audit(path, root)]
    for finding in findings:
        print(json.dumps(dataclasses.asdict(finding), sort_keys=True))
    violations = sum(finding.level == "violation" for finding in findings)
    print(
        f"Checked {len(paths)} Python files: {violations} violations.", file=sys.stderr
    )
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
