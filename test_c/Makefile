CC      = gcc
LIBUSB  = /opt/homebrew/opt/libusb
CFLAGS  = -Wall -O2 -I$(LIBUSB)/include/libusb-1.0
LDFLAGS = -L$(LIBUSB)/lib -lusb-1.0

all: can_test

can_test: can_test.c
	$(CC) $(CFLAGS) -o can_test can_test.c $(LDFLAGS)

clean:
	rm -f can_test
