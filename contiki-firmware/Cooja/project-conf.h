/* project-conf.h */
#ifndef PROJECT_CONF_H_
#define PROJECT_CONF_H_

/* CSMA configuration — required by this version of Contiki-NG */
#define CSMA_CONF_FRAMER         framer_802154
#define CSMA_CONF_ACK_WAIT_TIME  RTIMER_SECOND / 2500
#define CSMA_CONF_ACK_LEN        3
#define CSMA_CONF_AFTER_ACK_DETECTED_WAIT_TIME  RTIMER_SECOND / 1500
#define QUEUEBUF_CONF_NUM 16

#endif /* PROJECT_CONF_H_ */
