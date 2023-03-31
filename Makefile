.PHONY: run run-no-output monitor upload reset clean ls build
.DEFAULT_GOAL := build

SRC_DIR = src
MAIN = main.py
PORT = /dev/ttyACM0

upload-everything:
	ampy --port $(PORT) put $(SRC_DIR) /

upload-src:
	for f in $(shell ls -p src | grep -v /); do \
		ampy --port $(PORT) put src/$$f; \
	done

reset:
	ampy --port $(PORT) reset --hard

clean:
	for f in $(shell make ls); do \
		ampy --port $(PORT) rm $$f; \
	done
	ampy --port $(PORT) rm lib/primitives
	ampy --port $(PORT) rm lib
	
run: upload-src reset
	sleep 1
	minicom -o -D $(PORT) -b 115200

run-no-output: upload-src
	ampy --port $(PORT) run --no-output $(SRC_DIR)/$(MAIN)
	
monitor:
	minicom -o -D $(PORT) -b 115200
	
ls:
	@ampy --port $(PORT) ls -r

build: upload-everything reset