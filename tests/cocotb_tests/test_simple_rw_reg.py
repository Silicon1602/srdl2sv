from enum import Enum
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
import cocotb
import random

from libs import AMBA3AHBLiteDriver

@cocotb.test()
async def test_ahb_access(dut):
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

@cocotb.test()
async def test_hw_access(dut):
    """Test writing via the hardware interface
    and reading it back.
    """

    clock = Clock(dut.clk, 1, units="ns")  # Create a 10us period clock on port clk
    cocotb.fork(clock.start())  # Start the clock

    bus = AMBA3AHBLiteDriver.AMBA3AHBLiteDriver(dut=dut, nbytes=4)

    await bus.reset()

    write_dict = {}
    read_dict = {}

    # TODO: At this point, CocoTB has issues with single dimension unpacked but
    #       multidimensional packed arrays. Only check first dimension
    dut.register_0__f1_hw_wr <= 1
    dut.register_0__f2_hw_wr <= 1

    rand_val = []

    for addr in (0, 2):
        # Save value that was written in dictionary
        write_dict[addr] = random.randint(0, (1 << 16)-1)

    dut.register_0__f2_in <= [write_dict[2], 0] #, write_dict[6]]
    dut.register_0__f1_in <= [write_dict[0], 0] #, write_dict[4]]

    await RisingEdge(dut.clk)

    dut.register_0__f1_hw_wr <= 0
    dut.register_0__f2_hw_wr <= 0

    for addr in range(0, 4, 2):
        read_dict.update(
            await bus.read(
                address=addr,
                nbytes=2,
                step_size=2))

    dut._log.info(f"Wrote dictionary {write_dict}")
    dut._log.info(f"Read back dictionary {read_dict}")
    assert write_dict == read_dict, "Read and write values differ!"

@cocotb.test()
async def test_hw_access_hw_wr_inactive(dut):
    """Test writing via the hardware interface but
    keeping the write-enable 0. The value that is
    read back should *not* be the same as the value
    that was fed by the testbench.
    """

    clock = Clock(dut.clk, 1, units="ns")  # Create a 10us period clock on port clk
    cocotb.fork(clock.start())  # Start the clock

    bus = AMBA3AHBLiteDriver.AMBA3AHBLiteDriver(dut=dut, nbytes=4)

    await bus.reset()

    write_dict = {}
    read_dict = {}

    # Force initial value
    dut.register_0__f1_q <= [0, 0]
    dut.register_0__f2_q <= [0, 0]

    # Disable write
    dut.register_0__f1_hw_wr <= 0
    dut.register_0__f2_hw_wr <= 0

    rand_val = []

    for addr in (0, 2, 4, 6):
        # Save value that was written in dictionary
        write_dict[addr] = random.randint(0, (1 << 16)-1)

    dut.register_0__f2_in <= [write_dict[2], write_dict[6]]
    dut.register_0__f1_in <= [write_dict[0], write_dict[4]]

    await RisingEdge(dut.clk)

    dut.register_0__f1_hw_wr <= 0
    dut.register_0__f2_hw_wr <= 0

    for addr in range(0, 8, 2):
        read_dict.update(
            await bus.read(
                address=addr,
                nbytes=2,
                step_size=2))

    dut._log.info(f"Wrote dictionary {write_dict}")
    dut._log.info(f"Read back dictionary {read_dict}")
    assert write_dict != read_dict, "Read and write values differ!"

@cocotb.test()
async def test_illegal_address(dut):
    """Test reading and writing to an illegal address.
    The logic should return a correct error sequence.
    """

    clock = Clock(dut.clk, 1, units="ns")  # Create a 10us period clock on port clk
    cocotb.fork(clock.start())  # Start the clock

    bus = AMBA3AHBLiteDriver.AMBA3AHBLiteDriver(dut=dut, nbytes=4)
    await bus.reset()

    rand_addr = random.randint(8, 1337)
    rand_val = random.randint(0, (1 << 8)-1)

    dut._log.info(f"Write value {rand_val} to illegal addres {rand_addr}.")

    write_error = False

    try:
        await bus.write(
            address=rand_addr,
            value=rand_val,
            nbytes=1,
            step_size=1)
    except AMBA3AHBLiteDriver.BusErrorResponse:
        write_error = True

    assert write_error == True, "Write to illegal address did not return an error!"

    read_error = False

    try:
        await bus.read(
            address=rand_addr,
            nbytes=1,
            step_size=1)
    except AMBA3AHBLiteDriver.BusErrorResponse:
        read_error = True

    assert read_error == True, "Read from illegal address did not return an error!"
