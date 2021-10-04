from enum import Enum
from cocotb.clock import Clock
import cocotb
import random

from libs import AMBA3AHBLiteDriver

@cocotb.test()
async def test_simple_rw_reg(dut):
    """Test writing via the bus and reading back"""

    clock = Clock(dut.clk, 1, units="ns")  # Create a 10us period clock on port clk
    cocotb.fork(clock.start())  # Start the clock

    bus = AMBA3AHBLiteDriver.AMBA3AHBLiteDriver(dut=dut, nbytes=4)
    await bus.reset()

    # Write in 1, 2, and 4 byte steps
    for step_size in (1, 2, 4):
        dut._log.info(f"Writing in {step_size} steps.")

        write_dict = {}
        read_dict = {}

        for addr in range(0, 8, step_size):
            rand_val = random.randint(0, (1 << (step_size * 8))-1)

            dut._log.info(f"Write value {rand_val} to addres {addr}.")

            write_dict.update(
                await bus.write(
                    address=addr,
                    value=rand_val,
                    nbytes=step_size,
                    step_size=step_size))

        for addr in range(0, 8, step_size):
            read_dict.update(
                await bus.read(
                    address=addr,
                    nbytes=step_size,
                    step_size=step_size))

        # Check at end of every step_size
        dut._log.info(f"Wrote dictionary {write_dict}")
        dut._log.info(f"Read back dictionary {read_dict}")

        assert write_dict == read_dict, "Read and write values differ!"



