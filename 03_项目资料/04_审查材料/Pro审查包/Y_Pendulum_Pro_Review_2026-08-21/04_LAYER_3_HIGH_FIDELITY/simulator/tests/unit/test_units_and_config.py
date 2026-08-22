import copy
import numpy as np
import pytest
from ypendulum.config import ConfigurationError, load_config, resolved_config_dict
from ypendulum.config.units import UnitError, as_vector3, to_si


def _hf_mapping(config_dict, *, claim_level="VERIFIED"):
    data = copy.deepcopy(config_dict)
    data["run"]["mode"] = "high_fidelity"
    data["run"]["claim_level"] = claim_level
    data["initial_condition"] = {"type": "static_equilibrium"}
    return data

def test_unit_conversion_and_dimension_check():
    assert to_si({"value":12.0,"unit":"cm"},default_unit="m")==pytest.approx(0.12)
    assert to_si({"value":"200","unit":"g"},default_unit="kg")==pytest.approx(0.2)
    assert to_si({"value":180.0,"unit":"degree"},default_unit="rad")==pytest.approx(np.pi)
    with pytest.raises(UnitError): to_si({"value":1.0,"unit":"kg"},default_unit="m")
    with pytest.raises(UnitError): to_si({"value":True,"unit":"kg"},default_unit="kg")
    with pytest.raises(UnitError): to_si({"value":[1.0,False],"unit":"m"},default_unit="m")
    with pytest.raises(UnitError):
        to_si({"value":"200 g","unit":"kg"},default_unit="kg")
    with pytest.raises(UnitError, match="Unknown quantity metadata fields"):
        to_si({"value": 1.0, "unit": "m", "typo_unit": "cm"}, default_unit="m")

def test_vector_shape_check():
    assert np.allclose(as_vector3({"value":[1,2,3],"unit":"cm"},default_unit="m"),[.01,.02,.03])
    with pytest.raises(UnitError): as_vector3({"value":[1,2],"unit":"m"},default_unit="m")

def test_cable_inheritance_and_resolved_newmark(config_dict):
    cfg=load_config(config_dict); assert cfg.cables.upper_B.rest_length==cfg.cables.upper_A.rest_length
    assert resolved_config_dict(cfg)["solver"]["newmark_force_tolerance"]==pytest.approx(1e-7)

def test_invalid_mesh_and_newmark_parameters(config_dict):
    bad=copy.deepcopy(config_dict); bad["solver"]["allow_subminimum_mesh"]=False
    with pytest.raises(ConfigurationError): load_config(bad)
    bad=copy.deepcopy(config_dict); bad["solver"]["newmark_beta"]=0.1; bad["solver"]["newmark_gamma"]=0.5
    with pytest.raises(ValueError): load_config(bad)

def test_passive_drag_and_resource_contracts_fail_closed(config_dict):
    bad=copy.deepcopy(config_dict); bad["bob"]["drag"]["linear_coefficient"]={"value":-1,"unit":"N*s/m"}
    with pytest.raises(ConfigurationError): load_config(bad)
    bad=copy.deepcopy(config_dict); bad["environment"]["air_density"]={"value":-1,"unit":"kg/m^3"}
    with pytest.raises(ConfigurationError): load_config(bad)
    bad=copy.deepcopy(config_dict); bad["cables"]["upper_A"]["drag_linear_normal_per_length"]={"value":-1,"unit":"N*s/m^2"}
    with pytest.raises(ConfigurationError): load_config(bad)
    bad=copy.deepcopy(config_dict); bad["solver"]["output_dt"]={"value":1e-20,"unit":"s"}
    with pytest.raises(ConfigurationError): load_config(bad)

def test_hf_claim_and_native_material_boundaries(config_dict):
    bad=_hf_mapping(config_dict, claim_level="VALIDATED")
    bad["cables"]["upper_A"]["elements"]=12; bad["cables"]["lower"]["elements"]=20
    bad["run"]["validation_manifest"]="irrelevant.yaml"
    with pytest.raises(ConfigurationError, match="capped at VERIFIED"):
        load_config(bad)

    bad=_hf_mapping(config_dict)
    bad["cables"]["lower"]["material_model"]="tabulated_tension_extension"
    bad["cables"]["lower"]["table_file"]="not-used.csv"
    with pytest.raises(ConfigurationError, match="tabulated FWD materials"):
        load_config(bad)


