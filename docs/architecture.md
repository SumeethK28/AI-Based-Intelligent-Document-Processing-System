# Current application documentation

- [System architecture and permissions](architecture/system.md)
- [Installation, onboarding and storage](architecture/operations.md)
- [Implemented algorithms](algorithms/processing.md)

React/TypeScript and FastAPI are the active application. These guides describe the current single-organization implementation. Older milestone guides and the original architecture guide are preserved privately in data/archives/documentation_20261016/; use these current guides for operation.

The active local installation selects data/operational/organization.db through private IDP_DATABASE_PATH configuration. The code fallback remains data/idp.db if no configuration is supplied. Historical databases and retained sources remain preserved. No default accounts or demonstration records are imported.
