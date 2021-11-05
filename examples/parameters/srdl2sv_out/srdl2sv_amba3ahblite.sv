/*
 * Copyright 2021 Dennis Potter <dennis@dennispotter.eu>
 * 
 * Permission is hereby granted, free of charge, to any person 
 * obtaining a copy of this software and associated documentation
 * files (the "Software"), to deal in the Software without 
 * restriction, including without limitation the rights to use, 
 * copy, modify, merge, publish, distribute, sublicense, and/or 
 * sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following 
 * conditions:
 * 
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 * 
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
 * OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
 * NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
 * WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING 
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
 * OTHER DEALINGS IN THE SOFTWARE.
 */

module srdl2sv_amba3ahblite #(
    parameter bit FLOP_REGISTER_IF = 0,
    parameter     BUS_BITS         = 32,
    parameter     NO_BYTE_ENABLE   = 0
)
(
    // Bus protocol
    input                       HCLK,
    input                       HRESETn,
    input                       HSEL,
    input  [31:0]               HADDR,
    input                       HWRITE,
    input  [ 2:0]               HSIZE,
    input  [ 3:0]               HPROT, // Might be used in the future together with an RDL UDP
    input  [ 1:0]               HTRANS,
    input  [BUS_BITS-1:0]       HWDATA,

    output logic                HREADYOUT,
    output logic                HRESP,
    output logic [BUS_BITS-1:0] HRDATA,

    // Interface to internal logic
    srdl2sv_widget_if.widget    widget_if
);

    localparam BUS_BYTES = BUS_BITS/8;
    localparam BUS_BYTES_W = $clog2(BUS_BYTES);

    /***********************
     * Define enums 
     ***********************/
    typedef enum logic [2:0] {
        SINGLE = 3'b000,
        INCR   = 3'b001,
        WRAP4  = 3'b010,
        INCR4  = 3'b011,
        WRAP8  = 3'b100,
        INCR8  = 3'b101,
        WRAP16 = 3'b110,
        INCR16 = 3'b111
    } HBURST_t;

    typedef enum logic [1:0] {
        IDLE   = 2'b00,
        BUSY   = 2'b01,
        NONSEQ = 2'b10,
        SEQ    = 2'b11
    } HTRANS_t;

    typedef enum logic {
        OKAY   = 1'b0,
        ERROR  = 1'b1
    } HRESP_t;

    typedef enum logic {
        READ   = 1'b0,
        WRITE  = 1'b1
    } OP_t;

    typedef enum logic [1:0] {
        FSM_IDLE  = 2'b00,
        FSM_TRANS = 2'b01,
        FSM_ERR_0 = 2'b10,
        FSM_ERR_1 = 2'b11
    } fsm_t;

    /****************************
     * Determine current address
     ****************************/
    logic [31:0] HADDR_q;
    logic [2:0]  HSIZE_q;
    OP_t         operation_q;

    wire addr_err = HADDR % (32'b1 << HSIZE) != 32'b0; 

    always_ff @ (posedge HCLK)
    begin
        case (HTRANS)
            IDLE: ;// Do nothing
            BUSY: ;// Do nothing
            NONSEQ: 
            begin
                // When a transfer is extended it has the side-effecxt
                // of extending the address phase of the next transfer
                if (HREADYOUT)
                begin
                    HADDR_q     <= HADDR;
                    HSIZE_q     <= HSIZE;
                    operation_q <= HWRITE ? WRITE : READ;
                end
            end
            SEQ:
            begin
                if (HREADYOUT)
                begin
                    HADDR_q     <= HADDR;
                    HSIZE_q     <= HSIZE;
                end
            end
        endcase
    end

    /****************************
     * Statemachine
     ****************************/
    logic [BUS_BITS-1:0] HRDATA_temp;
    fsm_t                fsm_next, fsm_q;

    always_comb
    begin
        // Defaults
        HREADYOUT = 1'b1;
        HRESP     = OKAY;

        // When reading back, the data of the bit that was accessed over the bus
        // should be at byte 0 of the HRDATA bus and bits that were not accessed
        // should be masked with 0s.
        HRDATA_temp = widget_if.r_data >> (8*HADDR_q[BUS_BYTES_W-1:0]);

        for (int i = 0; i < BUS_BYTES; i++)
            if (i < (1 << HSIZE_q))
                HRDATA[8*(i+1)-1 -: 8] = HRDATA_temp[8*(i+1)-1 -: 8];
            else
                HRDATA[8*(i+1)-1 -: 8] = 8'b0;

        widget_if_w_vld_next = 0;
        widget_if_r_vld_next = 0;
        fsm_next       = fsm_q;

        case (fsm_q)
            default: // FSM_IDLE
            begin
                if (HSEL && HTRANS > BUSY)
                begin
                    if (addr_err)
                        // In case the address is illegal, switch to an error state
                        fsm_next = FSM_ERR_0;
                    else if (HTRANS == NONSEQ)
                        // If NONSEQ, go to NONSEQ state
                        fsm_next = FSM_TRANS;
                    else if (HTRANS == SEQ)
                        // If a SEQ is provided, something is wrong
                        fsm_next = FSM_ERR_0;
                end
            end
            FSM_TRANS:
            begin
                HREADYOUT = widget_if.rdy;
                widget_if_w_vld_next = operation_q == WRITE;
                widget_if_r_vld_next = operation_q == READ;

                if (HTRANS == BUSY)
                begin
                    // Wait
                    fsm_next = FSM_TRANS;
                end
                else if (widget_if.err && widget_if.rdy)
                begin
                    HREADYOUT = 0;
                    HRESP     = ERROR;
                    fsm_next  = FSM_ERR_1;
                end
                else if (HTRANS == NONSEQ)
                begin
                    // Another unrelated access is coming
                    fsm_next = FSM_TRANS;
                end
                else if (HTRANS == SEQ)
                begin
                    // Another part of the burst is coming
                    fsm_next = FSM_TRANS;
                end
                else if (HTRANS == IDLE)
                begin
                    // All done, wrapping things up!
                    fsm_next = widget_if.rdy ? FSM_IDLE : FSM_TRANS;
                end
            end
            FSM_ERR_0:
            begin
                HREADYOUT = 0;

                if (HTRANS == BUSY)
                begin
                    // Slaves must always provide a zero wait state OKAY response 
                    // to BUSY transfers and the transfer must be ignored by the slave.
                    HRESP     = OKAY;
                    fsm_next  = FSM_ERR_0;
                end
                else
                begin
                    HRESP     = ERROR;
                    fsm_next  = FSM_ERR_1;
                end
            end
            FSM_ERR_1:
            begin
                if (HTRANS == BUSY)
                begin
                    // Slaves must always provide a zero wait state OKAY response 
                    // to BUSY transfers and the transfer must be ignored by the slave.
                    HREADYOUT = 0;
                    HRESP     = OKAY;
                    fsm_next  = FSM_ERR_0;
                end
                else
                begin
                    HREADYOUT = 1;
                    HRESP     = ERROR;

                    fsm_next  = FSM_IDLE;
                end
            end
        endcase
    end


    always_ff @ (posedge HCLK or negedge HRESETn)
        if (!HRESETn)
            fsm_q <= FSM_IDLE;
        else
            fsm_q <= fsm_next;

    /***
     * Determine the number of active bytes
     ***/
    logic [BUS_BYTES-1:0] HSIZE_bitfielded;
    logic [BUS_BYTES-1:0] widget_if_byte_en_next;
    logic                 widget_if_w_vld_next;
    logic                 widget_if_r_vld_next;

    generate
    if (NO_BYTE_ENABLE)
    begin
        assign widget_if_byte_en_next = {BUS_BYTES{1'b1}}; 
    end
    else
    begin
        always_comb
        begin
            for (int i = 0; i < BUS_BYTES; i++)
                HSIZE_bitfielded[i] = i < (1 << HSIZE_q);

            // Shift if not the full bus is accessed
            widget_if_byte_en_next = HSIZE_bitfielded << (HADDR_q % BUS_BYTES);
        end
    end
    endgenerate

    /***
     * Drive interface to registers
     ***/
    generate
    if (FLOP_REGISTER_IF)
    begin
        always_ff @ (posedge HCLK or negedge HRESETn)
            if (!HRESETn)
            begin
                widget_if.w_vld <= 1'b0;
                widget_if.r_vld <= 1'b0;
            end
            else
            begin
                widget_if.w_vld <= widget_if_w_vld_next;
                widget_if.r_vld <= widget_if_r_vld_next;
            end

        always_ff @ (posedge HCLK)
        begin
            widget_if.addr    <= {HADDR_q[31:BUS_BYTES_W], {BUS_BYTES_W{1'b0}}};
            widget_if.w_data  <= HWDATA << (8*HADDR_q[BUS_BYTES_W-1:0]);
            widget_if.byte_en <= widget_if_byte_en_next;
        end
    end
    else
    begin
        assign widget_if.w_vld   = widget_if_w_vld_next;
        assign widget_if.r_vld   = widget_if_r_vld_next;
        assign widget_if.addr    = {HADDR_q[31:BUS_BYTES_W], {BUS_BYTES_W{1'b0}}};
        assign widget_if.w_data  = HWDATA << (8*HADDR_q[BUS_BYTES_W-1:0]);
        assign widget_if.byte_en = widget_if_byte_en_next;
    end
    endgenerate

endmodule


