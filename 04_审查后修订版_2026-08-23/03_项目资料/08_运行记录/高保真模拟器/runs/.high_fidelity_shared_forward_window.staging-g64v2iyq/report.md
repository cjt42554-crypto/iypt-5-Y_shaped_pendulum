# YP-FPSim run report: high_fidelity_shared_forward_window

- Model: `HF-DISCRETE-ROD-RIGID-BOB-1.0`
- Scientific claim: `VERIFIED`
- Status: `undetermined`
- Simulated duration: `0.12` s

## Principal outputs

- frequency_fast_hz: `nan`
- frequency_slow_hz: `nan`
- frequency_ratio: `nan`
- phase_drift_rad_s: `nan`
- minimum_tension_N: `0.0`
- maximum_tension_N: `1.0852798580755236`
- max_abs_energy_balance_residual: `7.914037742054811e-11`

## Numerical diagnostics

- model_id: `HF-DISCRETE-ROD-RIGID-BOB-1.0`
- physics_path: `local material beads + passive unilateral/bilateral KV blend + three-point bending + finite rigid bob`
- particle_count: `81`
- state_size: `499`
- junction_index: `80`
- bob_inertia_kg_m2: `1.279737148144409e-05`
- bob_attachment_body_m: `[-0.0, -0.0, -0.01999794636444272]`
- bob_contact_radius_m: `0.01999794636444272`
- physical_force_scale_N: `0.9382218188`
- tension_zero_tolerance_N: `2.1332694332159008e-13`
- axial_material_model: `passive_unilateral_bilateral_kelvin_voigt_blend`
- cable_material_field_semantics: `E, eta, area parameter source only; HF axial_material_model owns the constitutive branch`
- compression_regularization_scale: `1.0`
- geometry_singularity_floor_m: `3.26e-16`
- length_guard_m: `3.26e-13`
- bending_turn_clearance_floor: `1e-08`
- aerodynamic_chord_guard_m: `3.26e-15`
- quaternion_stabilization_rate_s_inv: `1.0`
- contact_registration_id: `FIXED_REST_MATERIAL_SOCKETS_PROJECTIVE_V2`
- same_branch_minimum_material_separation_m: `{'upper_A': 0.003232, 'upper_B': 0.003232, 'lower': 0.003232}`
- bob_socket_rest_material_length_m: `0.02169794636444272`
- junction_pair_socket_rest_material_length_m: `{'upper_A__upper_B': 0.0064, 'upper_A__lower': 0.0064, 'upper_B__lower': 0.0064}`
- junction_socket_projective_opening_definition: `inf_{s,t>=0,s+t>0} ||p_i(s)-p_j(t)||^2/(s+t)^2 minus (required_center_separation/(2*socket_length))^2`
- branch_beads: `{'upper_A': 24, 'upper_B': 24, 'lower': 32}`
- branch_bending_stiffness_N_m2: `{'upper_A': 6.750000000000001e-06, 'upper_B': 6.750000000000001e-06, 'lower': 6.750000000000001e-06}`
- contact_scope: `bob-vs-rod and rod-vs-rod root guards; friction, compliant contact, fracture, ground contact and knot sliding excluded`
- runtime_seconds: `4881.448216948003`
- solver_method: `Radau`
- rtol: `1e-08`
- position_atol_m: `1e-10`
- velocity_atol_m_s: `1e-09`
- quaternion_atol: `1e-10`
- angular_velocity_atol_rad_s: `1e-09`
- max_step_s: `7.8125e-06`
- minimum_cell_wave_time_s: `0.0003221570366296537`
- jacobian_kind: `colored_finite_difference_from_local_HF_dependency_graph`
- jacobian_sparsity_nnz: `7612`
- nfev: `107544`
- njev: `3`
- nlu: `30714`
- accepted_integration_step_count: `15361`
- accepted_integration_step_hard_cap: `61444`
- resource_upper_bound: `{'estimate_id': 'HF_SINGLE_RUN_RESOURCE_HARD_CAP_V1', 'runtime_enforcement_id': 'MANUAL_SCIPY_RADAU_BDF_ACCEPTED_STEP_CAP_V1', 'total_elements': 80, 'state_size': 499, 'output_samples': 15361, 'output_sample_limit': 2000001, 'nominal_accepted_steps': 15361, 'accepted_step_budget': 61444, 'accepted_step_hard_cap': 61444, 'presentation_float_budget': 32442432, 'accepted_trace_float_budget': 306605560, 'implicit_workspace_float_budget': 1494006, 'serialized_result_float_budget': 88848024, 'estimated_peak_memory_bytes': 3405419980, 'peak_memory_limit_bytes': 8589934592, 'estimated_result_bytes': 888480240, 'result_limit_bytes': 8589934592, 'accepted_step_limit': 2000001}`
- resource_runtime_enforcement: `MANUAL_SCIPY_RADAU_BDF_ACCEPTED_STEP_CAP_V1`
- machine_scale_terminal_steps_coalesced: `0`
- terminal_time_coalescing_tolerance_s: `4.145611919760125e-14`
- minimum_accepted_integration_step_s: `5.410836493496104e-06`
- maximum_accepted_integration_step_s: `7.812500000002609e-06`
- preparation_force_residual_inf_N: `1.5437046920157953e-09`
- preparation_iterations: `5391`
- preparation_bob_held: `True`
- preparation_mode: `held_endpoint_bilateral_stable_equilibrium`
- preparation_audit: `{'protocol': 'HELD_ENDPOINT_STABLE_BILATERAL_EQUILIBRIUM_V1', 'fixed_dofs': ['junction_position', 'bob_com_position', 'bob_orientation', 'bob_attachment_position', 'support_A_position', 'support_B_position'], 'static_free_material_residual_inf_N': 1.5437046920157953e-09, 'static_fixture_reaction_force_world_N': {'support_A': [-0.07821699442635402, -0.0, -0.1448519448901286], 'support_B': [0.07821699442635402, -0.0, -0.1448519448901286], 'junction': [0.0005476018724985343, 0.00031291535571351705, 0.17117848668256488], 'bob_com': [-0.0005476009904306607, -0.0003129148516603168, -0.7898822322924116]}, 'static_fixture_reaction_torque_world_Nm': {'bob': [-6.257654420140566e-06, 1.0950895235748065e-05, -0.0]}, 'actual_release_free_material_net_force_inf_N': 1.5437046920157953e-09, 'actual_release_junction_net_force_world_N': [-0.0005476018724985343, -0.00031291535571351705, -0.17117848668256488], 'actual_release_bob_net_force_world_N': [0.0005476009904306607, 0.0003129148516603168, 0.7898822322924116], 'actual_release_bob_net_torque_world_Nm': [6.257654420140566e-06, -1.0950895235748065e-05, 0.0], 'minimum_hessian_eigenvalue_N_per_m': 0.005849874080496648, 'hessian_tolerance_N_per_m': 0.00023558282208588956, 'hessian_parallel_worker_count': 8, 'stability_class': 'PSD_STABLE_LOCAL_MINIMUM', 'seed_candidate_count': 4, 'selected_seed': 'gravity_plane', 'seed_geometry': {'upper_A': {'compressed_chord': False, 'gravity_seed_max_offset_m': 0.0, 'gravity_seed_direction_world': [0.0, 0.0, 0.0], 'out_of_plane_perturbation_max_m': 1.4276806003782876e-05}, 'upper_B': {'compressed_chord': False, 'gravity_seed_max_offset_m': 0.0, 'gravity_seed_direction_world': [0.0, 0.0, 0.0], 'out_of_plane_perturbation_max_m': 1.4276806003782876e-05}, 'lower': {'compressed_chord': True, 'gravity_seed_max_offset_m': 0.041803315186298394, 'gravity_seed_direction_world': [-0.860994275200534, -0.4919967286860193, 0.1289499012568943], 'out_of_plane_perturbation_max_m': 0.002080101039883404}}, 'candidate_records': [{'seed': 'gravity_plane', 'iterations': 1236, 'energy_J': -0.022341458844346317, 'free_material_residual_inf_N': 1.5437046920157953e-09, 'minimum_hessian_eigenvalue_N_per_m': 0.005849874080496648, 'stability_audit_skipped_reason': None, 'escaped_negative_curvature': False, 'guards_valid': True, 'minimum_normalized_guard_margin': 7.566645359280319e-05, 'optimizer_messages': ['STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT'], 'accepted_stable_candidate': True}, {'seed': 'mirror_all_compressed', 'iterations': 1600, 'energy_J': -0.022186041947690038, 'free_material_residual_inf_N': 0.00011297495957152126, 'minimum_hessian_eigenvalue_N_per_m': None, 'stability_audit_skipped_reason': None, 'escaped_negative_curvature': False, 'guards_valid': True, 'minimum_normalized_guard_margin': 5.236196248098869e-05, 'optimizer_messages': ['STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT'], 'accepted_stable_candidate': False}, {'seed': 'gravity_plane_out_of_plane_plus', 'iterations': 1276, 'energy_J': -0.022341458844345168, 'free_material_residual_inf_N': 1.5750570823991079e-09, 'minimum_hessian_eigenvalue_N_per_m': None, 'stability_audit_skipped_reason': 'duplicate_of_existing_psd_stable_candidate', 'escaped_negative_curvature': False, 'guards_valid': True, 'minimum_normalized_guard_margin': 7.566649342038333e-05, 'optimizer_messages': ['STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT'], 'accepted_stable_candidate': False}, {'seed': 'gravity_plane_out_of_plane_minus', 'iterations': 1279, 'energy_J': -0.02234145884434539, 'free_material_residual_inf_N': 1.9866696243013657e-09, 'minimum_hessian_eigenvalue_N_per_m': None, 'stability_audit_skipped_reason': 'duplicate_of_existing_psd_stable_candidate', 'escaped_negative_curvature': False, 'guards_valid': True, 'minimum_normalized_guard_margin': 7.566653791061283e-05, 'optimizer_messages': ['STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT', 'STOP: TOTAL NO. of ITERATIONS REACHED LIMIT'], 'accepted_stable_candidate': False}], 'gravity_continuation_steps': 6, 'negative_curvature_line_search_min_fraction': 1e-05, 'total_optimizer_iterations': 5391}`
- raw_guard_certification_status: `ACCEPTED_STEP_CONTINUOUS_CERTIFICATE_REQUIRED`
- energy_balance_scale_J: `0.3058603129288`
- energy_balance_scale_definition: `total_gravitational_force_scale_times_characteristic_length`
- max_abs_energy_balance_residual: `7.914037742054811e-11`
- minimum_tension_N: `0.0`
- maximum_tension_N: `1.0852798580755236`
- minimum_signed_axial_force_N: `-0.003832001748020747`
- maximum_signed_axial_force_N: `1.0852798580755236`
- minimum_contact_margin_m: `0.00022466726387125385`
- minimum_bob_contact_margin_m: `0.01592681535430633`
- minimum_rod_self_contact_margin_m: `0.00022466726387125385`
- guard_component_metadata: `{'MINIMUM_SEGMENT_LENGTH': {'unit': 'm', 'scale': 0.326, 'tolerance': 7.412381819449365e-14}, 'BENDING_TURN_CLEARANCE': {'unit': 'dimensionless', 'scale': 1.0, 'tolerance': 2.2737367544323206e-13}, 'AERODYNAMIC_CHORD_LENGTH': {'unit': 'm', 'scale': 0.326, 'tolerance': 7.412381819449365e-14}, 'BOB_ROD_CLEARANCE': {'unit': 'm', 'scale': 0.326, 'tolerance': 7.412381819449365e-14}, 'ROD_SELF_CLEARANCE': {'unit': 'm', 'scale': 0.326, 'tolerance': 7.412381819449365e-14}, 'BOB_SOCKET_MATERIAL_EXTENT': {'unit': 'm', 'scale': 0.326, 'tolerance': 7.412381819449365e-14}, 'BOB_SOCKET_RADIAL_MONOTONICITY': {'unit': 'm^2', 'scale': 0.10627600000000001, 'tolerance': 2.4164364731404932e-14}, 'BOB_SOCKET_CUT_CLEARANCE': {'unit': 'm', 'scale': 0.326, 'tolerance': 7.412381819449365e-14}, 'JUNCTION_SOCKET_MATERIAL_EXTENT': {'unit': 'm', 'scale': 0.326, 'tolerance': 7.412381819449365e-14}, 'JUNCTION_SOCKET_PROJECTIVE_OPENING': {'unit': 'dimensionless', 'scale': 1.0, 'tolerance': 2.2737367544323206e-13}, 'JUNCTION_SOCKET_CUT_CLEARANCE': {'unit': 'm', 'scale': 0.326, 'tolerance': 7.412381819449365e-14}}`
- minimum_segment_length_m: `0.005092123395091335`
- minimum_bending_turn_clearance: `1.9912222481126416`
- minimum_aerodynamic_chord_length_m: `0.015275832408854478`
- minimum_bob_socket_material_extent_m: `0.30430205363555735`
- minimum_bob_socket_radial_monotonicity_m2: `5.880181031666499e-05`
- minimum_bob_socket_cut_clearance_m: `0.015726815354306332`
- minimum_junction_socket_material_extent_m: `0.2816`
- minimum_junction_socket_projective_opening: `0.16939850581951935`
- minimum_junction_socket_cut_clearance_m: `0.0029670614048509414`
- maximum_quaternion_norm_error: `4.107825191113079e-15`
- bending_energy_fraction_peak: `0.16695231149282255`

## Interpretation boundary

This report verifies a numerical run. It is not experimental validation. `VALIDATED` or `PREDICTIVE` claims require an independent frozen validation manifest.
