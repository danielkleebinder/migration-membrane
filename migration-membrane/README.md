# VSR Migration Membrane for WAMR

> **Research artifact.** This repository contains only the source files,
> integration delta, and workloads contributed by this work. It does not
> redistribute a complete WebAssembly Micro Runtime (WAMR) source tree.
> [`reconstruct.sh`](./reconstruct.sh) reconstructs the
> complete prototype from the exact upstream revision used in the paper.

This artifact accompanies our work on the **Virtual Stationarity Runtime
(VSR)**. VSR treats recurrent migration between passing satellite hosts as a
steady-state execution primitive. The prototype implements the runtime-side
Migration Membrane and integrates it with WAMR's classic interpreter.

The artifact does **not** implement orbital prediction, successor selection,
migration scheduling, or network path control. Those responsibilities belong
to an external orbital orchestrator, which supplies the successor host,
handover trigger, and migration budget.

## Repository Layout

| Path | Contents |
| --- | --- |
| [`membrane/`](./membrane/) | Migration Membrane implementation introduced by this work |
| [`samples/`](./samples/) | Smoke tests, example applications, and evaluation workloads |
| [`wamr.patch`](./wamr.patch) | Modifications to existing upstream WAMR integration points |
| [`reconstruct.sh`](./reconstruct.sh) | Reconstructs a complete, buildable WAMR prototype |

The separation is intentional. New implementation files remain directly
inspectable under `membrane/` and `samples/`; the patch contains only the
changes needed in existing WAMR files. During reconstruction, the script
applies the patch and copies the contribution files into the appropriate
locations in the upstream tree.

## Relationship to Upstream WAMR

