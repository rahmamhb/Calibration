/*
 * sender.c
*/

#include "contiki.h"
#include "lib/random.h"
#include "sys/ctimer.h"
#include "sys/etimer.h"

#include "net/ipv6/uip.h"
#include "net/ipv6/uip-ds6.h"
#include "net/ipv6/uip-debug.h"

#include "sys/node-id.h"
#include "net/ipv6/simple-udp.h"

#include "dev/radio.h"

#include <stdio.h>
#include <string.h>

/*---------------------------------------------------------------------------*/
/* Experiment parameters — controlled from Makefile                         */
/*---------------------------------------------------------------------------*/

#define UDP_PORT        1234

#ifndef NB_PACKETS
#define NB_PACKETS      15        /* packets per burst */
#endif

#ifndef SEND_BUFFER_SIZE
#define SEND_BUFFER_SIZE 8        /* payload size in bytes */
#endif

#ifndef NB_SECONDS
#define NB_SECONDS      1         /* interval between bursts in seconds */
#endif

#define SEND_INTERVAL   (NB_SECONDS * CLOCK_SECOND)

#define RECEIVER_ADDR_1  0xfe80
#define RECEIVER_ADDR_2  0x0000
#define RECEIVER_ADDR_3  0x0000
#define RECEIVER_ADDR_4  0x0000
#define RECEIVER_ADDR_5  0xc30c   
#define RECEIVER_ADDR_6  0x0000   
#define RECEIVER_ADDR_7  0x0000  
#define RECEIVER_ADDR_8  0x0001

/*---------------------------------------------------------------------------*/

static struct simple_udp_connection unicast_connection;
static uint32_t cpt = 0;
static uip_ipaddr_t id;

/*---------------------------------------------------------------------------*/
static void
receiver(struct simple_udp_connection *c,
         const uip_ipaddr_t *sender_addr,
         uint16_t sender_port,
         const uip_ipaddr_t *receiver_addr,
         uint16_t receiver_port,
         const uint8_t *data,
         uint16_t datalen)
{
  /* not used on sender side */
}
/*---------------------------------------------------------------------------*/
static void
set_global_address(void)
{
  int i;
  uint8_t state;

  printf("IPv6 addresses: ");
  for(i = 0; i < UIP_DS6_ADDR_NB; i++) {
    state = uip_ds6_if.addr_list[i].state;
    if(uip_ds6_if.addr_list[i].isused &&
       (state == ADDR_TENTATIVE || state == ADDR_PREFERRED)) {
      uip_debug_ipaddr_print(&uip_ds6_if.addr_list[i].ipaddr);
      
      if(uip_ds6_if.addr_list[i].ipaddr.u8[0] == 0xfe) {
        id = uip_ds6_if.addr_list[i].ipaddr;
      }
      printf("\n");
    }
  }
}
/*---------------------------------------------------------------------------*/
PROCESS(unicast_sender_process, "Unicast sender process");
AUTOSTART_PROCESSES(&unicast_sender_process);
/*---------------------------------------------------------------------------*/
PROCESS_THREAD(unicast_sender_process, ev, data)
{
  static struct etimer send_timer;
  static uip_ipaddr_t receiver_addr;
  int i;

  PROCESS_BEGIN();

  /* Print our IPv6 addresses */
  set_global_address();

  simple_udp_register(&unicast_connection, UDP_PORT, NULL, UDP_PORT, receiver);

  /* Set hardcoded receiver IPv6 address — pass via Makefile RECEIVER_ADDR_* */
  uip_ip6addr(&receiver_addr,
              RECEIVER_ADDR_1, RECEIVER_ADDR_2,
              RECEIVER_ADDR_3, RECEIVER_ADDR_4,
              RECEIVER_ADDR_5, RECEIVER_ADDR_6,
              RECEIVER_ADDR_7, RECEIVER_ADDR_8);

  printf("Receiver address set to: ");
  uip_debug_ipaddr_print(&receiver_addr);
  printf("\n");



  printf("SENDER STARTED: nb_packets=%d interval=%ds\n",NB_PACKETS, NB_SECONDS);

  etimer_set(&send_timer, SEND_INTERVAL);

  while(1) {
    PROCESS_WAIT_EVENT();
    if(etimer_expired(&send_timer)) {

      for(i = 0; i < NB_PACKETS; i++) {
        char buf[SEND_BUFFER_SIZE + 1];
        snprintf(buf, sizeof(buf), "%08ld", cpt);
        cpt++;
        /* Log format compatible with run_analysis.py */
        printf("s ");
        uip_debug_ipaddr_print(&id);
        printf(" %s\n", buf);

        simple_udp_sendto(&unicast_connection, buf, SEND_BUFFER_SIZE, &receiver_addr);
      }

      etimer_reset(&send_timer);
    }
  }

  PROCESS_END();
}
/*---------------------------------------------------------------------------*/
