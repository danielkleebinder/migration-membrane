#ifndef _WASM_MIGRATION_WAMR_INTEGRATION_H_
#define _WASM_MIGRATION_WAMR_INTEGRATION_H_

#include "wasm_runtime_common.h"
#include "wasm_export.h"
#include "wasm_exec_env.h"
#include "wasm_interp.h"
#include "transport.h"
#include "protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

struct WASMFunctionInstance;
struct WASMModuleInstance;

uint32_t
ptr_to_stack_offset(WASMExecEnv *exec_env, const void *ptr);

uint32_t
ptr_to_func_code_offset(struct WASMFunctionInstance *func, const uint8 *ptr);

uint8 *
func_code_offset_to_ptr(struct WASMFunctionInstance *func, uint32_t offset);

bool
serialize_execution_frames(WASMExecEnv *exec_env,
                           struct WASMModuleInstance *module_inst,
                           LiveMigrationSerializedFrameStream *stream);

bool
restore_state(wasm_exec_env_t exec_env, int fd);

bool
live_migration_resume(wasm_exec_env_t exec_env, const clock_t benchmark_start);

#ifdef __cplusplus
}
#endif

#endif /* _WASM_MIGRATION_WAMR_INTEGRATION_H_ */
