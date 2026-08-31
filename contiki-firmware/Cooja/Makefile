CONTIKI_PROJECT = sender receiver
all: $(CONTIKI_PROJECT)


# Experiment parameters (override from command line)
NB_PACKETS     ?= 15
SEND_BUFFER_SIZE ?= 8
NB_SECONDS     ?= 1

# MAC layer (CSMA) parameters — override from command line, e.g.:
#   make CSMA_MIN_BE=0 CSMA_MAX_BE=4 CSMA_MAX_BACKOFF=5 CSMA_MAX_FRAME_RETRIES=7
# Defaults below match Contiki-NG's own compiled-in defaults (csma-output.c),
# so building with no override reproduces the exact behavior of past scenarios.
CSMA_MIN_BE            ?= 3
CSMA_MAX_BE            ?= 5
CSMA_MAX_BACKOFF       ?= 5
CSMA_MAX_FRAME_RETRIES ?= 7

CFLAGS += -DNB_PACKETS=$(NB_PACKETS)
CFLAGS += -DSEND_BUFFER_SIZE=$(SEND_BUFFER_SIZE)
CFLAGS += -DNB_SECONDS=$(NB_SECONDS)
CFLAGS += -DCSMA_CONF_MIN_BE=$(CSMA_MIN_BE)
CFLAGS += -DCSMA_CONF_MAX_BE=$(CSMA_MAX_BE)
CFLAGS += -DCSMA_CONF_MAX_BACKOFF=$(CSMA_MAX_BACKOFF)
CFLAGS += -DCSMA_CONF_MAX_FRAME_RETRIES=$(CSMA_MAX_FRAME_RETRIES)

CFLAGS += -DPROJECT_CONF_H=\"project-conf.h\"

CONTIKI = ../..
include $(CONTIKI)/Makefile.include
