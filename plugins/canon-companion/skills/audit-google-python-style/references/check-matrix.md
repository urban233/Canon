# Google Python Style Audit Matrix

| Rule family | Owner | Severity | Exemptions and evidence |
| --- | --- | --- | --- |
| Syntax and unreadable source | Supplemental checker | violation | None; standard library only. |
| One module/symbol per import; no wildcard imports | Supplemental checker | violation | None. |
| Import modules rather than classes | Supplemental checker plus actor | violation | `typing`, `typing_extensions`, `collections.abc`, and `six.moves` are exempt. A PascalCase name is flagged only when a constructor call or base-class use confirms it is a class rather than a module. |
| PascalCase classes; snake_case functions/methods/parameters/bindings; no `tmp_` | Checker plus actor | violation | Dunder/private names, uppercase constants, and exact AST visitor overrides are exceptions. |
| Mutable function defaults | Supplemental checker | violation or review | Literals, comprehensions, and confirmed built-in constructors violate the rule; uncertain constructors require review. |
| Docstrings and summaries | Supplemental checker plus actor | violation | Modules, classes, public/private functions and methods; summaries and section descriptions end with periods. |
| Args completeness | Supplemental checker | violation | Positional-only, positional, keyword-only, `*args`, and `**kwargs`; `self`/`cls` excluded. |
| Returns/Yields completeness | Supplemental checker | violation | Current scope plus non-None value annotations; nested scopes excluded. |
| Raises completeness and matching | Supplemental checker | violation | Current scope only; named/qualified forms match by leaf or qualified name. |
| Forbidden markup | Supplemental checker | violation | Leading comments are excluded; later comments and all docstrings are checked. |
| Comment punctuation | Supplemental checker | violation | Leading comments and exact fold/region/separator markers are excluded. |
| Supplemental review rules | Supplemental checker | review/violation | Type comments, TODO format, broad exceptions, assertions, lambdas, state, legacy aliases, nested definitions, and size/readability findings. |
| Exclusions | Supplemental checker | policy | Case-insensitive `.agents`, caches, build output, generated, vendor, site-packages, and related components. |
| Ruff lint and formatting | Repository wrapper | report separately | Never run Pylint; report unavailable wrappers honestly. |
| Types and contextual design | Actor judgment | review | Exceptions, state, resources, APIs, and behavior require repository context. |

## Independent Coverage Boundary

The checker and this skill own general import, naming, documentation, comment,
exclusion, and supplemental-review rules. Scope approvals and diff evidence
belong to the workflow. Eval fixture paths, Git allowlists, and oracle output
belong only to the evaluation harness and must not be reproduced by this skill.
