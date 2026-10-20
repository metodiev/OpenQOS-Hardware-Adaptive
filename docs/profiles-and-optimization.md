# Profiles and optimization

Phase 2 turns a hardware inventory into a **normalised hardware profile**, matches
it against **versioned, data-driven rules**, and produces a **validated
optimization plan**. Nothing is applied: the plan is input for the installer
(Phase 3) and the runtime service (Phase 4).

```
inventory.json  ->  profile.json  ->  rules  ->  plan.json (decisions + rollback)
```

## Commands

```bash
openqos profile build   --inventory inventory.json --output profile.json
openqos profile explain --inventory inventory.json          # why a profile matched
openqos profile validate profile.json

openqos optimize --inventory inventory.json --policy balanced --format json
openqos optimize --inventory inventory.json --policy power-saving
```

Policies: `balanced` (default), `performance`, `power-saving`.

## What a profile contains

`openqos.profiles.model.build_profile()` reduces the inventory to the vocabulary
the rules need:

| Section | Examples |
| --- | --- |
| `machine` | `form_factor` (laptop/desktop/unknown), `is_virtual_machine`, firmware mode, Secure Boot state, OS id/version, architecture |
| `cpu` | `vendor` (intel/amd/other/unknown), model, topology, `cpufreq_driver`, feature flags (`avx2`, `avx512f`, `aes`, `virt_host`) |
| `memory` | total MiB, `tier` (low < 4 GiB, standard, high ≥ 16 GiB), swap |
| `graphics` | adapters with `kind` (integrated/discrete/unknown), `hybrid`, `drivers`, `requires_third_party_driver` |
| `storage` | devices, `primary` (ssd/hdd/unknown), transports, NVMe, removable |
| `network` | wired/wireless, drivers |
| `power` | current governor, EPP, platform profile, **available** governors/EPP values/choices, battery |
| `audio`, `peripherals` | card and device counts |
| `unavailable` | collectors that could not read data |

Facts that could not be detected stay `null` or appear in `unavailable`; the
optimizer never substitutes a guess.

Output is validated against
[`hardware-profile-1.0.0.json`](../src/openqos/schemas/hardware-profile-1.0.0.json).

## Rules

Rules live in [`src/openqos/config/hardware-profiles.json`](../src/openqos/config/hardware-profiles.json)
and are validated before use. A rule is data, not code:

```json
{
  "id": "hybrid-graphics-laptop",
  "description": "Laptop with two graphics vendors (integrated plus discrete).",
  "priority": 80,
  "match": {
    "all": [
      { "field": "machine.form_factor", "op": "eq", "value": "laptop" },
      { "field": "graphics.hybrid", "op": "eq", "value": true }
    ]
  },
  "package_sets": ["power-management-laptop"],
  "default_policy": "balanced",
  "notes": ["Keep the integrated adapter as the primary render device."]
}
```

* Supported operators: `eq`, `ne`, `in`, `not_in`, `ge`, `le`, `exists`.
* Fields are dotted paths into the profile; a missing field never matches.
* Selection is deterministic: highest `priority` wins, ties break on `id`.
* Exactly one rule may be the `fallback` and it must be unconditional. If no
  rule matches, the fallback (`generic-x86-64`) is used and the plan says so.
* Package sets are named, typed by source (`fedora`, `third-party`, `manual`) and
  carry a reason. Every package name was checked against Fedora 44 repositories
  (`iwlwifi-firmware` no longer exists, for example; the split
  `iwlwifi-mvm-firmware` is used instead).

`openqos profile explain` prints which conditions matched and, for rejected
rules, the first condition that failed.

## Policies

[`src/openqos/config/optimization-policies.json`](../src/openqos/config/optimization-policies.json)
defines the three policies:

| Policy | Governor | EPP | Platform profile | zram |
| --- | --- | --- | --- | --- |
| `balanced` | `powersave` | `balance_performance` | `balanced` | 50% of RAM |
| `performance` | `performance` | `performance` | `performance` | 25% of RAM |
| `power-saving` | `powersave` | `power` | `low-power` | 100% of RAM |

These are the values Fedora itself uses on `intel_pstate` and
`amd-pstate-epp`; no custom kernel patch is required.

## Decisions

Every entry in `decisions[]` has a status:

| Status | Meaning |
| --- | --- |
| `plan` | A change is proposed. It **must** carry a rollback. |
| `keep` | The desired value is already active; nothing to do. |
| `skip` | The hardware does not support the setting; the reason is recorded. |
| `manual` | Requires an explicit user decision (for example the proprietary NVIDIA driver). |

Each decision records `target`, `value`, `current_value`, `rationale`,
`evidence`, `risk`, `reversible`, `rollback`, `apply_stage`, `packages` and
`source`.

Examples from the synthetic Intel hybrid laptop:

* `cpu-governor` — `keep`: `powersave` is already active.
* `platform-profile` — `keep`: firmware reports `balanced`.
* `graphics-proprietary-driver` — `manual`: not redistributable, never installed
  automatically.
* `memory-swap` — `plan`: zram at 50% of RAM, rollback removes the config.
* `storage-trim` — `plan`: `fstrim.timer` on SSD; skipped on rotational media.

### Safety rules encoded in the planner

1. A setting is only planned when the hardware advertises support for the value
   (governor in `available_governors`, EPP in the available list, platform
   profile in `platform_profile_choices`).
2. Planned changes always carry a rollback action.
3. Package installation never includes a third-party or proprietary source
   automatically.
4. No kernel parameters, mount options, service disables, or security features
   are touched in Phase 2.
5. `summary.all_reversible` must be true whenever anything is planned; the
   validator enforces it.

## Fallback

The plan carries a `fallback` block: re-run with `generic-x86-64` and
`balanced`, and restore the recorded `current_value` of each decision. This is
the same path used when a rule does not match, when plan validation fails, or
when the kernel rejects a runtime change.

## Validation

* `hardware-profile-1.0.0.json` and `optimization-plan-1.0.0.json` use
  `additionalProperties: false`.
* A dependency-free structural validator always runs; full JSON Schema
  validation runs when `jsonschema` is installed.
* `openqos optimize` validates the inventory, the profile, and the plan before
  emitting anything.
* Tests cover invalid operators, duplicate ids, unknown package sets, duplicate
  decisions, planned changes without rollback, and unsupported hardware values.

## Not implemented yet

* Applying a plan (installer, Phase 3).
* Measuring whether a planned change actually helps (benchmarks, Phase 5).
* Hardware-specific kernel builds (optional, later).
