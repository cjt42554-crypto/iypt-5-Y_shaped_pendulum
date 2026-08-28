"""Closed identity and capability boundary for the migration draft."""

MODEL_ID = "YPS-DISCRETE-ROD-RIGID-BOB-NO-CONTACT-STATIC-REFERENCE-DRAFT-1.0"
CAPABILITY = "conservative_no_contact_static_reference_only"
CLAIM_CEILING = "G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED"
QUALIFICATION_STATUS = "NOT_CARRIED_BY_MIGRATION"

EXPLICIT_EXCLUSIONS = (
    "contact",
    "friction",
    "P3_to_P3R5_packages",
    "dynamics",
    "dynamic_contact",
    "RC1_replacement",
    "continuous_cable_replacement",
    "complete_simulator",
    "device_level_physics",
    "experimental_validation",
)
