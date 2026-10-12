# Contributing to VERIDEX

Thank you for your interest in contributing to VERIDEX!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/madeesh-nissanka/veridex.git`
3. Install development dependencies: `pip install -e ".[dev]"`
4. Run tests: `pytest -q`

## Development Guidelines

### Code Style
- Python 3.10+ with type hints everywhere
- Stdlib-only core (no required external dependencies)
- Every source and test file must start with the header:
  ```python
  # VERIDEX v0.2.0 - reference validation and provenance auditing.
  # Copyright (c) 2026 Madeesh P. Nissanka
  # MIT License - see LICENSE file.
  ```
- Deterministic output: sort where iteration order could vary
- No wall-clock timestamps outside ledger records

### Testing
- All unit tests must run offline (no network)
- Use the injected `TRANSPORT` pattern for HTTP mocking
- Test fixtures must be synthetic or clearly generic public data
- Run full test suite before submitting: `pytest -q`

### Examples and Data
- Use textbook-level engineering topics (soil consolidation, beam deflection, slope stability, concrete durability, pavement fatigue, heat conduction) or non-engineering topics (baking bread, bird migration, chess endgames)
- Never include: email addresses, institutional or departmental affiliations, names of advisors or colleagues, unpublished research material, project or application names, absolute machine paths

### Commit Messages
- Clear, concise subject line
- Reference issue numbers where applicable

## Pull Request Process

1. Ensure all tests pass (`pytest -q`)
2. Update CHANGELOG.md with your changes
3. Update documentation if needed (README.md, SKILL.md)
4. Submit PR with a clear description of changes

## Reporting Issues

- Use the GitHub issue tracker
- Include steps to reproduce, expected vs actual behavior
- For network-related issues, note which source adapter(s) are affected

## Code of Conduct

Be respectful and constructive. This project follows standard open-source community norms.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.