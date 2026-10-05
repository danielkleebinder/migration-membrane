This repository contains the source code, simulation infrastructure, experiment
scripts, and evaluation data accompanying our paper:

> **Migration as a Steady-State Execution Primitive: A Runtime for Virtual Stationarity in Low-Earth Orbit**  
> Daniel Kleebinder, Alireza Furutanpey, and Stefan Nastic  
> *The 16th International Conference on the Internet of Things (IoT 2026)*

Low-Earth Orbit (LEO) satellite constellations provide an opportunity to execute
latency-sensitive applications close to users on the ground. However, individual
satellites remain in direct line-of-sight of a fixed geographic region for only
a limited amount of time. Maintaining geographic proximity therefore requires
applications to migrate continuously between successive satellites.

Our work treats **live migration as a steady-state execution primitive** rather
than as an exceptional infrastructure operation. We introduce the
**Virtual Stationarity Runtime (VSR)** and a **Migration Membrane** that combines:

- **Capability Virtualization**, which decouples logical application capabilities
  from host-specific resources and rebinds them on the successor host.
- **Continuous State Projection**, which reconstructs the evolving execution state
  on the successor while the source continues executing.
- An explicit **authority transfer mechanism** that ensures that only one host can
  produce externally visible effects at any point in time.

Our prototype is implemented on top of the
[WebAssembly Micro Runtime (WAMR)](https://github.com/wasm-micro-runtime/wasm-micro-runtime).

## Repository Structure

The project is organized as follows:

### `constellation-simulator/`

Contains the constellation simulation engine used to generate orbital and network
traces for the experiments in the paper.

The simulator includes:

- satellite constellation and link simulation,
- experiment trace generation,
- visualization utilities, and
- a **Hardware-in-the-Loop-style orchestrator** that controls our Raspberry Pi
  testbed according to simulated satellite link configurations.

### `hardware-experiments/`

Contains the infrastructure used to execute experiments on our physical Raspberry
Pi testbed, including:

- Ansible configuration,
- shell scripts, and
- experiment-specific setup and execution utilities.

This directory primarily contains the smaller-scale and physical testbed
experiments presented in the paper.

### `migration-membrane/`

Contains our implementation of the **Migration Membrane** as well as scripts for
integrating the modified source files into a specific version of WAMR.

The implementation provides the runtime mechanisms used for recurrent migration,
including capability rebinding, continuation recording and replay, and authority
transfer between source and successor hosts.

## Experimental Data

Where possible, the corresponding experiment traces are included alongside the
experiment implementations in:

- `constellation-simulator/`
- `hardware-experiments/`

Some raw traces exceeded GitHub's 100 MB file-size limit and are therefore not
included in this repository.

All **aggregated results used in the paper are included**, allowing the reported
figures and evaluation results to be inspected without the omitted raw traces.

## Evaluation

The evaluation covers recurrent migration, semantic continuity, migration
scalability, cross-architecture portability, and orbital feasibility.

Among the results reported in the paper:

- **300 consecutive migrations** complete without cumulative growth in migration
  time or continuation state.
- The measured **p95 migration downtime remains below 6 ms**.
- Continuous State Projection remains effectively invariant to application
  memory-write rate, unlike pre-copy migration.
- The prototype successfully migrates workloads between **x86-64 and ARM64**.
- Under simulated orbital schedules, migrations complete within the available
  handover windows for target latency SLOs between **6 ms and 14 ms**.

## Paper

If you use this artifact in your work, please cite:

> Daniel Kleebinder, Alireza Furutanpey, and Stefan Nastic.  
> **Migration as a Steady-State Execution Primitive: A Runtime for Virtual
> Stationarity in Low-Earth Orbit.**  
> In *Proceedings of the 16th International Conference on the Internet of Things
> (IoT 2026)*, 2026.

<!--
Add the final DOI / BibTeX entry here once available.
-->

## License

<!-- Add the repository license here. -->
