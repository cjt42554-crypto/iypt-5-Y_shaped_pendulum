from copy import deepcopy

import pytest

from yps_experiment_pipeline.contracts import (
    SCHEMA_ROOT,
    TEMPLATE_ROOT,
    ContractError,
    assert_no_fake_measurements,
    assert_templates_are_human_unset,
    load_json,
    load_schema,
    validate_all_templates,
    validate_document,
)


def test_all_schemas_self_validate_and_templates_validate():
    for path in sorted((TEMPLATE_ROOT.parent / "schemas").glob("*.schema.json")):
        load_schema(path.name)
    result = validate_all_templates()
    assert len(result) == 5
    assert set(result.values()) == {"VALID"}


def test_contract_roots_can_be_supplied_explicitly_for_installed_cli():
    result = validate_all_templates(schema_root=SCHEMA_ROOT, template_root=TEMPLATE_ROOT)
    assert len(result) == 5


def test_unknown_key_fails_closed():
    document = load_json(TEMPLATE_ROOT / "apparatus_measurements.template.json")
    document["unexpected"] = True
    with pytest.raises(ContractError, match="unexpected"):
        validate_document("apparatus_measurements.schema.json", document)


def test_measured_without_raw_binding_fails_closed():
    document = load_json(TEMPLATE_ROOT / "apparatus_measurements.template.json")
    document["data_origin"] = "MEASURED_BUNDLE"
    document["apparatus_revision"] = "REAL_RIG_V1"
    record = deepcopy(document["measurements"][0])
    record["source_type"] = "MEASURED"
    record["raw_repeats"] = [[1.0, 2.0, 3.0]]
    record["value_si"] = [1.0, 2.0, 3.0]
    record["type_a_standard_uncertainty"] = [0.1, 0.1, 0.1]
    record["type_b_standard_uncertainty"] = [0.1, 0.1, 0.1]
    record["combined_standard_uncertainty"] = [0.2, 0.2, 0.2]
    record["covariance_si"] = [[0.01, 0.0, 0.0], [0.0, 0.01, 0.0], [0.0, 0.0, 0.01]]
    record["instrument_id"] = "REAL_INSTRUMENT"
    record["calibration_ref"] = "REAL_CALIBRATION"
    record["timestamp"] = "2030-01-01T00:00:00Z"
    document["measurements"] = [record]
    with pytest.raises(ContractError, match="raw_data_sha256"):
        validate_document("apparatus_measurements.schema.json", document)
    with pytest.raises(ContractError, match="raw_data_sha256"):
        assert_no_fake_measurements(document)


def test_committed_templates_contain_no_measured_claims():
    assert_templates_are_human_unset()


def test_derived_record_requires_derivation_binding():
    document = load_json(TEMPLATE_ROOT / "apparatus_measurements.template.json")
    document["data_origin"] = "MEASURED_BUNDLE"
    document["apparatus_revision"] = "REAL_RIG_V1"
    record = deepcopy(document["measurements"][0])
    record["source_type"] = "DERIVED_FROM_MEASURED"
    record["value_si"] = [1.0, 2.0, 3.0]
    record["derivation"] = None
    document["measurements"] = [record]
    with pytest.raises(ContractError, match="derivation"):
        validate_document("apparatus_measurements.schema.json", document)
