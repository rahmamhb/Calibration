/*
 * senderInterferer.c
 *
 * Stays silent for DELAY_S seconds, then floods the receiver's UDP service
 * (same SERVICE_ID/protocol as sender.c) for ACTIVE_S seconds, then goes
 * silent again for the rest of the experiment.
 *
 * DELAY_S/ACTIVE_S are baked in at compile time so the join/leave timing is
 * driven by each node's own clock once the experiment is Running — no
 * runtime signal from the orchestrator is needed, which lets every node
 * (main senders, receiver, interferers) be reserved in a single FIT IoT-LAB
 * experiment submission from t=0.
 *
 * Two binaries are built from this same source (DELAY_S/ACTIVE_S differ),
 * one per interferer group — see run_interference_experiment.sh.
 */

#include "contiki.h"
#include "lib/random.h"
#include "sys/ctimer.h"
#include "sys/etimer.h"
#include "net/ip/uip.h"
#include "net/ipv6/uip-ds6.h"
#include "net/ip/uip-debug.h"
#include "sys/node-id.h"
#include "simple-udp.h"
#include "servreg-hack.h"

#include <stdio.h>
#include <string.h>

/*---------------------------------------------------------------------------*/
/* Experiment parameters — controlled from Makefile                          */
/*---------------------------------------------------------------------------*/

#define UDP_PORT        1234
#define SERVICE_ID      190

#ifndef NB_PACKETS
#define NB_PACKETS      15        /* packets per burst while active */
#endif

#ifndef SEND_BUFFER_SIZE
#define SEND_BUFFER_SIZE 8        /* payload size in bytes */
#endif

#ifndef NB_SECONDS
#define NB_SECONDS      1         /* interval between bursts in seconds */
#endif

#ifndef DELAY_S
#define DELAY_S         0         /* seconds of silence before joining as interferer */
#endif

#ifndef ACTIVE_S
#define ACTIVE_S        600       /* seconds spent actively flooding once joined */
#endif

#define SEND_INTERVAL   (NB_SECONDS * CLOCK_SECOND)

/*---------------------------------------------------------------------------*/

static struct simple_udp_connection unicast_connection;
static uint32_t cpt = 0;
static uip_ipaddr_t id;
static uint8_t active = 0;
static uint8_t joined = 0;   /* set once the single join/leave cycle has fired */

/*---------------------------------------------------------------------------*/
PROCESS(interferer_process, "Interferer sender process");
AUTOSTART_PROCESSES(&interferer_process);
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
  uip_ipaddr_t ipaddr;
  int i;
  uint8_t state;

  uip_ip6addr(&ipaddr, UIP_DS6_DEFAULT_PREFIX, 0, 0, 0, 0, 0, 0, 0);
  uip_ds6_set_addr_iid(&ipaddr, &uip_lladdr);
  uip_ds6_addr_add(&ipaddr, 0, ADDR_AUTOCONF);

  printf("IPv6 addresses: ");
  for(i = 0; i < UIP_DS6_ADDR_NB; i++) {
    state = uip_ds6_if.addr_list[i].state;
    if(uip_ds6_if.addr_list[i].isused &&
       (state == ADDR_TENTATIVE || state == ADDR_PREFERRED)) {
      uip_debug_ipaddr_print(&uip_ds6_if.addr_list[i].ipaddr);
      id = uip_ds6_if.addr_list[i].ipaddr;
      printf("\n");
    }
  }
}

/*---------------------------------------------------------------------------*/
PROCESS_THREAD(interferer_process, ev, data)
{
  static struct etimer send_timer;
  static struct etimer join_timer;
  static struct etimer leave_timer;
  uip_ipaddr_t *addr;
  int i;

  PROCESS_BEGIN();

  servreg_hack_init();
  set_global_address();
  simple_udp_register(&unicast_connection, UDP_PORT, NULL, UDP_PORT, receiver);

  printf("INTERFERER WAITING delay=%us active=%us\n", DELAY_S, ACTIVE_S);
  etimer_set(&join_timer, (clock_time_t)DELAY_S * CLOCK_SECOND);

  while(1) {
    PROCESS_WAIT_EVENT();

    /* ── Join: silence -> active (fires exactly once) ─────────────────────── */
    if(!joined && etimer_expired(&join_timer)) {
      joined = 1;
      active = 1;
      printf("INTERFERER JOIN\n");
      etimer_set(&send_timer, SEND_INTERVAL);
      etimer_set(&leave_timer, (clock_time_t)ACTIVE_S * CLOCK_SECOND);
    }

    /* ── Leave: active -> silence ───────────────────────────────────────── */
    /* send_timer is simply left unreset once active drops back to 0, so no
       further bursts go out — same "leave it expired" guard senderTX.c uses
       for its phase timer. */
    if(active && etimer_expired(&leave_timer)) {
      active = 0;
      printf("INTERFERER LEAVE\n");
    }

    /* ── Send burst while active ────────────────────────────────────────── */
    if(active && etimer_expired(&send_timer)) {
      addr = servreg_hack_lookup(SERVICE_ID);

      if(addr != NULL) {
        for(i = 0; i < NB_PACKETS; i++) {
          char buf[SEND_BUFFER_SIZE + 1];
          snprintf(buf, sizeof(buf), "%08lu", (unsigned long)cpt);
          cpt++;

          printf("s ");
          uip_debug_ipaddr_print(&id);
          printf(" %s\n", buf);

          simple_udp_sendto(&unicast_connection, buf, SEND_BUFFER_SIZE, addr);
        }
      } else {
        printf("Service %d not found\n", SERVICE_ID);
      }

      etimer_reset(&send_timer);
    }
  }

  PROCESS_END();
}
/*---------------------------------------------------------------------------*/
