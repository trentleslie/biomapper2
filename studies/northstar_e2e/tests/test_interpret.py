import pandas as pd

from studies.northstar_e2e import interpret
from studies.northstar_e2e.grounding import GroundedPathways


def test_interpret_returns_structured_answer(fake_llm_fn):
    grounded = GroundedPathways(("map00280", "map00010"), {"map00280": ["x"], "map00010": ["y"]})
    measurements = pd.DataFrame({"metabolite_name": ["dextrose"], "direction": ["up"]})
    out = interpret.interpret(
        grounded,
        measurements,
        "which pathways?",
        fake_llm_fn,
        name_col="metabolite_name",
        dir_col="direction",
    )
    assert isinstance(out, interpret.Interpretation)
    assert set(out.ranked_pathways) == {"map00280", "map00010"}
    assert out.disease_label == "type 2 diabetes"


def test_prompt_includes_candidates_and_measurements():
    grounded = GroundedPathways(("map00020",), {"map00020": ["z"]})
    measurements = pd.DataFrame({"metabolite_name": ["citric acid"], "direction": ["down"]})
    prompt = interpret.build_prompt(grounded, measurements, "Q?", name_col="metabolite_name", dir_col="direction")
    assert "map00020" in prompt
    assert "citric acid" in prompt
    assert "down" in prompt


def test_interpret_filters_to_known_map_ids(fake_llm_fn):
    # A hallucinated non-candidate pathway from the llm_fn is dropped.
    grounded = GroundedPathways(("map00280",), {"map00280": ["x"]})
    measurements = pd.DataFrame({"metabolite_name": ["valine"], "direction": ["up"]})

    def liar(_prompt):
        return {"ranked_pathways": ["map00280", "map99999"], "disease_label": "t2d"}

    out = interpret.interpret(grounded, measurements, "Q?", liar, name_col="metabolite_name", dir_col="direction")
    assert out.ranked_pathways == ("map00280",)
