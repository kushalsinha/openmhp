## What does this change

A short description of the change and why it's needed.

## Type of change

- [ ] Bug fix
- [ ] New feature (adapter, driver, CLI capability)
- [ ] Protocol / spec change (SPEC.md)
- [ ] Documentation only
- [ ] Test / conformance coverage

## Checklist

- [ ] I opened an issue to discuss this first, for anything beyond a small fix (see CONTRIBUTING.md)
- [ ] Tests pass locally: `python tests/test_adapters.py && python tests/test_runs.py && python tests/test_safety_gates.py && python tests/test_methods.py`
- [ ] I added or updated tests for this change
- [ ] If this touches safety gates, state, jobs, leases, or concurrency, I added regression coverage for that specifically
- [ ] If this changes wire-level or adapter behavior, I documented the compatibility impact
- [ ] SPEC.md is updated if this changes normative protocol behavior

## Related issues

Closes #
