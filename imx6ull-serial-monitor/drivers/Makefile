obj-m += mon_sensors.o
KDIR ?= /path/to/exact-running-linux-source
CROSS_COMPILE ?= arm-linux-gnueabihf-
.PHONY: all clean
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm CROSS_COMPILE=$(CROSS_COMPILE) modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=arm CROSS_COMPILE=$(CROSS_COMPILE) clean
