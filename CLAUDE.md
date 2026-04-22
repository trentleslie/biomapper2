# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Build and Development Commands

```bash
# Install dependencies (uses uv package manager)
uv sync --dev

# Run all code quality checks (ruff, black, pyright, pytest)
./scripts/check.sh

# Auto-fix formatting and linting issues
./scripts/fix.sh

# Run tests
uv run pytest           # All tests
uv run pytest -v        # Verbose output
uv run pytest -vs       # Verbose with logging/prints
uv run pytest tests/test_specific.py::test_name  # Single test

# Run examples
uv run python examples/basic_entity_kg_mapping.py
uv run python examples/basic_dataset_kg_mapping.py

# Add dependencies
uv add <package-name>  # Then commit both pyproject.toml and uv.lock
```

## Code Quality Tools

- **Black**: Formatter (line-length: 120)
- **Ruff**: Linting and import sorting (line-length: 120)
- **Pyright**: Type checking

All tools are configured in `pyproject.toml`.

## Architecture

biomapper2 maps biological entities (metabolites, proteins, etc.) to knowledge graph nodes through a four-step pipeline:

```
Input Entity → Annotation → Normalization → Linking → Resolution → Mapped Entity
```

### Pipeline Steps (all in `src/biomapper2/core/`)

1. **Annotation** (`annotation_engine.py`): Assigns additional vocabulary IDs via external APIs. Uses annotator plugins in `annotators/` that implement `BaseAnnotator`. The engine selects annotators based on entity type (metabolite, protein, etc.).

2. **Normalization** (`normalizer/normalizer.py`): Converts local IDs to Biolink-standard CURIEs. Validates IDs against regex patterns using `validators.py` and `vocab_config.py`.

3. **Linking** (`linker.py`): Maps CURIEs to knowledge graph node IDs via the Kestrel API.

4. **Resolution** (`resolver.py`): Resolves one-to-many KG matches by voting (CURIE support count).

### Adding New Annotators

To add a new annotator (e.g., for Metabolomics Workbench API):
1. Create a new file in `src/biomapper2/core/annotators/` (e.g., `mw_api.py`)
2. Implement `BaseAnnotator` abstract class with required methods:
   - `get_annotations()`: Single entity annotation
   - `get_annotations_bulk()`: Bulk annotation for DataFrames
3. Register in `AnnotationEngine._select_annotators()` for appropriate entity types

### Key Entry Points

- `Mapper.map_entity_to_kg()`: Single entity mapping
- `Mapper.map_dataset_to_kg()`: Bulk dataset mapping from TSV files

### Data Flow

- **Provided IDs**: User-supplied identifiers (e.g., KEGG, PubChem)
- **Assigned IDs**: IDs obtained via annotation APIs
- Both are normalized to CURIEs, linked to KG, then merged

### Configuration

`src/biomapper2/config.py` contains:
- `KESTREL_API_URL`: Knowledge graph API endpoint
- `BIOLINK_VERSION_DEFAULT`: Biolink model version
- `KESTREL_API_KEY`: Required environment variable (from `.env`)

## Development Workflow

- Create feature branches from `main`
- Submit pull requests back to `main` (no direct commits to `main`)
- All PRs require passing tests before merge
- Once merged, auto-sync to arpanauts via GitHub Action

## Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

Type | Description | Example
-- | -- | --
feat: | New features | feat: add protein annotation support
fix: | Bug fixes | fix: resolve DataFrame corruption in Step 3
docs: | Documentation only | docs: update installation instructions
test: | Test additions/changes | test: add unit tests for harmonization pipeline
refactor: | Code restructuring (no behavior change) | refactor: extract validation logic to separate module
chore: | Dependency updates, tooling | chore: update pandas to 2.2.0

## Code Style

- Use type hints
- Add docstrings for public functions and classes

Example:
```python
def harmonize_phenotype(raw_data: pd.DataFrame, schema: str) -> pd.DataFrame:
    """
    Harmonize phenotype data to target schema.

    Args:
        raw_data: Input DataFrame with raw phenotype measurements
        schema: Target harmonization schema name

    Returns:
        Harmonized DataFrame with standardized columns
    """
    ...
```

## IDE Setup (Optional)

For real-time checking in your IDE, install these extensions/plugins:
- **Ruff** - For inline linting warnings
- **Black** - For format-on-save (VS Code users: install extension from ms-python)
- **Pyright** (optional) - For real-time type checking

Exact installation steps vary by IDE.

## Project Tracking

- Use GitHub Issues for task tracking
- Move cards across Kanban board:
  - Backlog → Ready → In progress → In review → Done
- Link PRs to issues: `Closes #42` in PR description
- Label issues: `bug`, `enhancement`, `documentation`, `planning`

## Dependency Management

When adding dependencies, always commit both files:
```bash
uv add <package-name>
git add pyproject.toml uv.lock
git commit -m "chore: add <package-name> dependency"
```

---

## Biomapper Architecture Patterns

### Separation of Concerns

| Component | Responsibility | Does NOT do |
|-----------|---------------|-------------|
| **Annotators** | Fetch raw data from APIs, return raw field names | Vocab name mapping, ID cleaning |
| **Normalizer** | Map field names to standard vocabs, clean IDs, validate | API calls |
| **Linker** | Map CURIEs to KG nodes | Normalization |

### Annotator Guidelines

When implementing annotators:

1. **Use raw API field names** - Return field names exactly as the API provides them (e.g., `pubchem_cid`, not `pubchem.compound`)
2. **Don't clean IDs** - Don't strip prefixes like "RM" from refmet_id; the Normalizer handles this
3. **Grab all available fields** - Include all ID fields the API returns, not just a subset
4. **Reference existing annotators** - Use `kestrel_text.py` as a pattern example

### Before Submitting PRs

1. **Merge latest main**: `git fetch origin main && git merge origin/main`
2. **Check for duplicates** in pyproject.toml dependencies
3. **Run quality checks**: `./scripts/check.sh`
4. **Verify patterns** match existing annotators (raw field names, no ID cleaning)
5. **Commit both files** when adding dependencies: `pyproject.toml` and `uv.lock`
6. **Test requirements** for new features:
   - **Target: 8 or fewer tests** per feature/component in a single test file
   - Group tests in single class: `TestFeatureName`
   - Include at least one end-to-end test using `Mapper.map_entity_to_kg()`
   - Mark integration tests with `@pytest.mark.integration`
   - Required test types: unit tests (mocked), edge case tests, integration test (real API if applicable), end-to-end test

---

## Claude Code Workflow

### PR Comments and External Communications

- Always review Claude's proposed PR comments BEFORE they are posted
- Say "show me the comment first" or "let me review before posting"
- Claude should present comment drafts for approval

### Code Review Workflow

1. Claude implements changes
2. Claude runs `./scripts/check.sh`
3. Claude shows you the diff for review
4. Claude drafts PR comment for your review
5. You approve → Claude posts and pushes

### Before Finalizing

- **Use /pr-prep**: Run the PR preparation checklist before finalizing
