RTL_TARGETS = $(subst .rdl,.sv,srdl2sv_out/$(shell ls *.rdl))

.PHONY: clean 

default: verilog_compile

verilog_compile: $(RTL_TARGETS)
	verilator -cc -sv $(shell ls srdl2sv_out/*.sv)

srdl2sv_out/%.sv: %.rdl $(shell which srdl2sv)
	srdl2sv $< --out-dir $(shell dirname $@) --stdout-logging INFO -d 31 

clean:
	rm -rf srdl2sv_out
