#ifndef PROJECT_CONF_H_
#define PROJECT_CONF_H_

/*=======================================
 * CSMA Configuration - Minimal needed for Contiki-NG
 *=======================================*/

/* Let Contiki-NG use its default values for everything */
/* We'll control parameters through our runtime functions instead */

/* Ensure the radio uses CSMA */
#define NETSTACK_CONF_MAC csma_driver

/* Disable TSCH if it's enabled by default */
#undef NETSTACK_CONF_MAC
#define NETSTACK_CONF_MAC csma_driver

#endif /* PROJECT_CONF_H_ */
