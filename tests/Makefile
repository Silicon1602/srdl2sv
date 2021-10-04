ALL_COCOTB_TESTS = $(shell ls cocotb_tests/test_*.py | sed -E 's|.*?/test_(.*?).py|\1|g')

default: $(ALL_COCOTB_TESTS)

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
	
build_dirs/%/*.sv: systemrdl/%.rdl
	../srdl2sv/main.py $? --out_dir $(shell dirname $@) --file_log_level DEBUG --stream_log_level DEBUG

build_dirs/%/compile.f: build_dirs/%/*.sv 
	ls $(PWD)/$(@D)/*_pkg.sv > $@
	ls $(PWD)/$(@D)/*amba*.sv >> $@
	ls $(PWD)/$(@D)/*.sv | grep -v '.*_pkg.sv$$' | grep -v '.*amba.*' >> $@

.PHONY: clean

clean:
	rm -rf build_dirs
