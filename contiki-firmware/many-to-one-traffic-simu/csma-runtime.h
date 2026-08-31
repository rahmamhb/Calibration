#ifndef CSMA_RUNTIME_H_
#define CSMA_RUNTIME_H_

#include <stdint.h>

/* Runtime CSMA parameter access */
extern uint8_t csma_min_be;
extern uint8_t csma_max_be;
extern uint8_t csma_max_backoff;
extern uint8_t csma_max_frame_retries;

void set_csma_min_be(uint8_t v);
int get_csma_min_be(void);

void set_csma_max_be(uint8_t v);
int get_csma_max_be(void);

void set_csma_max_backoff(uint8_t v);
int get_csma_max_backoff(void);

void set_csma_max_frame_retries(uint8_t v);
int get_csma_max_frame_retries(void);

#endif /* CSMA_RUNTIME_H_ */
