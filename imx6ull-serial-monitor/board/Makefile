CROSS_COMPILE ?= arm-linux-gnueabihf-
CC = $(CROSS_COMPILE)gcc
CFLAGS ?= -O2 -g
CFLAGS += -std=c11 -Wall -Wextra -Werror -Iinclude -I../common -pthread
SOURCES = src/main.c src/serial.c src/sensors.c src/storage.c src/config.c ../common/protocol.c
.PHONY: all clean
all: monitor
monitor: $(SOURCES) include/monitor.h ../common/protocol.h
	$(CC) $(CFLAGS) $(SOURCES) -o $@ -pthread
clean:
	rm -f monitor
