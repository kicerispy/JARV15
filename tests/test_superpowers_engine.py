from datetime import date

from superpowers_engine import (
    CORE_SKILLS,
    SUPERPOWERS_VERSION,
    artifact_paths,
    classify_software_request,
    planner_directives,
    status,
)


def test_superpowers_version_and_skill_surface():
    assert SUPERPOWERS_VERSION == "6.4.1"
    assert len(CORE_SKILLS) == 12
    current = status()
    assert current["native_adapter"] is True
    assert current["skill_count"] == len(CORE_SKILLS)
    assert all(item["available"] for item in current["skills"])


def test_repair_requests_use_debugging_tdd_and_verification():
    workflow = classify_software_request(
        "debug and repair browser_controller.py"
    )
    assert workflow is not None
    assert workflow.classification == "bounded"
    assert "systematic-debugging" in workflow.skills
    assert workflow.requires_tdd is True
    assert workflow.requires_verification is True


def test_architectural_requests_require_design_and_plan():
    workflow = classify_software_request(
        "integrate a new autonomous coding subsystem with planning, testing, "
        "code review, and branch management"
    )
    assert workflow is not None
    assert workflow.classification == "architectural"
    assert workflow.requires_design is True
    assert workflow.requires_plan is True
    assert "brainstorming" in workflow.skills
    assert "writing-plans" in workflow.skills
    assert "verification-before-completion" in workflow.skills


def test_non_software_conversation_is_not_governed_by_superpowers():
    assert classify_software_request("tell me a joke") is None
    assert planner_directives("what is the weather?") == ""


def test_planner_directives_include_evidence_and_validation_rules():
    text = planner_directives("fix the broken planner.py tests")
    assert "SUPERPOWERS WORKFLOW" in text
    assert "evidence" in text.lower()
    assert "validation" in text.lower()


def test_artifact_paths_are_project_local():
    paths = artifact_paths(
        "integrate a new subsystem",
        today=date(2026, 9, 24),
    )
    assert paths["spec"].startswith("docs/superpowers/specs/2026-09-24-")
    assert paths["plan"].startswith("docs/superpowers/plans/2026-09-24-")


def test_architecture_terms_are_classified_as_software_work():
    workflow = classify_software_request("integrate a new subsystem")
    assert workflow is not None
    assert workflow.classification == "architectural"
    assert workflow.requires_design is True
    assert workflow.requires_plan is True



def test_read_only_project_file_lookup_is_not_governed_by_superpowers():
    assert classify_software_request(
        "find browser_controller.py in my project"
    ) is None


def test_read_only_code_explanation_is_not_misclassified_as_architectural():
    assert classify_software_request(
        "inspect planner.py and explain how the Superpowers workflow is integrated"
    ) is None


def test_read_only_python_file_inspection_does_not_invoke_superpowers():
    assert classify_software_request(
        "inspect main.py"
    ) is None

def test_architectural_signal_requires_a_real_word_boundary():
    workflow = classify_software_request(
        "integrate a new autonomous coding subsystem"
    )
    assert workflow is not None
    assert workflow.classification == "architectural"
