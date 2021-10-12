from enum import Enum
import math
import cocotb
from cocotb.triggers import Timer, RisingEdge

class BusErrorResponse(Exception):
    pass

class WrongErrorSequence(Exception):
    pass

class WrongHREADYOUTSequence(Exception):
    pass

class HTRANS(Enum):
    IDLE = 0
    BUSY = 1
    NONSEQ = 2
    SEQ = 3

class AMBA3AHBLiteDriver:
    """Wraps up a collection of functions to drive an AMBA3AHBLite Bus.

    This is not an extensive set of features and merely enough to test
    out SRDL2SV registers.
    """

    def __init__(self, dut, nbytes: int):
        self._nbytes = nbytes
        self._dut = dut

    @cocotb.coroutine
    async def reset(self, time: int = 10):
        """Resets bus for a given amount of time"""

        self._dut.HRESETn <= 0

        await Timer(time, units='ns')
        await RisingEdge(self._dut.clk)

        self._dut.HRESETn <= 1

    @cocotb.coroutine
    async def write(self, address: int, value: int, nbytes = None, step_size = None):
        if not nbytes:
            nbytes = self._nbytes

        if not step_size:
            if (step_size := address % self._nbytes) == 0:
                step_size = self._nbytes

        # Dictionary to return address/value pairs
        write_dict = {}

        # Start counting bytes
        nbytes_cnt = 0

        # Initiate write
        self._dut.HSEL <= 1
        self._dut.HWRITE <= 1
        self._dut.HADDR <= address
        self._dut.HTRANS <= HTRANS.NONSEQ.value
        self._dut.HSIZE <= int(math.log2(step_size))

        await RisingEdge(self._dut.clk)

        while True:
            if self._dut.HREADYOUT.value:
                # Save address from previous phase
                previous_address = int(self._dut.HADDR.value)

                # Set data for dataphase
                self._dut.HWDATA <= (value >> (nbytes_cnt * 8))

                # Check if we are done in next phase
                if (nbytes_cnt := nbytes_cnt + step_size) >= nbytes:
                    self._dut.HTRANS <= HTRANS.IDLE.value
                else:
                    # Update address
                    self._dut.HADDR <= self._dut.HADDR.value + step_size

                # Wait for next clock cycle
                await RisingEdge(self._dut.clk)

                # Save into dictionary
                write_dict[previous_address] = int(self._dut.HWDATA.value)

            # If HREADYOUT == 0 immediately after the first address phase
            # this is illegal
            elif nbytes_cnt == 0:
                raise WrongHREADYOUTSequence
            # If the slave is not yet ready, just wait
            else:
                await RisingEdge(self._dut.clk)
                continue

            # Check for error condition
            if self._dut.HRESP.value:
                if self._dut.HREADYOUT.value:
                    raise WrongErrorSequence

                await RisingEdge(self._dut.clk)

                if self._dut.HREADYOUT.value:
                    raise BusErrorResponse

                raise WrongErrorSequence


            if nbytes_cnt >= nbytes:
                break

        self._dut.HWRITE <= 0
        self._dut.HSEL <= 0

        await RisingEdge(self._dut.clk)

        return write_dict

    @cocotb.coroutine
    async def read(self, address: int, nbytes = None, step_size = None):
        if not nbytes:
            nbytes = self._nbytes

        if not step_size:
            if (step_size := address % self._nbytes) == 0:
                step_size = self._nbytes

        # Dictionary to return address/value pairs
        read_dict = {}

        # Start counting bytes
        nbytes_cnt = 0

        # Initiate read
        self._dut.HSEL <= 1
        self._dut.HWRITE <= 0
        self._dut.HADDR <= address
        self._dut.HTRANS <= HTRANS.NONSEQ.value
        self._dut.HSIZE <= int(math.log2(step_size))

        await RisingEdge(self._dut.clk)

        while True:
            if self._dut.HREADYOUT.value:
                # Save address from previous phase
                previous_address = int(self._dut.HADDR.value)

                # Check if we are done in next phase
                if (nbytes_cnt := nbytes_cnt + step_size) >= nbytes:
                    self._dut.HTRANS <= HTRANS.IDLE.value
                else:
                    # Update address
                    self._dut.HADDR <= self._dut.HADDR.value + step_size

                # Wait for next clock cycle
                await RisingEdge(self._dut.clk)

                # Save into dictionary
                read_dict[previous_address] = int(self._dut.HRDATA.value)
            # If HREADYOUT == 0 immediately after the first address phase
            # this is illegal
            elif nbytes_cnt == 0:
                raise WrongHREADYOUTSequence
            # If the slave is not yet ready, just wait
            else:
                await RisingEdge(self._dut.clk)
                continue

            # Check for error condition
            if self._dut.HRESP.value:
                if self._dut.HREADYOUT.value:
                    raise WrongErrorSequence

                await RisingEdge(self._dut.clk)

                if self._dut.HREADYOUT.value:
                    raise BusErrorResponse

                raise WrongErrorSequence

            if nbytes_cnt >= nbytes:
                break

        self._dut.HTRANS <= HTRANS.IDLE.value
        self._dut.HSEL <= 0

        await RisingEdge(self._dut.clk)

        return read_dict