The prototype is based on Bytecode Alliance WAMR revision
[`c6fbf20d17d36b1fb5bdf75c8ef7273475daa206`](https://github.com/wasm-micro-runtime/wasm-micro-runtime/commit/c6fbf20d17d36b1fb5bdf75c8ef7273475daa206).
Upstream WAMR provides the portable execution engine, including the classic
interpreter, module loader, memory model, and WASI implementation. This work
contributes the Migration Membrane, its runtime integration, and the workloads
used to exercise and evaluate it.

In particular:

- `membrane/` a post-evaluation structural refactoring that exposes the contribution more clearly.
- `samples/` readable copies of the custom workloads.
- `wamr.patch` the exact, immutable implementation delta used for all reported experiments.
- The unmodified WAMR source is retrieved directly from the upstream
  repository and is not part of this artifact.

## Reconstructing the Prototype

### Requirements

- Git
- Bash
- Network access to GitHub
- CMake 3.14 or newer
- A C/C++ compiler and GNU Make
- Linux with POSIX threads, TCP networking, and `memfd_create` support

From the artifact root, run:

```bash
chmod +x ./reconstruct.sh

./reconstruct.sh \
  ./wamr.patch \
  ./runtime
```

The script:

1. clones the upstream WAMR repository;
2. checks out revision
   `c6fbf20d17d36b1fb5bdf75c8ef7273475daa206`;
3. validates and applies `wamr.patch`;
4. stages the resulting changes for inspection without creating a commit.

The script refuses to overwrite an existing destination. On success,
`./runtime` contains the complete reconstructed prototype.

## Inspecting the Contribution

The complete contribution can be inspected as an ordinary Git diff against
the pinned upstream revision:

```bash
git -C ./runtime diff --cached
```

Useful variants include:

```bash
# Compact change summary
git -C ./runtime diff --cached --stat

# Added and modified paths
git -C ./runtime diff --cached --name-status

# Classic-interpreter integration only
git -C ./runtime diff --cached --word-diff=color -- \
  core/iwasm/interpreter/wasm_interp_classic.c

# Capability integration only
git -C ./runtime diff --cached -- \
  core/iwasm/libraries/libc-wasi \
  core/iwasm/libraries/lib-socket

# Configured graphical diff tool, if available
git -C ./runtime difftool --cached
```

The changes to existing upstream files can also be viewed without
reconstruction:

```bash
less ./wamr.patch
```

## Implementation Structure

The files under [`membrane/`](./membrane/) separate the mechanisms from their
WAMR integration:

| File | Responsibility |
| --- | --- |
| [`membrane.c`](./membrane/membrane.c), [`membrane.h`](./membrane/membrane.h) | Public membrane lifecycle and runtime modes |
| [`projection.c`](./membrane/projection.c), [`projection.h`](./membrane/projection.h) | Base transfer, continuation recording and replay, convergence, and authority transfer |
| [`capabilities.c`](./membrane/capabilities.c), [`capabilities.h`](./membrane/capabilities.h) | Logical capability handling and target-local resource rebinding |
| [`integration.c`](./membrane/integration.c), [`integration.h`](./membrane/integration.h) | WAMR execution-state capture, restoration, and interpreter resumption |
| [`transport.c`](./membrane/transport.c), [`transport.h`](./membrane/transport.h) | Reliable transfer helpers used by the control and projection channels |
| [`protocol.h`](./membrane/protocol.h) | Wire-format records, control markers, and protocol constants |
| [`internals.h`](./membrane/internals.h) | Internal context shared by membrane modules |
| [`utilities.c`](./membrane/utilities.c), [`utilities.h`](./membrane/utilities.h) | Internal utility functions |
| [`iwasm_migration.cmake`](./membrane/iwasm_migration.cmake) | Build integration for the membrane modules |

The patch modifies existing WAMR code only where integration is required,
including interpreter safe points, native-call interception, mutation tracking,
runtime configuration, socket rebinding, command-line control, and build
registration.

## Paper-to-Code Mapping

| Paper concept | Purpose | Primary implementation |
| --- | --- | --- |
| Portable Execution ($\mathcal{X}$) | Represents execution independently of the source OS and ISA | Upstream WAMR classic interpreter |
| State Capture and Restoration ($\mathcal{S}$) | Captures a relocatable base state and restores it on the successor | [`integration.c`](./membrane/integration.c) and the interpreter hooks in [`wamr.patch`](./wamr.patch) |
| Continuous State Projection ($\mathcal{P}$) | Projects host-call outcomes and application-memory mutations while the source continues executing | [`projection.c`](./membrane/projection.c) |
| Capability Virtualization ($\mathcal{V}$) | Rebinds logical capabilities to target-local resources | [`capabilities.c`](./membrane/capabilities.c) and the WASI/socket hooks in [`wamr.patch`](./wamr.patch) |
| Runtime modes and authority fence | Suppresses effects during replay and transfers authority exactly once | [`membrane.c`](./membrane/membrane.c), [`projection.c`](./membrane/projection.c), and [`protocol.h`](./membrane/protocol.h) |
| Orbital orchestration | Selects the successor, trigger, budget, and path update | External to this artifact |

## Handover Protocol

The prototype realizes the four VSR handover phases:

1. **Prepare:** The source reaches an interpreter safe point and captures a
   portable base state. Linear memory is backed by `memfd_create`; a private
   copy-on-write mapping preserves the base while source execution resumes.
2. **Reconstruct:** The base is transferred and restored on the successor.
   Target-local capability bindings are created but remain inactive.
3. **Project:** The authoritative source enters Record mode and emits ordered
   continuation events. The successor enters Replay mode and reconstructs the
   same execution without invoking its local capability bindings.
4. **Commit:** The source revokes authority and emits an `END` event containing
   an execution fence. The successor activates only after consuming all prior
   events and reaching the same fence.

Each runtime operates in one of four modes:

- **Live:** normal authoritative execution;
- **Record:** authoritative execution that additionally emits continuation
  events;
- **Replay:** non-authoritative reconstruction without new external effects;
  and
- **Inactive:** prepared or revoked bindings that cannot produce effects.

## Continuous State Projection

Continuous State Projection combines a portable base snapshot with an ordered
continuation of host interactions that occur while the base is in transit. A
control channel carries the base state and handover messages, while a separate
projection channel carries continuation events and replay progress.

For every intercepted host call, the source records:

- a monotonically increasing sequence number;
- a hash identifying the imported module and function;
- the direct return values; and
- the application-memory regions modified by the call.

Memory mutations are serialized as application-memory offsets, lengths, and
copied bytes. This distinction matters for operations such as file or socket
reads: their direct return value contains only a status or byte count, while
the actual payload is written into application memory. During replay, the
successor applies these mutations and returns the recorded result without
executing the target-local operation. Background sender and receiver threads
decouple event transport from interpreter execution.

At commit, the source emits a terminal `END` event containing its completed
opcode counter and opcode identifier. The successor becomes authoritative only
after consuming all preceding events and reaching that execution fence.

## Capability Virtualization

Capability Virtualization separates the logical identity of a host-dependent
operation from its physical realization. The prototype interposes at WAMR's
native-call boundary. WASI provides the capability surface used in this
implementation, but the mechanism is a runtime abstraction: logical
capabilities persist across hosts while physical resources are recreated and
rebound locally.

During migration:

- the source invokes its active local bindings in Live or Record mode;
- the successor prepares target-local bindings during reconstruction;
- successor bindings remain inactive during Replay;
- missing optional operations return the defined unavailable behavior;
- commit revokes source bindings before activating successor bindings; and
- subsequent calls use target-local resources without predecessor access.

The evaluated UDP capability preserves its logical descriptor and port while
creating a new target-local socket and updating WAMR's descriptor mapping.

## Building the Reconstructed Prototype

After reconstruction, enter the generated WAMR tree and build the prototype:

```bash
cd ./runtime
bash build.sh
```

The build configures WAMR's classic interpreter with the migration modules and
produces the `iwasm` executable in the reconstructed repository root.

## Compile, Run, and Migrate a Sample

The following smoke test migrates a small WebAssembly program between two
runtime instances on one machine. It requires a WASI-capable Clang toolchain.
Run these commands from the reconstructed repository root.

Compile the sample module:

```bash
clang \
  --target=wasm32-wasi \
  -O2 \
  -I ./core/iwasm/libraries/lib-socket/inc \
  ./core/iwasm/libraries/lib-socket/src/wasi/wasi_socket_ext.c \
  ./samples/hello/hello.c \
  -o ./samples/hello/hello.wasm
```

In the first terminal, start the authoritative source and expose its migration
endpoint on port `8080`:

```bash
./iwasm \
  --addr-pool=0.0.0.0/0 \
  --migration-server=8080 \
  ./samples/hello/hello.wasm
```

In a second terminal, start the successor and request migration from the
source:

```bash
./iwasm \
  --addr-pool=0.0.0.0/0 \
  --migrate=localhost:8080 \
  --migration-server=8090 \
  ./samples/hello/hello.wasm
```

The successor reconstructs the running application, reaches the transferred
execution fence, and assumes authority. It then exposes its own migration
endpoint on port `8090`, allowing the handover sequence to continue.

For two physical hosts, place the reconstructed runtime and identical module
on both machines, replace `localhost` with the source host's reachable address,
and permit the selected ports through the network. `--addr-pool` grants the
WebAssembly application network access and is required by the UDP workloads.

## Evaluation Workloads

The [`samples/`](./samples/) directory contains the custom applications used to
exercise the prototype:

- `hello/`: minimal reconstruction and migration smoke test;
- `state-continuity/`: sequence, nondeterministic-state, and effect-continuity
  validation;
- `recurrent-migration-soak/`: repeated-handover longevity workload;
- `membrane-overhead/`: steady-state interception overhead;
- `memory-load/`: base-state and memory-write scaling;
- `syscalls/`: native-call record and replay microbenchmarks;
- `udp-server/`, `udp-broadcast/`, and `udp-broadcast-memory/`: UDP capability
  and memory-mutation workloads; and
- `vr-benchmark/`: packet-oriented workload used with the emulated orbital
  profiles.

Large generated binaries, build products, and benchmark datasets are excluded
from the source artifact. They are not required for reconstructing or compiling
the prototype.

## Current Scope and Assumptions

The prototype currently assumes:

- reliable FIFO transport, implemented over TCP;
- single-threaded WebAssembly modules;
- synchronous host interactions through WAMR's native-call boundary;
- deterministic execution between intercepted host calls;
- Linux `memfd_create` support for copy-on-write base capture;
- WAMR's classic interpreter;
- target-local rebinding for the implemented capability classes; and
- an external component for successor selection, trigger timing, migration
  budgets, and path updates.

Failures before source-authority revocation abort reconstruction and leave the
source authoritative. Recovery after source revocation is outside the current
prototype scope.

## License and Attribution

The reconstructed runtime remains subject to WAMR's original licensing and
attribution. Research-specific additions and modifications use the same
`Apache-2.0 WITH LLVM-exception` SPDX identifier unless stated otherwise.
