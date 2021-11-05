RTL_TARGETS = $(subst .rdl,.sv,srdl2sv_out/$(shell ls *.rdl))

.PHONY: clean 

default: $(RTL_TARGETS)

srdl2sv_out/%.sv: %.rdl $(shell which srdl2sv)
	srdl2sv $< --out-dir $(shell dirname $@) --stdout-logging INFO

clean:
	rm -rf srdl2sv_out
