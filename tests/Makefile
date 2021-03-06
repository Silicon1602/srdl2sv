ALL_COCOTB_TESTS = $(shell ls cocotb_tests/test_*.py | sed -E 's|.*?/test_(.*?).py|\1|g')

.PHONY: clean examples
.PRECIOUS: build_dirs/%/compile.f

default: $(ALL_COCOTB_TESTS) examples
	@echo ""
	@echo "-------------------------------------------------------------------------------"
	@echo "Showing all FAILs in simulation logs:"
	@grep -r 'test.*FAIL' build_dirs && exit 1 || echo ''
	@echo "-------------------------------------------------------------------------------"
	@echo ""
	@echo "SUCCESS: NO FAILURES FOUND!"

# This target will always rebuild, which is fine since we want to be sure to execute any
# test if we kick it off.
%: build_dirs/%/compile.f
	rm -rf cocotb_tests/dump.fst
	rm -rf cocotb_tests/results.xml
	rm -rf cocotb_tests/simulation.log

	mkdir -p $(PWD)/build_dirs/$@/cocotb_build
	$(MAKE) -C cocotb_tests \
		TOPLEVEL=$@\
		MODULE=test_$@\
		VERILOG_SOURCES="$(shell cat $^)"\
		SIM_BUILD=$(PWD)/build_dirs/$@/cocotb_build\
			| tee $(PWD)/build_dirs/$@/simulation.log

	# Move some files
	mv cocotb_tests/dump.fst $(PWD)/build_dirs/$@/
	mv cocotb_tests/results.xml $(PWD)/build_dirs/$@/

	@echo ""
	@echo "##############################################################################"
	@echo "# SIMULATION DONE ############################################################"
	@echo "##############################################################################"
	@echo "# Simulation dump: $(PWD)/build_dirs/$@/dump.fst"
	@echo "# Simulation log : $(PWD)/build_dirs/$@/simulation.log"
	@echo "# Results XML    : $(PWD)/build_dirs/$@/results.xml"
	@echo "##############################################################################"
	@echo "##############################################################################"
	
# Rebuild if RDL file or srdl2sv-software is newer
build_dirs/%/compile.f: systemrdl/%.rdl $(shell which srdl2sv)
	srdl2sv $< --out-dir $(shell dirname $@) --file-logging DEBUG --stdout-logging DEBUG

	ls $(PWD)/$(@D)/*_if.sv > $@
	ls $(PWD)/$(@D)/*amba*.sv >> $@
	ls $(PWD)/$(@D)/*.sv | grep -v '.*_if.sv$$' | grep -v '.*amba.*' >> $@

examples:
	# Make examples. This does not flag any functional issues, but if
	# a change breaks compilation, this will flag it.
	make -C ../examples/

clean:
	rm -rf build_dirs
	make -C ../examples/ clean
