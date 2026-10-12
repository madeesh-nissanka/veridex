# VERIDEX policy file

A policy file turns an audit into a machine-checkable gate (pre-commit hook,
GitHub Action, local CI). YAML is the primary format; the same mapping may be
given as JSON (`policy.json`). Example: `examples/policy.yaml`.

```yaml
fail_on:                      # any of these statuses/flags present -> exit 1
  - RETRACTED
  - DOI_NOT_FOUND
max_fabrication_score: 0.35   # fail if any reference scores above this (0..1)
max_weak_context_ratio: 0.5   # max share of references with weak citation context
min_verified_ratio: 0.5       # minimum share of references with VERIFIED status
required_fields:              # every input reference must carry these
  - title
  - year
allowed_venues: []            # empty = no allow-list; otherwise block all others
blocked_venues:               # matched case-insensitively against venue/journal
  - Predatory Reports Quarterly
```

## Evaluation and exit codes

```bash
veridex audit refs.bib --policy examples/policy.yaml   # gate the audit itself
veridex policy examples/policy.yaml --json             # validate the policy file
echo $?
```

| exit | meaning |
|---|---|
| 0 | policy valid / audit satisfies policy |
| 1 | audit violates the policy (`fail_on`, thresholds, missing required fields, blocked venue) |
| 2 | policy file unreadable or malformed |

Violations are listed one per line (and under the `violations` key in
`--json`), each naming the rule, so CI logs explain *why* the build failed.

## CI usage

`ci/github-actions-ci.yml` runs the offline suite (`pytest -q`) and then
`veridex audit examples/refs.bib --policy examples/policy.yaml` as a smoke
gate. The same pattern works in any runner that can execute `veridex`; see
`SKILL.md` and `.pre-commit-config.yaml` for the hook variant.
