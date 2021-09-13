package srdl2sv_if_pkg;

typedef struct packed { // .Verilator does not support unpacked structs in packages
    logic [31:0] addr;
    logic [31:0] data;
    logic        w_vld;
    logic        r_vld;
    logic [ 3:0] byte_en;
} b2r_t;

typedef struct packed { // .Verilator does not support unpacked structs in packages
    logic [31:0] data;
    logic        rdy;
    logic        err;
} r2b_t;

endpackage
