This is an aaPanel plugin.

## Versioning

`info.json`'s `versions` field must follow [semantic versioning](https://semver.org) (`MAJOR.MINOR.PATCH`).

On **every** change to this plugin, bump `versions` in `info.json` as part of the same commit:

- **PATCH** (`x.y.Z`) — bug fixes, internal refactors, no user-visible behavior change.
- **MINOR** (`x.Y.0`) — new backward-compatible functionality (new plugin actions, new UI, new options).
- **MAJOR** (`X.0.0`) — breaking changes (removed/renamed actions, incompatible config/data format changes).

Never leave `versions` unchanged when other files in this plugin are modified.