def test_yaml_duplicate_keys_are_rejected_before_model_validation(tmp_path):
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        'schema_version: "1.0"\nschema_version: "1.0"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="Duplicate YAML mapping key"):
        load_config(path)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("cables", "upper_A", "elements"), "12"),
        (("solver", "rtol"), "1e-6"),
        (("high_fidelity", "bending_stiffness_scale"), "1.0"),
        (("high_fidelity", "bob_contact_radius_fraction"), "1.0"),
        (("run", "seed"), True),
    ],
)
def test_typed_fields_do_not_silently_coerce_strings_or_booleans(
    config_dict, path, value
):
    bad = copy.deepcopy(config_dict)
    cursor = bad
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value
    with pytest.raises(ValueError):
        load_config(bad)


def test_hf_bilateral_scale_and_controlled_limit_identity(config_dict):
    production = _hf_mapping(config_dict)
    production["high_fidelity"] = {
        "compression_regularization_scale": 1.0,
    }
    cfg = load_config(production)
    assert cfg.high_fidelity.controlled_limit_study is False
    assert cfg.high_fidelity.axial_material_model == (
        "passive_unilateral_bilateral_kelvin_voigt_blend"
    )
    replayed = load_config(resolved_config_dict(cfg))
    assert replayed.initial_condition.type == "static_equilibrium"
    assert replayed.initial_condition.model_fields_set == {
        "type",
        "bob_velocity",
        "bob_angular_velocity",
    }

    for field, value in (
        ("bending_stiffness_scale", 0.01),
        ("compression_regularization_scale", 0.01),
        ("bob_attachment_radius_fraction", 0.01),
        ("bob_contact_radius_fraction", 0.01),
    ):
        disguised = copy.deepcopy(production)
        disguised["high_fidelity"][field] = value
        with pytest.raises(ConfigurationError) as caught:
            load_config(disguised)
        assert caught.value.code == "HF_PRODUCTION_SCALE_IDENTITY_MISMATCH"
        assert field in caught.value.details["nonproduction_scales"]

    disguised = copy.deepcopy(production)
    disguised["high_fidelity"]["compression_regularization_scale"] = 0.01
    wrong_claim = copy.deepcopy(disguised)
    wrong_claim["high_fidelity"]["controlled_limit_study"] = True
    with pytest.raises(ConfigurationError, match="OUT_OF_SCOPE"):
        load_config(wrong_claim)

    controlled = _hf_mapping(config_dict, claim_level="OUT_OF_SCOPE")
    controlled["solver"]["allow_subminimum_mesh"] = False
    controlled["cables"]["upper_A"]["elements"] = 12
    controlled["cables"]["lower"]["elements"] = 20
    controlled["high_fidelity"] = {
        "compression_regularization_scale": 1.0e-4,
        "controlled_limit_study": True,
    }
    assert load_config(controlled).high_fidelity.controlled_limit_study is True

    exact_zero = copy.deepcopy(controlled)
    exact_zero["high_fidelity"]["compression_regularization_scale"] = 0.0
    with pytest.raises(ConfigurationError, match="mathematical endpoints"):
        load_config(exact_zero)

    subnormal = copy.deepcopy(controlled)
    for field in (
        "bending_stiffness_scale",
        "compression_regularization_scale",
        "bob_attachment_radius_fraction",
        "bob_contact_radius_fraction",
    ):
        subnormal["high_fidelity"][field] = 5.0e-324
    with pytest.raises(ConfigurationError, match="representable formal"):
        load_config(subnormal)

    controlled_held = copy.deepcopy(controlled)
    controlled_held["initial_condition"] = {
        "type": "held_endpoint_equilibrium_release",
        "junction_position": {"value": [0.0, 0.0, -0.42], "unit": "m"},
        "bob_position": {"value": [0.0, 0.0, -0.70], "unit": "m"},
    }
    controlled_held["solver"]["static"]["method"] = "energy_minimize"
    with pytest.raises(ConfigurationError) as caught:
        load_config(controlled_held)
    assert caught.value.code == "HF_HELD_PREPARATION_REQUIRES_BILATERAL_ROD"


