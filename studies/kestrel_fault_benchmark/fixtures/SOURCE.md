# Fixture Provenance and Licensing

## Vendored Biolink Model Files

Repository: `https://github.com/biolink/biolink-model`

Upstream licence metadata in `biolink/biolink-model`:
- Repository `LICENSE` file (`https://github.com/biolink/biolink-model/blob/v4.2.5/LICENSE` and `v4.2.2/LICENSE`): **Apache License, Version 2.0** (`http://www.apache.org/licenses/LICENSE-2.0`).
- Schema header inside `biolink-model.yaml` (`line 5`): **CC0 1.0 Universal** (`https://creativecommons.org/publicdomain/zero/1.0/`).
- Package metadata in `pyproject.toml` (`line 6` at `v4.2.5`): **`MIT`**.

Pinned files in this directory:

1. `biolink-model_4.2.5.yaml`
   - Upstream URL: `https://raw.githubusercontent.com/biolink/biolink-model/refs/tags/v4.2.5/biolink-model.yaml`
   - Version / tag: `v4.2.5`
   - Commit SHA: `57345faddc36b127648292dd8c20bb9e9cf2b149`
   - SHA-256: `8284cb90dbabc0ab71e695f698b26b08c79508a843dfd9b28788596e06afadaf`
   - Licence: CC0-1.0 (in-file LinkML `license:` header) / Apache-2.0 (repository `LICENSE`)

2. `biolink-model-prefix-map_4.2.5.json`
   - Upstream URL: `https://raw.githubusercontent.com/biolink/biolink-model/refs/tags/v4.2.5/project/prefixmap/biolink-model-prefix-map.json`
   - Version / tag: `v4.2.5`
   - Commit SHA: `57345faddc36b127648292dd8c20bb9e9cf2b149`
   - SHA-256: `5faf5d1899d4b56ae83e4a1c5ee84bbf05bdd724de7ae244a43aa6239464c4b9`
   - Licence: Apache-2.0 (repository `LICENSE`; formatted with `json.dumps(..., indent=2)` matching `BiolinkClient._load_biolink_file`)

3. `biolink-predicate-mapping.yaml`
   - Upstream URL: `https://raw.githubusercontent.com/biolink/biolink-model/v4.2.2/predicate_mapping.yaml`
   - Version / tag: `v4.2.2` (the default `PREDICATE_MAP` target in `bmt==1.4.6`)
   - Commit SHA: `6a6adc35597b5e82c8f5b61b420e0ae1b6ffb9ba`
   - SHA-256: `0cf83888b7a3f45fe9cf11b48f360df9cc0a4e3b2c43afc6ff741886a4bd297d`
   - Licence: Apache-2.0 (repository `LICENSE`)
