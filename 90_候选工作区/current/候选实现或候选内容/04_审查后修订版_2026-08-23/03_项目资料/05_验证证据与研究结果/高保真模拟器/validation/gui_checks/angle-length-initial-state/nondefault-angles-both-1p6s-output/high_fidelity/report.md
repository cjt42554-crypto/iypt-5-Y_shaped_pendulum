# YP-FPSim run report: desktop_multicycle_preview

- Model: `HF-DISCRETE-ROD-RIGID-BOB-1.0`
- Scientific claim: `DERIVED`
- Status: `undetermined`
- Simulated duration: `1.6` s

## Principal outputs

- frequency_fast_hz: `nan`
- frequency_slow_hz: `nan`
- frequency_ratio: `nan`
- phase_drift_rad_s: `nan`
- minimum_tension_N: `0.24066439962302205`
- maximum_tension_N: `1.1403927206482602`
- max_abs_energy_balance_residual: `1.093907951462477e-06`

## Numerical diagnostics

- model_id: `HF-DISCRETE-ROD-RIGID-BOB-1.0`
- physics_path: `local material beads + passive unilateral/bilateral KV blend + three-point bending + finite rigid bob`
- particle_count: `4`
- state_size: `37`
- junction_index: `3`
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
- same_branch_full_contact_pair_count: `{'upper_A': 0, 'upper_B': 0, 'lower': 0}`
- same_branch_partial_contact_pair_count: `{'upper_A': 1, 'upper_B': 1, 'lower': 1}`
- junction_contact_pair_count: `3`
- contact_topology_precomputed: `True`
- bob_socket_rest_material_length_m: `0.02169794636444272`
- junction_pair_socket_rest_material_length_m: `{'upper_A__upper_B': 0.0064, 'upper_A__lower': 0.0064, 'upper_B__lower': 0.0064}`
- junction_socket_projective_opening_definition: `inf_{s,t>=0,s+t>0} ||p_i(s)-p_j(t)||^2/(s+t)^2 minus (required_center_separation/(2*socket_length))^2`
- branch_beads: `{'upper_A': 1, 'upper_B': 1, 'lower': 1}`
- branch_bending_stiffness_N_m2: `{'upper_A': 6.750000000000001e-06, 'upper_B': 6.750000000000001e-06, 'lower': 6.750000000000001e-06}`
- contact_scope: `bob-vs-rod and rod-vs-rod root guards; friction, compliant contact, fracture, ground contact and knot sliding excluded`
- runtime_seconds: `3.399725369999942`
- integration_wall_seconds: `3.399725369999942`
- integration_checkpoint_schema: `YPS-HF-INTEGRATION-CHECKPOINT-1.0`
- integration_checkpoint_path: `/home/cjt/Desktop/iypt/5 Y形摆/第一性原理模拟/Y-Pendulum-Simulator-v1.0.0-rc1/validation/gui_checks/angle-length-initial-state/nondefault-angles-both-1p6s-output/.high_fidelity.integration-checkpoint.npz`
- integration_checkpoint_reused: `False`
- checkpoint_original_integration_wall_seconds: `3.399725369999942`
- presentation_sample_evaluation_wall_seconds: `1.9271424239996122`
- postprocess_wall_seconds: `1.9274739920001593`
- postprocess_process_tree_cpu_seconds: `32.099999999999994`
- postprocess_average_equivalent_cpu_cores: `16.653921211507242`
- postprocess_average_cpu_utilization_percent: `1665.3921211507243`
- postprocess_worker_count: `12`
- postprocess_physical_core_count: `16`
- postprocess_parallel_backend: `DETERMINISTIC_FIXED_CONTIGUOUS_SPAWN_PROCESS_POOL_V1`
- solver_method: `BDF`
- rtol: `1e-07`
- position_atol_m: `1e-09`
- velocity_atol_m_s: `1e-08`
- quaternion_atol: `1e-09`
- angular_velocity_atol_rad_s: `1e-09`
- max_step_s: `0.0018232594040092174`
- minimum_cell_wave_time_s: `0.00831384387633061`
- jacobian_kind: `colored_finite_difference_from_local_HF_dependency_graph`
- jacobian_sparsity_nnz: `451`
- nfev: `3711`
- njev: `4`
- nlu: `250`
- accepted_integration_step_count: `1471`
- accepted_integration_step_hard_cap: `3516`
- resource_upper_bound: `{'estimate_id': 'HF_SINGLE_RUN_RESOURCE_HARD_CAP_V1', 'runtime_enforcement_id': 'MANUAL_SCIPY_RADAU_BDF_ACCEPTED_STEP_CAP_V1', 'total_elements': 3, 'state_size': 37, 'output_samples': 321, 'output_sample_limit': 2000001, 'nominal_accepted_steps': 879, 'accepted_step_budget': 3516, 'accepted_step_hard_cap': 3516, 'presentation_float_budget': 84744, 'accepted_trace_float_budget': 1300920, 'implicit_workspace_float_budget': 8214, 'serialized_result_float_budget': 358932, 'estimated_peak_memory_bytes': 13938780, 'peak_memory_limit_bytes': 8589934592, 'estimated_result_bytes': 3589320, 'result_limit_bytes': 8589934592, 'accepted_step_limit': 2000001}`
- resource_runtime_enforcement: `MANUAL_SCIPY_RADAU_BDF_ACCEPTED_STEP_CAP_V1`
- machine_scale_terminal_steps_coalesced: `0`
- terminal_time_coalescing_tolerance_s: `3.637978807091713e-13`
- minimum_accepted_integration_step_s: `5.065032813058179e-07`
- maximum_accepted_integration_step_s: `0.00157995832156832`
- preparation_force_residual_inf_N: `1.1542359270447287e-11`
- preparation_iterations: `82`
- preparation_bob_held: `True`
- preparation_mode: `held_endpoint_bilateral_stable_equilibrium`
- preparation_audit: `{'protocol': 'HELD_ENDPOINT_STABLE_BILATERAL_EQUILIBRIUM_V1', 'fixed_dofs': ['junction_position', 'bob_com_position', 'bob_orientation', 'bob_attachment_position', 'support_A_position', 'support_B_position'], 'static_free_material_residual_inf_N': 1.1542359270447287e-11, 'static_fixture_reaction_force_world_N': {'support_A': [-0.1498680200100563, 0.013282562889798531, -0.2681336314614812], 'support_B': [0.1498680200100563, 0.013282562889798531, -0.2681336314614812], 'junction': [-0.0727172780863827, 0.02868257117740262, -0.08706935930341542], 'bob_com': [0.07271727809792507, -0.055247696965845, -0.28507101922469086]}, 'static_fixture_reaction_torque_world_Nm': {'bob': [-0.0011048404806819532, -0.001454196227170571, -0.0]}, 'actual_release_free_material_net_force_inf_N': 1.1542359270447287e-11, 'actual_release_junction_net_force_world_N': [0.0727172780863827, -0.02868257117740262, 0.08706935930341542], 'actual_release_bob_net_force_world_N': [-0.07271727809792507, 0.055247696965845, 0.28507101922469086], 'actual_release_bob_net_torque_world_Nm': [0.0011048404806819532, 0.001454196227170571, 0.0], 'minimum_hessian_eigenvalue_N_per_m': 4.011530155396652, 'hessian_tolerance_N_per_m': 8.333333333333334e-06, 'hessian_parallel_worker_count': 8, 'stability_class': 'PSD_STABLE_LOCAL_MINIMUM', 'seed_candidate_count': 1, 'selected_seed': 'gravity_plane', 'seed_geometry': {'upper_A': {'compressed_chord': False, 'gravity_seed_max_offset_m': 0.0, 'gravity_seed_direction_world': [0.0, 0.0, 0.0], 'out_of_plane_perturbation_max_m': 1.763491390772189e-21}, 'upper_B': {'compressed_chord': False, 'gravity_seed_max_offset_m': 0.0, 'gravity_seed_direction_world': [0.0, 0.0, 0.0], 'out_of_plane_perturbation_max_m': 1.763491390772189e-21}, 'lower': {'compressed_chord': False, 'gravity_seed_max_offset_m': 0.0, 'gravity_seed_direction_world': [0.0, 0.0, 0.0], 'out_of_plane_perturbation_max_m': 1.9961742826101854e-21}}, 'candidate_records': [{'seed': 'gravity_plane', 'iterations': 82, 'energy_J': -0.017588537089205415, 'free_material_residual_inf_N': 1.1542359270447287e-11, 'minimum_hessian_eigenvalue_N_per_m': 4.011530155396652, 'stability_audit_skipped_reason': None, 'escaped_negative_curvature': False, 'guards_valid': True, 'minimum_normalized_guard_margin': 0.00033210633383878917, 'optimizer_messages': ['CONVERGENCE: NORM OF PROJECTED GRADIENT <= PGTOL', 'CONVERGENCE: NORM OF PROJECTED GRADIENT <= PGTOL', 'ABNORMAL: ', 'CONVERGENCE: NORM OF PROJECTED GRADIENT <= PGTOL', 'CONVERGENCE: NORM OF PROJECTED GRADIENT <= PGTOL', 'CONVERGENCE: NORM OF PROJECTED GRADIENT <= PGTOL'], 'accepted_stable_candidate': True}], 'gravity_continuation_steps': 6, 'negative_curvature_line_search_min_fraction': 1e-05, 'total_optimizer_iterations': 82}`
- raw_guard_certification_status: `ACCEPTED_STEP_CONTINUOUS_CERTIFICATE_REQUIRED`
- energy_balance_scale_J: `0.3058603129288`
- energy_balance_scale_definition: `total_gravitational_force_scale_times_characteristic_length`
- max_abs_energy_balance_residual: `1.093907951462477e-06`
- minimum_tension_N: `0.24066439962302205`
- maximum_tension_N: `1.1403927206482602`
- minimum_signed_axial_force_N: `0.24066439962302205`
- maximum_signed_axial_force_N: `1.1403927206482602`
- minimum_contact_margin_m: `0.000297263917053535`
- minimum_bob_contact_margin_m: `0.020914569949555525`
- minimum_rod_self_contact_margin_m: `0.000297263917053535`
- guard_component_metadata: `{'MINIMUM_SEGMENT_LENGTH': {'unit': 'm', 'scale': 0.326, 'tolerance': np.float64(7.412381819449365e-14)}, 'BENDING_TURN_CLEARANCE': {'unit': 'dimensionless', 'scale': 1.0, 'tolerance': np.float64(2.2737367544323206e-13)}, 'AERODYNAMIC_CHORD_LENGTH': {'unit': 'm', 'scale': 0.326, 'tolerance': np.float64(7.412381819449365e-14)}, 'BOB_ROD_CLEARANCE': {'unit': 'm', 'scale': 0.326, 'tolerance': np.float64(7.412381819449365e-14)}, 'ROD_SELF_CLEARANCE': {'unit': 'm', 'scale': 0.326, 'tolerance': np.float64(7.412381819449365e-14)}, 'BOB_SOCKET_MATERIAL_EXTENT': {'unit': 'm', 'scale': 0.326, 'tolerance': np.float64(7.412381819449365e-14)}, 'BOB_SOCKET_RADIAL_MONOTONICITY': {'unit': 'm^2', 'scale': 0.10627600000000001, 'tolerance': np.float64(2.4164364731404932e-14)}, 'BOB_SOCKET_CUT_CLEARANCE': {'unit': 'm', 'scale': 0.326, 'tolerance': np.float64(7.412381819449365e-14)}, 'JUNCTION_SOCKET_MATERIAL_EXTENT': {'unit': 'm', 'scale': 0.326, 'tolerance': np.float64(7.412381819449365e-14)}, 'JUNCTION_SOCKET_PROJECTIVE_OPENING': {'unit': 'dimensionless', 'scale': 1.0, 'tolerance': np.float64(2.2737367544323206e-13)}, 'JUNCTION_SOCKET_CUT_CLEARANCE': {'unit': 'm', 'scale': 0.326, 'tolerance': np.float64(7.412381819449365e-14)}}`
- minimum_segment_length_m: `0.14690779828456288`
- minimum_bending_turn_clearance: `1.9947443452683613`
- minimum_aerodynamic_chord_length_m: `0.2939322603796785`
- minimum_bob_socket_material_extent_m: `0.3043020536355573`
- minimum_bob_socket_radial_monotonicity_m2: `0.0004448735039980627`
- minimum_bob_socket_cut_clearance_m: `0.020714569949555527`
- minimum_junction_socket_material_extent_m: `0.28159999999999996`
- minimum_junction_socket_projective_opening: `0.20200752523380217`
- minimum_junction_socket_cut_clearance_m: `0.0033838088006108128`
- maximum_quaternion_norm_error: `3.373061940870059e-09`
- bending_energy_fraction_peak: `4.987106616446459e-05`

## Interpretation boundary

This report verifies a numerical run. It is not experimental validation. `VALIDATED` or `PREDICTIVE` claims require an independent frozen validation manifest.
