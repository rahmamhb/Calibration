#ifndef CSMA_CONF_H_
#define CSMA_CONF_H_

#include "net/mac/framer/framer-802154.h"
#include "sys/rtimer.h"

/* CSMA Framer */
#define CSMA_FRAMER framer_802154

/* ACK parameters */
#define CSMA_ACK_LEN 3
#define CSMA_ACK_WAIT_TIME (RTIMER_SECOND / 400)
#define CSMA_AFTER_ACK_DETECTED_WAIT_TIME (RTIMER_SECOND / 1500)

/* Header size */
#define CSMA_MAC_MAX_HEADER 21

#endif /* CSMA_CONF_H_ */
