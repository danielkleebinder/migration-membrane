# Copyright (C) 2019 Intel Corporation.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

set (IWASM_MIGRATION_DIR ${CMAKE_CURRENT_LIST_DIR})

include_directories (${IWASM_MIGRATION_DIR})

set (IWASM_MIGRATION_SOURCE
    ${IWASM_MIGRATION_DIR}/membrane.c
    ${IWASM_MIGRATION_DIR}/projection.c
    ${IWASM_MIGRATION_DIR}/capabilities.c
    ${IWASM_MIGRATION_DIR}/utilities.c
    ${IWASM_MIGRATION_DIR}/transport.c
    ${IWASM_MIGRATION_DIR}/integration.c
)
