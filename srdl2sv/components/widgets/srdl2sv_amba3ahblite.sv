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

module srdl2sv_amba3ahblite
    import srdl2sv_if_pkg::*;
#(
    parameter bit FLOP_REGISTER_IF = 0,
    parameter     BUS_BITS         = 32
)
(
    // Outputs to internal logic
    output b2r_t                b2r,

    // Inputs from internal logic
    input  r2b_t                r2b,
 
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
    output logic [BUS_BITS-1:0] HRDATA
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
    logic [31:0] addr_q;
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
                    // Floor address. Sub-register access will be handled by byte-enables
                    addr_q      <= {HADDR[31:BUS_BYTES_W], {BUS_BYTES_W{1'b0}}};
                    operation_q <= HWRITE ? WRITE : READ;
                end
            end
            SEQ:
            begin
                if (HREADYOUT)
                    // Floor address. Sub-register access will be handled by byte-enables
                    addr_q      <= {HADDR[31:BUS_BYTES_W], {BUS_BYTES_W{1'b0}}};
            end
        endcase
    end

    /****************************
     * Statemachine
     ****************************/
    fsm_t fsm_next, fsm_q;

    always_comb
    begin
        // Defaults
        HREADYOUT = 1'b1;
        HRESP     = 1'b0;
        HRDATA    = r2b.data;

        b2r_w_vld_next = 0;
        b2r_r_vld_next = 0;
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
                HREADYOUT = r2b.rdy;
                b2r_w_vld_next = operation_q == WRITE;
                b2r_r_vld_next = operation_q == READ;

                if (r2b.err && r2b.rdy)
                begin
                    fsm_next = FSM_ERR_0;
                end
                else if (HTRANS == BUSY)
                begin
                    // Wait
                    fsm_next = FSM_TRANS;
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
                    fsm_next = r2b.rdy ? FSM_IDLE : FSM_TRANS;
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
    logic [BUS_BYTES-1:0] b2r_byte_en_next;
    logic                 b2r_w_vld_next;
    logic                 b2r_r_vld_next;

    always_comb
    begin
        for (int i = 0; i < BUS_BYTES; i++)
            HSIZE_bitfielded[i] = i < (1 << HSIZE);

        // Shift if not the full bus is accessed
        b2r_byte_en_next = HSIZE_bitfielded << (HADDR % BUS_BYTES);
    end

    /***
     * Drive interface to registers
     ***/
    generate
    if (FLOP_REGISTER_IF)
    begin
        always_ff @ (posedge HCLK or negedge HRESETn)
            if (!HRESETn)
            begin
                b2r.w_vld <= 1'b0;
                b2r.r_vld <= 1'b0;
            end
            else
            begin
                b2r.w_vld <= b2r_w_vld_next;
                b2r.r_vld <= b2r_r_vld_next;
            end

        always_ff @ (posedge HCLK)
        begin
            b2r.addr    <= addr_q;
            b2r.data    <= HWDATA << HADDR[BUS_BYTES_W-1:0];
            b2r.byte_en <= b2r_byte_en_next;
        end
    end
    else
    begin
        assign b2r.w_vld   = b2r_w_vld_next;
        assign b2r.r_vld   = b2r_r_vld_next;
        assign b2r.addr    = addr_q;
        assign b2r.data    = HWDATA << HADDR[BUS_BYTES_W-1:0];
        assign b2r.byte_en = b2r_byte_en_next;
    end
    endgenerate

endmodule
