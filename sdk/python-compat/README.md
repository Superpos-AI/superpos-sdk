# apiary-sdk (transitional stub)

**This package has been renamed to [`superpos-sdk`](https://github.com/Superpos-AI/superpos-sdk).**

Installing `apiary-sdk` will now pull in `superpos-sdk` automatically.
No code is shipped by this package -- the real SDK (including the
backward-compatible `apiary_sdk` import shim) lives entirely in
`superpos-sdk`.

## Migration

Update your dependency declarations:

```diff
- apiary-sdk
+ superpos-sdk
```

All existing `from apiary_sdk import ...` imports continue to work
after switching to `superpos-sdk` -- no code changes required.

## Why does this package exist?

When a PyPI distribution is renamed the old name stops resolving.
This stub keeps `pip install apiary-sdk` working by declaring a
dependency on the new name, following the standard PyPI rename
pattern (cf. `sklearn` -> `scikit-learn`).