def test_hf_contact_quaternion_and_inertia_contracts(config_dict):
    disabled = _hf_mapping(config_dict)
    disabled["high_fidelity"] = {"contact_guard_enabled": False}
    with pytest.raises(ConfigurationError, match="contact_guard_enabled=true"):
        load_config(disabled)

    configured = _hf_mapping(config_dict)
    configured["high_fidelity"] = {
        "quaternion_stabilization_rate": {"value": 2.5, "unit": "1/s"},
        "bob_inertia_factor": 2.0 / 3.0,
    }
    cfg = load_config(configured)
    assert resolved_config_dict(cfg)["high_fidelity"][
        "quaternion_stabilization_rate"
    ] == pytest.approx(2.5)

    wrong_unit = copy.deepcopy(configured)
    wrong_unit["high_fidelity"]["quaternion_stabilization_rate"] = {
        "value": 1.0,
        "unit": "m",
    }
    with pytest.raises((ConfigurationError, UnitError)):
        load_config(wrong_unit)

    excessive_inertia = copy.deepcopy(configured)
    excessive_inertia["high_fidelity"]["bob_inertia_factor"] = 0.667
    with pytest.raises(ValueError, match="2/3"):
        load_config(excessive_inertia)

    subnormal_inertia = copy.deepcopy(configured)
    subnormal_inertia["high_fidelity"]["bob_inertia_factor"] = 5.0e-324
    with pytest.raises(ConfigurationError) as caught:
        load_config(subnormal_inertia)
    assert caught.value.code == "HF_BOB_INERTIA_FACTOR_OUT_OF_EXECUTABLE_RANGE"

    unrepresentable_radius = copy.deepcopy(configured)
    unrepresentable_radius["bob"]["radius"] = {
        "value": 1.0e308,
        "unit": "m",
    }
    with pytest.raises(ConfigurationError) as caught:
        load_config(unrepresentable_radius)
    assert caught.value.code == "HF_DERIVED_PHYSICS_NOT_REPRESENTABLE"


@pytest.mark.parametrize(
    ("initial_type", "extra_field"),
    [
        ("restart", {"state_file": "unused.npz"}),
        ("direct_state", {"positions_file": "unused.npy"}),
        ("reduced_angles_release", {}),
    ],
)
def test_hf_unsupported_initial_protocols_fail_before_solver(
    config_dict, initial_type, extra_field
):
    bad = _hf_mapping(config_dict)
    bad["initial_condition"] = {"type": initial_type, **extra_field}
    with pytest.raises(ConfigurationError) as caught:
        load_config(bad)
    assert caught.value.code == "HF_INITIAL_CONDITION_PROTOCOL_UNSUPPORTED"
    assert caught.value.details["requested"] == initial_type


@pytest.mark.parametrize(
    ("protocol", "field", "value"),
    [
        (
            "static_equilibrium",
            "bob_position",
            {"value": [0.0, 0.0, -0.7], "unit": "kg"},
        ),
        (
            "static_equilibrium",
            "positions_file",
            "silently-unused.npy",
        ),
        (
            "cartesian_release",
            "junction_position",
            {"value": [0.0, 0.0, -0.4], "unit": "N"},
        ),
        (
            "geometric_direct_release",
            "phi",
            {"value": 123.0, "unit": "kg"},
        ),
        (
            "held_endpoint_equilibrium_release",
            "state_file",
            "silently-unused.npz",
        ),
    ],
)
def test_hf_supported_initial_protocols_reject_unconsumed_explicit_fields(
    config_dict, protocol, field, value
):
    bad = _hf_mapping(config_dict)
    initial = {"type": protocol, field: value}
    if protocol in {
        "cartesian_release",
        "geometric_direct_release",
        "held_endpoint_equilibrium_release",
    }:
        initial["bob_position"] = {
            "value": [0.0, 0.0, -0.70],
            "unit": "m",
        }
    if protocol in {
        "geometric_direct_release",
        "held_endpoint_equilibrium_release",
    }:
        initial["junction_position"] = {
            "value": [0.0, 0.0, -0.42],
            "unit": "m",
        }
    # Preserve the deliberately invalid explicit value if it is one of the
    # protocol's otherwise required fields in a future parametrization.
    initial[field] = value
    bad["initial_condition"] = initial
    if protocol == "held_endpoint_equilibrium_release":
        bad["solver"]["static"]["method"] = "energy_minimize"
    with pytest.raises(ConfigurationError) as caught:
        load_config(bad)
    assert caught.value.code == "HF_INITIAL_CONDITION_FIELDS_UNCONSUMED"
    assert field in caught.value.details["unconsumed_explicit_fields"]


