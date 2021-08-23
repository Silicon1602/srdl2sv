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

module amba3ahblite_widget
    import srdl2sv_widget_pkg::*;
#(
    parameter FLOP_IN = 0, // Set to '1' to flop input from the AHB bus. This is meant
                           // to help meet timing. Don't use this to synchronize the input.
    parameter SYNC_IO = 0  // Set to '1' to in case HCLK and bus_clk are asynchronous
                           // By default, mainly for it to directly work in simulations,
                           // it will double-flops based on always_ff-blocks. To replace
                           // this module with a proper MTBF-optimized double flop cell,
                           // the contents of the synchronizer module `srdl2sv_sync.sv`
                           // shall be updated
)
(
    // Register clock
    input               reg_clk,

    // Outputs to internal logic
    output b2r_t        b2r,

    // Inputs from internal logic
    input  r2b_t        r2b,
 
    // Bus protocol
    input               HRESETn,
    input               HCLK,
    input               HSEL,
    input  [31:0]       HADDR,
    input               HWRITE,
    input  [ 2:0]       HSIZE,
    input  [ 2:0]       HBURST,
    input  [ 3:0]       HPROT,
    input  [ 1:0]       HTRANS,
    input  [31:0]       HWDATA,
    input               HREADY,

    output logic        HREADYOUT,
    output logic        HRESP,
    output logic [31:0] HRDATA
);

    // TODO: Add synchronizer logic
 
    /***
     * Translate HWRITE & HSEL into a write/read operation for the register logic
     ***/
    logic r_vld_next;
    logic w_vld_next;

    always_comb
    begin
        w_vld_next = 1'b0;
        r_vld_next = 1'b0;

        if (HWRITE)
            w_vld_next = HSEL;
        else
            r_vld_next = HSEL;
    end

    /***
     * Determine the number of active bytes
     ***/
    logic [3:0] b2r_byte_en_next;

    always_comb
    begin
        case (HTRANS)
            3'b000 : b2r_byte_en_next = 4'b0001;
            3'b001 : b2r_byte_en_next = 4'b0011;
            3'b010 : b2r_byte_en_next = 4'b1111;
            // TODO: Implement larger sizes
            default: b2r_byte_en_next = 4'b1111;
        endcase
    end

    /***
     * Flop or sync input if required
     ***/
    generate
        if (FLOP_IN)
        begin
            always_ff @(posedge HCLK or negedge HRESETn)
            if (!HRESETn)
            begin
                b2r.r_vld <= 1'b0;
                b2r.w_vld <= 1'b0;
            end
            else
            begin
                b2r.r_vld <= r_vld_next;
                b2r.w_vld <= w_vld_next;
            end

            always_ff @(posedge HCLK)
                if (HWRITE)
                begin
                    b2r.data    <= HWDATA;
                    b2r.byte_en <= b2r_byte_en_next;
                end
        end
        else
        begin
            assign b2r.r_vld = r_vld_next;
            assign b2r.w_vld = w_vld_next;
            assign b2r.data  = HWDATA;
        end
    endgenerate

    /***
     * Keep track of an ungoing transaction
     ***/
    logic reg_busy_q;

    always_ff @(posedge HCLK or negedge HRESETn)
        if (!HRESETn)
            reg_busy_q <= 1'b0;
        else if ((b2r.r_vld || b2r.w_vld) && !r2b.rdy)
            reg_busy_q <= 1'b1;
        else if (r2b.rdy)
            reg_busy_q <= 1'b0;

    assign HREADYOUT = !reg_busy_q;

    /***
     * Return to AHB bus once the register block is ready
     ***/
    // Return actual data
    logic ongoing_read_q;

    always_ff @(posedge HCLK or negedge HRESETn)
        if (!HRESETn)
            ongoing_read_q <= 1'b0;
        else if (b2r.r_vld && !r2b.rdy)
            ongoing_read_q <= 1'b1;
        else if (r2b.rdy)
            ongoing_read_q <= 1'b0;

    always_ff @(posedge HCLK)
        if ((b2r.r_vld || ongoing_read_q) && r2b.rdy)
            HRDATA <= r2b.data;

    // Did an error occur while reading?
    always_ff @(posedge HCLK or negedge HRESETn)
        if (!HRESETn)
            HRESP <= 1'b0;
        else
            HRESP <= r2b.err;

endmodule
