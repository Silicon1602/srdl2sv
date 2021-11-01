from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
import cocotb
import random

from libs import AMBA3AHBLiteDriver

@cocotb.test()
async def test_rclr_rset(dut):
    """After reset, all rset fields are set to 0 and
    all rclr fields to 255. At the first read, these
    values shall be returned. At the second read, the
    inverse values shall be returned
    """

    clock = Clock(dut.clk, 1, units="ns")  # Create a 10us period clock on port clk
    cocotb.fork(clock.start())  # Start the clock

    bus = AMBA3AHBLiteDriver.AMBA3AHBLiteDriver(dut=dut, nbytes=4)

    # Reset DUT
    dut.field_reset_n <= 0
    await bus.reset()
    dut.field_reset_n <= 1

    await RisingEdge(dut.clk)

    read_return = await bus.read(
        address=0,
        nbytes=4,
        step_size=1)

    assert read_return == {0: 255, 1: 255, 2: 0, 3: 0}, "Reset values of registers are wrong!"

    # After the first read, values should be cleared/set
    read_return = await bus.read(
        address=0,
        nbytes=4,
        step_size=1)

    assert read_return == {0: 0, 1: 0, 2: 255, 3: 255}, "rset/rclr not working propertyl!"

@cocotb.coroutine
async def set_wr_enable_1clk_in (clk, hw_wr_enable):
        await RisingEdge(clk)
        hw_wr_enable <= 1
        await RisingEdge(clk)
        hw_wr_enable <= 0

@cocotb.test()
async def test_rclr_rset_hw_precedence(dut):
    """This test is identical to test_rclr_rset
    except that some fields have precendence=hw
    set. In those cases, the fields shall not be
    cleared/set by SW.
    """

    clock = Clock(dut.clk, 1, units="ns")  # Create a 10us period clock on port clk
    cocotb.fork(clock.start())  # Start the clock

    bus = AMBA3AHBLiteDriver.AMBA3AHBLiteDriver(dut=dut, nbytes=4)

    # Reset DUT
    dut.field_reset_n <= 0
    await bus.reset()
    dut.field_reset_n <= 1

    await RisingEdge(dut.clk)

    rand_val = random.randint(0, (1 << 8)-4)

    hw_wr_enable = \
        [dut.read_props_reg__rclr_test_field_hw_wr,
         dut.read_props_reg__rclr_test_field_hw_prec_hw_wr,
         dut.read_props_reg__rset_test_field_hw_wr,
         dut.read_props_reg__rset_test_field_hw_prec_hw_wr]

    dut.read_props_reg__rclr_test_field_in <= rand_val
    dut.read_props_reg__rclr_test_field_hw_prec_in <= rand_val + 1
    dut.read_props_reg__rset_test_field_in <= rand_val + 2
    dut.read_props_reg__rset_test_field_hw_prec_in <= rand_val + 3

    for i in range (0, 4):
        cocotb.fork(set_wr_enable_1clk_in(dut.clk, hw_wr_enable[i]))

        read_return = await bus.read(
            address=i,
            nbytes=1,
            step_size=1)

        dut._log.info(f"Read {read_return}.")

        assert read_return == {i: 255 if i < 2 else 0}, f"Read out value of address {i} incorrect"

    # After the first read, values should be cleared/set
    read_return = await bus.read(
        address=0,
        nbytes=4,
        step_size=1)

    dut._log.info("Read {read_return}.")

    assert read_return == {0: 0, 1: rand_val + 1, 2: 255, 3: rand_val + 3}, "precendence not working as intended!"
