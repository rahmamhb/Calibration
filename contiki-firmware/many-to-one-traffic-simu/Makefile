CONTIKI_PROJECT = unicast-sender unicast-receiver
all: $(CONTIKI_PROJECT)

# Include our modified CSMA
PROJECTDIRS += $(CONTIKI)/os/net/mac/csma
PROJECT_SOURCEFILES += csma-covergecast.c

# Add required include paths
CFLAGS += -I$(CONTIKI)/os/net/mac/csma

# Explicitly define missing CSMA macros
CFLAGS += -DCSMA_ACK_LEN=4
CFLAGS += -DCSMA_MAC_MAX_HEADER=50
CFLAGS += -DCSMA_FRAMER=framer_802154
CFLAGS += -DCSMA_ACK_WAIT_TIME=49
CFLAGS += -DCSMA_AFTER_ACK_DETECTED_WAIT_TIME=3

CONTIKI = ../..
include $(CONTIKI)/Makefile.include
