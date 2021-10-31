ALL_DIRS = $(shell ls -d */)

.PHONY: clean $(ALL_DIRS)

default: $(ALL_DIRS)

$(ALL_DIRS):
	make -C $@

clean:
	rm -rf */srdl2sv_out
