CC ?= cc
CFLAGS ?= -O2
CPPFLAGS ?=
LDFLAGS ?=

.PHONY: all
all: libfriday_sync.so

libfriday_sync.so: friday_sync.c friday_sync.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -std=c11 -Wall -Wextra -Wpedantic -fPIC -pthread -shared $(LDFLAGS) -o $@ friday_sync.c
