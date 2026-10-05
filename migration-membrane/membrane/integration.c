#include "integration.h"

/* WAMR-specific execution-state capture, restoration, and resumption. */

#include "wasm_interp.h"
#include "wasm_runtime.h"
#include <stdio.h>
#include <string.h>

uint32_t
ptr_to_stack_offset(WASMExecEnv *exec_env, const void *ptr)
{
    if (!exec_env || !ptr)
        return LM_INVALID_OFFSET;

    return (uint32_t)((const uint8 *)ptr - exec_env->wasm_stack.bottom);
}

uint32_t
ptr_to_func_code_offset(WASMFunctionInstance *func, const uint8 *ptr)
{
    if (!func || !ptr || func->is_import_func)
        return LM_INVALID_OFFSET;

    return (uint32_t)(ptr - wasm_get_func_code(func));
}

uint8 *
func_code_offset_to_ptr(WASMFunctionInstance *func, uint32_t offset)
{
    if (!func || offset == LM_INVALID_OFFSET || func->is_import_func)
        return NULL;

    return wasm_get_func_code(func) + offset;
}

bool
serialize_execution_frames(WASMExecEnv *exec_env, WASMModuleInstance *module_inst,
                           LiveMigrationSerializedFrameStream *stream)
{
    WASMInterpFrame *frame;
    stream->offset = 0; // Reset stream pointer

    for (frame = exec_env->cur_frame; frame; frame = frame->prev_frame) {
        LMFrameRecord rec;
        uint32_t i;
        WASMBranchBlock *block;
        stream->count++;

        memset(&rec, 0, sizeof(rec));

        rec.frame_offset = ptr_to_stack_offset(exec_env, frame);
        rec.prev_frame_offset = ptr_to_stack_offset(exec_env, frame->prev_frame);

        if (frame->function && !frame->function->is_import_func) {
            rec.function_index = (uint32_t)(frame->function - module_inst->e->functions);
            rec.ip_offset = ptr_to_func_code_offset(frame->function, frame->ip);
            if (rec.ip_offset == LM_INVALID_OFFSET && frame->ip) {
                uint8 *code = wasm_get_func_code(frame->function);
                uint8 *code_end = wasm_get_func_code_end(frame->function);
                if (frame->ip >= code && frame->ip <= code_end) {
                    rec.ip_offset = (uint32_t)(frame->ip - code);
                }
            }
        }
        else if (frame->function && frame->function->is_import_func) {
            rec.function_index = (uint32_t)(frame->function - module_inst->e->functions);
            rec.ip_offset = LM_INVALID_OFFSET; // Native functions do not have bytecode ip
        }
        else {
            rec.function_index = LM_INVALID_OFFSET;
            rec.ip_offset = LM_INVALID_OFFSET;
        }

        rec.sp_offset = ptr_to_stack_offset(exec_env, frame->sp);
        rec.sp_bottom_offset = ptr_to_stack_offset(exec_env, frame->sp_bottom);
        rec.sp_boundary_offset = ptr_to_stack_offset(exec_env, frame->sp_boundary);

        rec.csp_offset = ptr_to_stack_offset(exec_env, frame->csp);
        rec.csp_bottom_offset = ptr_to_stack_offset(exec_env, frame->csp_bottom);
        rec.csp_boundary_offset = ptr_to_stack_offset(exec_env, frame->csp_boundary);

        if (frame->csp && frame->csp_bottom && frame->csp >= frame->csp_bottom)
            rec.active_csp_count = (uint32_t)(frame->csp - frame->csp_bottom);
        else
            rec.active_csp_count = 0;

        // --- SAFE IN-MEMORY WRITE (No Network Blocking) ---
        if (stream->offset + sizeof(rec) > sizeof(stream->buffer)) {
            return false; // Buffer overflow protection
        }
        memcpy(stream->buffer + stream->offset, &rec, sizeof(rec));
        stream->offset += sizeof(rec);

        // Serialize Control Stack Blocks (CSP)
        block = frame->csp_bottom;
        for (i = 0; i < rec.active_csp_count; i++, block++) {
            LMCSPRecord csp_rec;

            csp_rec.frame_sp_offset = ptr_to_stack_offset(exec_env, block->frame_sp);

            if (frame->function && !frame->function->is_import_func) {
                csp_rec.begin_addr_offset = ptr_to_func_code_offset(frame->function, block->begin_addr);
                csp_rec.target_addr_offset = ptr_to_func_code_offset(frame->function, block->target_addr);
            }
            else {
                csp_rec.begin_addr_offset = LM_INVALID_OFFSET;
                csp_rec.target_addr_offset = LM_INVALID_OFFSET;
            }

            if (stream->offset + sizeof(csp_rec) > sizeof(stream->buffer)) {
                return false;
            }
            memcpy(stream->buffer + stream->offset, &csp_rec, sizeof(csp_rec));
            stream->offset += sizeof(csp_rec);
        }
    }
    return true;
}

