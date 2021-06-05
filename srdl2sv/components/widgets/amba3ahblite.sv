module amba3ahblite_widget
(
    // Register clock
    input         reg_clk,

    // Outputs to internal logic
    output [31:0] addr,
    output        w_vld,
    output        r_vld,
    output [ 3:0] byte_enable,
    output [31:0] sw_wr_bus,
 
    // Bus protocol
    input         HRESETn,
    input         HCLK,
    input  [31:0] HADDR,
    input         HWRITE,
    input  [ 2:0] HSIZE,
    input  [ 2:0] HBURST,
    input  [ 3:0] HPROT,
    input  [ 1:0] HTRANS,
    input         HMASTLOCK,
    input         HREADY,

    output        HREADYOUT,
    output        HRESP,
    output [31:0] HRDATA
);


endmodule