def test_hf_resource_budget_rejects_legal_cross_product(config_dict):
    bad = _hf_mapping(config_dict)
    bad["cables"]["upper_A"]["elements"] = 128
    bad["cables"]["lower"]["elements"] = 128
    bad["solver"]["allow_subminimum_mesh"] = False
    bad["solver"]["t_end"] = {"value": 20.0, "unit": "s"}
    bad["solver"]["output_dt"] = {"value": 1.0e-5, "unit": "s"}
    with pytest.raises(ConfigurationError) as caught:
        load_config(bad)
    assert caught.value.code == "HF_RESOURCE_BUDGET_EXCEEDED"
    assert (
        caught.value.details["estimate_id"]
        == "HF_SINGLE_RUN_RESOURCE_HARD_CAP_V1"
    )
    assert (
        caught.value.details["accepted_step_hard_cap"]
        == caught.value.details["accepted_step_budget"]
    )
    assert caught.value.details["total_elements"] == 384
    assert caught.value.details["output_samples"] == 2_000_001
    assert (
        caught.value.details["estimated_peak_memory_bytes"]
        > caught.value.details["peak_memory_limit_bytes"]
    )


def test_hf_resource_estimator_is_total_at_extreme_finite_ratios(config_dict):
    enormous = _hf_mapping(config_dict)
    enormous["solver"]["t_end"] = {"value": 1.0e308, "unit": "s"}
    enormous["solver"]["output_dt"] = {"value": 1.0e-308, "unit": "s"}
    with pytest.raises(ConfigurationError) as caught:
        load_config(enormous)
    assert caught.value.code == "HF_RESOURCE_BUDGET_EXCEEDED"

    zero_gravity = _hf_mapping(config_dict)
    zero_gravity["environment"]["gravity"] = {
        "value": [0.0, 0.0, 0.0],
        "unit": "m/s^2",
    }
    with pytest.raises(ConfigurationError) as caught:
        load_config(zero_gravity)
    assert caught.value.code == "HF_NONZERO_GRAVITY_REQUIRED"


def test_hf_held_protocol_requires_its_registered_static_solver(config_dict):
    bad = _hf_mapping(config_dict)
    bad["initial_condition"] = {
        "type": "held_endpoint_equilibrium_release",
        "junction_position": {"value": [0.0, 0.0, -0.42], "unit": "m"},
        "bob_position": {"value": [0.0, 0.0, -0.70], "unit": "m"},
    }
    with pytest.raises(ConfigurationError, match="energy_minimize"):
        load_config(bad)

    bad["solver"]["static"]["method"] = "energy_minimize"
    bad["solver"]["static"]["continuation_steps"] = 1
    with pytest.raises(ConfigurationError, match=r"\[2,8\]"):
        load_config(bad)

    bad["solver"]["static"]["continuation_steps"] = 2
    bad["solver"]["static"]["force_tolerance"] = {
        "value": 0.0,
        "unit": "N",
    }
    with pytest.raises(ConfigurationError, match="strictly positive"):
        load_config(bad)

    bad["solver"]["static"]["force_tolerance"] = {
        "value": 1.0e-8,
        "unit": "N",
    }
    bad["solver"]["static"]["continuation_steps"] = 8
    bad["solver"]["static"]["max_iterations"] = 2_000
    with pytest.raises(ConfigurationError) as caught:
        load_config(bad)
    assert caught.value.code == "HF_STATIC_PREPARATION_BUDGET_EXCEEDED"

    subnormal = _hf_mapping(config_dict)
    subnormal["solver"]["static"]["line_search_min"] = 5.0e-324
    with pytest.raises(ConfigurationError, match="executable lower bound"):
        load_config(subnormal)

    windy = _hf_mapping(config_dict)
    windy["initial_condition"] = copy.deepcopy(bad["initial_condition"])
    windy["solver"]["static"]["method"] = "energy_minimize"
    windy["environment"]["air_velocity"] = {
        "value": [0.1, 0.0, 0.0],
        "unit": "m/s",
    }
    windy["bob"]["drag"]["enabled"] = True
    with pytest.raises(ConfigurationError, match="non-zero wind"):
        load_config(windy)
