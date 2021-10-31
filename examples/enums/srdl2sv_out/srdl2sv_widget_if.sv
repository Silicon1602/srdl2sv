interface srdl2sv_widget_if #(
    parameter ADDR_W = 32,
    parameter DATA_W = 32
);

    localparam DATA_BYTES = DATA_W >> 3;

    logic [ADDR_W-1:0]      addr;
    logic [DATA_W-1:0]      w_data;
    logic                   w_vld;
    logic                   r_vld;
    logic [DATA_BYTES-1:0]  byte_en;

    logic [DATA_W-1:0]      r_data;
    logic                   rdy;
    logic                   err;

    modport widget (
        output addr,
        output w_data,
        output w_vld,
        output r_vld,
        output byte_en,

        input  r_data,
        input  rdy,
        input  err
    );
endinterface

