#ifndef _WASM_MIGRATION_PROTOCOL_H_
#define _WASM_MIGRATION_PROTOCOL_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define LM_DUMP_MAGIC 0x57414D52u
#define LM_DUMP_VERSION 1u
#define LM_INVALID_OFFSET UINT32_MAX

/* Control Opcodes */
#define LM_EOF_START 0x01
#define LM_EOF_INITIAL 0x02
#define LM_EOF_RECONSTRUCT 0x03
#define LM_EOF_REPLAY 0x04
#define LM_EOF_COMPLETE_SERVER 0x05
#define LM_EOF_COMPLETE_CLIENT 0x06

typedef struct {
    uint32_t frame_offset;
    uint32_t prev_frame_offset;

    uint32_t function_index;
    uint32_t ip_offset;

    uint32_t sp_offset;
    uint32_t sp_bottom_offset;
    uint32_t sp_boundary_offset;

    uint32_t csp_offset;
    uint32_t csp_bottom_offset;
    uint32_t csp_boundary_offset;

    uint32_t active_csp_count;
} LMFrameRecord;

typedef struct {
    uint32_t frame_sp_offset;
    uint32_t begin_addr_offset;
    uint32_t target_addr_offset;
} LMCSPRecord;

#ifdef __cplusplus
}
#endif

#endif /* _WASM_MIGRATION_PROTOCOL_H_ */
