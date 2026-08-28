"""Closed identity and capability boundary for the static migration draft."""

MODEL_ID = "YPS-NO-CONTACT-STATIC-REFERENCE-DRAFT-1.1"
CAPABILITY = "position_orientation_conservative_no_contact_static_reference_only"
CLAIM_CEILING = "CANDIDATE_STATIC_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY"
QUALIFICATION_STATUS = "NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED"

EXPLICIT_EXCLUSIONS = (
    "contact",
    "friction",
    "qualification_packages_P3_through_P3R5",
    "dynamics",
    "dynamic_contact",
    "RC1_replacement",
    "continuous_cable_replacement",
    "complete_simulator",
    "device_level_physics",
    "experimental_validation",
)
