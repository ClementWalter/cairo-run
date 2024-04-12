import json
import logging
import os
import re
import shutil
from pathlib import Path
from time import perf_counter
from typing import AsyncGenerator

from starkware.cairo.lang.cairo_constants import DEFAULT_PRIME
from starkware.cairo.lang.compiler.cairo_compile import compile_cairo, get_module_reader
from starkware.cairo.lang.compiler.scoped_name import ScopedName
from starkware.cairo.lang.tracer.tracer_data import TracerData
from starkware.cairo.lang.vm import cairo_runner
from starkware.cairo.lang.vm.cairo_runner import CairoRunner
from starkware.cairo.lang.vm.memory_dict import MemoryDict
from starkware.cairo.lang.vm.memory_segments import FIRST_MEMORY_ADDR as PROGRAM_BASE
from starkware.starknet.business_logic.execution.execute_entry_point import (
    ExecuteEntryPoint,
)
from starkware.starknet.business_logic.state.state_api_objects import BlockInfo
from starkware.starknet.compiler.starknet_pass_manager import starknet_pass_manager
from starkware.starknet.definitions.general_config import StarknetGeneralConfig
from starkware.starknet.testing.starknet import Starknet

logger = logging.getLogger()

CASM_FILE = Path("target/dev/hello_scarb.casm")
SIERRA_FILE = CASM_FILE.with_suffix(".sierra.json")


start = perf_counter()
module_reader = get_module_reader(cairo_path=["."])
pass_manager = starknet_pass_manager(
    prime=DEFAULT_PRIME,
    read_module=module_reader.read,
    disable_hint_validation=True,
)
program = compile_cairo(
    CASM_FILE.read_text(),
    pass_manager=pass_manager,
    debug_info=False,
)
stop = perf_counter()
logger.info(f"{CASM_FILE} compiled in {stop - start:.2f}s")
sierra_program = json.loads(SIERRA_FILE.read_text())
entrypoint = [
    fun for fun in sierra_program["funcs"] if "main" in fun["id"]["debug_name"]
][0]
implicit_args = [
    re.sub(r"(?<!^)(?=[A-Z])", "_", arg["debug_name"]).lower().replace("_builtin", "")
    for arg in entrypoint["signature"]["param_types"]
]
add_output = len(entrypoint["signature"]["param_types"]) != len(
    entrypoint["signature"]["ret_types"]
)

# Fix builtins
program.builtins = [
    builtin
    # This list is extracted from the builtin runners
    # Builtins have to be declared in this order
    for builtin in [
        "output",
        "pedersen",
        "range_check",
        "ecdsa",
        "bitwise",
        "ec_op",
        "keccak",
        "poseidon",
        "range_check96",
    ]
    if builtin in implicit_args
]

memory = MemoryDict()
runner = CairoRunner(
    program=program,
    layout="starknet_with_keccak",
    memory=memory,
    proof_mode=False,
    allow_missing_builtins=False,
)
runner.initialize_segments()

stack = []
for arg in implicit_args:
    builtin_runner = runner.builtin_runners.get(f"{arg}_builtin")
    if builtin_runner is not None:
        stack.extend(builtin_runner.initial_stack())
        continue
    if arg == "gas":
        gas = runner.segments.add()
        stack.append(gas)
        continue

if add_output:
    output_ptr = runner.segments.add()
    stack.append(output_ptr)
return_fp = runner.segments.add()
end = runner.segments.add()
stack += [output_ptr, return_fp, end]

runner.initialize_state(entrypoint=entrypoint["entry_point"], stack=stack)
runner.initial_fp = runner.initial_ap = runner.execution_base + len(stack)
runner.final_pc = end

runner.initialize_vm(hint_locals={})
runner.run_until_pc(stack[-1])
runner.original_steps = runner.vm.current_step
runner.end_run(disable_trace_padding=False)
runner.relocate()
runner.print_segment_relocation_table()
runner.print_memory(relocated=False)
