"""Acquisition-time refusal of a gold accession column that is really a row index.

The defect this guards against was found in the certified-plasma delivery: an ``HMDB_ID`` column
whose values ran in file order, one per row, with the numeric parts forming the sequence one to n.
It has an accession's exact format, so every downstream consumer treated it as one, and the
identifier-based coverage figure computed from it read as a catastrophic resolver failure. It was
not a resolver result at all.

The structural rule is narrow on purpose: a gold accession column whose numeric parts are unique,
monotonically increasing, and exactly the sequence one to n is a row index wearing an accession's
format, and the run must refuse it rather than score against it. Genuine accession sets are unique
but not consecutive; a filtered subset of a genuine set has gaps. That distinction is what the
tests below pin, including the gotcha that a *filtered* subset can look sorted and consecutive-ish
while the full column is what actually decides.
"""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters.srm1950 import (
    RowIndexGoldColumnError,
    build_input_df,
    is_row_index_column,
)
from studies.external_benchmarks.config import SRM1950


class TestIsRowIndexColumn:
    def test_consecutive_from_one_is_a_row_index(self):
        values = [f"HMDB{i:07d}" for i in range(1, 21)]
        assert is_row_index_column(values) is True

    def test_genuine_accessions_are_not_a_row_index(self):
        """Real accessions are unique and unordered relative to the rows that carry them."""
        values = ["HMDB0000619", "HMDB0000626", "HMDB0000308", "HMDB0011131"]
        assert is_row_index_column(values) is False

    def test_sorted_but_non_consecutive_accessions_are_not_a_row_index(self):
        """The rule must not fire on a genuine set that merely happens to be sorted."""
        values = ["HMDB0000001", "HMDB0000042", "HMDB0000619", "HMDB0011131"]
        assert is_row_index_column(values) is False

    def test_duplicated_values_are_not_a_row_index(self):
        values = ["HMDB0000001", "HMDB0000001", "HMDB0000003"]
        assert is_row_index_column(values) is False

    def test_offset_sequence_is_not_flagged(self):
        """Only a sequence starting at one is a row index; an offset run is left alone."""
        values = [f"HMDB{i:07d}" for i in range(500, 520)]
        assert is_row_index_column(values) is False

    def test_blank_and_missing_values_do_not_crash(self):
        assert is_row_index_column(["", None, "HMDB0000001"]) is False

    def test_empty_column_is_not_a_row_index(self):
        assert is_row_index_column([]) is False

    def test_single_row_is_never_enough_evidence(self):
        """One row trivially satisfies "the sequence one to n"; that is not evidence."""
        assert is_row_index_column(["HMDB0000001"]) is False

    def test_a_filtered_subset_is_not_the_thing_to_check(self):
        """The routed gotcha, pinned.

        A filtered subset of the corrupt column shows gaps and looks like a genuine sorted
        accession set. Only the full column carries the evidence, which is why the guard runs at
        acquisition on the raw delivery and not on any downstream slice.
        """
        full = [f"HMDB{i:07d}" for i in range(1, 41)]
        subset = full[::3]
        assert is_row_index_column(full) is True
        assert is_row_index_column(subset) is False


class TestAcquisitionRefusesARowIndexGoldColumn:
    def _raw(self, hmdb_values: list[str]) -> pd.DataFrame:
        n = len(hmdb_values)
        return pd.DataFrame(
            {
                "NAME": [f"metabolite {i}" for i in range(n)],
                "SMILES": ["CCO"] * n,
                "INCHIKEY": [""] * n,
                "HMDB_ID": hmdb_values,
            }
        )

    def test_run_fails_loudly_on_a_row_index_gold_column(self):
        raw = self._raw([f"HMDB{i:07d}" for i in range(1, 16)])
        with pytest.raises(RowIndexGoldColumnError) as exc:
            build_input_df(raw, SRM1950)
        assert "row index" in str(exc.value).lower()

    def test_run_proceeds_on_genuine_accessions(self):
        raw = self._raw(["HMDB0000619", "HMDB0000626", "HMDB0000308"])
        out = build_input_df(raw, SRM1950)
        assert len(out) == 3


class TestGoldHmdbIsDropped:
    def test_adapter_no_longer_emits_the_column(self):
        """Dropped, not quarantined: a present-but-untrusted gold column is a trap for the next
        person who greps for a gold identifier. A column that does not exist cannot be misread."""
        raw = pd.DataFrame(
            {
                "NAME": ["Cholic acid", "Caffeine"],
                "SMILES": ["CCO", "CCC"],
                "INCHIKEY": ["", ""],
                "HMDB_ID": ["HMDB0000619", "HMDB0000058"],
            }
        )
        out = build_input_df(raw, SRM1950)
        assert "gold_hmdb" not in out.columns

    def test_config_no_longer_advertises_it_as_gold_coverage(self):
        assert all(column != "gold_hmdb" for _, column in SRM1950.gold_coverage_columns)
        assert all(namespace != "HMDB" for namespace, _ in SRM1950.gold_coverage_columns)

    def test_structure_oracle_columns_are_untouched(self):
        """Blast radius bound: the scoring path never read the dropped column, so accuracy is
        unaffected by the drop and needs no re-run. Only identifier-based coverage changes."""
        assert SRM1950.gold_inchikey_column == "gold_inchikey"
        assert SRM1950.gold_smiles_column == "gold_smiles"
        assert SRM1950.gold_chebi_column == ""