bool
restore_state(wasm_exec_env_t exec_env, int fd)
{
    WASMModuleInstance *module_inst;
    uint32_t magic = 0;
    uint32_t version = 0;

    uint32_t linear_memory_data_size = 0;
    uint8_t *new_linear_memory_base;

    uint32_t stored_stack_size = 0;
    uint32_t cur_frame_offset = LM_INVALID_OFFSET;
    uintptr_t old_stack_bottom = 0;
    uint8_t *new_stack_bottom;

    uint32_t frame_count = 0;
    uint32_t frame_i;

    if (!exec_env) {
        return false;
    }

    if (!transfer_read(fd, &magic, sizeof(magic)) || !transfer_read(fd, &version, sizeof(version))) {
        printf("[LM/Restore] ERROR: Could not read migration prefix and version\n");
        return false;
    }

    if (magic != LM_DUMP_MAGIC || version != LM_DUMP_VERSION) {
        return false;
    }

    module_inst = (WASMModuleInstance *)wasm_runtime_get_module_inst(exec_env);
    if (!module_inst || !module_inst->memories || !module_inst->memories[0]) {
        printf("[LM/Restore] ERROR: Could load module\n");
        return false;
    }

    if (!transfer_read(fd, &stored_stack_size, sizeof(stored_stack_size))
        || !transfer_read(fd, &old_stack_bottom, sizeof(old_stack_bottom))) {
        printf("[LM/Restore] ERROR: Could not read stack size\n");
        return false;
    }
    (void)old_stack_bottom;

    if (stored_stack_size > exec_env->wasm_stack_size) {
        printf("[LM/Restore] ERROR: Stack size does not match\n");
        return false;
    }

    new_stack_bottom = exec_env->wasm_stack.bottom;

    if (!transfer_read(fd, new_stack_bottom, stored_stack_size)) {
        printf("[LM/Restore] ERROR: Could not read new stack size\n");
        return false;
    }

    exec_env->wasm_stack.top = new_stack_bottom + stored_stack_size;

    uint32_t stored_global_data_size = 0;
    if (!transfer_read(fd, &stored_global_data_size, sizeof(stored_global_data_size))) {
        printf("[LM/Restore] ERROR: Could not read global data size\n");
        return false;
    }
    if (stored_global_data_size > module_inst->global_data_size) {
        printf("[LM/Restore] ERROR: Global data size from migration is too large\n");
        return false;
    }
    printf("[LM/Restore] State metadata loaded\n");

    if (!transfer_read(fd, module_inst->global_data, stored_global_data_size)) {
        printf("[LM/Restore] ERROR: Could not read global data\n");
        return false;
    }

    new_linear_memory_base = module_inst->memories[0]->memory_data;
    if (!transfer_read(fd, &linear_memory_data_size, sizeof(linear_memory_data_size))) {
        printf("[LM/Restore] ERROR: Could not read required linear memory size\n");
        return false;
    }

    if (linear_memory_data_size > module_inst->memories[0]->memory_data_size) {
        uint32_t current_memory_size = (uint32_t)module_inst->memories[0]->memory_data_size;
        uint32_t needed_bytes = linear_memory_data_size - current_memory_size;
        uint32_t inc_page_count = (needed_bytes + DEFAULT_NUM_BYTES_PER_PAGE - 1) / DEFAULT_NUM_BYTES_PER_PAGE;

        if (!wasm_enlarge_memory(module_inst, inc_page_count)) {
            printf("[LM/Restore] ERROR: Could not enlarge linear memory\n");
            return false;
        }
        new_linear_memory_base = module_inst->memories[0]->memory_data;
        printf("[LM/Restore] Had to enlarge linear memory for migration\n");
    }

    if (!transfer_read(fd, new_linear_memory_base, linear_memory_data_size)) {
        printf("[LM/Restore] ERROR: Could not read linear memory\n");
        return false;
    }
    printf("[LM/Restore] Linear memory loaded\n");

    if (!transfer_read(fd, &cur_frame_offset, sizeof(cur_frame_offset))
        || !transfer_read(fd, &frame_count, sizeof(frame_count))) {
        printf("[LM/Restore] ERROR: Could not read stack and shadow stack metadata\n");
        return false;
    }
    exec_env->cur_frame = (struct WASMInterpFrame *)(new_stack_bottom + cur_frame_offset);
    printf("[LM/Restore] Stack and shadow stack metadata loaded (frame count: %i, frame offset: %i)\n", frame_count,
           cur_frame_offset);

    for (frame_i = 0; frame_i < frame_count; frame_i++) {
        LMFrameRecord rec;
        WASMInterpFrame *frame;
        WASMFunctionInstance *func = NULL;
        uint32_t i;
        WASMBranchBlock *block;

        if (!transfer_read(fd, &rec, sizeof(rec))) {
            printf("[LM/Restore] ERROR: Could not load frame\n");
            return false;
        }

        frame = (WASMInterpFrame *)(new_stack_bottom + rec.frame_offset);

        if (rec.prev_frame_offset != LM_INVALID_OFFSET) {
            frame->prev_frame = (WASMInterpFrame *)(new_stack_bottom + rec.prev_frame_offset);
        }
        else {
            frame->prev_frame = NULL;
        }

        if (rec.function_index != LM_INVALID_OFFSET) {
            func = module_inst->e->functions + rec.function_index;
            frame->function = func;

            if (func->is_import_func) {
                // Native WASI frames do not have Wasm bytecode instructions
                frame->ip = NULL;
            }
            else {
                frame->ip = func_code_offset_to_ptr(func, rec.ip_offset);
                if (!frame->ip && rec.ip_offset != LM_INVALID_OFFSET) {
                    /* If offset is valid but ptr is NULL, it might be exactly at
                       code_end. Allow it if it's within bounds. */
                    uint8 *code = wasm_get_func_code(func);
                    uint32 code_size = wasm_get_func_code_end(func) - code;
                    if (rec.ip_offset <= code_size) {
                        frame->ip = code + rec.ip_offset;
                    }
                }
            }
        }
        else {
            frame->function = NULL;
            frame->ip = NULL;
        }

#define RESTORE_STACK_PTR(field, type)                                    \
    do {                                                                  \
        if (rec.field##_offset != LM_INVALID_OFFSET) {                    \
            frame->field = (type)(new_stack_bottom + rec.field##_offset); \
        }                                                                 \
        else {                                                            \
            frame->field = NULL;                                          \
        }                                                                 \
    } while (0)

        RESTORE_STACK_PTR(sp, uint32 *);
        RESTORE_STACK_PTR(sp_bottom, uint32 *);
        RESTORE_STACK_PTR(sp_boundary, uint32 *);
        RESTORE_STACK_PTR(csp, WASMBranchBlock *);
        RESTORE_STACK_PTR(csp_bottom, WASMBranchBlock *);
        RESTORE_STACK_PTR(csp_boundary, WASMBranchBlock *);

#undef RESTORE_STACK_PTR

        block = frame->csp_bottom;
        for (i = 0; i < rec.active_csp_count; i++, block++) {
            LMCSPRecord csp_rec;

            if (!transfer_read(fd, &csp_rec, sizeof(csp_rec))) {
                printf("[LM/Restore] ERROR: Could not load shadow frame\n");
                return false;
            }

            if (csp_rec.frame_sp_offset != LM_INVALID_OFFSET) {
                block->frame_sp = (uint32 *)(new_stack_bottom + csp_rec.frame_sp_offset);
            }
            else {
                block->frame_sp = NULL;
            }

            if (func && !func->is_import_func) {
                block->begin_addr = func_code_offset_to_ptr(func, csp_rec.begin_addr_offset);
                if (!block->begin_addr && csp_rec.begin_addr_offset != LM_INVALID_OFFSET) {
                    uint8 *code = wasm_get_func_code(func);
                    uint32 code_size = wasm_get_func_code_end(func) - code;
                    if (csp_rec.begin_addr_offset <= code_size)
                        block->begin_addr = code + csp_rec.begin_addr_offset;
                }
                block->target_addr = func_code_offset_to_ptr(func, csp_rec.target_addr_offset);
                if (!block->target_addr && csp_rec.target_addr_offset != LM_INVALID_OFFSET) {
                    uint8 *code = wasm_get_func_code(func);
                    uint32 code_size = wasm_get_func_code_end(func) - code;
                    if (csp_rec.target_addr_offset <= code_size)
                        block->target_addr = code + csp_rec.target_addr_offset;
                }
            }
            else {
                block->begin_addr = NULL;
                block->target_addr = NULL;
            }
        }
    }

    printf("[LM/Restore] State restored\n");
    return true;
}

bool
live_migration_resume(wasm_exec_env_t exec_env, const clock_t benchmark_start)
{
    WASMExecEnv *exec_env_internal = (WASMExecEnv *)exec_env;
    WASMInterpFrame *cur_frame;
    WASMModuleInstance *module_inst;
    WASMFunctionInstance *native_func = NULL;
    bool resuming_native = false;
    uint32_t ip_offset;
    clock_t benchmark_end;
    double duration;

    if (!exec_env_internal || !exec_env_internal->cur_frame) {
        printf("[LM/Resume] Error: exec_env or cur_frame is NULL\n");
        return false;
    }

    cur_frame = exec_env_internal->cur_frame;
    module_inst = (WASMModuleInstance *)exec_env_internal->module_inst;
    if (!module_inst || !cur_frame->function) {
        printf("[LM/Resume] Error: module or current function is NULL\n");
        return false;
    }

    if (cur_frame->function < module_inst->e->functions
        || cur_frame->function
               >= module_inst->e->functions + module_inst->e->function_count) {
        printf("[LM/Resume] Error: restored function is outside the module\n");
        return false;
    }

    if (!cur_frame->function->is_import_func && !cur_frame->ip) {
        printf("[LM/Resume] Error: restored bytecode instruction is NULL\n");
        return false;
    }

    ip_offset = cur_frame->function->is_import_func
                    ? LM_INVALID_OFFSET
                    : ptr_to_func_code_offset(cur_frame->function,
                                              cur_frame->ip);
    printf("[LM/Resume] function=%p ip-offset=%u is-import=%d\n",
           cur_frame->function, ip_offset,
           cur_frame->function->is_import_func);

    wasm_exec_env_set_cur_frame(exec_env_internal, cur_frame);

    /* Native dispatch allocates its own frame, so resume from its caller. */
    if (cur_frame->function->is_import_func) {
        resuming_native = true;
        native_func = cur_frame->function;
        wasm_exec_env_free_wasm_frame(exec_env_internal, cur_frame);
        cur_frame = exec_env_internal->cur_frame;
    }

    wasm_set_exception(module_inst, NULL);

    benchmark_end = clock();
    duration = ((double)(benchmark_end - benchmark_start)) / CLOCKS_PER_SEC;
    printf("[LM/Resume] State restored in %f ms\n", duration * 1000.0);

    if (resuming_native) {
        wasm_interp_call_func_native(module_inst, exec_env_internal,
                                     native_func, cur_frame);
        cur_frame = exec_env_internal->cur_frame;
        if (!cur_frame)
            return true;

        module_inst = (WASMModuleInstance *)exec_env_internal->module_inst;
        wasm_interp_call_func_bytecode(module_inst, exec_env_internal, NULL,
                                       cur_frame);
    }
    else {
        wasm_interp_call_func_bytecode(module_inst, exec_env_internal, NULL,
                                       cur_frame);
    }

    return !wasm_copy_exception(module_inst, NULL);
}
