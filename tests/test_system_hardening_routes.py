def test_tool_contract_audit_has_deterministic_fast_route():
    from commands import get_fast_command

    plan = get_fast_command("audit tool registry")

    assert plan == {
        "steps": [
            {
                "tool": "tool_contract_audit",
                "argument": "",
            }
        ]
    }


def test_integration_health_includes_tool_contract(monkeypatch):
    import integration_health

    monkeypatch.setattr(
        integration_health,
        "_tool_contract_component",
        lambda: integration_health._component(
            "Tool Contract",
            "READY",
            "registry is aligned",
        ),
    )

    result = integration_health.integration_health(
        '{"include_optional": false, "probe": false}'
    )
    names = {item["name"] for item in result["components"]}

    assert "Tool Contract" in names
