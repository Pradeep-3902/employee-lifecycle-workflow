# Source Manifest

## 1. Dataset Provenance

The dataset is generated entirely by this repository's synthetic data generator.

- **External data:** None. No public dataset was downloaded, copied, transformed, or redistributed.
- **Personal or confidential information:** None. Employee and manager records use synthetic identifiers and generic labels.
- **Default seed:** `20261022`
- **Default base date:** `2026-10-22`
- **Default employee count:** `500`

The generated records are intended for application development, workflow testing, validation, and challenge evaluation. They do not represent actual employees or real organizational records.

## 2. Generation Components

- **Data generator:** `generator/generate_data.py`
- **Anomaly injector:** `generator/inject_anomalies.py`
- **Ground-truth labels:** `data/ground_truth.csv`

The generator uses a fixed seed to support deterministic output. The employee count is configurable, and the generator is intended to apply consistent generation rules across supported dataset sizes.

The anomaly injector creates explicitly labelled synthetic exceptions for challenge evaluation. The operational anomaly-detection service should identify issues from operational records independently of the ground-truth labels.

## 3. Generated Outputs

| Output | Location | Purpose |
|---|---|---|
| Normalized CSV files | `data/csv/` | Tabular datasets for inspection and evaluation |
| Per-entity JSON files | `data/json/` | Structured representations of generated entities |
| Ground-truth labels | `data/ground_truth.csv` | Expected challenge exceptions and handling |
| SQL seed | `data/seed.sql` | SQL-compatible generated dataset |
| SQLite database | `database/workflow.db` | Persistent application state |
| Source manifest JSON | `data/source_manifest.json` | Machine-readable provenance and generation settings |
| Reproducibility metadata | `data/reproducibility.json` | Seed, record counts, file count, and SHA-256 checksums |

The SQLite database supports application operations and persisted workflow changes. Generated CSV, JSON, and SQL outputs support inspection, data exchange, and reproducibility checks.

## 4. Reproducibility

The default generation configuration is:

- Seed: `20261022`
- Base date: `2026-10-22`
- Employees: `500`

From the project root, run:

```powershell
py generator/generate_data.py --employees 500 --seed 20261022
```

The repository's documented command should produce the expected outputs using the same generation configuration. If the generator accepts a base-date argument, use `2026-10-22` explicitly when reproducing a dataset with a different default date.

The recorded checksums in `data/reproducibility.json` should be verified against the actual generated files. A checksum mismatch can indicate changed content, changed generation logic, or a different generation configuration.

The reproducibility metadata should be regenerated whenever the underlying files change. Checksums should not be copied forward from an older dataset version.

## 5. Validation and Testing

Run the data validator from the project root:

```powershell
py validators/validate_data.py --employees 500 --seed 20261022
```

Run the automated test suite:

```powershell
py -m pytest -q
```

The validator and tests should be used to assess:

- Expected record counts and deterministic identifiers.
- Primary-key uniqueness and foreign-key relationships.
- Valid state values and effective-dated records.
- Task dependencies and workflow prerequisites.
- Access approval and offboarding rules.
- SLA consistency and required anomaly coverage.
- Reproducibility metadata and file checksums, where supported by the implementation.

Validation results must be reported from actual command output. The presence of this document does not itself establish that the generator, validator, or tests pass.

## 6. External Sources and Licensing

No external dataset or source material was used to create the synthetic employee records.

Accordingly, no external source URL, dataset version, retrieval date, external dataset license, attribution, or discarded source fields apply.

This statement concerns the generated dataset's provenance. It does not replace the licensing obligations of third-party software dependencies used by the application.

## 7. Maintenance

Update this manifest when any of the following changes:

- The generator or anomaly-injection process changes.
- The default seed, base date, or employee count changes.
- The generated output formats or locations change.
- The provenance or data-handling policy changes.
- The reproducibility metadata format changes.

Keep `docs/source_manifest.md`, `data/source_manifest.json`, and `data/reproducibility.json` consistent with the actual generation process and output files.
